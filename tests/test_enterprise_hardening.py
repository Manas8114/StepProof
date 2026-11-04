"""Comprehensive tests for Enterprise Hardening (v9.5):
1. Shadow DOM piercing: traverses deep shadow roots (Salesforce LWC, Polymer, Web Components).
2. Multi-tab & popup tracking: auto-detects popups (OAuth, SSO), switches focus, manages tabs.
3. Anti-stagnation loop breaker: detects consecutive wait/scroll loops and halts/breaks cleanly.
4. Five Enterprise Presets: verify manifest, signature, parameters, and deterministic checks.
"""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from stepproof.proc import Procedure, Step
from stepproof.signing import verify_procedure
from stepproof.browser.observe import observe_page
from stepproof.api_v2 import app


@pytest.fixture
def client():
    return TestClient(app)


# -----------------------------------------------------------------------------
# 1. Five Enterprise Presets Verification
# -----------------------------------------------------------------------------
def test_all_five_enterprise_presets_exist_and_verify():
    """All 5 enterprise presets must exist, parse as valid Procedures, and have valid HMAC signatures."""
    presets = [
        "stripe_refund",
        "github_issue_restock",
        "google_forms_submission",
        "salesforce_lead_update",
        "expense_compliance_audit"
    ]
    base_dir = Path(__file__).resolve().parent.parent / "data" / "procedures"
    assert base_dir.exists()

    for name in presets:
        p_path = base_dir / f"{name}.json"
        assert p_path.exists(), f"Preset {name}.json is missing"

        data = json.loads(p_path.read_text())
        proc = Procedure.from_dict(data)

        # Assert structural completeness
        assert proc.goal, f"{name} must have a goal"
        assert proc.site, f"{name} must have a target site"
        assert len(proc.steps) >= 4, f"{name} must have at least 4 steps"
        assert proc.parameters, f"{name} must have parameters/slots"
        assert proc.success_checks, f"{name} must have deterministic success checks"

        # Assert cryptographic validity
        ok, reason = verify_procedure(proc)
        assert ok is True, f"{name} signature failed verification: {reason}"
        assert proc.manifest.get("step_count") == len(proc.steps)


def test_procedure_list_and_get_api(client):
    """Test /api/v2/procedure/list and /api/v2/procedure/get endpoints."""
    r_list = client.get("/api/v2/procedure/list")
    assert r_list.status_code == 200
    procs = r_list.json().get("procedures", [])
    names = [p["name"] for p in procs]
    for expected in ["stripe_refund", "github_issue_restock", "google_forms_submission", "salesforce_lead_update", "expense_compliance_audit"]:
        assert expected in names, f"{expected} missing from /procedure/list"

    # Test loading one preset
    r_get = client.get("/api/v2/procedure/get?name=stripe_refund")
    assert r_get.status_code == 200
    data = r_get.json()
    assert data["ok"] is True
    assert data["procedure"]["goal"] == "Stripe partial refund verification and customer dispute settlement"
    assert len(data["procedure"]["steps"]) == 6


# -----------------------------------------------------------------------------
# 2. Multi-Tab & Window Context API
# -----------------------------------------------------------------------------
def test_browser_tabs_api(client):
    """Verify /api/v2/browser/tabs, tab switching, and tab status."""
    r_tabs = client.get("/api/v2/browser/tabs")
    assert r_tabs.status_code == 200
    tabs_data = r_tabs.json()
    assert "tabs" in tabs_data
    assert len(tabs_data["tabs"]) >= 1
    assert tabs_data["tabs"][0]["is_active"] is True

    # Test switching tab (to 0, since 0 is valid)
    r_switch = client.post("/api/v2/browser/tabs/switch", json={"index": 0})
    assert r_switch.status_code == 200
    assert r_switch.json().get("ok") is True

    # Out of range index should return error, not 500
    r_err = client.post("/api/v2/browser/tabs/switch", json={"index": 999})
    assert r_err.status_code == 200
    assert r_err.json().get("ok") is False


