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

    def success_check_specs(self) -> list[dict]:
        out: list[dict] = []
        for s in self.steps:
            out.extend(s.success)
        out.extend(self.success_checks)
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Procedure":
        d = dict(d)
        steps = []
        for s in d.get("steps", []):
            s_dict = dict(s)
            s_dict.setdefault("vision_concept", "")
            locs = [Locator(**l) for l in s_dict.pop("locators", [])]
            steps.append(Step(**s_dict, locators=locs))
        d["steps"] = steps
        d["success_checks"] = d.get("success_checks", [])
        return cls(**{k: d.get(k, DEFAULTS[k]) for k in ("goal", "site", "parameters", "source")},
                   steps=d["steps"], success_checks=d["success_checks"])


DEFAULTS = {"goal": "", "site": "", "parameters": {}, "source": "manual"}
