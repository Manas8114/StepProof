"""Compact page observation for the agent: the a11y tree's interactive elements with
boxes, plus URL/title. This is what Muse Spark sees (text) alongside the screenshot
(JPEG). Password values are never included (safety rule: credentials are out of scope)."""
from __future__ import annotations

_OBSERVE_JS = """
() => {
  const out = [];
  const push = (el, role, name, kind) => {
    const r = el.getBoundingClientRect();
    out.push({role, name, kind, id: el.id || null,
              x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
              visible: r.width > 2 && r.height > 2});
  };
  document.querySelectorAll('button, input:not([type=hidden]), select, textarea, a[href], [role=button], [role=link], [contenteditable=true]').forEach(el => {
    if (el.closest('[type=hidden]')) return;
    const t = el.tagName.toLowerCase();
    let role, kind;
    const explicit = el.getAttribute('role');
    if (explicit) { role = explicit; }
    else if (t === 'button') { role = 'button'; }
    else if (t === 'a') { role = 'link'; }
    else if (t === 'select') { role = 'combobox'; }
    else if (t === 'textarea') { role = 'textbox'; }
    else if (t === 'input') { role = (el.type === 'checkbox' || el.type === 'radio') ? el.type : 'textbox'; }
    else role = 'textbox';
    if (t === 'input') kind = el.type; else kind = t;
    // credentials are out of scope by construction: a password field is observed as a
    // field (role/kind/box) but its value never becomes the element name the model sees
    let name = (t === 'input' && el.type === 'password') ? ''
                : (el.getAttribute('aria-label') || el.getAttribute('title')
                || (t === 'input' || t === 'select' ? el.value || '' : (el.textContent || '').trim().slice(0, 60))
                || el.id || '').trim();
    name = name.slice(0, 60);
    push(el, role, name, kind);
  });
  const txt = document.body.innerText.slice(0, 400);
  return {url: location.href, title: document.title, body_text: txt, elements: out.slice(0, 48)};
}
"""


def observe_page(page) -> dict:
    """Return {url, title, body_text, elements: [{role,name,kind,id,x,y,w,h,visible}]} (<=48, visible-prefixed)."""
    data = page.evaluate(_OBSERVE_JS)
    els = data.get("elements", [])
    els.sort(key=lambda e: (not e.get("visible"), e.get("y", 0), e.get("x", 0)))
    return data


def elements_text(obs: dict) -> str:
    """Compact text form for the model prompt: '[n] role "name" (x,y w×h)'. Password values excluded by construction."""
    lines = [f"URL: {obs.get('url')}  TITLE: {obs.get('title')}"]
    for i, e in enumerate(obs.get("elements", [])):
        lines.append(f"[{i}] {e.get('role','?')} {e.get('name','')!r} @({e.get('x')},{e.get('y')}) {e.get('w')}x{e.get('h')}"
                     + ("" if e.get("visible") else " (offscreen)"))
    if obs.get("body_text"):
        lines.append("TEXT: " + obs["body_text"].replace("\n", " | ")[:600])
    return "\n".join(lines)
