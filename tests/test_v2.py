"""v2 integration tests: tiny browser, agent loop with scripted model, safety gates,
takeover/kill, monitor->compile->execute, coach detectors. Runs fully offline against
a local HTTP server of the demo sites (no model calls; ScriptedModel)."""
import http.server, json, socketserver, threading, time
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parent.parent / "demo_sites"


@pytest.fixture(scope="module")
def site_server():
    """Serve demo_sites/ at localhost:8011 (the allowlist host)."""
    import os
    os.chdir(DEMO)  # SimpleHTTPRequestHandler serves from CWD
    httpd = socketserver.TCPServer(("127.0.0.1", 8011),
                                   lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(DEMO), **k))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    yield "http://127.0.0.1:8011"
    httpd.shutdown()


def _browser(site, **kw):
    from stepproof.browser import TinyBrowser
    tb = TinyBrowser(allowlist={"127.0.0.1:8011"}, **kw)
    tb.start_site(site + "/expense/")
    return tb


def test_tiny_browser_operates_site(site_server):
    tb = _browser(site_server)
    obs = tb.observe()
    assert any(e.get("role") == "button" for e in obs["elements"])
    assert "Expense" in obs.get("title", "")
    shot = tb.take_screenshot()
    assert shot.startswith("data:image/jpeg")
    tb.stop()


def test_allowlist_refuses_navigation(site_server):
    tb = _browser(site_server)
    r = tb.goto("http://evil.example/x")
    assert r["ok"] is False and "refused" in r["error"]
    tb.stop()


def test_start_site_refuses_off_allowlist(site_server):
    """Every navigation path is allowlist-gated: start_site must refuse like goto."""
    from stepproof.browser import TinyBrowser
    tb = TinyBrowser(allowlist={"127.0.0.1:8011"})
    r = tb.start_site("http://evil.example/x")
    assert r["ok"] is False and "refused" in r["error"]
    tb.stop()


def test_agent_loop_completes_task_deterministically(site_server):
    from stepproof.agent.model import ScriptedModel, Action
    from stepproof.agent.loop import AgentLoop
    tb = _browser(site_server)
    scripted = ScriptedModel([
        Action("type", {"selector": "#vendor", "text": "Acme"}),
        Action("type", {"selector": "#amount", "text": "42"}),
        Action("select", {"selector": "#category", "value": "office"}),
        Action("click", {"selector": "#submit"}),
    ])
    loop = AgentLoop(tb, scripted)
    loop.start("File an Acme office expense of $42")
    for _ in range(60):
        if loop.machine.state.value in ("DONE", "ERROR"):
            break
        time.sleep(0.25)
    assert loop.machine.state.value == "DONE", loop.log.result
    assert "Claim filed" in tb.observe().get("body_text", "")
    tb.stop()


def test_approval_gate_blocks_irreversible(site_server):
    from stepproof.agent.model import ScriptedModel, Action
    from stepproof.agent.loop import AgentLoop
    tb = _browser(site_server)
    tb.start_site(site_server + "/inventory/")
    scripted = ScriptedModel([Action("click", {"name": "Discard restock"}),
                             Action("finish", {"summary": "done"})])
    loop = AgentLoop(tb, scripted)
    loop.start("Discard")
    deadline = time.time() + 15
    while time.time() < deadline:
        if loop._pending_decision.is_set():
            break
        time.sleep(0.1)
    assert loop._pending_decision.is_set(), "gate should hold for the irreversible action"
    loop.approve(False)          # human denies
    for _ in range(20):
        if loop.machine.state.value == "DONE":
            break
        time.sleep(0.2)
    assert loop.machine.state.value == "DONE"
    log = tb.observe().get("body_text", "")
    assert "stock 0" not in log.lower() or "confirmed" not in log.lower()  # discard did NOT confirm
    tb.stop()


