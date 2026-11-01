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
import json
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
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

BASE = Path(__file__).parent.parent
DEMO = BASE / "demo_sites"
APP_PORT = 8011
ALLOW = {f"localhost:{APP_PORT}"}

# ------------------------------------------------------------------ runtime state
_browser = TinyBrowser(allowlist=ALLOW)
_model = MuseAgentModel()
_agent = AgentLoop(_browser, _model, Budgets())
_recorder = Recorder(_browser)
_voice = VoiceCompanion()
_proc_cache: dict[str, Procedure] = {}

app = FastAPI(title="StepProof v2")
for name in ("expense", "inventory", "hostile"):
    app.mount(f"/site/{name}", StaticFiles(directory=DEMO / name, html=True), name=name)


class GoalIn(BaseModel):
    goal: str
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
    return {"mode": cfg.PROVIDER_MODE, "agent_model": _model.name,
            "browser": "playwright-chromium", "allowlist": sorted(ALLOW),
            "states": ["IDLE", "PLANNING", "RUNNING", "PAUSED_HUMAN",
                        "AWAITING_APPROVAL", "DONE", "ERROR"]}


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


@app.post("/api/v2/browser/start")
def browser_start(site: GoalIn):
    r = _browser.start_site(site.site)
    return {"ok": bool(r.get("ok")), "url": _browser.url}


@app.get("/api/v2/browser/shot")
def browser_shot():
    return {"screenshot": _browser.take_screenshot(), "url": _browser.url, "title": _browser.title}


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
def agent_run(site: GoalIn):
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


# ------------------------------------------------------------------ monitor + execute

@app.post("/api/v2/monitor/start")
def monitor_start(site: GoalIn):
    _recorder.start(site.site)
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
        _browser.start_site(proc.site)
    res = execute_procedure(_browser, proc, approve_fn=lambda tool, args: body.approve)
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
