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
    billed_frames: int = 0

    def metrics(self) -> dict:
        return {"success": self.success, "steps": self.steps_run, "model_calls": 0,
                "wall_s": self.wall_s, "takeovers": 0, "approvals": len(self.healed_steps),
                "billed_frames": self.billed_frames,
                "actions": [s.get("action") for s in self.healed_steps] + [],
                "result": {"success": self.success, "error": self.error}}


def _label_at_point(tb, x: int, y: int) -> str | None:
    """Resolve the visible label of the element at (x,y) via document.elementFromPoint.
    Returns None if unresolvable."""
    expr = ("(([cx, cy]) => {"
            "const el = document.elementFromPoint(cx, cy);"
            "if (!el) return null;"
            "return (el.textContent || el.getAttribute('aria-label') || el.id || el.getAttribute('title') || '').trim().slice(0, 60);"
            "})([%d, %d])" % (x, y))
    try:
        val = tb.act("eval", {"expr": expr})
        return str(val).strip() if val is not None else None
    except Exception:
        return None


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


def _fill_slots(arg: dict, params: dict) -> dict:
    if not params:
        return arg
    import re
    def sub(v):
        return re.sub(r"\{([a-zA-Z0-9_]+)\}", lambda m: str(params.get(m.group(1), m.group(0))), str(v))
    return {k: (sub(v) if isinstance(v, str) else v) for k, v in arg.items()}