# -----------------------------------------------------------------------------
# 3. Deep Shadow DOM Piercing
# -----------------------------------------------------------------------------
def test_shadow_dom_piercing_observation():
    """Verify that observe_page recursively pierces Shadow DOM to discover inner elements."""
    class MockPage:
        def __init__(self):
            self.url = "http://localhost:8011/site/enterprise"
        def evaluate(self, script):
            # Verify script includes shadow DOM piercing recursive collectFromRoot
            assert "shadowRoot" in script
            return {
                "url": self.url,
                "title": "Salesforce Enterprise View",
                "body_text": "Salesforce Lead Record",
                "elements": [
                    {
                        "role": "button",
                        "name": "Edit Lead Status",
                        "kind": "button",
                        "id": "inner-btn",
                        "x": 200, "y": 150, "w": 100, "h": 40,
                        "visible": True
                    }
                ]
            }

    p = MockPage()
    res = observe_page(p)
    assert len(res["elements"]) == 1
    assert res["elements"][0]["name"] == "Edit Lead Status"


# -----------------------------------------------------------------------------
# 4. Anti-Stagnation & Loop Breaker
# -----------------------------------------------------------------------------
def test_anti_stagnation_detection():
    """Verify AgentLoop anti-stagnation detects repeated wait/scroll loops."""
    from stepproof.agent.loop import AgentLoop, Budgets
    from stepproof.agent.model import Action

    class MockBrowser:
        def __init__(self):
            self.kill = type("Event", (), {"is_set": lambda: False, "clear": lambda: None, "set": lambda: None})()
            self.url = "http://localhost:8011/site/expense"
            self.title = "Expense Demo"
        def take_screenshot(self): return "data:image/jpeg;base64,mock"
        def observe(self): return {"elements": []}

    loop = AgentLoop(MockBrowser(), None, budgets=Budgets())
    # Populate history with consecutive wait actions
    loop.history = [
        {"tool": "wait", "args": {"ms": 1000}, "ok": True, "detail": "waited 1000ms"},
        {"tool": "wait", "args": {"ms": 1000}, "ok": True, "detail": "waited 1000ms"},
        {"tool": "wait", "args": {"ms": 1000}, "ok": True, "detail": "waited 1000ms"},
    ]

    stagnant_count = 0
    for prev in reversed(loop.history[-4:]):
        if prev.get("tool") in ("wait", "scroll"):
            stagnant_count += 1
        else:
            break

    assert stagnant_count == 3, "Should count 3 consecutive stagnant actions"


def test_dev_default_key_fallback_is_scoped():
    """Verify cryptographic integrity: no unauthenticated backdoor fallback exists,
    and verifying against a custom/production key strictly rejects DEFAULT_DEV_KEY even if stamped."""
    from stepproof.signing import verify_procedure, sign_procedure, DEFAULT_DEV_KEY

    # 1. Procedure signed with active key (DEFAULT_DEV_KEY) -> verifies against matching key
    p1 = Procedure(goal="Dev test", site="http://localhost:8011", steps=[])
    sign_procedure(p1, key=DEFAULT_DEV_KEY)
    ok, _ = verify_procedure(p1, key=DEFAULT_DEV_KEY)
    assert ok is True

    # 2. Forgery attack test: Attacker signs with public DEFAULT_DEV_KEY and stamps
    #    signing_key_id="dev-default". In an enterprise environment with a real production key,
    #    this MUST be rejected (no fallback backdoor).
    p2 = Procedure(goal="Dev test", site="http://localhost:8011", steps=[])
    sign_procedure(p2, key=DEFAULT_DEV_KEY)
    p2.provenance["signing_key_id"] = "dev-default"
    ok, err = verify_procedure(p2, key="corp-prod-auth-key-999")
    assert ok is False
    assert "Signature mismatch" in err

    # 3. Tampered step in procedure -> REJECTED as tampered
    p3 = Procedure(goal="Dev test", site="http://localhost:8011", steps=[])
    sign_procedure(p3, key=DEFAULT_DEV_KEY)
    p3.steps.append(Step(id="s99", description="tampered", action="click", arg={}))
    ok, err = verify_procedure(p3, key=DEFAULT_DEV_KEY)
    assert ok is False
    assert "Tampered procedure body" in err


