"""Natural-language procedure -> validated ProcedureSpec. The model proposes; this code sanitizes."""
from __future__ import annotations
import re
from .schemas import ProcedureSpec


def sanitize(spec: ProcedureSpec) -> tuple[ProcedureSpec, list[str]]:
    warnings: list[str] = []
    seen: set[str] = set()
    for i, s in enumerate(spec.steps, 1):
        if not s.id or s.id in seen:
            s.id = f"s{i}"
        raw = s.concept
        s.concept = re.sub(r"\s+", " ", re.split(r",|;| and | or ", raw)[0]).strip().lower()
        if s.concept != raw.strip().lower():
            warnings.append(f"{s.id}: concept '{raw}' reduced to '{s.concept}' (SAM takes one noun phrase per request).")
        if len(s.concept.split()) > 5:
            warnings.append(f"{s.id}: concept '{s.concept}' is long; short concrete nouns segment best.")
        bad = [a for a in s.after if a not in seen]
        if bad:
            warnings.append(f"{s.id}: dropped unknown prerequisites {bad}.")
            s.after = [a for a in s.after if a in seen]
        s.min_count = max(0, s.min_count)
        seen.add(s.id)
    return spec, warnings


def compile_procedure(text: str, vision) -> tuple[ProcedureSpec, list[str]]:
    return sanitize(vision.compile_procedure(text))
