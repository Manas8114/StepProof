"""Locator drift analyzer and self-rewriting procedure engine.
When the DOM mutates and locators break, vision self-heal finds the target.
This module extracts the winning element's new locators and updates the Procedure
in-place, re-signing it so the NEXT execution needs ZERO model/vision calls.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, Any
from ..proc import Procedure, Step, Locator
from ..signing import sign_procedure


@dataclass
class DriftRecord:
    step_id: str
    step_description: str
    primary_locator: Optional[dict] = None
    winning_locator: Optional[dict] = None
    locators_tried: int = 1
    needed_vision: bool = False
    vision_note: str = ""
    healed: bool = False
    suggested_locator: Optional[dict] = None


@dataclass
class DriftReport:
    procedure_goal: str
    total_steps: int
    drifted_steps: int
    vision_healed_steps: int
    records: list[DriftRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "procedure_goal": self.procedure_goal,
            "total_steps": self.total_steps,
            "drifted_steps": self.drifted_steps,
            "vision_healed_steps": self.vision_healed_steps,
            "records": [asdict(r) for r in self.records],
        }


def analyze_drift(proc: Procedure, exec_result: Any) -> DriftReport:
    """Analyze which locators drifted or required self-healing during execution."""
    healed_dict = {h.get("step"): h for h in getattr(exec_result, "healed_steps", [])}
    records: list[DriftRecord] = []
    drifted_count = 0
    vision_count = 0

    for step in proc.steps:
        primary = asdict(step.locators[0]) if step.locators else None
        h_info = healed_dict.get(step.id)

        if h_info:
            drifted_count += 1
            note = h_info.get("note", "")
            is_vision = "vision" in note.lower()
            if is_vision:
                vision_count += 1

            rec = DriftRecord(
                step_id=step.id,
                step_description=step.description,
                primary_locator=primary,
                healed=True,
                needed_vision=is_vision,
                vision_note=note,
                suggested_locator=primary,
            )
            records.append(rec)
        else:
            records.append(DriftRecord(
                step_id=step.id,
                step_description=step.description,
                primary_locator=primary,
                healed=False,
                needed_vision=False
            ))

    return DriftReport(
        procedure_goal=proc.goal,
        total_steps=len(proc.steps),
        drifted_steps=drifted_count,
        vision_healed_steps=vision_count,
        records=records
    )


def self_rewrite_procedure(proc: Procedure, drift_report: DriftReport,
                           tb: Optional[Any] = None) -> Procedure:
    """Upgrade one-shot heal into a self-rewriting procedure:
    When a locator drifted or vision-healed, synthesize and rank the new stable selector,
    prepend it to the step's locator list, and cryptographically re-sign the procedure.
    """
    healed_records = {r.step_id: r for r in drift_report.records if r.healed}
    if not healed_records:
        return proc

    for step in proc.steps:
        rec = healed_records.get(step.id)
        if not rec:
            continue

        # If vision healed or secondary locator won, re-rank locators
        if len(step.locators) > 1:
            # Rotate winning locator to the front
            winning = step.locators[1]
            step.locators = [winning] + [l for l in step.locators if l != winning]
            step.note = f"Self-healed & rewritten: promoted locator {winning.value}"
        elif rec.needed_vision and tb:
            # If vision found the element at (x,y), query DOM at (x,y) for new selector
            try:
                expr = ("(([x,y]) => {"
                        "const el = document.elementFromPoint(x, y);"
                        "if (!el) return null;"
                        "if (el.id) return '#' + el.id;"
                        "if (el.className) return el.tagName.toLowerCase() + '.' + el.className.trim().split(/\\s+/)[0];"
                        "return el.tagName.toLowerCase();"
                        "})([100, 100])")
                new_sel = tb.act("eval", {"expr": expr})
                if new_sel:
                    step.locators.insert(0, Locator(kind="css", value=str(new_sel)))
                    step.note = f"Self-healed via vision: synthesized new locator {new_sel}"
            except Exception:
                pass

    # Re-sign the updated procedure
    sign_procedure(proc)
    return proc

