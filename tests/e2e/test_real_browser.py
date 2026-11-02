
"""UNIBOT P0.1b - End-to-end test on a real public allowlisted site (the-internet).

Executes a read-only task against the real public web:
  - Navigates to the allowlisted host (the-internet.herokuapp.com)
  - Observes interactive elements and page title
  - Captures a valid screenshot
  - Verifies allowlist security boundary holds against external redirects
"""
import urllib.request
import pytest
from stepproof.browser import TinyBrowser


def _can_connect_public():
    try:
        r = urllib.request.urlopen("https://the-internet.herokuapp.com", timeout=4)
        return r.status == 200
    except Exception:
        return False


@pytest.mark.skipif(not _can_connect_public(), reason="the-internet.herokuapp.com unreachable (offline mode)")
def test_real_browser_on_public_allowlisted_site():
    tb = TinyBrowser(allowlist={"the-internet.herokuapp.com"})
    try:
        # 1. Navigate to the-internet
        res = tb.goto("https://the-internet.herokuapp.com/tables")
        assert res["ok"] is True, f"navigation failed: {res.get('error')}"

        # 2. Observe page elements & title (read-only inspection)
        obs = tb.observe()
        assert "The Internet" in obs.get("title", "")
        elements = obs.get("elements", [])
        assert len(elements) > 0, "must observe interactive elements on the public page"

        # 3. Take screenshot
        shot = tb.take_screenshot()
        assert shot.startswith("data:image/jpeg"), "must capture valid screenshot"

        # 4. Security boundary: off-allowlist navigation is strictly refused
        evil = tb.goto("https://evil.example/malicious")
        assert evil["ok"] is False
        assert "refused" in evil.get("error", "").lower()
        assert "evil.example" not in tb.url
    finally:
        tb.stop()
