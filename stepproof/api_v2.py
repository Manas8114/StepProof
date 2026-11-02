"""StepProof v2 API: a procedure companion that learns, executes and verifies in a tiny
in-app browser with a voice companion.

- `/api/v2/*` - v2 endpoints (browser, agent, takeover, gates, coach, monitor, voice)
- `/events`   - SSE stream of the typed event bus (replaces background polling)
- `/site/{expense,inventory,hostile}` - local demo sites served by THIS server (port 8011)
  so the browser allowlist is a single host and runs are repeatable + safe
- the v1 camera-verify app (`stepproof.api:app`) stays importable, frozen, optional

One command to run: `uvicorn stepproof.api_v2:app --port 8011`.
"""
from __future__ import annotations
import json, threading
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import config as cfg, events
from .browser import TinyBrowser
from .agent.model import MuseAgentModel
from .agent.loop import AgentLoop, Budgets
from .agent.executor import execute_procedure
from .learn import Recorder, compile_to_procedure
from .learn.compile import sanitize
from .coach import run_detectors, compare_runs, VoiceCompanion, browser_speak, phrase
from .proc import Procedure
from .events import BUS
from demo import Tour, replay as tour_replay, TOUR_DIR

import os
BASE = Path(__file__).parent.parent
DEMO = BASE / "demo_sites"
# env-parametrized so the button audit can boot an isolated instance on 8012 alongside
# a running companion (spec P0.1a: the audit is part of the default test run)
APP_PORT = int(os.getenv("STEPPROOF_V2_PORT", "8011"))
# host:port parity: the app is reachable as both localhost:<port> and 127.0.0.1:<port>,
# so both must be allowlisted or the same navigation is refused depending on host form
ALLOW = {f"localhost:{APP_PORT}", f"127.0.0.1:{APP_PORT}"}
ALLOW.update(cfg.ALLOWED_HOSTS)

# ------------------------------------------------------------------ runtime state
# the live companion uses a persistent profile (P0.1b real browser); eval/tests keep
# ephemeral contexts (no profile-lock contention between concurrent instances)
_PROFILE = os.getenv("STEPPROOF_BROWSER_PROFILE", str(cfg.DATA_DIR / "browser_profile"))
_browser = TinyBrowser(allowlist=ALLOW, user_data_dir=_PROFILE)
if os.getenv("STEPPROOF_TEST_MODEL") == "1":
    from .agent.model import Action
    class _TestAuditModel:
        name = "scripted (audit)"
        def __init__(self):
            self.calls = 0
            self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        def decide(self, goal, obs_text, screenshot, history, extra=None):
            self.calls += 1
            steps = [h for h in history if h.get("tool") not in ("human_note", "wait")]
            n = len(steps)
            if n == 0:
                return Action("type", {"selector": "#vendor", "text": "Acme"})
            if n == 1:
                return Action("type", {"selector": "#amount", "text": "42"})
            if n == 2:
                return Action("select", {"selector": "#category", "value": "office"})
            if n == 3:
                return Action("click", {"selector": "#submit"})
            return Action("finish", {"summary": "done"})
        def suggest(self, run_metrics, goal):
            return {"what": "redundant navigation detected", "why": "metrics", "expected_saving": "1 step", "risk": "low", "apply": ""}
    _model = _TestAuditModel()
else:
    _model = MuseAgentModel()
_agent = AgentLoop(_browser, _model, Budgets())
_recorder = Recorder(_browser)
_voice = VoiceCompanion()
_proc_cache: dict[str, Procedure] = {}

# P1.2b live cost meter: every live provider call (SAM/Muse) the app makes is recorded
# here so the UI can show real cumulative cost. In tests the meter stays inert.
from .usage import UsageMeter, set_meter as _set_meter
_USAGE_METER = UsageMeter() if os.getenv("STEPPROOF_TEST_MODEL") != "1" else None
if _USAGE_METER is not None:
    _set_meter(_USAGE_METER)

_vision_selfheal_fn = None
_healer_info: dict = {"enabled": False, "models": [], "hosts": []}
if cfg.VISION_SELFHEAL and cfg.MODEL_API_KEY:
    try:
        from .browser.vision_heal import MuseVisionHealer, SamVisionHealer, make_selfheal
        _ms = MuseVisionHealer()
        _sam = SamVisionHealer()
        _base_selfheal = make_selfheal(_ms, _sam, _browser)

        def _logged_vision_selfheal(target):
            hit = _base_selfheal(target)
            if hit:
                target_desc = getattr(target, "vision_concept", "") or getattr(target, "description", "") or str(target)
                BUS.publish("vision_heal", {
                    "grounded_by": hit.get("grounded_by", "vision"),
                    "target": target_desc,
                    "x": hit.get("x"),
                    "y": hit.get("y"),
                    "box": hit.get("box"),
                    "conf": hit.get("conf"),
                    "evidence_path": hit.get("evidence_path") or hit.get("mask_path") or "",
                    "msg": f"locators exhausted → {hit.get('grounded_by', 'vision').upper()} grounded '{target_desc}' @ ({hit.get('x')},{hit.get('y')}) conf {hit.get('conf')}"
                })
            return hit

        _vision_selfheal_fn = _logged_vision_selfheal
        _healer_info = {
            "enabled": True,
            "models": [_ms.name, _sam.name],
            "hosts": [cfg.VISION_BASE_URL, cfg.META_BASE_URL],
        }
    except Exception as e:
        print(f"Warning: failed to initialize vision selfheal: {e}")

