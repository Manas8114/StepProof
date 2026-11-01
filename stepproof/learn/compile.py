"""Monitor trace + transcript -> reusable, deterministic Procedure.

The model *proposes* the compile (goal phrasing, which recorded actions matter, which
deterministic success checks to attach); the code *sanitises* it so the result always
validates and always keeps its multi-locators and deterministic checks. No model call
is required when a goal text is supplied directly.
"""
from __future__ import annotations
import json, re
from typing import Optional
from ..proc import Procedure, Step, Locator, DEFAULTS


def _action_from_recorded(rec: dict, goal_site: str) -> Step:
    """Map one RecordedAction (from Recorder.stop()) to a Procedure Step. Multi-locator kept."""
    locs = [Locator(kind=l.get("kind", "css"), value=str(l.get("value", "")))
            for l in rec.get("locators", [])]
    tool = rec.get("tool", "click")
    recarg = rec.get("arg", {})          # recorder nests action payload under "arg"
    arg = {"locators": [asdict(l) for l in locs]}
    if tool == "type":
        arg["text"] = recarg.get("text", "")
    elif tool == "select":
        arg["value"] = recarg.get("value", "")
    s = Step(id=f"s{len([])+1}", description=rec.get("narration") or f"{tool} via {tool} step",
             action=tool, arg=arg, locators=locs)
    s.id = ""  # renumbered by caller
    return s


def compile_to_procedure(records: list[dict], goal: str, site: str = "",
                         success_checks: Optional[list[dict]] = None,
                         model=None, transcript: str = "") -> tuple[Procedure, list[str]]:
    """Deterministic path: records + goal -> Procedure with multi-locator steps + checks.

    `model` (optional) phrases the goal and picks which recorded actions to keep; without
    it we keep every record. `transcript` (narration) becomes each step's intent note.
    Returns (procedure, warnings).
    """
    warnings: list[str] = []
    kept = _keep_records(model, records, goal, transcript) if model else records
    steps = []
    for i, rec in enumerate(kept, 1):
        st = _action_from_recorded(rec, site)
        st.id = f"s{i}"
        st.description = rec.get("narration") or f"step {i}"
        steps.append(st)
    checks = success_checks or _default_checks(records)
    proc = Procedure(goal=goal or "(no goal text supplied)", site=site or _site_from(records),
                     steps=steps, success_checks=checks, source="learned")
    if not steps:
        warnings.append("no recorded actions to learn from; procedure has no steps.")
    if not checks:
        warnings.append("no deterministic success checks; execution will finish on step count only.")
    return proc, warnings


def _keep_records(model, records: list[dict], goal: str, transcript: str) -> list[dict]:
    """Ask the model which recorded actions advance the goal; fall back to all records."""
    try:
        data = model.decide_records(records, goal, transcript) if hasattr(model, "decide_records") else None
        idx = data.get("keep", [range(len(records))]) if isinstance(data, dict) else None
        if isinstance(idx, list) and idx:
            out = [records[i] for i in idx if isinstance(i, int) and 0 <= i < len(records)]
            return out or records
    except Exception:
        pass
    return records


def _site_from(records: list[dict]) -> str:
    for r in records:
        m = re.search(r"(?:https?://)?([^/\s]+)", r.get("url_after", r.get("url_before", "")))
        if m:
            return m.group(1)
    return ""


def _default_checks(records: list[dict]) -> list[dict]:
    """One deterministic check per record: the URL the step ended on."""
    out = []
    for r in records:
        url = r.get("url_after", "")
        if url and "://" in url:
            out.append({"kind": "url_contains", "spec": {"url": url}})
    return out


def sanitize(proc: Procedure) -> tuple[Procedure, list[str]]:
    """Code-side sanitising: keep multi-locators, drop empty steps, number ids, validate checks."""
    warnings: list[str] = []
    proc.steps = [s for s in proc.steps if s.action or s.locators]
    for i, s in enumerate(proc.steps, 1):
        s.id = f"s{i}"
        s.locators = [l for l in s.locators if l.value]
        if not s.locators and s.action in ("click", "type"):
            warnings.append(f"s{i}: no usable locator; step may fail at execution.")
    proc.success_checks = [c for c in proc.success_checks if c.get("kind")]
    return proc, warnings


def asdict(l: Locator) -> dict:
    from dataclasses import asdict as _a
    return _a(l)