def execute_procedure(tb, proc, human_demo: dict | None = None,
                      approve_fn: Optional[Callable[[str, dict], bool]] = None,
                      vision_selfheal: Optional[Callable[[Any], Optional[dict]]] = None,
                      max_steps: int = 60) -> ExecResult:
    """Run `proc` on the live browser. `approve_fn(tool, args)->bool` gates irreversible/external
    actions (the UI wires this to the approval-gate flow). `vision_selfheal(concept)->arg|None`
    is the optional SAM/Muse fallback when all recorded locators fail."""
    t0 = time.time()
    res = ExecResult(success=False, steps_run=0, wall_s=0.0)
    BUS.publish("exec_start", {"goal": proc.goal})

    # Pre-flight cost estimation and budget breaker tripwire
    from ..budget import estimate_procedure_cost, get_tripwire
    from ..audit import get_spine
    est = estimate_procedure_cost(proc)
    tripwire = get_tripwire()
    ok_pre, pre_err = tripwire.check_preflight(est)
    if not ok_pre:
        res.error = f"Budget tripwire breached: {pre_err}"
        BUS.publish("exec_fail", {"error": res.error})
        get_spine().append(
            run_id=f"proc-{int(t0*1000)}",
            verdict="BLOCKED",
            steps=[],
            evidence_paths=[],
            cost=est.to_dict(),
            model_disclosure={"tripwire_breach": pre_err}
        )
        return res

    params = getattr(proc, "parameters", {}) or {}
    run_billed_frames = 0
    for i, step in enumerate(proc.steps[:max_steps]):
        step_arg = _fill_slots(step.arg, params)
        irrev, ext = classify_action(step.action, step_arg, tb=tb)
        if irrev or ext:
            if approve_fn is None or not approve_fn(step.action, step_arg):
                res.error = f"step {i} ({step.action}) blocked: not approved"
                BUS.publish("exec_blocked", {"step": step.id, "action": step.action})
                break
            if irrev:
                res.healed_steps.append({"step": step.id, "action": step.action, "note": "approved irreversible"})
        # self-heal: fall through locators (the resolver already actuated the winning one);
        # optional vision fallback if every recorded locator failed
        text = step_arg.get("text", "") if step.action in ("type", "fill") else step_arg.get("value", "")
        worked, winning, used = (False, {}, 0)
        if step.locators:
            worked, winning, used = _resolve_locator(tb, step.locators, text, step.action)
            if worked and used > 0:
                res.healed_steps.append({"step": step.id, "action": step.action,
                                        "note": f"locator[{used}] used (self-heal from broken primary)"})
        if not worked and vision_selfheal is not None:
            # Tripwire check BEFORE invoking any billing SAM / vision model call
            ok_v, v_err = tripwire.check_before_vision_call(current_run_frames=run_billed_frames, expected_frames=50)
            if not ok_v:
                res.error = f"step {i} vision call blocked: {v_err}"
                BUS.publish("exec_blocked", {"step": step.id, "reason": "budget_tripwire"})
                break

            run_billed_frames += 50
            res.billed_frames = run_billed_frames

            healed = vision_selfheal(step)
            if healed:
                healed = dict(healed)
                if step.action in ("type", "fill"):
                    val = step_arg.get("text", "") or step_arg.get("value", "")
                    healed["text"] = val
                    if "enter" in step_arg:
                        healed["enter"] = step_arg["enter"]
                elif step.action == "select":
                    val = step_arg.get("value", "") or step_arg.get("text", "")
                    healed["value"] = val
                elif step.action in ("click", "select"):
                    from ..browser.actions import classify_element_text
                    hx, hy = int(healed.get("x", 0)), int(healed.get("y", 0))
                    label = _label_at_point(tb, hx, hy)
                    orig_label = str(step_arg.get("name", "") or step_arg.get("selector", "") or "")
                    desc_irrev, desc_ext = classify_element_text(step.description)
                    orig_irrev, orig_ext = classify_element_text(orig_label)
                    if label is None:
                        h_irrev, h_ext = True, True
                    else:
                        lbl_irrev, lbl_ext = classify_element_text(label)
                        h_irrev = lbl_irrev or desc_irrev or orig_irrev
                        h_ext = lbl_ext or desc_ext or orig_ext
                    if h_irrev or h_ext:
                        gate_arg = {**healed, "label": label or "unresolvable", "healed": True}
                        if approve_fn is None or not approve_fn(step.action, gate_arg):
                            res.error = f"step {i} ({step.action}) healed target blocked: not approved"
                            BUS.publish("exec_blocked", {"step": step.id, "action": step.action, "healed": True})
                            break
                        if h_irrev:
                            res.healed_steps.append({"step": step.id, "action": step.action,
                                                     "note": "approved vision-healed irreversible"})
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
        """Evidence screenshots go to the stable EVIDENCE dir (data/evidence), not a
        CWD-relative 'media/' - which is how demo_sites/media + stray media/ got polluted."""
        import time
        from .. import config as _cfg
        d = _cfg.EVIDENCE
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{tag}_{int(time.time()*1000)}.jpg"
        tb.act("screenshot", str(p))
        return str(p) if p.exists() else ""
    time.sleep(0.3)
    ok, cresults = checks.all_pass(tb, proc.success_check_specs(), shoot=_shoot, prefix=proc.goal[:12].replace(" ", "_"))
    res.check_results = cresults
    res.success = bool(ok and not res.error)
    res.wall_s = round(time.time() - t0, 2)
    BUS.publish("exec_done", {"success": res.success, "metrics": res.metrics()})

    # Record into append-only hash-chained AuditSpine
    run_id = f"proc-{int(t0*1000)}"
    verdict = "PASS" if res.success else ("BLOCKED" if "blocked" in res.error else "FAIL")
    checks_data = [{"name": c.name, "passed": c.passed, "detail": c.detail, "evidence": getattr(c, "evidence", "")}
                   for c in cresults]
    ev_paths = [c.evidence for c in cresults if getattr(c, "evidence", "")]
    get_spine().append(
        run_id=run_id,
        verdict=verdict,
        checks=checks_data,
        steps=[{"id": s.id, "action": s.action} for s in proc.steps[:res.steps_run]],
        evidence_paths=ev_paths,
        cost=est.to_dict(),
        model_disclosure={"mode": "deterministic_executor", "healed_count": len(res.healed_steps)}
    )

    return res
