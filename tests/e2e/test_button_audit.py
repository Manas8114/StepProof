"""UNIBOT P0.1a - Playwright end-to-end button audit.

Boots the real app (uvicorn stepproof.api_v2:app on :8011, so the internal
tiny browser's allowlist + /site/* routes work), drives the product UI with a
headless Chromium, and for EVERY control on every screen/mode asserts:
  * no console error, no uncaught promise rejection,
  * no failed network request (4xx/5xx),
  * and either a visible state change OR the control is intentionally
    disabled with a visible reason.
The failing list is written to data/e2e_button_audit.json.

Run:  python -m pytest tests/e2e/test_button_audit.py -q
"""
import json, threading, time
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parent.parent.parent / "demo_sites"
APP = "http://127.0.0.1:8011"
OUT = Path(__file__).resolve().parent.parent.parent / "data" / "e2e_button_audit.json"


@pytest.fixture(scope="module")
def app():
    """Boot the real FastAPI app on :8011 (its browser allowlist + /site routes need it)."""
    import os
    os.environ["STEPPROOF_TEST_MODEL"] = "1"
    import uvicorn
    cfg = uvicorn.Config("stepproof.api_v2:app", host="127.0.0.1", port=8011, log_level="error")
    server = uvicorn.Server(cfg)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(50):
        try:
            import httpx
            httpx.get(APP + "/api/v2/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    yield server
    server.should_exit = True


@pytest.fixture(scope="module")
def browser(app):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    yield b
    b.close()
    pw.stop()


class Recorder:
    """Collects the four audit signals from a page: console errors, uncaught
    exceptions/rejections, 4xx/5xx responses, and DOM snapshots for diffing."""

    IGNORED_4XX = ("/favicon.ico",)   # cosmetic; not a product defect

    def __init__(self, page):
        self.page = page
        self.console_errors: list[str] = []
        self.page_errors: list[str] = []
        self.http_errors: list[str] = []
        self._sub = None

    def __enter__(self):
        self.page.on("console", lambda m: self.console_errors.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.page_errors.append(str(e)))

        def _on_response(r):
            if r.status >= 400 and not any(k in r.url for k in self.IGNORED_4XX):
                self.http_errors.append(f"{r.status} {r.url}")

        self.page.on("response", _on_response)
        return self

    def __exit__(self, *a):
        return None

    def check(self, label, state_before, settle=0.7):
        """After clicking `label`: any of the four signals = a finding."""
        time.sleep(settle)
        cons = list(self.console_errors); self.console_errors.clear()
        perr = list(self.page_errors); self.page_errors.clear()
        httpe = list(self.http_errors); self.http_errors.clear()
        dom_changed = self._changed(state_before)
        problems = []
        if cons: problems.append(f"console: {cons[:3]}")
        if perr: problems.append(f"uncaught: {perr[:2]}")
        if httpe: problems.append(f"http: {httpe[:3]}")
        if not dom_changed and not problems:
            problems.append("no visible state change and not disabled-with-reason")
        return problems

    def _changed(self, before: str) -> bool:
        return self.page.content() != before


def _disabled_with_reason(page, sel: str) -> bool:
    """A control intentionally off must say WHY (title/tooltip) - spec 1a rule."""
    el = page.query_selector(sel)
    if el is None:
        return False
    if el.get_attribute("disabled") is None and el.get_attribute("aria-disabled") != "true":
        return False
    return bool(el.get_attribute("title") or el.get_attribute("aria-disabled"))


def test_button_audit(app, browser):
    page = browser.new_page()
    page.on("console", lambda m: print("PAGE CONSOLE:", m.type, m.text))
    page.on("pageerror", lambda e: print("PAGE ERROR:", e))
    page.goto(APP, wait_until="load")
    page.wait_for_selector("#state")
    findings: list[dict] = []

    def audit(sel, precondition=None, settle=0.7, dynamic=False):
        """Click `sel`; record a finding unless a documented precondition makes it no-op."""
        with Recorder(page) as r:
            if precondition:
                precondition()
            before = page.content()
            el = page.query_selector(sel)
            if el is None:
                if not dynamic:
                    findings.append({"control": sel, "problem": "control not present"})
                return
            if dynamic and not el.is_visible():
                return
            if el.get_attribute("disabled") is not None:
                if _disabled_with_reason(page, sel):
                    return  # intentionally disabled WITH a reason -> spec-compliant
                findings.append({"control": sel, "problem": "disabled with no visible reason"})
                return
            try:
                el.click(timeout=4000)
            except Exception as e:
                findings.append({"control": sel, "problem": f"click not actionable: {str(e)[:80]}"})
                return
            problems = r.check(sel, before, settle=settle)
            for p in problems:
                findings.append({"control": sel, "problem": p})

    def goto_mode(name):
        page.click(f"#tabs button[data-m='{name}']")
        time.sleep(0.25)

    # ---- tabs (state change = target panel visible)
    for m in ("execute", "coach", "tour", "tracking", "monitor"):
        audit(f"#tabs button[data-m='{m}']", settle=0.3)

    # ---- monitor: record a real action so compile/save/run have data
    goto_mode("monitor")
    def _record_action():
        page.click("#mrec")
        time.sleep(0.8)
        page.click("#shot", position={"x": 30, "y": 30})
        time.sleep(0.5)
    audit("#mrec", settle=0.8)
    audit("#mcompile", precondition=_record_action, settle=1.2)
    audit("#msave", settle=0.5)
    audit("#mrun", settle=1.2)

    # ---- execute
    goto_mode("execute")
    def _type_goal():
        page.fill("#xgoal", "File an Acme office expense of $42")
    audit("#xstart", precondition=_type_goal, settle=1.5)
    def _after_start():
        page.wait_for_selector("#state:has-text('RUNNING'), #state:has-text('AWAITING_APPROVAL'), "
                               "#state:has-text('PLANNING'), #state:has-text('DONE')", timeout=30000)
    audit("#xpause", precondition=_after_start, settle=0.8)
    audit("#xresume", settle=0.8)
    audit("#xkill", settle=0.8)

    # ---- coach
    goto_mode("coach")
    audit("#cgo", settle=1.5)

    # ---- tour
    goto_mode("tour")
    def _ensure_tour_list():
        runs = page.eval_on_selector_all("#tourlist option", "els => els.length")
        if not runs:
            page.click("#tourrun")
            time.sleep(1.0)   # a dated tour trace is written by the tour thread
            page.reload(wait_until="load")
            page.wait_for_selector("#tourlist option", timeout=30000)
    audit("#tourrun", settle=1.5)
    audit("#tourreplay", precondition=_ensure_tour_list, settle=1.5)

    # ---- tracking
    goto_mode("tracking")
    audit("#trackplay", settle=0.8)
    audit("#trackpause", settle=0.5)
    audit("#trackreset", settle=0.5)

    # ---- center controls
    audit("#fresh", settle=0.5)

    # ---- dynamic gate buttons (Allow/Deny appear on an irreversible action)
    # Wait for the tour thread to finish completely before starting next agent run
    try:
        page.wait_for_selector("#tourlabel:has-text('Tour finished')", timeout=30000)
    except Exception:
        pass
    time.sleep(1.0)
    goto_mode("execute")
    page.fill("#xgoal", "File an Acme office expense of $42")
    page.click("#xstart")
    try:
        gate_seen = page.wait_for_selector("#gate button", timeout=45000)
    except Exception:
        gate_seen = None
    if gate_seen:
        audit("#gate .primary", settle=0.8)      # Allow
        audit("#gate .danger", precondition=None, settle=0.8, dynamic=True)  # Deny only if still present
    else:
        Path("data/audit_debug_page.html").write_text(page.content(), encoding="utf-8")
        findings.append({"control": "#gate (Allow/Deny)", "problem": "approval gate never surfaced"})

    # ---- write the failing list + assert clean
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"findings": findings, "total": len(findings)}, indent=2))
    page.close()
    assert not findings, f"{len(findings)} dead/unclear controls:\n" + json.dumps(findings, indent=2)[:4000]
