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


def derive_vision_concept(tool: str, element_name: str = "",
                          locators: list[dict | Locator] | None = None,
                          narration: str = "") -> str:
    """Derive one short noun phrase per step for visual grounding (SAM 3.1).
    SAM wants short noun phrases (e.g. 'Vendor text input', 'Submit claim button'),
    never full sentences or instructions."""
    raw = element_name.strip()
    generic_ids = {"endpoint", "container", "wrapper", "content", "item", "main", "root", "app"}
    if raw.lower() in generic_ids:
        raw = ""
    if not raw and locators:
        for l in locators:
            val = getattr(l, "value", None) or (l.get("value") if isinstance(l, dict) else "")
            kind = getattr(l, "kind", None) or (l.get("kind") if isinstance(l, dict) else "")
            if kind in ("text", "role") and val:
                candidate = val.strip()
                if candidate.lower() not in generic_ids:
                    raw = candidate
                    break
            if kind == "css" and val:
                m = re.search(r"#([a-zA-Z0-9_-]+)", val)
                if m:
                    cid = m.group(1).replace("-", " ").replace("_", " ").title()
                    if cid.lower() not in generic_ids:
                        raw = cid
                        break
    if not raw and narration:
        m = re.search(r"(?:enter|type|select|pick|click|file|submit|the)\s+([a-zA-Z0-9\s_-]+)", narration, re.I)
        raw = m.group(1).strip() if m else narration.strip()

    low = raw.lower()
    if tool in ("type", "fill"):
        if "input" in low or "field" in low or "box" in low:
            return raw
        if any(k in low for k in ("amount", "qty", "quantity", "price", "count")):
            return f"{raw} number input".strip()
        return f"{raw} text input".strip()
    elif tool == "click":
        if "button" in low:
            return raw
        if any(k in low for k in ("row", "table", "item", "entry")):
            return raw if "row" in low else f"{raw} row"
        return f"{raw} button".strip()
    elif tool == "select":
        if "dropdown" in low or "menu" in low or "select" in low:
            return raw
        return f"{raw} dropdown menu".strip()
    return raw or f"{tool} target"


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
    name = recarg.get("element_name", "") or rec.get("element_name", "")
    if name:
        arg["name"] = name
    concept = rec.get("vision_concept") or derive_vision_concept(tool, name, locs, rec.get("narration", ""))
    s = Step(id=f"s{len([])+1}", description=rec.get("narration") or f"{tool} via {tool} step",
             vision_concept=concept,
             action=tool, arg=arg, locators=locs)
    s.id = ""  # renumbered by caller
    return s


def compile_to_procedure(records: list[dict], goal: str, site: str = "",
                         success_checks: Optional[list[dict]] = None,
                         model=None, transcript: str = "",
                         parameters: Optional[dict] = None) -> tuple[Procedure, list[str]]:
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
                     steps=steps, parameters=parameters or {},
                     success_checks=checks, source="learned")
    proc.sign()
    if not steps:
        warnings.append("no recorded actions to learn from; procedure has no steps.")
    if not checks:
        warnings.append("no deterministic success checks; execution will finish on step count only.")
    return proc, warnings


def compile_from_agent_trace(steps: list[dict], goal: str, site: str = "",
                             success_checks: Optional[list[dict]] = None,
                             transcript: str = "",
                             parameters: Optional[dict] = None) -> tuple[Procedure, list[str]]:
    """Learn-from-own-run (Agent-Workflow-Memory step, one function): turn a successful
    goal-only agent trace into a reusable, deterministic Procedure.

    `steps` are `RunLog.steps` entries: {"tool", "args", "ok", "detail"}. Only ok, actuating
    steps become procedure steps: a css `selector` keeps a css locator; a visible `name` gets
    role+text locators - so the learned procedure self-heals exactly like a Monitor-recorded
    one (fall through on UI drift). Runs 1 costs an agent; runs 2+ cost zero model calls.
    """
    warnings: list[str] = []
    recs = []
    for s in steps:
        if not s.get("ok", False):
            continue
        tool, a = s.get("tool", ""), s.get("args", {})
        if tool not in ("click", "type", "select"):
            continue
        locs = []
        if a.get("selector"):
            locs.append({"kind": "css", "value": a["selector"]})
        if a.get("name"):
            locs.append({"kind": "text", "value": a["name"]})
        if not locs:
            warnings.append(f"agent step {tool!r} had no usable locator; skipped")
            continue
        recs.append({"tool": tool, "locators": locs, "narration": f"agent: {tool}",
                     "arg": {"text": a.get("text", ""), "value": a.get("value", ""),
                             "element_name": a.get("name", "")}})
    if not recs:
        warnings.append("no usable actuating steps in the agent trace; procedure is empty.")
    proc, w2 = compile_to_procedure(recs, goal, site, success_checks or [], parameters=parameters)
    return proc, warnings + w2


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