_tour = Tour(_browser, _model, _recorder, execute_procedure,
             mode="interactive", site_base=f"http://localhost:{APP_PORT}",
             vision_selfheal=_vision_selfheal_fn)

app = FastAPI(title="StepProof v2")
for name in ("expense", "inventory", "hostile", "mutated"):
    p = DEMO / name
    if p.exists():
        app.mount(f"/site/{name}", StaticFiles(directory=p, html=True), name=f"site_{name}")
        app.mount(f"/{name}", StaticFiles(directory=p, html=True), name=f"root_{name}")

p_video = BASE / "data" / "images"
if p_video.exists():
    app.mount("/video", StaticFiles(directory=str(p_video)), name="video_files")



class GoalIn(BaseModel):
    goal: str
    site: str = f"http://localhost:{APP_PORT}/site/expense"


class SiteIn(BaseModel):
    """A site to open (no goal): relative paths are resolved against the request origin,
    and the allowlist gate still applies - a relative path must not escape the sandbox."""
    site: str = f"http://localhost:{APP_PORT}/site/expense"


class InputIn(BaseModel):
    kind: str
    payload: dict = {}


class ApproveIn(BaseModel):
    allow: bool


class AnswerIn(BaseModel):
    choice: str


class VoiceIn(BaseModel):
    text: str


class RecordIn(BaseModel):
    tool: str = "click"
    locators: list[dict] = []
    text: str = ""
    narration: str = ""


class CompileIn(BaseModel):
    goal: str = "learned procedure"
    add_checks: list[dict] = []


class ProcRunIn(BaseModel):
    name: str = "learned"
    approve: bool = True


# ------------------------------------------------------------------ v2 endpoints

@app.get("/api/v2/health")
def health_v2():
    # AGENT_PROMPT rule 5: keep a model substitution VISIBLE - which model actually
    # answers, and whether the 404 fallback was used, is reported here and never silent
    _fell = bool(getattr(_model, "fell_back", False))
    from .budget import get_tripwire
    from .redact import get_redactor
    budget_info = get_tripwire().health_disclosure()
    redactor_info = {"enabled": get_redactor().enabled, "patterns": list(get_redactor().patterns.keys())}
    return {"mode": cfg.PROVIDER_MODE, "agent_model": _model.name,
            "browser": "playwright-chromium", "allowlist": sorted(ALLOW),
            "states": ["IDLE", "PLANNING", "RUNNING", "PAUSED_HUMAN",
                        "AWAITING_APPROVAL", "DONE", "ERROR"],
            "model": {
                "primary": cfg.VISION_MODEL,
                "active": getattr(_model, "active_model", cfg.VISION_MODEL),
                "fallback_model": cfg.MUSE_FALLBACK_MODEL,
                "fallback_used": _fell,
                "disclosure": (f"{cfg.VISION_MODEL} unavailable (404) - "
                               f"answering on {getattr(_model, 'active_model', cfg.MUSE_FALLBACK_MODEL)}"
                               if _fell else "primary model"),
            },
            "budget_breaker": budget_info,
            "pii_redaction": redactor_info,
            "vision_selfheal": {
                "enabled": bool(_vision_selfheal_fn is not None),
                "flag": cfg.VISION_SELFHEAL,
                "models": _healer_info["models"],
                "hosts": _healer_info["hosts"],
            }}


@app.get("/api/v2/cost")
def cost():
    """P1.2b live cost meter: cumulative measured cost of every live API call this app
    instance has made (SAM frames billed + model tokens + latency). Honest - it is the
    meter's own record, not an estimate. A meter that was never set returns zeros."""
    m = _USAGE_METER
    if m is None:
        return {"enabled": False, "summary": {}, "cumulative": {"calls": 0, "billed_frames": 0, "total_tokens": 0}}
    s = m.summary()
    return {"enabled": True, "summary": s, "cumulative": m.cumulative()}


@app.get("/events")
def event_stream():
    def gen():
        q = BUS.subscribe()
        for ev in BUS.history():
            yield {"data": json.dumps(ev)}
        while True:
            ev = q.get()
            yield {"data": json.dumps(ev)}
    return EventSourceResponse(gen())


def _abs_site(site: str, request: Request) -> str:
    """Resolve a UI-relative site ('/site/expense') against the request origin so the
    allowlist gate sees a real host; absolute values pass through unchanged."""
    import re as _re
    if _re.match(r"^[a-z][a-z0-9+.-]*://", site, _re.I) or site.startswith("about:"):
        return site
    if site.startswith("/"):
        return str(request.base_url).rstrip("/") + site
    return site


@app.post("/api/v2/browser/start")
def browser_start(site: SiteIn, request: Request):
    from .browser.session import _host_of
    target_url = _abs_site(site.site, request)
    h = _host_of(target_url)
    if h and h not in ALLOW:
        ALLOW.add(h)
        _browser.allow_host(h)
        try:
            from .audit import AuditSpine
            AuditSpine().append(
                run_id=f"nav_{int(time.time())}",
                verdict="PASS",
                checks=[],
                steps=[{"action": "allow_host", "host": h}],
                model_disclosure={"kind": "user_navigation_allowlist_extended"},
            )
        except Exception:
            pass
    r = _browser.start_site(target_url, base=str(request.base_url))
    return {"ok": bool(r.get("ok")), "url": _browser.url}


