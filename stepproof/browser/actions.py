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


def _resolve_target(tb, sel: str | None) -> tuple[str | None, int | None, int | None]:
    """Resolve a selector string.
    If it's an element index like '[0]' or '[1]', map it to:
    1. Its actual CSS ID (e.g. '#vendor') or CSS selector
    2. Or its center coordinates (cx, cy) so fill_at / click_box can actuate it.
    """
    if not sel or not tb:
        return sel, None, None
    s = str(sel).strip()
    m = re.match(r"^\[(\d+)\]$", s)
    if m:
        try:
            idx = int(m.group(1))
            obs = tb.observe()
            elements = [e for e in obs.get("elements", []) if e.get("visible")]
            if idx < len(elements):
                el = elements[idx]
                if el.get("id"):
                    return f"#{el['id']}", None, None
                name = el.get("name", "")
                if el.get("kind") == "input" and name:
                    return f"input[name='{name}']", None, None
                cx = el["x"] + el["w"] // 2
                cy = el["y"] + el["h"] // 2
                return None, cx, cy
        except Exception:
            pass
    return sel, None, None


def _label_of(tb, selector: str) -> str | None:
    """Visible label of the element a CSS selector addresses; None when no such element
    exists (deterministic page read - no model)."""
    if not selector:
        return None
    rsel, cx, cy = _resolve_target(tb, selector)
    if not rsel:
        if cx is not None and cy is not None:
            expr = ("(()=>{const el=document.elementFromPoint(%d, %d);"
                    "if(!el)return null;"
                    "return (el.textContent||el.getAttribute('aria-label')||el.id||'').trim().slice(0,60);})()"
                    % (cx, cy))
            try:
                return tb.act("eval", {"expr": expr})
            except Exception:
                return None
        return None
    expr = ("(()=>{const el=document.querySelector(%r);"
            "if(!el)return null;"
            "return (el.textContent||el.getAttribute('aria-label')||el.id||'').trim().slice(0,60);})()"
            % rsel)
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
                rsel, cx, cy = _resolve_target(tb, sel)
                if rsel:
                    tb.act("click_sel", {"selector": rsel})
                    detail = f"clicked {rsel}"
                elif cx is not None and cy is not None:
                    tb.act("click_box", {"x": cx, "y": cy})
                    detail = f"clicked @({cx},{cy}) (resolved from {sel})"
                else:
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
            text = str(arg.get("text", "") or arg.get("value", ""))
            if sel:
                rsel, cx, cy = _resolve_target(tb, sel)
                if rsel:
                    tb.act("fill", {"selector": rsel, "text": text})
                    detail = f"typed into {rsel}"
                elif cx is not None and cy is not None:
                    res = tb.act("fill_at", {"x": cx, "y": cy,
                                             "text": text,
                                             "enter": bool(arg.get("enter", False))})
                    if isinstance(res, dict) and not res.get("ok"):
                        raise RuntimeError(res.get("error", "fill_at failed"))
                    detail = f"typed into @({cx},{cy}) (resolved from {sel})"
                else:
                    tb.act("fill", {"selector": sel, "text": text})
                    detail = f"typed into {sel}"
            elif "x" in arg and "y" in arg:
                res = tb.act("fill_at", {"x": int(arg["x"]), "y": int(arg["y"]),
                                         "text": text,
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
            sel = arg.get("selector")
            val = str(arg.get("value", ""))
            if sel:
                rsel, cx, cy = _resolve_target(tb, sel)
                if rsel:
                    tb.act("select", {"selector": rsel, "value": val})
                    detail = f"selected {val} in {rsel}"
                elif cx is not None and cy is not None:
                    res = tb.act("select_at", {"x": cx, "y": cy, "value": val})
                    if isinstance(res, dict) and not res.get("ok"):
                        raise RuntimeError(res.get("error", "select_at failed"))
                    detail = f"selected {val} @({cx},{cy}) (resolved from {sel})"
                else:
                    tb.act("select", {"selector": sel, "value": val})
                    detail = f"selected {val} in {sel}"
            elif "x" in arg and "y" in arg:
                res = tb.act("select_at", {"x": int(arg["x"]), "y": int(arg["y"]), "value": str(arg.get("value", ""))})
                if isinstance(res, dict) and not res.get("ok"):
                    raise RuntimeError(res.get("error", "select_at failed"))
                grounded = arg.get("grounded_by", "vision")
                detail = f"selected {arg.get('value')} @({arg['x']},{arg['y']}) ({grounded} healed)"
            else:
                raise ValueError("select needs 'selector' or (x,y) coordinates")
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
    """Click the best-matching visible element: exact substring first, then token ratio match,
    and falls back to querying the live page DOM for matching text/links/buttons."""
    obs = tb.observe()
    low = name.strip().lower()
    words = [w for w in re.findall(r"\w+", low) if len(w) > 1]
    best, best_score = None, 0

    for el in obs.get("elements", []):
        if not el.get("visible"):
            continue
        hay = f"{el.get('name', '')} {el.get('kind', '')} {el.get('role', '')}".lower()
        score = 0
        if low in hay:
            score = 100
        elif words:
            matched = sum(1 for w in words if w in hay)
            if matched == len(words):
                score = 80 + len(words)
            elif matched / len(words) >= 0.5:
                score = int(40 + 40 * (matched / len(words)))
        elif len(low) >= 4 and low in hay.replace(" ", ""):
            score = 35
        if score > best_score:
            best, best_score = el, score

    if best and best_score >= 40:
        tb.act("click_box", {"x": best["x"] + best["w"] // 2, "y": best["y"] + best["h"] // 2})
        return

    # Fallback: Query the live DOM across all clickable/heading/link elements
    try:
        import json
        words_json = json.dumps(words)
        q_json = json.dumps(low)
        js_find = f"""(() => {{
            const searchWords = {words_json};
            const rawQ = {q_json};
            const candidates = Array.from(document.querySelectorAll(
                'a, button, [role=button], [role=link], h1, h2, h3, h4, ytd-video-renderer, #video-title, span, p'
            ));
            let bestEl = null;
            let bestScore = 0;
            for (const el of candidates) {{
                const r = el.getBoundingClientRect();
                if (r.width < 5 || r.height < 5) continue;
                const text = (el.getAttribute('title') || el.getAttribute('aria-label') || el.innerText || el.textContent || '').toLowerCase().replace(/\\s+/g, ' ');
                if (!text) continue;
                let score = 0;
                if (text.includes(rawQ)) {{
                    score = 100;
                }} else if (searchWords.length > 0) {{
                    let matched = 0;
                    for (const w of searchWords) {{
                        if (text.includes(w)) matched++;
                    }}
                    if (matched === searchWords.length) {{
                        score = 85;
                    }} else if (matched / searchWords.length >= 0.4) {{
                        score = Math.round(35 + 45 * (matched / searchWords.length));
                    }}
                }}
                if (score > bestScore) {{
                    bestScore = score;
                    bestEl = el;
                }}
            }}
            if (bestEl && bestScore >= 35) {{
                try {{ bestEl.scrollIntoView({{ behavior: 'instant', block: 'center' }}); }} catch(e) {{}}
                const r2 = bestEl.getBoundingClientRect();
                return {{
                    found: true,
                    score: bestScore,
                    x: Math.round(r2.x + r2.width / 2),
                    y: Math.round(r2.y + r2.height / 2)
                }};
            }}
            return {{ found: false }};
        }})()"""
        dom_res = tb.act("eval", {"expr": js_find})
        if isinstance(dom_res, dict) and dom_res.get("found"):
            tb.act("click_box", {"x": dom_res["x"], "y": dom_res["y"]})
            return
    except Exception:
        pass

    if best and best_score >= 30:
        tb.act("click_box", {"x": best["x"] + best["w"] // 2, "y": best["y"] + best["h"] // 2})
        return

    raise ValueError(f"no visible element matching {name!r}")
