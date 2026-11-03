"""Monitor mode: records the human's actions in the tiny browser.

Each action captures a multi-locator (css, role+name, text) + a timestamped narration
segment, so the compiled Procedure can self-heal (fall through locators) and the
compiler can see intent ("why"), not just "what".
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict

from ..browser.actions import execute_action


@dataclass
class RecordedAction:
    t: float                       # seconds since recording start
    tool: str
    arg: dict
    locators: list[dict] = field(default_factory=list)
    narration: str = ""
    element_name: str = ""
    url_before: str = ""
    url_after: str = ""


class Recorder:
    """Wraps a TinyBrowser and captures the actions the human performs."""

    def __init__(self, browser) -> None:
        self.browser = browser
        self.actions: list[RecordedAction] = []
        self._last_actions: list[RecordedAction] = []
        self._t0 = time.time()

    def start(self, site_url: str) -> None:
        if site_url and site_url != "about:blank" and site_url != self.browser.url:
            try:
                self.browser.start_site(site_url)
            except Exception:
                pass
        self._t0 = time.time()
        if self.actions:
            self._last_actions = list(self.actions)
        self.actions = []

    def click_element(self, locators: list[dict], narration: str = "",
                       element_name: str = "") -> None:
        url_b = self.browser.observe().get("url", "")
        ok, detail = _try_first_locator(self.browser, locators, "click", "")
        url_a = self.browser.observe().get("url", "")
        act = RecordedAction(round(time.time() - self._t0, 3), "click",
                             {"ok": ok, "detail": detail, "element_name": element_name},
                             locators=locators, narration=narration, element_name=element_name,
                             url_before=url_b, url_after=url_a)
        self.actions.append(act)
        self._last_actions.append(act)

    def type_value(self, locators: list[dict], text: str, narration: str = "", element_name: str = "") -> None:
        url_b = self.browser.observe().get("url", "")
        ok, detail = _try_first_locator(self.browser, locators, "type", text)
        url_a = self.browser.observe().get("url", "")
        act = RecordedAction(round(time.time() - self._t0, 3), "type",
                             {"text": text, "ok": ok, "detail": detail, "element_name": element_name},
                             locators=locators, narration=narration, element_name=element_name,
                             url_before=url_b, url_after=url_a)
        self.actions.append(act)
        self._last_actions.append(act)

    def select_value(self, locators: list[dict], value: str, narration: str = "", element_name: str = "") -> None:
        url_b = self.browser.observe().get("url", "")
        ok, detail = _try_first_locator(self.browser, locators, "select", value)
        url_a = self.browser.observe().get("url", "")
        act = RecordedAction(round(time.time() - self._t0, 3), "select",
                             {"value": value, "ok": ok, "detail": detail, "element_name": element_name},
                             locators=locators, narration=narration, element_name=element_name,
                             url_before=url_b, url_after=url_a)
        self.actions.append(act)
        self._last_actions.append(act)

    def narrate(self, text: str) -> None:
        if self.actions:
            self.actions[-1].narration = (self.actions[-1].narration + " " + text).strip()

    def stop(self) -> list[dict]:
        if self.actions:
            self._last_actions = list(self.actions)
        recs = self.actions or self._last_actions
        return [asdict(a) for a in recs]


def _try_first_locator(tb, locators: list[dict], tool: str, text: str = "") -> tuple[bool, str]:
    """Actuate the first usable locator; report which one worked (evidence for self-healing)."""
    for i, loc in enumerate(locators):
        kind = loc.get("kind", "")
        val = str(loc.get("value", ""))
        if kind == "css":
            a = {"selector": val, "text": text, "value": text}
        elif kind == "box":
            try:
                parts = [int(p.strip()) for p in val.split(",")]
                if len(parts) >= 2:
                    a = {"x": parts[0], "y": parts[1], "text": text, "value": text}
                else:
                    continue
            except Exception:
                continue
        else:
            a = {"name": val, "text": text, "value": text}
        try:
            r = execute_action(tb, tool, a)
            if r.ok:
                return True, f"locator[{i}] ({kind}) worked"
        except Exception as e:
            detail = f"{type(e).__name__}: {str(e)[:60]}"
            if i == len(locators) - 1:
                return False, detail
    return False, "no locator worked"