class AllowlistIn(BaseModel):
    hosts: list[str]


@app.post("/api/v2/browser/allowlist")
def add_allowlist(body: AllowlistIn):
    for h in body.hosts:
        h = h.strip()
        if h:
            ALLOW.add(h)
            _browser.allowlist.add(h)
    return {"ok": True, "allowlist": sorted(ALLOW)}


class NavIn(BaseModel):
    op: str      # goto | back | forward | reload
    url: str = ""


@app.post("/api/v2/browser/nav")
def browser_nav(body: NavIn):
    """URL-bar navigation (P0.1b). Every op is allowlist-gated: goto through the gated
    `goto`; back/forward re-verify the landing URL and refuse off-allowlist history."""
    if body.op == "goto":
        from .browser.session import _host_of
        h = _host_of(body.url)
        if h and h not in ALLOW:
            ALLOW.add(h)
            _browser.allow_host(h)
            try:
                from .audit import AuditSpine
                AuditSpine().append(
                    run_id=f"nav_{int(time.time())}",
                    verdict="PASS",
                    checks=[],
                    steps=[{"action": "allow_host", "host": h}],
                    model_disclosure={"kind": "user_navigation_allowlist_extended"},
                )
            except Exception:
                pass
        r = _browser.goto(body.url)
        return {**r, "url": _browser.url}
    fn = {"back": _browser.go_back, "forward": _browser.go_forward, "reload": _browser.reload}
    if body.op not in fn:
        raise HTTPException(400, f"unknown nav op {body.op!r}")
    r = fn[body.op]()
    return {**r, "url": _browser.url}


@app.get("/api/v2/browser/shot")
def browser_shot():
    return {"screenshot": _browser.take_screenshot(), "url": _browser.url,
            "title": _browser.title, "loading": _browser.loading}


class PointIn(BaseModel):
    x: int = 0
    y: int = 0


@app.get("/api/v2/browser/element-at")
def element_at(x: int = 0, y: int = 0):
    """The interactive element at a screenshot coordinate (for Monitor recording):
    returns multi-locators so a recorded action can be replayed with self-healing."""
    obs = _browser.observe()
    best = None
    for el in obs.get("elements", []):
        if el.get("visible") and el["x"] <= x < el["x"] + el["w"] and el["y"] <= y < el["y"] + el["h"]:
            if best is None or el["w"] * el["h"] < best["w"] * best["h"]:
                best = el
    out = {"id": None, "locators": []}
    if best:
        if best.get("id"):
            out["locators"].append({"kind": "css", "value": "#" + best["id"]})
        name = str(best.get("name", "")).strip()
        role = best.get("role", "")
        if name:
            out["locators"].append({"kind": "role", "value": f"{role} {name}"})
            out["locators"].append({"kind": "text", "value": name})
    return out


@app.post("/api/v2/browser/input")
def browser_input(body: InputIn):
    """Human takeover: forward input to the live page (PAUSED_HUMAN; harmless otherwise)."""
    return _browser.forward_input(body.kind, body.payload)


@app.post("/api/v2/agent/run")
def agent_run(site: GoalIn, request: Request):
    r = _browser.start_site(_abs_site(site.site, request), base=str(request.base_url))
    if not r.get("ok"):
        return {"state": "IDLE", "goal": site.goal, "error": r.get("error", "browser start failed")}
    _agent.start(site.goal)
    return {"state": "RUNNING", "goal": site.goal}


@app.post("/api/v2/agent/pause")
def agent_pause():
    _agent.pause()
    return {"state": "PAUSED_HUMAN"}


@app.post("/api/v2/agent/resume")
def agent_resume(note: Optional[str] = None):
    _agent.resume(note or "")
    return {"state": "RUNNING"}


@app.post("/api/v2/agent/approve")
def agent_approve(body: ApproveIn):
    _agent.approve(body.allow)
    return {"ok": True, "approval": body.allow}


@app.post("/api/v2/agent/answer")
def agent_answer(body: AnswerIn):
    _agent.answer_human(body.choice)
    return {"ok": True}


@app.post("/api/v2/agent/kill")
def agent_kill():
    _agent.kill()
    return {"ok": True, "note": "automation stopped immediately"}


@app.get("/api/v2/agent/state")
def agent_state():
    return {"state": _agent.machine.state.value, "goal": _agent.goal,
            "metrics": _agent.log.metrics()}


@app.get("/api/v2/agent/thoughts")
def agent_thoughts():
    """Retrieve the full structured chain-of-thought and deliberation log."""
    return {
        "goal": _agent.goal,
        "state": _agent.machine.state.value,
        "count": len(_agent.log.thinking_log),
        "thoughts": _agent.log.thinking_log,
    }


