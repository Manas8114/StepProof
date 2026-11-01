"""Execute a learned/manual Procedure deterministically: walk the steps, fall through
locators on failure (self-healing), run deterministic success checks at the end.
The model is NOT in this path except an optional vision self-heal step.
Approval gates and budgets are still enforced via the same safety helpers."""
from __future__ import annotations
import json, time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Optional

from .. import checks
from ..browser.actions import classify_action, execute_action
from ..events import BUS


@dataclass
class ExecResult:
    success: bool
    steps_run: int
    healed_steps: list[dict] = field(default_factory=list)
    check_results: list = field(default_factory=list)
    wall_s: float = 0.0
    error: str = ""

    def metrics(self) -> dict:
        return {"success": self.success, "steps": self.steps_run, "model_calls": 0,
                "wall_s": self.wall_s, "takeovers": 0, "approvals": len(self.healed_steps),
                "actions": [s.get("action") for s in self.healed_steps] + [],
                "result": {"success": self.success, "error": self.error}}


def _resolve_locator(tb, locators: list, text: str = "", tool: str = "click") -> tuple[bool, dict, int]:
    """Try each locator in order; return (worked, winning-arg, index) - the self-heal."""
    def L(x, k, d=None):
        return x.get(k, d) if isinstance(x, dict) else getattr(x, k, d)
    if not locators:
        return False, {}, 0
    for i, loc in enumerate(locators):
        key = "selector" if L(loc, "kind", "css") == "css" else "name"
        a = {key: L(loc, "value", "")}
        if tool in ("type", "fill"):
            a["text"] = text
        elif tool == "select":
            a["value"] = text  # select records carry the value in `text` position
        r = execute_action(tb, tool if tool in ("click", "type", "select") else "click", a)
        if r.ok:
            return True, a, i
    return False, {}, len(locators)


def execute_procedure(tb, proc, human_demo: dict | None = None,
                      approve_fn: Optional[Callable[[str, dict], bool]] = None,
                      vision_selfheal: Optional[Callable[[str], Optional[dict]]] = None,
                      max_steps: int = 60) -> ExecResult:
    """Run `proc` on the live browser. `approve_fn(tool, args)->bool` gates irreversible/external
    actions (the UI wires this to the approval-gate flow). `vision_selfheal(concept)->arg|None`
    is the optional SAM/Muse fallback when all recorded locators fail."""
    t0 = time.time()
    res = ExecResult(success=False, steps_run=0, wall_s=0.0)
    BUS.publish("exec_start", {"goal": proc.goal})
    for i, step in enumerate(proc.steps[:max_steps]):
        irrev, ext = classify_action(step.action, {k: step.arg.get(k) for k in ("name", "url")})
        if irrev or ext:
            if approve_fn is None or not approve_fn(step.action, step.arg):
                res.error = f"step {i} ({step.action}) blocked: not approved"
                BUS.publish("exec_blocked", {"step": step.id, "action": step.action})
                break
            if irrev:
                res.healed_steps.append({"step": step.id, "action": step.action, "note": "approved irreversible"})
        # self-heal: fall through locators (the resolver already actuated the winning one);
        # optional vision fallback if every recorded locator failed
        text = step.arg.get("text", "") if step.action in ("type", "fill") else step.arg.get("value", "")
        worked, winning, used = (False, {}, 0)
        if step.locators:
            worked, winning, used = _resolve_locator(tb, step.locators, text, step.action)
            if worked and used > 0:
                res.healed_steps.append({"step": step.id, "action": step.action,
                                        "note": f"locator[{used}] used (self-heal from broken primary)"})
        if not worked and vision_selfheal is not None:
            healed = vision_selfheal(step.description)
            if healed:
                r = execute_action(tb, step.action, healed)
                worked = r.ok
                res.healed_steps.append({"step": step.id, "action": step.action,
                                         "note": f"vision healed -> {json.dumps(healed)[:80]}"})
        if not worked:
            res.error = f"step {i} ({step.action}) failed on all locators"
            BUS.publish("exec_fail", {"step": step.id})
            break
        res.steps_run += 1
        BUS.publish("exec_step", {"step": step.id, "ok": bool(worked)})

    # deterministic success checks (code, never the model); every verdict gets a
    # before/after evidence screenshot from the live page
    def _shoot(tag: str) -> str:
        import time
        d = "media"
        Path(d).mkdir(exist_ok=True)
        p = Path(d) / f"{tag}_{int(time.time()*1000)}.jpg"
        tb.act("screenshot", str(p))
        return str(p) if p.exists() else ""
    ok, cresults = checks.all_pass(tb, proc.success_check_specs(), shoot=_shoot, prefix=proc.goal[:12].replace(" ", "_"))
    res.check_results = cresults
    res.success = bool(ok and not res.error)
    res.wall_s = round(time.time() - t0, 2)
    BUS.publish("exec_done", {"success": res.success, "metrics": res.metrics()})
    return res
