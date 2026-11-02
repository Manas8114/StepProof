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
        self._t0 = time.time()

    def start(self, site_url: str) -> None:
        self.browser.start_site(site_url)
        self._t0 = time.time()
        self.actions = []

    def click_element(self, locators: list[dict], narration: str = "",
                       element_name: str = "") -> None:
        url_b = self.browser.observe().get("url", "")
        ok, detail = _try_first_locator(self.browser, locators, "click", "")
        url_a = self.browser.observe().get("url", "")
        self.actions.append(RecordedAction(round(time.time() - self._t0, 3), "click",
                                           {"ok": ok, "detail": detail, "element_name": element_name},
                                           locators=locators, narration=narration, element_name=element_name,
                                           url_before=url_b, url_after=url_a))

    def type_value(self, locators: list[dict], text: str, narration: str = "", element_name: str = "") -> None:
        url_b = self.browser.observe().get("url", "")
        ok, detail = _try_first_locator(self.browser, locators, "type", text)
        url_a = self.browser.observe().get("url", "")
        self.actions.append(RecordedAction(round(time.time() - self._t0, 3), "type",
                                           {"text": text, "ok": ok, "detail": detail, "element_name": element_name},
                                           locators=locators, narration=narration, element_name=element_name,
                                           url_before=url_b, url_after=url_a))

    def select_value(self, locators: list[dict], value: str, narration: str = "", element_name: str = "") -> None:
        url_b = self.browser.observe().get("url", "")
        ok, detail = _try_first_locator(self.browser, locators, "select", value)
        url_a = self.browser.observe().get("url", "")
        self.actions.append(RecordedAction(round(time.time() - self._t0, 3), "select",
                                           {"value": value, "ok": ok, "detail": detail, "element_name": element_name},
                                           locators=locators, narration=narration, element_name=element_name,
                                           url_before=url_b, url_after=url_a))

    def narrate(self, text: str) -> None:
        if self.actions:
            self.actions[-1].narration = (self.actions[-1].narration + " " + text).strip()

    def stop(self) -> list[dict]:
        return [asdict(a) for a in self.actions]


def _try_first_locator(tb, locators: list[dict], tool: str, text: str = "") -> tuple[bool, str]:
    """Actuate the first usable locator; report which one worked (evidence for self-healing)."""
    for i, loc in enumerate(locators):
        key = "selector" if loc.get("kind") == "css" else "name"
        a = {key: loc.get("value", ""), "text": text}
        try:
            r = execute_action(tb, tool, a)
            if r.ok:
                return True, f"locator[{i}] ({loc.get('kind')}) worked"
        except Exception as e:
            detail = f"{type(e).__name__}: {str(e)[:60]}"
            if i == len(locators) - 1:
                return False, detail
    return False, "no locator worked"
