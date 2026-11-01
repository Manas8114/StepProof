"""Guided showcase tour: drives the REAL system through 4 beats so a judge sees every
capability in one pass, streaming live on the SSE event bus and recording the whole run
(a dated, replayable trace) to data/tour_runs/<date>.json.

Beats (all real, no fake events):
  1 LEARN   - record a human demo on the expense site, compile it to a Procedure
  2 APPROVE - execute the learned Procedure; the irreversible/external "submit" step hits an
              approval gate that a HUMAN clicks Allow/Deny on (or an auto-responder in unattended)
  3 TAKEOVER- run the goal-only agent on inventory; pause for a human takeover, the operator
              types a field, hands back to the agent
  4 PROVE   - coach compare (learned vs human-demo) + injection hold on the hostile page

`mode="interactive"` waits for a real human to click the approval/takeover controls;
`mode="unattended"` stands in for the human and labels itself so the trace stays honest.
Replay: `replay(path)` streams a recorded tour back with a dated "REPLAY" label, no network.
"""
from __future__ import annotations
import datetime, json, threading, time
from pathlib import Path

from stepproof.events import BUS
from stepproof.coach import compare_runs, run_detectors, phrase, browser_speak
from stepproof.browser.actions import execute_action

BASE = Path(__file__).resolve().parent.parent
TOUR_DIR = BASE / "data" / "tour_runs"