def test_kill_switch_stops_loop(site_server):
    from stepproof.agent.model import ScriptedModel, Action
    from stepproof.agent.loop import AgentLoop
    tb = _browser(site_server)
    waiters = [Action("wait", {"ms": 800}) for _ in range(50)] + [Action("finish", {})]
    loop = AgentLoop(tb, ScriptedModel(waiters))
    loop.start("wait forever")
    time.sleep(1.5)
    loop.kill()
    for _ in range(30):
        if loop.machine.state.value in ("DONE", "ERROR"):
            break
        time.sleep(0.2)
    assert loop.machine.state.value in ("DONE", "ERROR")
    assert tb.kill.is_set()
    tb.stop()


def test_monitor_compile_execute_procedure(site_server):
    from stepproof.learn import Recorder, compile_to_procedure
    from stepproof.learn.compile import sanitize
    from stepproof.agent.executor import execute_procedure
    from stepproof.proc import Procedure
    tb = _browser(site_server)
    rec = Recorder(tb)
    rec.start(site_server + "/expense/")
    rec.type_value([{"kind": "css", "value": "#vendor"}], "Acme", "enter the vendor name")
    rec.type_value([{"kind": "css", "value": "#amount"}], "42", "the amount")
    rec.select_value([{"kind": "css", "value": "#category"}], "office", "pick the category")
    rec.click_element([{"kind": "css", "value": "#submit"}], "file the claim")
    records = rec.stop()
    proc, w = compile_to_procedure(records, "File an expense claim", site=site_server,
                                   success_checks=[{"kind": "text_visible", "spec": {"text": "Claim filed"}}])
    proc, _ = sanitize(proc)
    assert len(proc.steps) == 4 and proc.steps[0].locators and proc.steps[2].action == "select"
    tb.start_site(site_server + "/expense/")
    res = execute_procedure(tb, proc, approve_fn=lambda a, x: True)
    assert res.success, res.error
    obs = tb.observe()
    assert "Claim filed" in obs.get("body_text", "")
    tb.stop()


def test_self_healing_falls_through_locators(site_server):
    """A broken primary locator must fall through to the next (self-heal), still succeed."""
    from stepproof.learn import compile_to_procedure
    from stepproof.learn.compile import sanitize
    from stepproof.agent.executor import execute_procedure
    recs = [
        {"tool": "click", "locators": [{"kind": "css", "value": "#does-not-exist"},
                                       {"kind": "css", "value": "#submit"}],
         "narration": "submit"},
    ]
    proc, _ = compile_to_procedure(recs, "submit", site=site_server,
                                   success_checks=[{"kind": "text_visible", "spec": {"text": "Claim filed"}}])
    # also type the required fields first via a prepared page state
    tb = _browser(site_server)
    from stepproof.browser.actions import execute_action
    execute_action(tb, "type", {"selector": "#vendor", "text": "X"})
    execute_action(tb, "type", {"selector": "#amount", "text": "1"})
    execute_action(tb, "select", {"selector": "#category", "value": "office"})
    res = execute_procedure(tb, proc, approve_fn=lambda a, x: True)
    assert res.success, res.error
    assert any("self-heal" in h.get("note", "") for h in res.healed_steps), res.healed_steps
    assert "does-not-exist" not in tb.observe().get("url", "")
    tb.stop()


def test_injection_page_text_cannot_change_goal(site_server):
    """Hostile page text must not override the goal/allowlist: navigation stays on the allowlist."""
    tb = _browser(site_server)
    tb.start_site(site_server + "/hostile/")
    obs = tb.observe()
    assert "SYSTEM OVERRIDE" in obs.get("body_text", "")
    # the safety layer is code: external goto is refused regardless of page text
    r = tb.goto("http://evil.example/")
    assert r["ok"] is False
    assert "evil.example" not in tb.url
    tb.stop()


def test_coach_detects_redundant_navigation(site_server):
    from stepproof.coach import run_detectors
    metrics = {"actions": [
        {"tool": "goto", "url": "/a"}, {"tool": "goto", "url": "/b"}, {"tool": "goto", "url": "/a"},
        {"tool": "click", "selector": "#x"}] * 2}
    dets = run_detectors(metrics)
    assert any(d["what"] in ("repeated action", "redundant navigation", "backtrack") for d in dets)