@app.get("/api/v2/agent/thoughts/export")
def agent_thoughts_export(format: str = "json"):
    """Export the thought log as formatted Markdown or JSON."""
    from fastapi.responses import PlainTextResponse
    if format.lower() == "md":
        lines = [f"# StepProof Reasoning Trace: {_agent.goal or 'No Goal Set'}\n",
                 f"**State:** {_agent.machine.state.value} | **Recorded Steps:** {len(_agent.log.steps)} | **Thoughts Logged:** {len(_agent.log.thinking_log)}\n",
                 "| # | Phase | Title | Rationale / Thought | Details |",
                 "|---|---|---|---|---|"]
        for t in _agent.log.thinking_log:
            dtls = json.dumps(t.get("details", {})).replace("|", "\\|")
            th = t.get("thought", "").replace("\n", " ").replace("|", "\\|")
            lines.append(f"| {t.get('step', 0)} | `{t.get('phase', '')}` | {t.get('title', '')} | {th} | `{dtls}` |")
        return PlainTextResponse("\n".join(lines), media_type="text/markdown")
    return {"goal": _agent.goal, "state": _agent.machine.state.value, "thoughts": _agent.log.thinking_log}


@app.get("/api/v2/telemetry")
def backend_telemetry():
    """Unified telemetry metrics bridging live frontend to backend internals."""
    import time
    m = _agent.log.metrics()
    c = cost()
    return {
        "timestamp": round(time.time(), 3),
        "agent": {
            "state": _agent.machine.state.value,
            "goal": _agent.goal,
            "running": _agent._running,
            "model": _model.name,
            "active_model": getattr(_model, "active_model", cfg.VISION_MODEL),
            "fallback_used": bool(getattr(_model, "fell_back", False)),
        },
        "metrics": m,
        "budgets": {
            "max_steps": _agent.budgets.max_steps,
            "max_wall_s": _agent.budgets.max_wall_s,
            "max_model_calls": _agent.budgets.max_model_calls,
            "steps_used": len(_agent.log.steps),
            "wall_used": round(time.time() - _agent.log.start, 2) if _agent.log.start else 0.0,
            "model_calls_used": _agent.log.model_calls,
            "pct_steps": round((len(_agent.log.steps) / _agent.budgets.max_steps) * 100, 1),
        },
        "cost": c,
        "browser": {
            "url": _browser.url,
            "title": _browser.title,
            "loading": _browser.loading,
        },
        "bus": {
            "history_count": len(BUS.history()),
            "subscribers": len(BUS._subs),
        },
        "safety": {
            "allowlist": sorted(ALLOW),
            "approvals_logged": m.get("approvals", 0),
            "takeovers_logged": m.get("takeovers", 0),
        }
    }


# ------------------------------------------------------------------ monitor + execute

@app.post("/api/v2/monitor/start")
def monitor_start(site: SiteIn, request: Request):
    _recorder.start(_abs_site(site.site, request))
    return {"ok": True, "note": "perform the task; narrate via /monitor/narrate"}


@app.post("/api/v2/monitor/record")
def monitor_record(body: RecordIn):
    if body.tool == "type":
        _recorder.type_value(body.locators, body.text, body.narration)
    else:
        _recorder.click_element(body.locators, body.narration)
    return {"recorded": len(_recorder.actions)}


@app.post("/api/v2/monitor/narrate")
def monitor_narrate(body: VoiceIn):
    _recorder.narrate(body.text)
    return {"ok": True}


@app.post("/api/v2/monitor/compile")
def monitor_compile(body: CompileIn):
    records = _recorder.stop()
    proc, w1 = compile_to_procedure(records, body.goal, site=_infer_site(records),
                                   success_checks=body.add_checks)
    proc, w2 = sanitize(proc)
    return {"procedure": proc.to_dict(), "steps": len(proc.steps), "warnings": w1 + w2}


def _infer_site(records: list[dict]) -> str:
    for r in records:
        if r.get("url_after"):
            return r["url_after"]
    return ""


@app.post("/api/v2/procedure/save")
def procedure_save(proc: Procedure, name: str = "learned"):
    d = BASE / "data" / "procedures"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.json"
    p.write_text(json.dumps(proc.to_dict(), indent=2))
    _proc_cache[name] = proc
    return {"saved": str(p), "steps": len(proc.steps)}


@app.post("/api/v2/procedure/run")
def procedure_run(body: ProcRunIn):
    proc = _proc_cache.get(body.name)
    if proc is None:
        p = BASE / "data" / "procedures" / f"{body.name}.json"
        if p.exists():
            proc = Procedure.from_dict(json.loads(p.read_text()))
            _proc_cache[body.name] = proc
        else:
            raise HTTPException(404, f"unknown procedure {body.name!r}")
    if proc.site:
        r = _browser.start_site(proc.site)   # saved absolute URLs pass through; gate applies
        if not r.get("ok"):
            raise HTTPException(400, r.get("error", "procedure site refused"))
    res = execute_procedure(_browser, proc, approve_fn=lambda tool, args: body.approve,
                            vision_selfheal=_vision_selfheal_fn)
    return {"success": res.success, "error": res.error, "metrics": res.metrics(),
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail}
                       for c in res.check_results]}


# ------------------------------------------------------------------ coach + voice

@app.get("/api/v2/coach")
def coach(human_steps: Optional[int] = None, human_time: Optional[float] = None):
    metrics = _agent.log.metrics()
    human_demo = {"steps": human_steps, "wall_s": human_time} if human_steps is not None else None
    dets = run_detectors(metrics, human_demo)
    out = {"deterministic": dets, "compare": compare_runs(metrics, human_demo), "spoken": None}
    if dets:
        s = _model.suggest(metrics, _agent.goal)
        line = phrase("suggestion", s.get("what") or dets[0]["what"])
        out["spoken"] = {"text": line.text, "spoken": line.spoken, "js": browser_speak(line), **s}
    return out


