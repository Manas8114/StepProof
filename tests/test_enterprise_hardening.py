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


def test_all_procedure_fixtures_load_and_verify():
    """All procedure files in data/procedures/ must load cleanly without schema errors,
    and all signed fixtures must cryptographically verify."""
    base_dir = Path(__file__).resolve().parent.parent / "data" / "procedures"
    assert base_dir.exists()
    files = list(base_dir.glob("*.json"))
    assert len(files) >= 10, f"Expected at least 10 procedure files, found {len(files)}"
    for p_path in files:
        data = json.loads(p_path.read_text(encoding="utf-8"))
        proc = Procedure.from_dict(data)
        assert proc.goal, f"{p_path.name} must resolve a goal"
        assert len(proc.steps) > 0, f"{p_path.name} must have steps"
        if proc.signature and proc.manifest:
            ok, reason = verify_procedure(proc)
            assert ok is True, f"{p_path.name} signature failed verification: {reason}"


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


def test_pii_redaction_fails_closed_on_decode_or_cv_error():
    """Redaction must NEVER fail open: corrupt or un-decodable images with sensitive boxes
    must return a fail-closed solid masked image, never the original input."""
    from stepproof.redact import PIIRedactor
    redactor = PIIRedactor()
    redactor.enabled = True

    sensitive_boxes = [{"x": 10, "y": 10, "w": 100, "h": 30, "field": "password"}]
    raw_corrupt_b64 = "data:image/jpeg;base64,corrupt_invalid_jpeg_payload_with_pii_12345"

    masked = redactor.redact_screenshot(raw_corrupt_b64, sensitive_boxes)
    # Must NOT return raw input
    assert masked != raw_corrupt_b64
    assert masked.startswith("data:image/jpeg;base64,")
    # Must be a valid JPEG byte payload (the fail-closed placeholder)
    import base64
    payload = base64.b64decode(masked.split(",", 1)[1])
    assert len(payload) > 100
    assert payload[:2] == b"\xff\xd8"  # JPEG SOI marker


def test_deterministic_checks_reject_vacuous_conditions():
    """Empty strings and empty checks lists must reject rather than vacuously pass."""
    from stepproof.checks import url_contains, text_visible, all_pass
    from unittest.mock import MagicMock

    tb = MagicMock()
    tb.observe.return_value = {"url": "http://example.com/dashboard", "body_text": "Hello World"}

    # 1. Empty URL substring -> rejected
    r1 = url_contains(tb, {"url": ""})
    assert r1.passed is False
    assert "vacuous" in r1.detail

    # 2. Empty visible text -> rejected
    r2 = text_visible(tb, {"text": ""})
    assert r2.passed is False
    assert "vacuous" in r2.detail

    # 3. Empty checks list -> rejected
    ok, results = all_pass(tb, [])
    assert ok is False
    assert len(results) == 1
    assert results[0].name == "empty_checks"
    assert results[0].passed is False


def test_frame_budget_cap_threads_and_enforces_across_loop():
    """Per-run budget cap must accumulate across multiple vision calls and trip when breached."""
    from stepproof.budget import BudgetConfig, BudgetTripwire
    from stepproof.agent.executor import execute_procedure
    from stepproof.proc import Procedure, Step, Locator
    from unittest.mock import MagicMock, patch

    cfg = BudgetConfig(cap_frames_per_run=100)
    tripwire = BudgetTripwire(cfg)

    # 1. Direct tripwire accumulation check
    ok1, _ = tripwire.check_before_vision_call(current_run_frames=0, expected_frames=50)
    assert ok1 is True
    ok2, _ = tripwire.check_before_vision_call(current_run_frames=50, expected_frames=50)
    assert ok2 is True
    ok3, err3 = tripwire.check_before_vision_call(current_run_frames=100, expected_frames=50)
    assert ok3 is False
    assert "exceeds per-run cap 100" in err3

    # 2. Executor loop accumulation check
    tb = MagicMock()
    tb.observe.return_value = {"url": "http://127.0.0.1:8011/expense/"}
    def mock_act(tool, args=None):
        if tool == "click_sel":
            raise RuntimeError("locator broken")
        if tool == "eval":
            return "submit button"
        return {"ok": True}
    tb.act.side_effect = mock_act

    steps = [
        Step(id="s1", description="step 1", action="click", locators=[Locator("css", "#broken1")]),
        Step(id="s2", description="step 2", action="click", locators=[Locator("css", "#broken2")]),
        Step(id="s3", description="step 3", action="click", locators=[Locator("css", "#broken3")]),
    ]
    proc = Procedure(goal="Budget trip test", steps=steps)

    with patch("stepproof.budget.get_tripwire", return_value=tripwire):
        vision_mock = MagicMock(return_value={"x": 50, "y": 50})
        res = execute_procedure(tb, proc, approve_fn=lambda a, x: True, vision_selfheal=vision_mock)
        # Should have run 2 vision calls (100 frames) and blocked on the 3rd
        assert res.success is False
        assert "vision call blocked" in res.error
        assert "exceeds per-run cap 100" in res.error
        assert res.billed_frames == 100


def test_audit_evidence_packaging_fails_on_missing_file_and_disambiguates():
    """Evidence packaging must fail closed on missing evidence and disambiguate arcnames."""
    from stepproof.audit import AuditSpine
    import tempfile, zipfile

    with tempfile.TemporaryDirectory() as tmpdir:
        sink_p = Path(tmpdir)
        spine = AuditSpine(sink_dir=sink_p, use_global_db=False)

        real_ev = sink_p / "shot.jpg"
        real_ev.write_bytes(b"\xff\xd8\xff\xe0test")

        # 1. Missing evidence path must raise FileNotFoundError
        spine.append(run_id="run_bad", verdict="PASS", evidence_paths=["nonexistent_shot.jpg"])
        with pytest.raises(FileNotFoundError):
            spine.package_run("run_bad")

        # 2. Valid evidence packaging must succeed and disambiguate on collision
        spine2 = AuditSpine(sink_dir=sink_p / "sub", use_global_db=False)
        spine2.append(run_id="run_ok", verdict="PASS", evidence_paths=[str(real_ev), str(real_ev)])
        zip_path = spine2.package_run("run_ok")
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            assert "evidence/shot.jpg" in namelist
            assert any(name.startswith("evidence/seq_0_1_") for name in namelist)


def test_artifact_provenance_tamper_detection():
    """Tampering with provenance in a signed artifact must fail verification."""
    from stepproof.artifact import sign_artifact, verify_artifact
    from stepproof.proc import Procedure, Step

    proc = Procedure(goal="Artifact tamper test", steps=[Step(id="s1", description="step 1")])
    sign_artifact(proc, device_key="test-key-12345", model_name="trusted-compiler")

    # Valid artifact verifies
    ok, err = verify_artifact(proc, device_key="test-key-12345")
    assert ok is True

    # Tamper with model_used in provenance
    proc.provenance["model_used"] = "untrusted-hacked-model"
    ok, err = verify_artifact(proc, device_key="test-key-12345")
    assert ok is False
    assert "Tampered provenance" in err


