"""Deterministic success checks. Success is decided by code inspecting browser state,
NEVER by the model claiming "done". Each check returns a CheckResult.
No model calls anywhere in this file.
"""
from __future__ import annotations


class CheckResult:
    __slots__ = ("name", "passed", "detail", "evidence")

    def __init__(self, name: str, passed: bool, detail: str = "", evidence: str = "") -> None:
        self.name, self.passed, self.detail, self.evidence = name, passed, detail, evidence


def _js(tb, sel: str, prop: str) -> object:
    """Ask the page (in JS) for a property of element `sel`. Deterministic, no model."""
    expr = f"(()=>{{const el=document.querySelector({sel!r});if(!el)return null;{prop};}})()"
    return tb.act("eval", {"expr": expr})


def url_contains(tb, spec: dict) -> CheckResult:
    want, got = spec.get("url", ""), tb.observe().get("url", "")
    return CheckResult("url_contains", want in got, f"url={got!r} (wanted substring {want!r})")


def text_visible(tb, spec: dict) -> CheckResult:
    hay = tb.observe().get("body_text", "").lower()
    want = spec.get("text", "").lower()
    return CheckResult("text_visible", want in hay, f"body contains {want!r}: {want in hay}")


def element_state(tb, spec: dict) -> CheckResult:
    sel, state = spec.get("selector", ""), spec.get("state", "visible")
    if not sel:
        return CheckResult("element_state", False, "no selector given")
    prop = {
        "visible": "return el.getBoundingClientRect().width>2&&el.getBoundingClientRect().height>2",
        "hidden": "return !(el.getBoundingClientRect().width>2&&el.getBoundingClientRect().height>2)",
        "enabled": "return !el.disabled",
        "disabled": "return !!el.disabled",
        "checked": "return !!el.checked",
        "unchecked": "return !el.checked",
    }.get(state)
    if prop is None:
        return CheckResult("element_state", False, f"unknown state {state!r}")
    res = _js(tb, sel, prop)
    return CheckResult("element_state", res is True, f"{sel!r} {state!r}: observed={res}")


def value_equals(tb, spec: dict) -> CheckResult:
    sel, want = spec.get("selector", ""), str(spec.get("value", ""))
    if not sel:
        return CheckResult("value_equals", False, "no selector given")
    got = _js(tb, sel, "return el.value")
    return CheckResult("value_equals", got == want, f"{sel!r} value={got!r} (wanted {want!r})")


_RUNNERS = {"url_contains": url_contains, "text_visible": text_visible,
            "element_state": element_state, "value_equals": value_equals}


def run_check(tb, check: dict) -> CheckResult:
    kind = check.get("kind") or check.get("type", "")
    fn = _RUNNERS.get(kind)
    if fn is None:
        return CheckResult(kind or "unknown", False, "unsupported check kind")
    spec = check.get("spec") if "spec" in check else {k: v for k, v in check.items() if k not in ("kind", "type")}
    return fn(tb, spec)


def all_pass(tb, checks: list[dict], shoot=None, prefix: str = "check") -> tuple[bool, list[CheckResult]]:
    """The run passes only when ALL checks pass (conjunctive).
    With `shoot(tag)->path` supplied, every verdict links to an evidence screenshot
    (master-prompt requirement: verdicts + evidence)."""
    results = []
    for i, c in enumerate(checks):
        r = run_check(tb, c)
        if shoot is not None:
            r.evidence = shoot(f"{prefix}_{i}_{'pass' if r.passed else 'fail'}_{r.name}")
        results.append(r)
    return all(r.passed for r in results), results
