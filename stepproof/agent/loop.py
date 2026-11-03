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
    thinking_log: list[dict] = field(default_factory=list)
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
                "usage": getattr(self, "_usage", {}) or {},
                "actions": [s["tool"] for s in self.steps],
                "thinking_log": list(self.thinking_log)}


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
        if getattr(self, "_thread_handle", None) and self._thread_handle.is_alive():
            self._running = False
            self.browser.kill.set()
            self._pending_decision.set()
            self._thread_handle.join(timeout=1.5)
        self.browser.kill.clear()
        self._pending_decision.clear()
        self.goal = goal
        self.log = RunLog()
        self.history = []
        self.machine = StateMachine()
        self._running = True
        self._thread_handle = threading.Thread(target=self._thread, daemon=True)
        self._thread_handle.start()

    def kill(self) -> None:
        self._running = False
        self.browser.kill.set()
        self._pending_decision.set()

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

    def _log_thought(self, step: int, phase: str, title: str, thought: str, details: dict | None = None) -> dict:
        entry = {
            "ts": round(time.time(), 3),
            "step": step,
            "phase": phase,
            "title": title,
            "thought": thought,
            "details": details or {}
        }
        self.log.thinking_log.append(entry)
        BUS.publish("thought", entry)
        return entry

    def _thread(self) -> None:
        self.machine.transition(State.PLANNING, "start")
        BUS.publish("state", {"state": "PLANNING"})
        self._log_thought(0, "PLANNING", "Goal Initialization", f"Starting run for goal: '{self.goal}' on site {self.browser.url}")
        self.machine.transition(State.RUNNING, "planned")
        BUS.publish("state", {"state": "RUNNING"})
        steps = 0
        while self._running and not self.browser.kill.is_set():
            # budgets + pause at the action boundary
            exceeded = self.budgets.exceeded(steps, time.time() - self.log.start, self.log.model_calls)
            if exceeded:
                BUS.publish("budget", {"reason": exceeded})
                self._log_thought(steps, "BUDGET_HALT", "Budget Exceeded", f"Execution halted: {exceeded}")
                self._stop("ERROR", {"error": "budget", "detail": exceeded})
                return
            # model decides one action
            self._maybe_wait_for_human()
            if self.browser.kill.is_set():
                break
            shot = self.browser.take_screenshot()
            obs = self.browser.observe()

            # Anti-bot and CAPTCHA challenge detection & automated/human resolution
            captcha_info = self.browser.detect_captcha()
            if captcha_info.get("detected"):
                kind = captcha_info.get("kind", "unknown")
                self._log_thought(steps + 1, "SECURITY_CHALLENGE", f"Anti-Bot Challenge Detected ({kind})",
                                  f"Detected {kind} challenge on {self.browser.url}. Attempting automated solve / handler.")
                solve_res = self.browser.solve_captcha()
                res_dict = solve_res.get("result", {})
                if res_dict.get("ok"):
                    self._log_thought(steps + 1, "SECURITY_CHALLENGE", "Challenge Resolved",
                                      f"Successfully solved {kind} challenge via {res_dict.get('method')}.")
                    time.sleep(0.5)
                    continue
                else:
                    self._log_thought(steps + 1, "SECURITY_CHALLENGE", "Operator Takeover Required",
                                      f"{kind} challenge requires operator intervention. Halting for human takeover.")
                    self.pause()
                    self._maybe_wait_for_human()

            # Pre-flight PII redaction pass: strip emails, credit cards, phones, SSNs
            from ..redact import get_redactor
            redactor = get_redactor()
            redacted_obs, r_boxes = redactor.redact_observation(obs)
            outbound_shot = redactor.redact_screenshot(shot, r_boxes) if r_boxes else shot

            num_el = len(redacted_obs.get("elements", []))
            self._log_thought(steps + 1, "PERCEPTION", "Inspecting Page State",
                              f"Observed '{self.browser.title}' at {self.browser.url} with {num_el} interactive elements.")
            t0 = time.time()
            try:
                act = self.model.decide(self.goal, elements_text(redacted_obs), outbound_shot, self.history)
                dt_ms = round((time.time() - t0) * 1000, 1)
                self.log.model_calls += 1
                self._consec_errors = 0
            except Exception as e:
                self._consec_errors += 1
                err_msg = f"{type(e).__name__}: {str(e)[:160]}"
                self._log_thought(steps + 1, "MODEL_ERROR", "Deliberation Error",
                                  f"Model failed ({self._consec_errors}/{self._max_consec_errors}): {err_msg}")
                BUS.publish("decision_error", {"error": err_msg})
                if self._consec_errors >= self._max_consec_errors:
                    self._stop("ERROR", {"error": "model circuit breaker",
                                          "detail": f"{self._consec_errors} consecutive failures: {str(e)[:120]}"})
                    return
                time.sleep(1.0)  # bounded pause, then the next iteration retries
                continue
            if act is None:
                act = Action("finish", {"summary": "model returned no action"})
            
            thought_desc = act.thought or f"Targeting tool '{act.tool}' with args {json.dumps(act.args)} to advance goal."
            self._log_thought(steps + 1, "DELIBERATION", f"Tool Selection: {act.tool}", thought_desc,
                              details={"tool": act.tool, "args": act.args, "latency_ms": dt_ms})
            BUS.publish("decision", {"tool": act.tool, "args": act.args, "thought": thought_desc})

            # Anti-stagnation & loop circuit breaker (prevents looping on wait/scroll in open exploration)
            stagnant_count = 0
            for prev in reversed(self.history[-4:]):
                if prev.get("tool") in ("wait", "scroll"):
                    stagnant_count += 1
                else:
                    break
            if act.tool in ("wait", "scroll") and stagnant_count >= 2:
                self._log_thought(steps + 1, "ANTI_LOOP", "Stagnation Warning",
                                  f"Detected {stagnant_count} consecutive {act.tool} actions without state progression. Shifting strategy to target on-screen interactive elements.")
                if stagnant_count >= 4:
                    self._log_thought(steps + 1, "ANTI_LOOP", "Loop Circuit Breaker",
                                      "Agent stuck in wait/scroll cycle. Pausing for operator guidance.")
                    self.pause()
                    BUS.publish("agent_stuck", {"reason": "repeated wait/scroll cycle", "tool": act.tool})
                    continue
                else:
                    self.history.append({
                        "tool": "system_directive",
                        "args": {},
                        "ok": False,
                        "detail": "STAGNATION NOTICE: Repeated wait/scroll is not advancing the page. Focus on clicking active buttons, inputs, links, or finishing if the goal is satisfied."
                    })

            if act.is_finish:
                summary = act.args.get("summary", "")
                self._log_thought(steps + 1, "COMPLETION", "Task Finished", f"Achieved goal '{self.goal}': {summary}")
                self._stop("DONE", {"summary": summary})
                return

            if act.is_ask:
                self._log_thought(steps + 1, "HUMAN_ASK", "Agent Inquiring", f"Prompting operator: {act.args.get('question', '')}")
                self._handle_ask(act)
                continue

            # safety gate FIRST (code-first; model can only escalate)
            irrev, ext = classify_action(act.tool, act.args, tb=self.browser)
            if irrev or ext:
                reason = "Action is " + ("IRREVERSIBLE" if irrev else "") + (" & " if (irrev and ext) else "") + ("EXTERNAL" if ext else "")
                self._log_thought(steps + 1, "SAFETY_GATE", "Approval Gate Triggered",
                                  f"{reason}: halting for explicit operator confirmation before executing {act.tool}.",
                                  details={"args": act.args})
                ok = self._approval_gate(act, irrev, ext)
                if not ok:
                    self._log_thought(steps + 1, "SAFETY_GATE", "Action Refused", "Human operator rejected the action. Bypassing.", details={"args": act.args})
                    self.history.append({"tool": act.tool, "args": act.args, "ok": False, "detail": "not approved"})
                    continue
                else:
                    self._log_thought(steps + 1, "SAFETY_GATE", "Action Permitted", "Human operator approved the action.", details={"args": act.args})
            else:
                self._log_thought(steps + 1, "SAFETY_EVAL", "Safety Gate Clear", "Deterministic code check: action is safe, reversible, and allowlisted.")

            result = execute_action(self.browser, act.tool, act.args)
            # action recovery: if the actuation missed (element not settled / gone), re-observe
            # and retry once - a code-level self-heal, reported transparently
            if not result.ok and act.tool in ("click", "type", "select"):
                self._log_thought(steps + 1, "RETRY_HEAL", "Actuation Missed", f"Initial {act.tool} missed ({result.detail}). Re-observing and attempting retry self-heal.")
                self.browser.observe()
                r2 = execute_action(self.browser, act.tool, act.args)
                if r2.ok:
                    r2.detail = "recovered on retry: " + r2.detail
                    result = r2
                    self._log_thought(steps + 1, "RETRY_HEAL", "Retry Succeeded", f"Code self-heal succeeded: {r2.detail}")
            rec = {"tool": act.tool, "args": act.args, "ok": result.ok, "detail": result.detail}
            self.history.append(rec)
            self.log.steps.append(rec)          # so metrics().actions reports the agent's own actions
            self._log_thought(steps + 1, "ACTUATION", f"Actuation: {act.tool}",
                              f"{'Succeeded' if result.ok else 'Failed'}: {result.detail}",
                              details={"tool": act.tool, "ok": result.ok, "detail": result.detail})
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
        if hasattr(self.model, "usage"):
            self.log._usage = dict(self.model.usage)   # surface token accounting in metrics()
        from .state import State as _S
        self.machine = StateMachine()
        self.machine.state = _S(to) if to in ("DONE", "ERROR", "RUNNING") else _S.ERROR
        BUS.publish("done", {"state": self.machine.state.value, **result, "metrics": self.log.metrics()})

        # Record into append-only hash-chained AuditSpine
        try:
            from ..audit import get_spine
            run_id = f"agent-{int(self.log.start*1000)}"
            verdict = "PASS" if to == "DONE" else "ERROR"
            get_spine().append(
                run_id=run_id,
                verdict=verdict,
                checks=[],
                steps=[{"tool": s.get("tool", ""), "ok": s.get("ok", True)} for s in self.log.steps],
                evidence_paths=[],
                cost=self.log.metrics().get("usage", {}),
                model_disclosure={
                    "active_model": getattr(self.model, "active_model", getattr(self.model, "name", "unknown")),
                    "fell_back": bool(getattr(self.model, "fell_back", False))
                }
            )
        except Exception:
            pass