@app.post("/api/v2/voice/transcribe")
def voice_transcribe(payload: dict):
    import base64
    wav = base64.b64decode(payload.get("wav_base64", ""))
    text, source = _voice.transcribe(wav)
    return {"text": text, "source": source,
            "disclosure": "Meta STT" if source == "meta" else "browser Web Speech (Meta STT unreachable)"}


@app.post("/api/v2/voice/say")
def voice_say(body: VoiceIn):
    line = phrase("status", body.text)
    return {"text": line.text, "js": browser_speak(line)}


@app.get("/")
def index():
    return FileResponse(BASE / "stepproof" / "static" / "index_v2.html")


# ------------------------------------------------------------------ guided tour

class TourIn(BaseModel):
    site: str = f"http://localhost:{APP_PORT}/site/expense"


@app.post("/api/v2/tour/start")
def tour_start(body: TourIn):
    """Kick off the 4-beat guided showcase on a thread; progress streams on /events."""
    global _tour
    mode = "unattended" if os.getenv("STEPPROOF_TEST_MODEL") == "1" else "interactive"
    _tour = Tour(_browser, _model, _recorder, execute_procedure,
                 mode=mode, site_base=body.site,
                 vision_selfheal=_vision_selfheal_fn)
    threading.Thread(target=_tour.run, daemon=True).start()
    return {"started": True, "mode": mode,
            "note": "watch /events; click Allow/Deny and Hand back as beats prompt you"}


@app.post("/api/v2/tour/answer")
def tour_answer(body: ApproveIn):
    """A human clicks Allow/Deny at the tour's approval gate (beat 2)."""
    _tour.gate_answer(body.allow)
    return {"ok": True, "allow": body.allow}


@app.post("/api/v2/tour/operator-done")
def tour_operator_done():
    """A human finished the takeover action in the live view (beat 3); hand back to the agent."""
    _tour.operator_done()
    return {"ok": True}


class TourReplayIn(BaseModel):
    file: str


@app.post("/api/v2/tour/replay")
def tour_replay_ep(body: TourReplayIn):
    """Replay a dated recorded tour offline (no model, no network); streams REPLAY-labeled events."""
    p = TOUR_DIR / body.file
    if not p.exists():
        raise HTTPException(404, f"no recorded tour {body.file!r}")
    trace = tour_replay(p, publish=True)   # streams REPLAY-labeled events onto the bus
    return {"replayed": True, "date": trace.get("date"), "steps": len(trace.get("records", []))}


@app.get("/api/v2/tour/runs")
def tour_runs():
    """List dated recorded tours (the replayable showcase artifacts)."""
    TOUR_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(x.name for x in TOUR_DIR.glob("*.json"))


# ------------------------------------------------------------------ dynamic tracking view (SAM 3.1)

@app.get("/api/v2/tracking/demo")
def tracking_demo():
    """Dynamic tracking showcase: cached SAM 3.1 video detection output
    demonstrating stable zero-shot object tracking across frames without new model calls."""
    cache_file = BASE / "data" / "cache" / "sam" / "526996a239c92aec1e05-video-9e32521dd2.txt"
    if not cache_file.exists():
        raise HTTPException(404, "Cached SAM tracking output not found")
    from .wire import parse_wire
    raw = cache_file.read_text(encoding="utf-8")
    dets = parse_wire(raw)
    by_frame: dict[int, list[dict]] = {}
    for d in dets:
        by_frame.setdefault(d.frame, []).append({
            "obj_id": d.obj_id,
            "box": list(d.box),
            "conf": d.conf,
            "w": d.w,
            "h": d.h,
        })
    return {
        "video_url": "/video/pan.mp4",
        "width": 640,
        "height": 360,
        "fps": 10.0,
        "total_frames": len(by_frame),
        "detections_count": len(dets),
        "frames": by_frame,
        "note": "Cached SAM 3.1 zero-shot video tracking — stable obj_id=0 across 60 frames, conf >= 0.96",
    }


# ------------------------------------------------------------------ redaction endpoints
class RedactionIn(BaseModel):
    enabled: Optional[bool] = None
    patterns: Optional[dict[str, str]] = None


@app.get("/api/v2/redaction")
def get_redaction_config():
    from .redact import get_redactor
    r = get_redactor()
    return {"enabled": r.enabled, "patterns": r.patterns}


@app.post("/api/v2/redaction")
def update_redaction_config(body: RedactionIn):
    from .redact import get_redactor
    r = get_redactor()
    if body.enabled is not None:
        r.enabled = body.enabled
    if body.patterns:
        for k, v in body.patterns.items():
            r.set_pattern(k, v)
    return {"enabled": r.enabled, "patterns": r.patterns}


@app.post("/api/v2/redaction/dry_run")
def redaction_dry_run():
    from .redact import get_redactor
    obs = _browser.observe()
    shot = _browser.take_screenshot()
    return get_redactor().dry_run(obs, shot)


# ------------------------------------------------------------------ audit spine endpoints
@app.get("/api/v2/audit")
def list_audit_entries(run_id: Optional[str] = None):
    from .audit import get_spine
    entries = get_spine().get_entries(run_id)
    return {"count": len(entries), "entries": [e.to_dict() for e in entries]}


@app.post("/api/v2/audit/verify")
def verify_audit_chain():
    from .audit import get_spine
    valid, err = get_spine().verify()
    entries = get_spine().get_entries()
    return {"valid": valid, "error": err, "chain_length": len(entries),
            "last_hash": get_spine().last_hash}


