"""v2 browser Procedure: goal, steps (multi-locator + action), parameters, and deterministic
success checks. Pure data; no model calls. Learned Procedures execute deterministically;
the model is only used to PLAN from a goal and to SELF-HEAL a broken locator (vision fallback)."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Locator:
    """Multi-locator: try each in order (role+name, text, CSS). Self-healing = fall through."""
    kind: str = "css"          # css | role | text
    value: str = ""


@dataclass
class Step:
    id: str
    description: str
    action: str = "click"      # click | type | select | goto | wait
    arg: dict = field(default_factory=dict)         # action args (text, value, url, ms...)
    locators: list[Locator] = field(default_factory=list)  # where the action targets
    success: list[dict] = field(default_factory=list)      # deterministic checks
    note: str = ""
    vision_concept: str = ""


@dataclass
class SuccessCheck:
    kind: str                 # url_contains | text_visible | element_state | value_equals
    spec: dict = field(default_factory=dict)


@dataclass
class Procedure:
    goal: str
    site: str = ""                       # allowlisted host
    steps: list[Step] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)
    success_checks: list[dict] = field(default_factory=list)   # run at end of run
    source: str = "manual"               # manual | learned | model
    manifest: dict = field(default_factory=dict)
    signature: str = ""
    provenance: dict = field(default_factory=dict)

    def success_check_specs(self) -> list[dict]:
        out: list[dict] = []
        for s in self.steps:
            out.extend(s.success)
        out.extend(self.success_checks)
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    def sign(self, key: Optional[str] = None) -> "Procedure":
        from .signing import sign_procedure
        return sign_procedure(self, key=key)

    def verify(self, key: Optional[str] = None) -> tuple[bool, Optional[str]]:
        from .signing import verify_procedure
        return verify_procedure(self, key=key)

    @classmethod
    def from_dict(cls, d: dict, verify_signature: bool = True) -> "Procedure":
        d = dict(d)
        steps = []
        for s in d.get("steps", []):
            s_dict = dict(s)
            concept = s_dict.pop("concept", "")
            if concept and not s_dict.get("vision_concept"):
                s_dict["vision_concept"] = concept
            locs = [Locator(**l) for l in s_dict.pop("locators", [])]
            step_kwargs = {
                "id": s_dict.get("id", ""),
                "description": s_dict.get("description", ""),
                "action": s_dict.get("action", "click"),
                "arg": s_dict.get("arg", {}),
                "locators": locs,
                "success": s_dict.get("success", []),
                "note": s_dict.get("note", ""),
                "vision_concept": s_dict.get("vision_concept", ""),
            }
            steps.append(Step(**step_kwargs))
        d["steps"] = steps
        d["success_checks"] = d.get("success_checks", [])
        manifest = d.get("manifest", {})
        signature = d.get("signature", "")
        provenance = d.get("provenance", {})

        goal = d.get("goal") or d.get("name") or ""
        proc = cls(goal=goal, site=d.get("site", ""),
                   parameters=d.get("parameters", {}), source=d.get("source", "manual"),
                   steps=d["steps"], success_checks=d["success_checks"],
                   manifest=manifest, signature=signature, provenance=provenance)

        # Tamper-evident check: if signature is provided and verify_signature is True, verify integrity
        if verify_signature and signature and manifest:
            from .signing import verify_procedure
            valid, err = verify_procedure(proc)
            if not valid:
                raise ValueError(f"Tampered procedure bundle: {err}")

        return proc


DEFAULTS = {"goal": "", "site": "", "parameters": {}, "source": "manual",
            "manifest": {}, "signature": "", "provenance": {}}
