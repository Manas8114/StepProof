"""Deterministic success checks. Success is decided by code inspecting browser state,
NEVER by the model claiming "done". Each check returns a CheckResult.
No model calls anywhere in this file.
"""
from __future__ import annotations


class CheckResult:
    __slots__ = ("name", "passed", "detail")

    def __init__(self, name: str, passed: bool, detail: str = "") -> None:
        self.name, self.passed, self.detail = name, passed, detail


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
    fn = _RUNNERS.get(check.get("kind", ""))
    if fn is None:
        return CheckResult(check.get("kind", "unknown"), False, "unsupported check kind")
    return fn(tb, check.get("spec", {}))   # each runner reads the nested spec


def all_pass(tb, checks: list[dict]) -> tuple[bool, list[CheckResult]]:
    """The run passes only when ALL checks pass (conjunctive)."""
    results = [run_check(tb, c) for c in checks]
    return all(r.passed for r in results), results
