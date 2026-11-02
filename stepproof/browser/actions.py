"""Agent actions + code-first safety classification, all through the TinyBrowser worker.

`execute_action` runs one action on the live page and returns a result with evidence.
`classify_action` is CODE-FIRST: the model's classification may only ever *add* gates,
never remove them (ground rule: code decides safety)."""
from __future__ import annotations
import re
from dataclasses import dataclass

from ..events import BUS

IRREVERSIBLE_HINTS = [
    "delete", "remove", "discard", "unsubscribe", "erase", "purge", "terminate",
    "cancel order", "logout", "sign out",
]
EXTERNAL_HINTS = [
    "send", "pay", "post", "submit", "publish", "order", "confirm",
    "email", "notify", "transfer", "book", "deploy",
]
_EXTERNAL_URL = re.compile(r"(?i)^https?://(?!localhost|127\.0\.0\.1)")


@dataclass
class ActionResult:
    ok: bool
    action: str
    detail: str = ""
    irreversible: bool = False
    external: bool = False
    evidence: dict | None = None


def classify_element_text(label: str) -> tuple[bool, bool]:
    """(irreversible, external) from an element's visible label. Pure string rules."""
    low = label.lower()
    irrev = any(h in low for h in IRREVERSIBLE_HINTS)
    ext = any(h in low for h in EXTERNAL_HINTS)
    return irrev, ext


def classify_action(name: str, arg: dict, tb=None) -> tuple[bool, bool]:
    """Classify an action by name/args. Code decides; the model may escalate, never
    downgrade. For click/select, the element's visible label drives the verdict: a
    `name`-addressed action uses it directly; a `selector`-addressed action resolves the
    element's label via the live page (`tb` required - gate call sites pass it), so a
    selector click on "Submit" gates exactly like a name click. A target that cannot
    be resolved is escalated to the gate (external), never run ungated. Without `tb`
    only `name`/`url` are classified (informational callers keep the pure behavior)."""
    if name == "goto":
        return False, bool(_EXTERNAL_URL.match(str(arg.get("url", ""))))
    if name in ("click", "select"):
        label = str(arg.get("name", "")).strip()
        if not label and arg.get("selector"):
            if tb is None:
                return False, False
            found = _label_of(tb, str(arg["selector"]))
            if found is None:
                return False, True    # unknown target -> escalate, never run ungated
            label = found
        return classify_element_text(label)
    return False, False


def _label_of(tb, selector: str) -> str | None:
    """Visible label of the element a CSS selector addresses; None when no such element
    exists (deterministic page read - no model)."""
    expr = ("(()=>{const el=document.querySelector(%r);"
            "if(!el)return null;"
            "return (el.textContent||el.getAttribute('aria-label')||el.id||'').trim().slice(0,60);})()"
            % selector)
    try:
        return tb.act("eval", {"expr": expr})
    except Exception:
        return None


def execute_action(tb, name: str, arg: dict) -> ActionResult:
    """Run one action on the browser (through the worker thread). Evidence = URL before/after."""
    irrev, ext = classify_action(name, arg, tb=tb)   # keep ActionResult flags consistent with the gate
    before_url = tb.observe().get("url", "")
    BUS.publish("action", {"name": name, "arg": arg, "step_url": before_url})
    ok, detail = True, ""
    try:
        if name == "click":
            sel, selname = arg.get("selector"), arg.get("name")
            if sel:
                tb.act("click_sel", {"selector": sel})
                detail = f"clicked {sel}"
            elif selname:
                _click_by_name(tb, selname)
                detail = f"clicked {selname!r}"
            elif "x" in arg and "y" in arg:
                tb.act("click_box", {"x": int(arg["x"]), "y": int(arg["y"])})
                detail = f"clicked @({arg['x']},{arg['y']}) " + arg.get("grounded_by", "coords")
            else:
                raise ValueError("click needs 'selector', 'name', or (x,y) coordinates")
        elif name in ("type", "fill"):
            sel = arg.get("selector")
            if sel:
                tb.act("fill", {"selector": sel, "text": arg.get("text", "")})
                detail = f"typed into {sel}"
            elif "x" in arg and "y" in arg:
                res = tb.act("fill_at", {"x": int(arg["x"]), "y": int(arg["y"]),
                                         "text": str(arg.get("text", "") or arg.get("value", "")),
                                         "enter": bool(arg.get("enter", False))})
                if isinstance(res, dict) and not res.get("ok"):
                    raise RuntimeError(res.get("error", "fill_at failed"))
                grounded = arg.get("grounded_by", "vision")
                detail = f"typed into @({arg['x']},{arg['y']}) ({grounded} healed)"
            else:
                raise ValueError("type/fill needs 'selector' or (x,y) coordinates")
        elif name in ("key", "press"):
            tb.act("press", {"key": arg.get("key", "Enter")})
            detail = f"pressed {arg.get('key', 'Enter')}"
        elif name == "scroll":
            tb.act("wheel", {"dy": int(arg.get("dy", 0))})
            detail = f"scrolled {arg.get('dy', 0)}px"
        elif name == "goto":
            r = tb.goto(str(arg.get("url", "")))
            ok = r.get("ok", False)
            detail = r.get("url") if ok else r.get("error", "goto failed")
        elif name == "select":
            tb.act("select", {"selector": arg["selector"], "value": arg.get("value")})
            detail = f"selected {arg.get('value')} in {arg['selector']}"
        elif name == "wait":
            import time
            time.sleep(int(arg.get("ms", 250)) / 1000)
            detail = f"waited {arg.get('ms', 250)}ms"
        else:
            ok, detail = False, f"unknown action {name!r}"
    except Exception as e:
        ok, detail = False, f"{type(e).__name__}: {str(e)[:120]}"
    after_url = tb.observe().get("url", "")
    BUS.publish("action_done", {"name": name, "ok": ok, "detail": detail, "url": after_url})
    return ActionResult(ok=ok, action=name, detail=detail, irreversible=irrev, external=ext,
                        evidence={"before_url": before_url, "after_url": after_url})


def _click_by_name(tb, name: str) -> None:
    """Click the best-matching visible element: exact substring first, then token match
    (every word of `name` present in the element's name/kind). Box-centre click."""
    obs = tb.observe()
    low = name.strip().lower()
    toks = low.split()
    best, best_score = None, 0
    for el in obs.get("elements", []):
        if not el.get("visible"):
            continue
        hay = f"{el.get('name', '')} {el.get('kind', '')}".lower()
        score = 0
        if low in hay:
            score = 100
        elif toks and all(t in hay for t in toks):
            score = 50 + len(toks)
        elif len(low) >= 4 and low in hay.replace(" ", ""):
            score = 30
        if score > best_score:
            best, best_score = el, score
    if best_score < 30:
        raise ValueError(f"no visible element matching {name!r}")
    tb.act("click_box", {"x": best["x"] + best["w"] // 2, "y": best["y"] + best["h"] // 2})