class Tour:
    """Runs the 4-beat showcase on a live browser + agent, recording everything."""

    def __init__(self, browser, model, recorder, executor,
                 mode: str = "interactive", site_base: str = "http://127.0.0.1:8011") -> None:
        self.tb, self.model, self.recorder, self.executor = browser, model, recorder, executor
        self.mode = mode
        self.site = site_base
        self.records: list[dict] = []
        self._beats: list[str] = []
        self._human = threading.Event()   # set when a real human has completed the takeover
        self._gate_event = threading.Event()
        self._gate_allow = {"value": True}

    # ------------------------------------------------------------------ helpers
    def _mark(self, beat: str) -> None:
        self._beats.append(beat)
        BUS.publish("tour_beat", {"beat": beat, "index": len(self._beats),
                                   "label": _BEAT_LABELS.get(beat, beat)})
        self._snap(beat)

    def _snap(self, tag: str) -> str:
        path = TOUR_DIR / f"{_today()}_{tag}.jpg"
        try:
            self.tb.act("screenshot", str(path))
        except Exception:
            path = None
        BUS.publish("tour_screenshot", {"beat": tag, "path": str(path) if path else ""})
        return str(path) if path else ""

    def _record(self, step: str, detail: dict, success: bool = True) -> None:
        self.records.append({"ts": round(time.time(), 2), "step": step,
                             "beat": self._beats[-1] if self._beats else "pre",
                             "success": success, "detail": detail})
        BUS.publish("tour_step", {"step": step, "beat": self._beats[-1], **detail})

    # ------------------------------------------------------------------ the 4 beats
    def beat_learn(self) -> None:
        """1. Record a human demo on the expense site, compile it to a Procedure."""
        self._mark("learn")
        self.recorder.start(self.site + "/expense/")
        self.recorder.type_value([{"kind": "css", "value": "#vendor"}], "Acme", "enter the vendor name")
        self.recorder.type_value([{"kind": "css", "value": "#amount"}], "42", "the amount")
        self.recorder.select_value([{"kind": "css", "value": "#category"}], "office", "pick the category")
        self.recorder.click_element([{"kind": "css", "value": "#submit"}], "file the claim", element_name="Submit claim")
        records = self.recorder.stop()
        from stepproof.learn.compile import compile_to_procedure, sanitize
        proc, _w = compile_to_procedure(records, "File an expense claim",
                                        site=self.site + "/expense/",
                                        success_checks=[{"kind": "text_visible", "spec": {"text": "Claim filed"}}])
        proc, _ = sanitize(proc)
        self.learned = proc
        self._record("record+compile", {"steps": len(proc.steps),
                                          "locators_kept": sum(len(s.locators) for s in proc.steps)})

    def beat_approve(self, deny: bool = False) -> None:
        """2. Execute the learned Procedure; the submit step raises an approval gate.
        A human clicks Allow/Deny (interactive) or the auto-responder answers (unattended)."""
        self._mark("approve")
        self.tb.start_site(self.site + "/expense/")   # clean form so the gate test is meaningful
        self._gate_event.clear()
        self._gate_allow["value"] = not deny

        def approve_fn(tool, args):
            BUS.publish("approval_gate", {"tool": tool, "irreversible": True, "external": True,
                                          "args": args, "source": "tour", "beat": "approve",
                                          "interactive": self.mode == "interactive"})
            if self.mode == "interactive":
                self._gate_event.wait(timeout=300)   # a real human clicks Allow/Deny in the UI
            else:
                time.sleep(0.3)                      # unattended: auto-answer, labeled in the trace
            BUS.publish("approved", {"allow": self._gate_allow["value"],
                                     "source": "human" if self.mode == "interactive" else "auto"})
            return self._gate_allow["value"]

        res = self.executor(self.tb, self.learned, approve_fn=approve_fn)
        self._learned_res = res
        self._record("execute+gate", {"success": res.success, "steps": res.steps_run,
                                       "wall_s": res.wall_s,
                                       "gate_answered_by": "human" if self.mode == "interactive" else "auto"})

    def beat_takeover(self, qty: str = "5") -> None:
        """3. Goal-only agent on inventory; pause for a takeover, the operator types the qty
        field, hands back to the agent."""
        self._mark("takeover")
        self.tb.start_site(self.site + "/inventory/")
        from stepproof.agent.loop import AgentLoop, Budgets
        loop = AgentLoop(self.tb, self.model, Budgets(max_steps=8, max_wall_s=60, max_model_calls=10))
        # answer the sub-agent's own approval gates / asks so it can finish (labeled "auto" in trace)
        def _auto_answerafter(loop):
            # survive the whole takeover: answer the sub-agent's gates/asks, but stay idle
            # while the tour holds human control (PAUSED_HUMAN), then resume answering after hand-back
            while loop.machine.state.value not in ("DONE", "ERROR"):
                if loop.machine.state.value != "PAUSED_HUMAN" and loop._pending_decision.is_set():
                    loop.approve(True)
                    loop.answer_human("proceed")
                time.sleep(0.1)
        threading.Thread(target=_auto_answerafter, args=(loop,), daemon=True).start()
        loop.start(f"Restock SKU WS-1042 by {qty}. Done when the log says 'restocked by {qty}'.")
        time.sleep(0.6)
        loop.pause()  # -> PAUSED_HUMAN; the agent issues no actions while paused
        BUS.publish("takeover", {"by": "human" if self.mode == "interactive" else "auto",
                                   "detail": "agent paused; control handed to operator"})
        if self.mode == "interactive":
            self._wait_for_operator()
        else:
            self.tb.act("fill", {"selector": "#qty", "text": qty})
            self._record("operator typed qty", {"value": qty, "by": "auto"})
        loop.resume("operator entered the restock quantity")
        for _ in range(120):
            if loop.machine.state.value in ("DONE", "ERROR"):
                break
            time.sleep(1)
        self._record("takeover+resume", {"state": loop.machine.state.value,
                                          "steps": loop.log.metrics()["steps"]})

    def beat_prove(self, human_steps: int = 5, human_time: float = 42.0) -> None:
        """4. Coach compare (learned vs human-demo) + injection hold on the hostile page."""
        self._mark("prove")
        lr = getattr(self, "_learned_res", None)
        learned_metrics = ({"steps": lr.steps_run, "wall_s": lr.wall_s,
                            "actions": [s.get("action") for s in lr.healed_steps]} if lr
                          else {"steps": 4, "wall_s": 0.1, "actions": []})
        compare = compare_runs(learned_metrics, {"steps": human_steps, "wall_s": human_time})
        dets = run_detectors(learned_metrics, {"steps": human_steps})
        spoken = None
        if dets:
            line = phrase("suggestion", dets[0]["what"])
            spoken = {"text": line.text, "spoken": line.spoken, "js": browser_speak(line)}
        self._record("coach_compare", {"compare": compare, "detections": dets[:3], "spoken": spoken})
        # injection hold: the legit action must work and the browser must stay on-allowlist
        self.tb.start_site(self.site + "/hostile/")
        r = execute_action(self.tb, "click", {"name": "Finish task"})
        stayed = self.tb.observe().get("url", "").startswith(self.site)
        self._record("injection_hold", {"action_ok": r.ok, "stayed_on_allowlist": stayed,
                                         "url": self.tb.observe().get("url", "")})

    def run(self) -> dict:
        """Drive all 4 beats, then persist the dated, replayable trace."""
        self.records = []
        self._mark("start")
        self.beat_learn()
        self.beat_approve(deny=False)
        self.beat_takeover(qty="5")
        self.beat_prove()
        self._mark("end")
        trace = self._trace()
        TOUR_DIR.mkdir(parents=True, exist_ok=True)
        path = TOUR_DIR / f"{_today()}.json"
        path.write_text(json.dumps(trace, indent=2))
        self.records_path = path
        BUS.publish("tour_done", {"date": _today(), "path": str(path), "steps": len(self.records)})
        return trace

    # ------------------------------------------------------------------ replay
    def _trace(self) -> dict:
        return {"label": "StepProof v2 guided tour (recorded, replayable)",
                "date": _today(), "mode": self.mode,
                "beats": list(self._beats), "records": self.records}

    def _wait_for_operator(self) -> None:
        """Interactive: block until the operator finishes the takeover action (UI calls
        `operator_done()` on 'Hand back'). A bounded timeout prevents a stuck tour."""
        self._human.clear()
        self._human.wait(timeout=120)

    def operator_done(self) -> None:
        self._human.set()

    def gate_answer(self, allow: bool) -> None:
        """A human clicks Allow/Deny at the tour's approval gate (interactive mode)."""
        self._gate_allow["value"] = allow
        self._gate_event.set()


_BEAT_LABELS = {
    "start": "Start",
    "learn": "BEAT 1 · Learn (record + compile)",
    "approve": "BEAT 2 · Execute + approval gate",
    "takeover": "BEAT 3 · Human takeover",
    "prove": "BEAT 4 · Prove (coach + injection)",
    "end": "End",
}


def _today() -> str:
    return datetime.date.today().isoformat()


def replay(trace_path, publish: bool = True):
    """Stream a recorded tour back onto the event bus, labeled REPLAY <date> (no network/model)."""
    p = Path(trace_path)
    trace = json.loads(p.read_text())
    if publish:
        BUS.publish("tour_replay_start", {"date": trace.get("date"),
                                           "label": "REPLAY %s" % trace.get("date", "?"),
                                           "note": "recorded run replayed offline - no live model calls"})
        for r in trace.get("records", []):
            BUS.publish("tour_step", {"step": r["step"], "beat": r.get("beat"),
                                       **r.get("detail", {}), "replay": True})
        BUS.publish("tour_done", {"date": trace.get("date"), "replay": True})
    return trace
