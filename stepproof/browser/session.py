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
from pathlib import Path
from urllib.parse import urljoin
from .. import events

_SHOT_Q = 70


class TinyBrowser:
    """Wraps one headless Chromium page with a worker thread and a command queue.

    `user_data_dir` (optional) gives the browser a persistent profile (the live
    companion, UNIBOT P0.1b); tests and eval harnesses use an ephemeral one so
    concurrent instances don't contend on the profile lock.
    """

    def __init__(self, allowlist: set[str] | None = None,
                 user_data_dir: str | None = None,
                 cdp_url: str | None = None) -> None:
        from stepproof import config as cfg
        default_allow = {"localhost:8011", "localhost:8012", "127.0.0.1:8011", "127.0.0.1:8012"}.union(cfg.ALLOWED_HOSTS)
        self.allowlist = allowlist if allowlist is not None else default_allow
        self.kill = threading.Event()
        self.last_shot: str = ""          # data URL (JPEG)
        self.url = "about:blank"
        self.title = ""
        self.loading = False             # page not yet finished loading (URL-bar state)
        self._profile = user_data_dir
        self._cdp_url = cdp_url
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._cmd: queue.Queue[tuple[str, object, Future]] = queue.Queue()
        self._done = threading.Event()
        self._worker.start()

    # ---- public API (thread-safe: everything goes through the worker) ----

    def _is_allowed(self, host: str) -> bool:
        if not host:
            return False
        if "*" in self.allowlist or "all" in self.allowlist:
            return True
        from stepproof import config as cfg
        if getattr(cfg, "ALLOW_ALL_SITES", False):
            return True
        return host in self.allowlist

    def allow_host(self, host: str) -> None:
        """Dynamically add host to allowlist."""
        if host:
            self.allowlist.add(host.lower())

    def start_site(self, url: str, base: str | None = None) -> dict:
        """Alias for `goto` (allowlist-gated). Every nav path refuses off-allowlist hosts.
        Relative paths ('/site/expense') are resolved against `base` so the UI's relative
        values don't trip the gate with an empty host."""
        return self.goto(url, base=base)

    def goto(self, url: str, base: str | None = None) -> dict:
        """Allowlist-gated navigation. Refused (and explained) when the host is not allowed."""
        raw = (url or "").strip()
        if not raw or raw == "current":
            return {"ok": True, "url": self.url}
        url = _absolutize(raw, base)
        host = _host_of(url)
        if not self._is_allowed(host):
            return {"ok": False, "error": f"refused: host {host!r} not on the allowlist"}
        try:
            r = self._call("goto", url)
            self._after_nav()
            return r
        except Exception as e:
            return {"ok": False, "error": f"navigation failed: {e}"}

    # ---- URL-bar navigation (P0.1b): back/forward/reload + loading state.
    # Every history op re-verifies the result against the allowlist: the UI's URL bar can
    # only move within allowed hosts; an off-allowlist landing is refused, not followed.

    def go_back(self) -> dict:
        r = self._call("back", None)
        self._after_nav()
        return self._verify_on_allowlist()

    def go_forward(self) -> dict:
        r = self._call("forward", None)
        self._after_nav()
        return self._verify_on_allowlist()

    def reload(self) -> dict:
        r = self._call("refresh", None)
        self._after_nav()
        return {"ok": True, "url": self.url}

    def _verify_on_allowlist(self) -> dict:
        """After a history op, the page may have landed off-allowlist (a back/forward into
        a saved off-allowlist entry). Refuse it: report + navigate back to about:blank."""
        host = _host_of(self.url)
        if host and not self._is_allowed(host):
            self._call("goto", "about:blank")
            self._after_nav()
            return {"ok": False, "error": f"refused: host {host!r} not on the allowlist"}
        return {"ok": True, "url": self.url}

    def act(self, op: str, arg: object = None) -> object:
        """Run a low-level page op on the worker thread (actions/agent use this)."""
        return self._call(op, arg)

    def fill_at(self, x: int, y: int, text: str, enter: bool = False) -> dict:
        """Type into element at (x,y) visually; refuses password fields."""
        return self._call("fill_at", {"x": x, "y": y, "text": text, "enter": enter})

    def select_at(self, x: int, y: int, value: str) -> dict:
        """Select an option in dropdown at (x,y) visually."""
        return self._call("select_at", {"x": x, "y": y, "value": value})

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
        if kind == "fill_at":
            return self._call("fill_at", payload)
        return {"ok": False, "error": f"unknown input kind {kind!r}"}

    def get_tabs(self) -> list[dict]:
        """Return list of active browser tabs/windows (for OAuth popups and multi-tab workflows)."""
        return self._call("tabs", None)

    def switch_tab(self, index: int) -> dict:
        """Switch active page to tab at given index."""
        r = self._call("switch_tab", index)
        self._after_nav()
        return r

    def close_tab(self, index: int) -> dict:
        """Close tab at given index."""
        r = self._call("close_tab", index)
        self._after_nav()
        return r

    def detect_captcha(self) -> dict:
        """Detect Cloudflare Turnstile, hCaptcha, reCAPTCHA, or interstitial on active page."""
        return self._call("detect_captcha", None)

    def solve_captcha(self, provider: str | None = None, api_key: str | None = None) -> dict:
        """Attempt automated or remote solving for detected anti-bot challenge."""
        return self._call("solve_captcha", {"provider": provider, "api_key": api_key})

    def take_screenshot(self) -> str:
        """JPEG data URL (password fields masked). Also refreshes url/title on the worker thread."""
        try:
            shot, url, title = self._call("shot", None)
            self.last_shot, self.url, self.title = shot, url, title
            return shot
        except Exception:
            return self.last_shot or ""

    @property
    def worker_done(self) -> threading.Event:
        return self._done

    def stop(self) -> None:
        self._cmd.put(("__stop__", None, None))
        self._done.wait(10)

    def close(self) -> None:
        self.stop()

    # ---- worker ----

    def _call(self, op, arg):
        fut: Future = Future()
        self._cmd.put((op, arg, fut))
        return fut.result(timeout=120)

    def _dismiss_popups(self, p) -> None:
        """Auto-dismiss common cookie consent banners, GDPR dialogs, and welcome overlays
        on public sites so interactions aren't blocked by backdrop elements."""
        try:
            p.evaluate("""() => {
                const selectors = [
                    '#onetrust-accept-btn-handler',
                    '#accept-cookie-notification',
                    'button#L2AGLb',
                    'button[aria-label*="Accept all"]',
                    'button[aria-label*="Agree"]',
                    'button[data-testid*="cookie-policy-manage-dialog-accept-button"]',
                    '.cookie-consent-accept',
                    '.js-cookie-consent-agree',
                    'button.agree-button',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.offsetParent !== null) { el.click(); return; }
                }
                const btns = Array.from(document.querySelectorAll('button, a[role="button"]'));
                for (const b of btns) {
                    const t = (b.textContent || '').trim().toLowerCase();
                    if (['accept all', 'i agree', 'accept cookies', 'got it', 'agree', 'allow all'].includes(t)) {
                        if (b.offsetParent !== null) { b.click(); return; }
                    }
                }
            }""")
        except Exception:
            pass

    def _navigate(self, p, url: str) -> None:
        """Navigate with a visible loading state (URL bar) + the password mask re-applied
        on the new document (the model never sees a typed credential)."""
        self.loading = True
        try:
            p.goto(url, wait_until="load")
            p.add_style_tag(content="input[type=password]{display:none!important}")
            self._dismiss_popups(p)
        finally:
            self.loading = False

    def _wait_load(self, p) -> None:
        """best-effort settle wait for history ops; the UI's loading chip reflects this."""
        try:
            p.wait_for_load_state("load", timeout=5000)
        except Exception:
            pass

    def _run_worker(self) -> None:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            # real browser (P0.1b): persistent profile when given (the live companion),
            # remote CDP grid worker when cdp_url is specified,
            # ephemeral for eval/tests so concurrent instances don't fight for the lock
            launch = dict(headless=True)
            if self._cdp_url:
                self._browser = pw.chromium.connect_over_cdp(self._cdp_url)
                ctx = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context(
                    viewport={"width": 1024, "height": 640},
                    accept_downloads=False
                )
                self._page = ctx.pages[0] if ctx.pages else ctx.new_page()
            elif self._profile:
                Path(self._profile).mkdir(parents=True, exist_ok=True)
                ctx = pw.chromium.launch_persistent_context(self._profile, headless=True,
                                                            viewport={"width": 1024, "height": 640},
                                                            accept_downloads=False)  # downloads blocked by default
                self._browser = None
                self._page = ctx.pages[0] if ctx.pages else ctx.new_page()
            else:
                self._browser = pw.chromium.launch(**launch)
                ctx = self._browser.new_context(viewport={"width": 1024, "height": 640},
                                                accept_downloads=False)
                self._page = ctx.new_page()

            self._pages = [self._page]

            def _setup_page(pg):
                pg.on("dialog", lambda d: d.dismiss())
                pg.on("download", lambda d: d.cancel())
                try:
                    pg.add_style_tag(content="input[type=password]{display:none!important}")
                except Exception:
                    pass

            def _on_new_page(new_pg):
                _setup_page(new_pg)
                if new_pg not in self._pages:
                    self._pages.append(new_pg)
                self._page = new_pg
                events.BUS.publish("tab_opened", {
                    "url": getattr(new_pg, "url", ""),
                    "count": len(self._pages),
                    "active_index": len(self._pages) - 1
                })
                def _on_close():
                    if new_pg in self._pages:
                        self._pages.remove(new_pg)
                    if self._page == new_pg:
                        self._page = self._pages[-1] if self._pages else None
                        self._after_nav()
                    events.BUS.publish("tab_closed", {"count": len(self._pages)})
                new_pg.on("close", _on_close)

            _setup_page(self._page)
            ctx.on("page", _on_new_page)
            self._page.on("popup", _on_new_page)
            self._page.goto("about:blank")
            while True:
                op, arg, fut = self._cmd.get()          # blocking; __stop__ ends the loop
                if op == "__stop__":
                    break
                if fut is not None:
                    try:
                        fut.set_result(self._do(op, arg))
                    except Exception as e:
                        fut.set_exception(e)
            (self._browser or ctx).close()
        self._done.set()

    def _do(self, op: str, arg) -> object:
        p = self._page
        if op == "goto":
            self._navigate(p, str(arg))
            return {"ok": True, "url": p.url}
        if op == "back":
            p.go_back()
            self._wait_load(p)
            return {"ok": True}
        if op == "forward":
            p.go_forward()
            self._wait_load(p)
            return {"ok": True}
        if op == "shot":
            try:
                shot = p.screenshot(type="jpeg", quality=_SHOT_Q)
                return ("data:image/jpeg;base64," + base64.b64encode(shot).decode()), p.url, p.title()
            except Exception:
                try:
                    import time as _t
                    _t.sleep(0.1)
                    shot = p.screenshot(type="jpeg", quality=_SHOT_Q)
                    return ("data:image/jpeg;base64," + base64.b64encode(shot).decode()), p.url, p.title()
                except Exception:
                    return (self.last_shot or ""), getattr(p, "url", ""), (p.title() if hasattr(p, "title") else "")
        if op == "detect_captcha":
            from ..captcha.detector import detect_challenge
            ch = detect_challenge(p)
            return ch.to_dict()
        if op == "solve_captcha":
            from ..captcha.solver import CaptchaHandler
            handler = CaptchaHandler(
                auto_solve_turnstile=True,
                remote_provider=arg.get("provider") if isinstance(arg, dict) else None,
                provider_api_key=arg.get("api_key") if isinstance(arg, dict) else None
            )
            ch, res = handler.handle(p)
            return {"challenge": ch.to_dict(), "result": res.to_dict()}
        if op == "observe":
            self._dismiss_popups(p)
            from .observe import observe_page
            return observe_page(p)
        if op == "fill":
            p.fill(arg["selector"], str(arg.get("text", "")), timeout=int(arg.get("timeout", 1500)))
            return {"ok": True}
        if op == "fill_at":
            x, y = int(arg.get("x", 0)), int(arg.get("y", 0))
            text = str(arg.get("text", ""))
            enter = bool(arg.get("enter", False))
            check = p.evaluate("""([cx, cy]) => {
                const el = document.elementFromPoint(cx, cy);
                if (!el) return { ok: false, error: "no element at coordinates" };
                if (el.matches('input[type="password"]') || el.closest('input[type="password"]')) {
                    return { ok: false, error: "refusing to type into password field" };
                }
                const tag = el.tagName.toLowerCase();
                const isInput = tag === 'input' && !['submit', 'button', 'checkbox', 'radio', 'file', 'image', 'reset'].includes(el.type);
                const isTextarea = tag === 'textarea';
                const isEditable = el.isContentEditable || el.getAttribute('role') === 'textbox';
                if (!isInput && !isTextarea && !isEditable) {
                    return { ok: false, error: "refusing to type into unknown/non-input field: " + tag };
                }
                return { ok: true };
            }""", [x, y])
            if not check.get("ok"):
                return {"ok": False, "error": check.get("error", "fill_at check failed")}
            p.mouse.click(x, y)
            p.keyboard.type(text)
            if enter:
                p.keyboard.press("Enter")
            return {"ok": True}
        if op == "select":
            p.select_option(arg["selector"], arg.get("value"), timeout=int(arg.get("timeout", 1500)))
            return {"ok": True}
        if op == "select_at":
            x, y = int(arg.get("x", 0)), int(arg.get("y", 0))
            val = str(arg.get("value", ""))
            return p.evaluate("""([cx, cy, v]) => {
                const el = document.elementFromPoint(cx, cy);
                if (!el) return { ok: false, error: "no element at coordinates" };
                const sel = el.matches('select') ? el : el.closest('select') || el.querySelector('select');
                if (!sel) return { ok: false, error: "no select element at coordinates" };
                sel.value = v;
                sel.dispatchEvent(new Event('change', { bubbles: true }));
                return { ok: true };
            }""", [x, y, val])
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
            p.click(arg["selector"], force=True, timeout=int(arg.get("timeout", 1500)))
            return {"ok": True}
        if op == "refresh":
            self.loading = True
            try:
                p.reload()
                p.add_style_tag(content="input[type=password]{display:none!important}")
            finally:
                self.loading = False
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
        if op == "tabs":
            res = []
            for i, pg in enumerate(getattr(self, "_pages", [self._page])):
                try:
                    u = pg.url
                    t = pg.title()
                except Exception:
                    u, t = "unknown", "unknown"
                res.append({
                    "index": i,
                    "url": u,
                    "title": t,
                    "is_active": (pg == self._page)
                })
            return res
        if op == "switch_tab":
            idx = int(arg)
            pages = getattr(self, "_pages", [self._page])
            if 0 <= idx < len(pages):
                self._page = pages[idx]
                return {"ok": True, "active": idx, "url": self._page.url, "title": self._page.title()}
            return {"ok": False, "error": f"tab index {idx} out of range (0-{len(pages)-1})"}
        if op == "close_tab":
            idx = int(arg)
            pages = getattr(self, "_pages", [self._page])
            if len(pages) <= 1:
                return {"ok": False, "error": "cannot close the only open tab"}
            if 0 <= idx < len(pages):
                target_pg = pages[idx]
                target_pg.close()
                return {"ok": True, "remaining": len(getattr(self, "_pages", []))}
            return {"ok": False, "error": f"tab index {idx} out of range"}
        raise ValueError(f"unknown op {op!r}")

    def _after_nav(self) -> None:
        try:
            self.take_screenshot()
        except Exception:
            pass
        events.BUS.publish("nav", {"url": self.url, "title": self.title})


_HOST_RE = re.compile(r"https?://([^/:]+)(?::(\d+))?")


def _host_of(url: str) -> str:
    m = _HOST_RE.match(url)
    if not m:
        return ""
    return f"{m.group(1).lower()}:{m.group(2)}" if m.group(2) else m.group(1).lower()


def _absolutize(url: str, base: str | None) -> str:
    """Turn a relative site path ('/site/expense') into an absolute URL against `base` so
    the allowlist gate sees a real host instead of an empty one. Scheme-less values that
    still don't parse are left as-is (the gate will refuse them with an empty host)."""
    if re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        return url
    if base and url.startswith("/"):
        return urljoin(base, url)
    return url
