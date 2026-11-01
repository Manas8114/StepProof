"""Tiny browser: Playwright Chromium in a dedicated worker thread.

One page at a time. The agent loop, Monitor recorder and human input all talk to the
page *through this thread* (Playwright's sync API is not thread-safe). The UI gets a
pollable JPEG screenshot plus forwarded human input and a kill switch.
Page content is untrusted: it can never change the allowlist, goal or safety rules
(the prompt-injection boundary, enforced in code).
"""
from __future__ import annotations
import base64, queue, re, threading
from concurrent.futures import Future
from .. import events

_SHOT_Q = 70


class TinyBrowser:
    """Wraps one headless Chromium page with a worker thread and a command queue."""

    def __init__(self, allowlist: set[str] | None = None) -> None:
        self.allowlist = allowlist or {"localhost:8011", "localhost:8012"}
        self.kill = threading.Event()
        self.last_shot: str = ""          # data URL (JPEG)
        self.url = "about:blank"
        self.title = ""
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._cmd: queue.Queue[tuple[str, object, Future]] = queue.Queue()
        self._done = threading.Event()
        self._worker.start()

    # ---- public API (thread-safe: everything goes through the worker) ----

    def start_site(self, url: str) -> dict:
        """Alias for `goto` (allowlist-gated). Every nav path refuses off-allowlist hosts."""
        return self.goto(url)

    def goto(self, url: str) -> dict:
        """Allowlist-gated navigation. Refused (and explained) when the host is not allowed."""
        host = _host_of(url)
        if host not in self.allowlist:
            return {"ok": False, "error": f"refused: host {host!r} not on the allowlist"}
        r = self._call("goto", url)
        self._after_nav()
        return r

    def act(self, op: str, arg: object = None) -> object:
        """Run a low-level page op on the worker thread (actions/agent use this)."""
        return self._call(op, arg)

    def observe(self) -> dict:
        """Compact interactive-element + text snapshot for the model (a11y-derived)."""
        return self._call("observe", None)

    def forward_input(self, kind: str, payload: dict) -> dict:
        """Human takeover: forward mouse/keyboard to the live page (PAUSED_HUMAN only)."""
        if kind == "click":
            return self._call("fclick", (int(payload.get("x", 0)), int(payload.get("y", 0))))
        if kind == "dblclick":
            return self._call("fdoubleclick", (int(payload.get("x", 0)), int(payload.get("y", 0))))
        if kind == "key":
            return self._call("fkey", str(payload.get("key", "")))
        if kind == "type":
            return self._call("ftype", str(payload.get("text", "")))
        if kind == "scroll":
            return self._call("fscroll", int(payload.get("dy", 0)))
        if kind == "drag":
            return self._call("fdrag", (payload.get("x0", 0), payload.get("y0", 0),
                                         payload.get("x1", 0), payload.get("y1", 0)))
        return {"ok": False, "error": f"unknown input kind {kind!r}"}

    def take_screenshot(self) -> str:
        """JPEG data URL (password fields masked). Also refreshes url/title on the worker thread."""
        shot, url, title = self._call("shot", None)
        self.last_shot, self.url, self.title = shot, url, title
        return shot

    @property
    def worker_done(self) -> threading.Event:
        return self._done

    def stop(self) -> None:
        self._cmd.put(("__stop__", None, None))
        self._done.wait(10)

    # ---- worker ----

    def _call(self, op, arg):
        fut: Future = Future()
        self._cmd.put((op, arg, fut))
        return fut.result(timeout=120)

    def _run_worker(self) -> None:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            self._browser = pw.chromium.launch(headless=True)
            ctx = self._browser.new_context(viewport={"width": 1024, "height": 640})
            self._page = ctx.new_page()
            # dialog guard: never let a page's dialog block the worker; use approval gates instead
            self._page.on("dialog", lambda d: d.dismiss())
            self._page.goto("about:blank")
            self._page.add_style_tag(content="input[type=password]{display:none!important}")
            while True:
                op, arg, fut = self._cmd.get()          # blocking; __stop__ ends the loop
                if op == "__stop__":
                    break
                if fut is not None:
                    try:
                        fut.set_result(self._do(op, arg))
                    except Exception as e:
                        fut.set_exception(e)
            self._browser.close()
        self._done.set()

    def _do(self, op: str, arg) -> object:
        p = self._page
        if op == "goto":
            p.goto(str(arg), wait_until="load")
            return {"ok": True, "url": p.url}
        if op == "shot":
            shot = p.screenshot(type="jpeg", quality=_SHOT_Q)
            return ("data:image/jpeg;base64," + base64.b64encode(shot).decode()), p.url, p.title()
        if op == "observe":
            from .observe import observe_page
            return observe_page(p)
        if op == "fill":
            p.fill(arg["selector"], str(arg.get("text", "")))
            return {"ok": True}
        if op == "select":
            p.select_option(arg["selector"], arg.get("value"))
            return {"ok": True}
        if op == "press":
            p.keyboard.press(str(arg.get("key", "Enter")))
            return {"ok": True}
        if op == "wheel":
            p.mouse.wheel(0, int(arg.get("dy", 0)))
            return {"ok": True}
        if op == "click_box":
            p.mouse.click(arg["x"], arg["y"])
            return {"ok": True}
        if op == "click_sel":
            p.click(arg["selector"], force=True)
            return {"ok": True}
        if op == "refresh":
            p.reload()
            return {"ok": True}
        if op == "eval":
            return p.evaluate(str(arg["expr"]))
        if op == "screenshot":
            p.screenshot(path=str(arg), type="jpeg", quality=75)
            return str(arg)
        if op == "fclick":
            p.mouse.click(*arg)
            return {"ok": True}
        if op == "fdoubleclick":
            p.mouse.dblclick(*arg)
            return {"ok": True}
        if op == "fkey":
            p.keyboard.press(str(arg))
            return {"ok": True}
        if op == "ftype":
            p.keyboard.type(str(arg))
            return {"ok": True}
        if op == "fscroll":
            p.mouse.wheel(0, int(arg))
            return {"ok": True}
        if op == "fdrag":
            p.mouse.move(arg[0], arg[1]); p.mouse.down(); p.mouse.move(arg[2], arg[3]); p.mouse.up()
            return {"ok": True}
        raise ValueError(f"unknown op {op!r}")

    def _after_nav(self) -> None:
        self.take_screenshot()
        events.BUS.publish("nav", {"url": self.url, "title": self.title})


_HOST_RE = re.compile(r"https?://([^/:]+)(?::(\d+))?")


def _host_of(url: str) -> str:
    m = _HOST_RE.match(url)
    if not m:
        return ""
    return f"{m.group(1).lower()}:{m.group(2)}" if m.group(2) else m.group(1).lower()