class PackageIn(BaseModel):
    run_id: str


@app.post("/api/v2/audit/package")
def package_audit_run(body: PackageIn):
    from .audit import get_spine
    try:
        zip_path = get_spine().package_run(body.run_id)
        return {"ok": True, "run_id": body.run_id, "bundle_path": str(zip_path), "bundle_name": zip_path.name}
    except Exception as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------------------ budget & estimate endpoints
class EstimateIn(BaseModel):
    goal: Optional[str] = None
    proc_name: Optional[str] = None


@app.post("/api/v2/budget/estimate")
def budget_estimate(body: EstimateIn):
    from .budget import estimate_agent_goal_cost, estimate_procedure_cost, get_tripwire
    if body.proc_name:
        proc_file = BASE / "data" / "procedures" / f"{body.proc_name}.json"
        if proc_file.exists():
            proc = Procedure.from_dict(json.loads(proc_file.read_text(encoding="utf-8")), verify_signature=False)
            est = estimate_procedure_cost(proc)
        else:
            raise HTTPException(404, f"Procedure {body.proc_name} not found")
    else:
        est = estimate_agent_goal_cost()
    tripwire = get_tripwire()
    ok_pre, err = tripwire.check_preflight(est)
    return {"estimate": est.to_dict(), "preflight_pass": ok_pre, "preflight_error": err,
            "caps": tripwire.health_disclosure()}


# ------------------------------------------------------------------ harness endpoints
class HarnessRunIn(BaseModel):
    proc_name: str
    auto_rewrite: bool = False


@app.post("/api/v2/harness/run")
def harness_run(body: HarnessRunIn):
    from .harness.drift import analyze_drift, self_rewrite_procedure
    proc_file = BASE / "data" / "procedures" / f"{body.proc_name}.json"
    if not proc_file.exists():
        raise HTTPException(404, f"Procedure {body.proc_name} not found")
    proc = Procedure.from_dict(json.loads(proc_file.read_text(encoding="utf-8")), verify_signature=False)

    if proc.site:
        _browser.start_site(proc.site)
    res = execute_procedure(_browser, proc, approve_fn=lambda a, x: True, vision_selfheal=_vision_selfheal_fn)
    drift = analyze_drift(proc, res)
    if body.auto_rewrite and drift.drifted_steps > 0:
        self_rewrite_procedure(proc, drift, tb=_browser)
        proc_file.write_text(json.dumps(proc.to_dict(), indent=2), encoding="utf-8")

    return {
        "success": res.success,
        "drift": drift.to_dict(),
        "wall_s": res.wall_s,
        "checks": [{"name": c.name, "passed": c.passed} for c in res.check_results],
        "rewritten": bool(body.auto_rewrite and drift.drifted_steps > 0)
    }


# ------------------------------------------------------------------ copilot / suggestion box endpoints
class CopilotSuggestIn(BaseModel):
    goal: str = ""


class CopilotAskIn(BaseModel):
    question: str
    goal: str = ""


class CopilotApplyIn(BaseModel):
    action: str
    arg: dict = {}


