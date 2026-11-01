"""The agent loop: observe -> model tool-call -> safety gate -> act -> log.

Deterministic, model-free safety layer runs FIRST and can always escalate (never
downgrade). The model proposes; the loop and the state machine decide. Every action is
recorded with before/after state and a screenshot. Budgets (steps / wall time / model
calls) pause the run and ask when exceeded. The kill switch and a human pause are honoured
at the next action boundary."""
from __future__ import annotations
import json, threading, time
from dataclasses import dataclass, field
from typing import Optional

from ..events import BUS
from ..browser.actions import classify_action, execute_action
from ..browser.observe import elements_text
from .model import Action
from .state import State, StateMachine


@dataclass
class Budgets:
    max_steps: int = 40
    max_wall_s: int = 300
    max_model_calls: int = 60

    def exceeded(self, steps: int, wall: float, model_calls: int) -> Optional[str]:
        if steps >= self.max_steps:
            return f"step budget {self.max_steps} reached"
        if wall >= self.max_wall_s:
            return f"time budget {self.max_wall_s}s reached"
        if model_calls >= self.max_model_calls:
            return f"model-call budget {self.max_model_calls} reached"
        return None


@dataclass
class RunLog:
    start: float = field(default_factory=time.time)
    steps: list[dict] = field(default_factory=list)
    model_calls: int = 0
    takeovers: int = 0
    approvals: int = 0
    backtracks: int = 0
    idle_s: float = 0.0
    result: dict = field(default_factory=dict)

    def metrics(self) -> dict:
        return {"start": self.start, "steps": len(self.steps),
                "wall_s": round(time.time() - self.start, 2),
                "model_calls": self.model_calls, "takeovers": self.takeovers,
                "approvals": self.approvals, "backtracks": self.backtracks,
                "idle_s": round(self.idle_s, 2), "result": self.result,
                "actions": [s["tool"] for s in self.steps]}


