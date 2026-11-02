"""P4 Onboarding skill compiler: turn natural descriptions or ~30s demos into signed skills.
Uses parameterised slots ({vendor}, {sku}, {amount}) to turn single examples into task families.
Enforces a gated re-teach flow when a new variant fails, and honestly discloses that
vision variant understanding on live physical footage is NOT YET MEASURED.
"""
from __future__ import annotations
import re, time
from typing import Optional, Any
from ..proc import Procedure, Step, Locator
from ..signing import sign_procedure
from ..audit import get_spine

SKILL_DISCLOSURE = "Vision understanding of new variants on real-world footage: NOT YET MEASURED (synthetic benchmark only)"


def _sub_slots(text: str, parameters: dict[str, str]) -> str:
    """Replace concrete parameter values with {slot} placeholders."""
    if not parameters or not text:
        return text
    res = str(text)
    for slot_name, slot_val in parameters.items():
        if slot_val and str(slot_val) in res:
            res = res.replace(str(slot_val), f"{{{slot_name}}}")
    return res


def describe_skill(goal: str, site: str, step_descriptions: list[str],
                   parameters: Optional[dict[str, str]] = None,
                   success_checks: Optional[list[dict]] = None) -> Procedure:
    """Compile a natural language step description into a signed Procedure with slots."""
    params = parameters or {}
    steps = []

    for i, desc in enumerate(step_descriptions, 1):
        # Extract intent and potential target
        action = "click"
        arg = {}
        locators = []
        low = desc.lower()

        if "type" in low or "enter" in low or "fill" in low:
            action = "type"
            val = "{value}"
            # Check if any param value is mentioned
            for k, v in params.items():
                if v and str(v).lower() in low:
                    val = f"{{{k}}}"
                    break
            arg = {"text": val}
            # Infer selector from common keywords
            if "vendor" in low:
                locators = [Locator("css", "#vendor"), Locator("text", "Vendor")]
            elif "amount" in low:
                locators = [Locator("css", "#amount"), Locator("text", "Amount")]
            else:
                locators = [Locator("css", f"#field{i}")]
        elif "select" in low or "choose" in low:
            action = "select"
            arg = {"value": "{category}"}
            locators = [Locator("css", "#category"), Locator("text", "Category")]
        elif "submit" in low or "click" in low or "finish" in low:
            action = "click"
            arg = {"name": desc}
            if "submit" in low:
                locators = [Locator("css", "#submit"), Locator("text", "Submit")]
            else:
                locators = [Locator("css", f"#btn{i}")]

        desc_slotted = _sub_slots(desc, params)
        steps.append(Step(
            id=f"s{i}",
            description=desc_slotted,
            action=action,
            arg=arg,
            locators=locators,
            vision_concept=desc_slotted,
        ))

    proc = Procedure(
        goal=goal,
        site=site,
        steps=steps,
        parameters=params,
        success_checks=success_checks or [],
        source="skill_compiler"
    )

    # Set honesty disclosure in provenance
    proc.provenance = {
        "compiler": "stepproof_skill_compiler_p4",
        "vision_on_real_footage": SKILL_DISCLOSURE,
        "ts": round(time.time(), 3),
    }

    # Cryptographically sign the skill artifact
    sign_procedure(proc)
    return proc


def demo_to_skill(recorded_steps: list[dict], goal: str, site: str,
                  parameters: dict[str, str],
                  success_checks: Optional[list[dict]] = None) -> Procedure:
    """Turn recorded ~30s operator demo actions into a parameterized, signed skill."""
    from ..learn.compile import compile_to_procedure
    proc, warnings = compile_to_procedure(recorded_steps, goal, site,
                                          success_checks=success_checks,
                                          parameters=parameters)

    # Parameterize step arguments: replace concrete values with {slot}
    for step in proc.steps:
        for k, v in list(step.arg.items()):
            if isinstance(v, str):
                step.arg[k] = _sub_slots(v, parameters)
        step.description = _sub_slots(step.description, parameters)

    proc.provenance = {
        "compiler": "stepproof_demo_to_skill_p4",
        "vision_on_real_footage": SKILL_DISCLOSURE,
        "ts": round(time.time(), 3),
    }
    sign_procedure(proc)
    return proc


def gated_reteach(proc: Procedure, failed_step_id: str,
                  human_correction: dict,
                  approved: bool = False) -> tuple[Procedure, bool, str]:
    """Human-gated re-teach flow: when a variant fails, merge human correction
    into the procedure and re-sign it (never silently retrain)."""
    if not approved:
        return proc, False, "Gated re-teach refused: human operator approval is required."

    target_step = None
    for s in proc.steps:
        if s.id == failed_step_id:
            target_step = s
            break

    if not target_step:
        return proc, False, f"Step ID {failed_step_id} not found in procedure."

    # Merge corrected locators
    new_locs = human_correction.get("locators", [])
    if new_locs:
        parsed_locs = [Locator(kind=l.get("kind", "css"), value=l.get("value", ""))
                       for l in new_locs]
        # Prepend corrected locator as top priority
        target_step.locators = parsed_locs + [l for l in target_step.locators if l not in parsed_locs]

    if "arg" in human_correction:
        target_step.arg.update(human_correction["arg"])

    target_step.note = f"Re-taught by operator at {round(time.time(), 1)}"

    # Re-sign the procedure
    sign_procedure(proc)

    # Record re-teach event in Audit Spine
    try:
        get_spine().append(
            run_id=f"reteach-{proc.goal[:10]}-{int(time.time()*1000)}",
            verdict="PASS",
            steps=[{"step": failed_step_id, "correction": human_correction}],
            evidence_paths=[],
            model_disclosure={"reteach_approved": True, "vision_on_real_footage": SKILL_DISCLOSURE}
        )
    except Exception:
        pass

    return proc, True, "Human-gated re-teach approved and procedure re-signed."