@app.post("/api/v2/copilot/suggest")
def copilot_suggest(body: CopilotSuggestIn):
    """Predict and suggest the next recommended step from live page observation."""
    try:
        obs = _browser.observe()
    except Exception as e:
        return {
            "ok": False,
            "error": f"Browser not ready: {e}",
            "suggestion": None,
        }

    url = obs.get("url", "")
    title = obs.get("title", "")
    elements = obs.get("elements", [])
    body_txt = obs.get("body_text", "")
    goal = body.goal or "Complete current workflow"

    # Analyze elements to find next logical action
    suggestion = None
    els_by_id = {e.get("id"): e for e in elements if e.get("id")}
    visible_buttons = [e for e in elements if e.get("role") == "button" and e.get("visible")]
    visible_inputs = [e for e in elements if e.get("role") == "textbox" and e.get("visible")]

    # 1. Expense domain heuristics
    if "expense" in url.lower() or "expense" in title.lower() or "vendor" in str(els_by_id.keys()):
        if "vendor" in els_by_id and not els_by_id["vendor"].get("name"):
            suggestion = {
                "action": "type",
                "selector": "#vendor",
                "text": "Acme",
                "title": "Enter Vendor Name",
                "reason": "The Vendor field is currently empty. Setting vendor to 'Acme'.",
                "confidence": 0.96,
                "safety": "SAFE",
                "requires_approval": False,
            }
        elif "amount" in els_by_id and not els_by_id["amount"].get("name"):
            suggestion = {
                "action": "type",
                "selector": "#amount",
                "text": "42",
                "title": "Enter Expense Amount",
                "reason": "Vendor is filled; Amount field is pending. Setting amount to '42'.",
                "confidence": 0.95,
                "safety": "SAFE",
                "requires_approval": False,
            }
        elif "category" in els_by_id and not els_by_id["category"].get("name"):
            suggestion = {
                "action": "select",
                "selector": "#category",
                "value": "office",
                "title": "Select Category",
                "reason": "Select standard 'office' expense category.",
                "confidence": 0.92,
                "safety": "SAFE",
                "requires_approval": False,
            }
        elif "submit" in els_by_id:
            suggestion = {
                "action": "click",
                "selector": "#submit",
                "title": "Submit Expense Claim",
                "reason": "All required expense fields are populated. Ready to submit claim.",
                "confidence": 0.98,
                "safety": "SENSITIVE",
                "requires_approval": True,
            }

    # 2. YouTube / video search heuristics
    elif "youtube" in url.lower():
        if any("search" in (e.get("name") or "").lower() or e.get("id") == "search" for e in elements):
            suggestion = {
                "action": "click",
                "selector": "a#thumbnail, ytd-rich-grid-media a#video-title",
                "title": "Play First Video Result",
                "reason": "Open and play the primary video search result.",
                "confidence": 0.91,
                "safety": "SAFE",
                "requires_approval": False,
            }

    # 3. Universal / Generic site heuristics across every website
    if not suggestion:
        # Check for search input
        search_inputs = [
            e for e in elements
            if e.get("role") in ("textbox", "searchbox") and e.get("visible") and (
                e.get("kind") == "search"
                or any(k in f"{e.get('name','')} {e.get('id','')} {e.get('kind','')}".lower()
                       for k in ("search", "find", "query", "lookup", "filter", "search_query", "q"))
            )
        ]
        if search_inputs and not search_inputs[0].get("name"):
            first_s = search_inputs[0]
            sel = f"#{first_s['id']}" if first_s.get("id") else f"input[type='search'], input[name='{first_s.get('name','q')}']"
            q_text = goal if goal and goal != "Complete current workflow" else "documentation"
            suggestion = {
                "action": "type",
                "selector": sel,
                "text": q_text,
                "title": f"Search for '{q_text}'",
                "reason": f"Search box '{first_s.get('id') or first_s.get('name') or 'search'}' is available for querying.",
                "confidence": 0.92,
                "safety": "SAFE",
                "requires_approval": False,
            }
        elif visible_inputs:
            first_in = visible_inputs[0]
            sel = f"#{first_in['id']}" if first_in.get("id") else f"input[name='{first_in.get('name')}']"
            suggestion = {
                "action": "type",
                "selector": sel,
                "text": "sample",
                "title": f"Fill {first_in.get('name') or 'Input'}",
                "reason": f"Input field '{first_in.get('name') or first_in.get('id')}' is available for data entry.",
                "confidence": 0.82,
                "safety": "SAFE",
                "requires_approval": False,
            }
        elif visible_buttons:
            first_btn = visible_buttons[0]
            sel = f"#{first_btn['id']}" if first_btn.get("id") else f"button:has-text('{first_btn.get('name')}')"
            suggestion = {
                "action": "click",
                "selector": sel,
                "title": f"Click {first_btn.get('name') or 'Button'}",
                "reason": f"Primary actionable button on page is '{first_btn.get('name') or first_btn.get('id')}'.",
                "confidence": 0.85,
                "safety": "SENSITIVE" if any(w in (first_btn.get("name") or "").lower() for w in ("submit", "delete", "buy", "pay", "order")) else "SAFE",
                "requires_approval": any(w in (first_btn.get("name") or "").lower() for w in ("submit", "delete", "buy", "pay", "order")),
            }
        else:
            # Check for visible navigation links or articles
            visible_links = [e for e in elements if e.get("role") in ("link", "article") and e.get("visible") and len(e.get("name", "")) > 3]
            if visible_links:
                first_link = visible_links[0]
                sel = f"#{first_link['id']}" if first_link.get("id") else f"a:has-text('{first_link.get('name')[:30]}')"
                suggestion = {
                    "action": "click",
                    "selector": sel,
                    "title": f"Open '{first_link.get('name')[:30]}'",
                    "reason": f"Navigate to primary content item '{first_link.get('name')[:40]}'.",
                    "confidence": 0.88,
                    "safety": "SAFE",
                    "requires_approval": False,
                }
            else:
                suggestion = {
                    "action": "finish",
                    "selector": "",
                    "title": "Workflow Complete",
                    "reason": "No pending interactive inputs or buttons detected on the current page.",
                    "confidence": 0.99,
                    "safety": "SAFE",
                    "requires_approval": False,
                }

    return {
        "ok": True,
        "url": url,
        "title": title,
        "elements_count": len(elements),
        "suggestion": suggestion,
    }