class AgentLoop:
    """Runs one task. Call `run()` and poll `.machine.state`; control via `pause()`,
    `resume()`, `approve()`, `answer_human()`, `kill()`."""

    def __init__(self, browser, model, budgets: Budgets = Budgets(),
                 max_consec_errors: int = 4) -> None:
        self.browser = browser
        self.model = model
        self.budgets = budgets
        self.machine = StateMachine()
        self.log = RunLog()
        self.goal = ""
        self.history: list[dict] = []
        self._ask_q: dict = {}
        self._human_answer: dict = {}
        self._pending_approval: Optional[Action] = None
        self._pending_decision: threading.Event = threading.Event()
        self._running = False
        # circuit breaker: consecutive model-decision errors that stop the run cleanly
        self._consec_errors = 0
        self._max_consec_errors = max_consec_errors

    # ---- control surface (called from the API/UI) ----

    def start(self, goal: str) -> None:
        self.goal = goal
        self.log = RunLog()
        self.history = []
        self.machine = StateMachine()
        self._running = True
        t = threading.Thread(target=self._thread, daemon=True)
        t.start()

    def kill(self) -> None:
        self.browser.kill.set()

    def pause(self, reason: str = "human") -> None:
        """Human takeover: stop issuing actions; the UI forwards input. Honoured at boundary."""
        if self.machine.can(State.PAUSED_HUMAN):
            self.machine.transition(State.PAUSED_HUMAN, reason)
            self.log.takeovers += 1
            self._pending_decision.set()
            BUS.publish("state", {"state": self.machine.state.value})

    def resume(self, note: str = "") -> None:
        """Hand back to the agent with an optional note; re-observe and continue/replan."""
        if self.machine.state == State.PAUSED_HUMAN:
            self.machine.transition(State.RUNNING, "resume")
            if note:
                self.history.append({"tool": "human_note", "args": {"note": note}, "ok": True, "detail": note})
            self._pending_decision.clear()
            BUS.publish("state", {"state": "RUNNING"})

    def approve(self, allow: bool) -> None:
        """Answer the approval gate for a flagged irreversible/external action."""
        self.log.approvals += 1
        self._human_answer["approval"] = allow
        self._pending_decision.clear()
        BUS.publish("approval", {"allow": allow})

    def answer_human(self, choice: str) -> None:
        """Answer an ask_human prompt."""
        self._human_answer["choice"] = choice
        self._pending_decision.clear()

    @property
    def paused(self) -> bool:
        return self._pending_decision.is_set()

    # ---- the loop ----

    def _thread(self) -> None:
        self.machine.transition(State.PLANNING, "start")
        BUS.publish("state", {"state": "PLANNING"})
        self.machine.transition(State.RUNNING, "planned")
        BUS.publish("state", {"state": "RUNNING"})
        steps = 0
        while self._running and not self.browser.kill.is_set():
            # budgets + pause at the action boundary
            exceeded = self.budgets.exceeded(steps, time.time() - self.log.start, self.log.model_calls)
            if exceeded:
                BUS.publish("budget", {"reason": exceeded})
                self._stop("ERROR", {"error": "budget", "detail": exceeded})
                return
            # model decides one action
            self._maybe_wait_for_human()
            if self.browser.kill.is_set():
                break
            shot = self.browser.take_screenshot()
            obs = self.browser.observe()
            try:
                act = self.model.decide(self.goal, elements_text(obs), shot, self.history)
                self.log.model_calls += 1
                self._consec_errors = 0
            except Exception as e:
                self._consec_errors += 1
                BUS.publish("decision_error", {"error": f"{type(e).__name__}: {str(e)[:160]}"})
                if self._consec_errors >= self._max_consec_errors:
                    self._stop("ERROR", {"error": "model circuit breaker",
                                          "detail": f"{self._consec_errors} consecutive failures: {str(e)[:120]}"})
                    return
                time.sleep(1.0)  # bounded pause, then the next iteration retries
                continue
            if act is None:
                act = Action("finish", {"summary": "model returned no action"})
            BUS.publish("decision", {"tool": act.tool, "args": act.args})

            if act.is_finish:
                self._stop("DONE", {"summary": act.args.get("summary", "")})
                return

            if act.is_ask:
                self._handle_ask(act)
                continue

            # safety gate FIRST (code-first; model can only escalate)
            irrev, ext = classify_action(act.tool, act.args)
            if irrev or ext:
                ok = self._approval_gate(act, irrev, ext)
                if not ok:
                    self.history.append({"tool": act.tool, "args": act.args, "ok": False, "detail": "not approved"})
                    continue

            result = execute_action(self.browser, act.tool, act.args)
            # action recovery: if the actuation missed (element not settled / gone), re-observe
            # and retry once - a code-level self-heal, reported transparently
            if not result.ok and act.tool in ("click", "type", "select"):
                self.browser.observe()
                r2 = execute_action(self.browser, act.tool, act.args)
                if r2.ok:
                    r2.detail = "recovered on retry: " + r2.detail
                    result = r2
            rec = {"tool": act.tool, "args": act.args, "ok": result.ok, "detail": result.detail}
            self.history.append(rec)
            self.log.steps.append(rec)          # so metrics().actions reports the agent's own actions
            BUS.publish("action", {"tool": act.tool, "ok": result.ok, "detail": result.detail})
            steps += 1

        self._stop("ERROR", {"error": "stopped", "detail": "kill switch"})

    def _maybe_wait_for_human(self) -> None:
        """If the loop is paused (human takeover or an unresolved ask/approval), wait for the
        human's decision event. This is how pause is honoured at the action boundary."""
        while self._pending_decision.is_set() and self._running and not self.browser.kill.is_set():
            time.sleep(0.05)
        self._pending_decision.clear()

    def _handle_ask(self, act: Action) -> None:
        self._ask_q = act.args
        BUS.publish("ask_human", {"question": act.args.get("question", ""),
                                   "options": act.args.get("options", [])})
        self._pending_decision.set()
        while self._pending_decision.is_set() and self._running and not self.browser.kill.is_set():
            time.sleep(0.05)
        choice = self._human_answer.pop("choice", "proceed")
        self._pending_decision.clear()
        self.history.append({"tool": "ask_human", "args": act.args, "ok": True, "detail": f"human chose {choice!r}"})
        BUS.publish("ask_answered", {"choice": choice})

    def _approval_gate(self, act: Action, irrev: bool, ext: bool) -> bool:
        """IRREV action always requires explicit approval. EXTERNAL action is auto-denied
        unless the host is allowlisted (the browser refuses the nav itself) - we still surface
        it for the human. Returns True only if the action may proceed."""
        self._pending_approval = act
        BUS.publish("approval_gate", {"tool": act.tool, "irreversible": irrev, "external": ext,
                                       "args": act.args})
        self._pending_decision.set()
        while self._pending_decision.is_set() and self._running and not self.browser.kill.is_set():
            time.sleep(0.05)
        allow = self._human_answer.pop("approval", False)
        self._pending_decision.clear()
        BUS.publish("approved", {"allow": allow})
        return allow

    def _stop(self, to: str, result: dict) -> None:
        self._running = False
        self.log.result = result
        from .state import State as _S
        self.machine = StateMachine()
        self.machine.state = _S(to) if to in ("DONE", "ERROR", "RUNNING") else _S.ERROR
        BUS.publish("done", {"state": self.machine.state.value, **result, "metrics": self.log.metrics()})