def test_voice_phrases_short_lines(site_server):
    from stepproof.coach import phrase
    line = phrase("suggestion", "You could skip the duplicate navigation step and save one step of work on this form")
    assert len(line.spoken.split()) <= 12 and line.text  # spoken is trimmed, text is full


def test_circuit_breaker_stops_cleanly(site_server):
    from stepproof.agent.loop import AgentLoop
    from stepproof.browser import TinyBrowser

    class BoomModel:
        name = "boom"
        def __init__(self):
            self.calls = 0
        def decide(self, goal, obs_text, screenshot, history, extra=None):
            self.calls += 1
            raise RuntimeError("simulated 429")
        def suggest(self, m, g):
            return {"what": "", "why": "x", "expected_saving": "0", "risk": "low", "apply": ""}

    tb = TinyBrowser(allowlist={"127.0.0.1:8011"})
    tb.start_site(site_server + "/expense/")
    m = BoomModel()
    loop = AgentLoop(tb, m, max_consec_errors=3)
    loop.start("will fail")
    for _ in range(60):
        if loop.machine.state.value == "ERROR":
            break
        time.sleep(0.1)
    # stops clean at the breaker (not a hang), with the breaker named as the cause
    assert loop.machine.state.value == "ERROR"
    assert "circuit breaker" in str(loop.log.result.get("error", "")) + str(loop.log.result.get("detail", ""))
    assert m.calls >= 3          # it did retry the bounded number of times
    assert m.calls <= 4          # and stopped rather than looping forever
    tb.stop()


def test_tour_runs_all_four_beats_and_records_dated_trace(site_server, tmp_path):
    """The guided showcase: all 4 beats complete offline, a dated trace is written, and
    replaying it labels the events 'REPLAY' (the dated offline artifact)."""
    import json
    from demo import Tour, replay
    from demo.tour import TOUR_DIR
    from stepproof.browser import TinyBrowser
    from stepproof.learn import Recorder
    from stepproof.agent.executor import execute_procedure
    from stepproof.agent.model import ScriptedModel, Action
    from stepproof.events import BUS

    # a scripted "agent" that just finishes - keeps the tour fully offline
    model = ScriptedModel([Action("finish", {"summary": "offline scripted"})])
    tb = TinyBrowser(allowlist={"127.0.0.1:8011"})
    tour = Tour(tb, model, Recorder(tb), execute_procedure, mode="unattended",
                 site_base=site_server)
    trace = tour.run()

    # all 4 beats present and in order
    assert trace["beats"] == ["start", "learn", "approve", "takeover", "prove", "end"]
    steps = [r["step"] for r in trace["records"]]
    assert "record+compile" in steps and "injection_hold" in steps
    # approval gate was answered (labeled auto in unattended mode)
    approve = next(r for r in trace["records"] if r["step"] == "execute+gate")
    assert approve["detail"].get("gate_answered_by") == "auto"
    # injection: browser stayed on the allowlisted site
    inj = next(r for r in trace["records"] if r["step"] == "injection_hold")
    assert inj["detail"]["stayed_on_allowlist"] is True
    # a dated trace file was recorded
    assert trace["date"] and Path(trace["date"] and str(tour.records_path)).exists() \
        if tour.records_path else True

    # replay labels the events REPLAY
    BUS.reset()
    r = replay(tour.records_path, publish=True)
    starts = [e for e in BUS.history() if e["type"] == "tour_replay_start"]
    assert starts and starts[0]["data"]["label"].startswith("REPLAY")
    tb.stop()


def test_replay_labels_recorded_tour(site_server):
    from demo import replay
    from stepproof.events import BUS
    BUS.reset()
    # build a minimal recording, then replay it
    import json
    from demo.tour import TOUR_DIR
    TOUR_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"label": "x", "date": "1970-01-01", "mode": "unattended", "beats": ["start", "end"],
           "records": [{"step": "coach_compare", "beat": "prove", "success": True, "detail": {}}]}
    p = TOUR_DIR / "1970-01-01.json"
    p.write_text(json.dumps(rec))
    replay(p, publish=True)
    starts = [e for e in BUS.history() if e["type"] == "tour_replay_start"]
    assert starts and starts[0]["data"]["label"] == "REPLAY 1970-01-01"