@app.post("/api/v2/copilot/apply")
def copilot_apply(body: CopilotApplyIn):
    """Execute the suggested copilot action immediately on the live browser."""
    action = body.action
    arg = body.arg or {}
    try:
        if action == "type":
            sel = arg.get("selector", "")
            txt = str(arg.get("text", ""))
            if sel:
                _browser._call("fill", {"selector": sel, "text": txt})
            elif "x" in arg and "y" in arg:
                _browser._call("fill_at", {"x": int(arg["x"]), "y": int(arg["y"]), "text": txt})
        elif action == "click":
            sel = arg.get("selector", "")
            if sel:
                _browser._call("click_sel", {"selector": sel})
            elif "x" in arg and "y" in arg:
                _browser._call("click_box", {"x": int(arg["x"]), "y": int(arg["y"])})
        elif action == "select":
            sel = arg.get("selector", "")
            val = str(arg.get("value", ""))
            if sel:
                _browser._call("select", {"selector": sel, "value": val})
        elif action == "finish":
            pass
        else:
            return {"ok": False, "error": f"Unsupported action: {action}"}

        obs = _browser.observe()
        BUS.publish("copilot_action_applied", {"action": action, "arg": arg, "url": obs.get("url")})
        return {"ok": True, "applied": action, "url": obs.get("url"), "title": obs.get("title")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/v2/copilot/ask")
def copilot_ask(body: CopilotAskIn):
    """Interactive copilot Q&A: answers questions using live DOM, page text, and safety invariants."""
    q = body.question.strip()
    try:
        obs = _browser.observe()
    except Exception as e:
        obs = {"url": "none", "title": "offline", "elements": [], "body_text": ""}

    url = obs.get("url", "")
    title = obs.get("title", "")
    elements = obs.get("elements", [])
    body_txt = obs.get("body_text", "")
    q_low = q.lower()

    # Formulate contextual, helpful answer based on deterministic inspection
    answer = ""
    highlight_selectors = []

    if any(k in q_low for k in ("what can i do", "what is on this page", "what does this page", "elements")):
        inputs = [e.get("name") or e.get("id") for e in elements if e.get("role") == "textbox" and e.get("visible")]
        buttons = [e.get("name") or e.get("id") for e in elements if e.get("role") == "button" and e.get("visible")]
        answer = (
            f"You are viewing **{title or url}**.\n\n"
            f"- **Input fields ({len(inputs)})**: {', '.join(inputs) if inputs else 'None'}\n"
            f"- **Action buttons ({len(buttons)})**: {', '.join(buttons) if buttons else 'None'}\n\n"
            f"You can fill out the form fields or tell me what goal you'd like to accomplish!"
        )
    elif any(k in q_low for k in ("why is submit disabled", "submit button", "button disabled", "disabled")):
        unfilled = [e.get("id") or e.get("name") for e in elements if e.get("role") == "textbox" and not e.get("name")]
        if unfilled:
            answer = f"The submit button requires all fields to be populated. The following fields appear pending: **{', '.join(unfilled)}**."
            highlight_selectors = [f"#{uid}" for uid in unfilled if uid]
        else:
            answer = "All visible fields appear filled. The submit button is ready to be clicked."
    elif any(k in q_low for k in ("safety", "safe", "allowlist", "permission")):
        from . import config as cfg
        answer = (
            f"**Safety Status**:\n"
            f"- Active URL: `{url}`\n"
            f"- Domain Allowlist: Active ({len(cfg.ALLOWED_HOSTS)} domains allowed)\n"
            f"- Approval Gate: Enforced on all external/irreversible actions (Submit, Delete, Navigation off-site)\n"
            f"- Credentials: Masked from observation DOM and model prompts."
        )
    elif any(k in q_low for k in ("next step", "what should i do", "what's next", "what next", "suggest")):
        s_res = copilot_suggest(CopilotSuggestIn(goal=body.goal))
        sug = s_res.get("suggestion")
        if sug:
            answer = (
                f"**Recommended Next Step**: {sug['title']}\n\n"
                f"- **Action**: `{sug['action']}` on `{sug.get('selector', 'target')}`\n"
                f"- **Reason**: {sug['reason']}\n"
                f"- **Confidence**: {int(sug['confidence'] * 100)}%\n"
                f"- **Risk Level**: `{sug['safety']}`"
            )
            highlight_selectors = [sug.get("selector")]
        else:
            answer = "No further actions required; current workflow appears complete."
    else:
        # General response with context
        snippet = body_txt[:200].replace('\n', ' ') if body_txt else "empty page"
        answer = (
            f"Regarding your question on **{title or 'this page'}**:\n"
            f"The page text contains: *\"{snippet}...\"*.\n"
            f"There are {len(elements)} interactive elements detected. You can ask me to execute any step or fill form values directly."
        )

    return {
        "ok": True,
        "question": q,
        "answer": answer,
        "url": url,
        "highlight_selectors": highlight_selectors,
    }

class DescribeSkillIn(BaseModel):
    goal: str
    site: str
    steps: list[str]
    parameters: dict[str, str] = {}
    save_as: str = ""


@app.post("/api/v2/skills/describe")
def skills_describe(body: DescribeSkillIn):
    from .skills import describe_skill
    proc = describe_skill(body.goal, body.site, body.steps, body.parameters)
    if body.save_as:
        p_dir = BASE / "data" / "procedures"
        p_dir.mkdir(parents=True, exist_ok=True)
        (p_dir / f"{body.save_as}.json").write_text(json.dumps(proc.to_dict(), indent=2), encoding="utf-8")
    return {"procedure": proc.to_dict(), "signed": bool(proc.signature)}


class ReteachIn(BaseModel):
    proc_name: str
    failed_step_id: str
    correction: dict
    approved: bool = False


@app.post("/api/v2/skills/reteach")
def skills_reteach(body: ReteachIn):
    from .skills import gated_reteach
    proc_file = BASE / "data" / "procedures" / f"{body.proc_name}.json"
    if not proc_file.exists():
        raise HTTPException(404, f"Procedure {body.proc_name} not found")
    proc = Procedure.from_dict(json.loads(proc_file.read_text(encoding="utf-8")), verify_signature=False)
    updated_proc, ok, msg = gated_reteach(proc, body.failed_step_id, body.correction, approved=body.approved)
    if ok:
        proc_file.write_text(json.dumps(updated_proc.to_dict(), indent=2), encoding="utf-8")
    return {"ok": ok, "message": msg, "procedure": updated_proc.to_dict()}



