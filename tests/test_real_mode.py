"""Comprehensive tests for StepProof Real Mode:
1. Pre-flight PII redaction pass (text, DOM, screenshot, dry-run, toggle)
2. Hash-chained audit spine + evidence bundles (append-only, tamper-detection, zip packaging)
3. Budget tripwire + pre-flight cost estimation (abort before billing, caps, unlimited disclosure)
4. Signed, portable procedure artifacts (canonical manifest, byte-determinism, tamper rejection)
5. Lead A: Locator drift, self-rewriting procedures, JUnit XML/HTML reports
6. Lead B: Standalone proof verifier + v1 adapter
7. Lead C: Describe-or-demo skill compiler with slots + gated re-teach flow
"""
import copy, json, os, time, zipfile
from pathlib import Path
import pytest

from stepproof.proc import Procedure, Step, Locator, SuccessCheck
from stepproof.redact import PIIRedactor, get_redactor, set_redactor
from stepproof.audit import AuditSpine, AuditEntry, GENESIS_HASH
from stepproof.budget import BudgetTripwire, BudgetConfig, estimate_procedure_cost, estimate_agent_goal_cost
from stepproof.signing import sign_procedure, verify_procedure, compute_procedure_hash
from stepproof.harness.drift import analyze_drift, self_rewrite_procedure
from stepproof.harness.reports import generate_junit_xml, generate_html_report
from stepproof.verifier.verify import verify_bundle
from stepproof.skills.compiler import describe_skill, demo_to_skill, gated_reteach, SKILL_DISCLOSURE


# =====================================================================
# 1. Pre-flight PII Redaction
# =====================================================================
def test_pii_redaction_text_patterns():
    redactor = PIIRedactor(enabled=True)
    raw = "Contact alice@example.com or call 555-123-4567. Card: 4111 2222 3333 4444. SSN: 123-45-6789. ACCT# 987654321."
    res = redactor.redact_text(raw)
    assert res.match_count >= 5
    assert "alice@example.com" not in res.redacted_text
    assert "[EMAIL_REDACTED]" in res.redacted_text
    assert "4111 2222 3333 4444" not in res.redacted_text
    assert "[CREDIT_CARD_REDACTED]" in res.redacted_text
    assert "123-45-6789" not in res.redacted_text
    assert "[SSN_REDACTED]" in res.redacted_text


def test_pii_redaction_dom_and_dry_run():
    redactor = PIIRedactor(enabled=True)
    obs = {
        "url": "https://bank.example/account",
        "title": "Welcome john.doe@corp.org",
        "body_text": "Your balance for account ACCT 12345678 is $1,200.",
        "elements": [
            {"role": "textbox", "name": "john.doe@corp.org", "id": "email_input", "x": 10, "y": 20, "w": 100, "h": 30, "visible": True},
            {"role": "button", "name": "Submit", "id": "btn", "x": 10, "y": 60, "w": 80, "h": 30, "visible": True}
        ]
    }
    sanitized, boxes = redactor.redact_observation(obs)
    assert "john.doe@corp.org" not in sanitized["title"]
    assert "[EMAIL_REDACTED]" in sanitized["title"]
    assert "ACCT 12345678" not in sanitized["body_text"]
    assert len(boxes) == 1
    assert boxes[0]["x"] == 10 and boxes[0]["y"] == 20

    dry = redactor.dry_run(obs)
    assert dry["enabled"] is True
    assert dry["redactions_count"] >= 2
    assert dry["redacted_boxes_count"] == 1


def test_pii_toggle_off():
    redactor = PIIRedactor(enabled=False)
    raw = "Email: secret@domain.com"
    res = redactor.redact_text(raw)
    assert res.redacted_text == raw
    assert res.match_count == 0


# =====================================================================
# 2. Hash-Chained Audit Log + Evidence Bundles (The Spine)
# =====================================================================
def test_audit_spine_hash_chain_integrity(tmp_path):
    spine = AuditSpine(sink_dir=tmp_path / "audit")
    assert spine.last_hash == GENESIS_HASH

    e1 = spine.append("run-1", "PASS", checks=[{"name": "c1", "passed": True}], steps=[{"id": "s1"}])
    assert e1.seq == 0
    assert e1.prev_hash == GENESIS_HASH
    assert e1.entry_hash != ""

    e2 = spine.append("run-2", "PASS", checks=[{"name": "c2", "passed": True}], steps=[{"id": "s2"}])
    assert e2.seq == 1
    assert e2.prev_hash == e1.entry_hash

    # Verify intact chain
    valid, err = spine.verify()
    assert valid is True
    assert err is None


def test_audit_spine_detects_tampering(tmp_path):
    spine = AuditSpine(sink_dir=tmp_path / "audit")
    spine.append("run-1", "PASS", checks=[{"name": "c1", "passed": True}])
    spine.append("run-2", "PASS", checks=[{"name": "c2", "passed": True}])

    entries = spine.get_entries()
    # Maliciously alter verdict of entry 0
    tampered_entries = copy.deepcopy(entries)
    tampered_entries[0].verdict = "FAIL"

    valid, err = spine.verify(tampered_entries)
    assert valid is False
    assert "Tampered entry at seq 0" in err


def test_audit_spine_package_run(tmp_path):
    spine = AuditSpine(sink_dir=tmp_path / "audit")
    ev_file = tmp_path / "shot.jpg"
    ev_file.write_bytes(b"\xff\xd8\xff\xe0mock_jpeg")

    spine.append("run-pkg", "PASS", checks=[{"name": "chk1", "passed": True, "evidence": str(ev_file)}],
                 evidence_paths=[str(ev_file)])

    zip_path = spine.package_run("run-pkg", out_path=tmp_path / "bundle.zip")
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "audit_entries.json" in names
        assert "evidence/shot.jpg" in names


# =====================================================================
# 3. Tripwire + Pre-Flight Cost Estimate
# =====================================================================
def test_preflight_cost_estimate():
    # 2 deterministic steps -> 0 frames, 0 tokens
    proc_det = Procedure(goal="Deterministic", steps=[
        Step("s1", "click", "click", locators=[Locator("css", "#btn")]),
        Step("s2", "type", "type", locators=[Locator("css", "#input")]),
    ])
    est_det = estimate_procedure_cost(proc_det)
    assert est_det.estimated_sam_frames == 0
    assert est_det.estimated_tokens == 0

    # 1 step with missing locator or vision concept -> 50 billed frames (SAM min)
    proc_vis = Procedure(goal="Vision Step", steps=[
        Step("s1", "locate target", "click", locators=[], vision_concept="blue widget")
    ])
    est_vis = estimate_procedure_cost(proc_vis)
    assert est_vis.estimated_sam_frames == 50
    assert est_vis.estimated_tokens == 850


def test_tripwire_aborts_before_billing():
    cfg = BudgetConfig(cap_frames_per_run=40, cap_tokens_per_run=500)
    tripwire = BudgetTripwire(cfg)

    # Procedure requiring 50 frames exceeds cap of 40 frames
    proc = Procedure(goal="Pathological", steps=[
        Step("s1", "vision", "click", locators=[], vision_concept="target")
    ])
    est = estimate_procedure_cost(proc)
    ok, err = tripwire.check_preflight(est)
    assert ok is False
    assert "exceeds per-run cap" in err

    # Check before vision call aborts before dispatch
    ok_v, err_v = tripwire.check_before_vision_call(current_run_frames=0, expected_frames=50)
    assert ok_v is False
    assert "Tripwire abort before vision call" in err_v


def test_tripwire_unlimited_disclosure():
    cfg = BudgetConfig(unlimited=True)
    tripwire = BudgetTripwire(cfg)
    disc = tripwire.health_disclosure()
    assert "unlimited" in disc["tripwire_status"]


# =====================================================================
# 4. Signed, Portable Procedure Artifacts
# =====================================================================
def test_byte_deterministic_canonical_manifest():
    proc1 = Procedure(goal="Task", site="http://example.com", steps=[
        Step("s1", "click submit", "click", {"name": "Submit"}, [Locator("css", "#btn")])
    ])
    proc2 = Procedure(goal="Task", site="http://example.com", steps=[
        Step("s1", "click submit", "click", {"name": "Submit"}, [Locator("css", "#btn")])
    ])
    h1 = compute_procedure_hash(proc1)
    h2 = compute_procedure_hash(proc2)
    assert h1 == h2
    assert len(h1) == 64


def test_procedure_signing_and_verification():
    proc = Procedure(goal="File claim", site="http://127.0.0.1:8011", steps=[
        Step("s1", "type vendor", "type", {"text": "Acme"}, [Locator("css", "#vendor")])
    ])
    sign_procedure(proc, key="test-secret-key")
    assert proc.signature != ""
    assert proc.manifest.get("procedure_hash") != ""

    valid, err = verify_procedure(proc, key="test-secret-key")
    assert valid is True
    assert err is None


def test_tampered_procedure_rejected_by_from_dict():
    proc = Procedure(goal="Legit Goal", site="http://example.com", steps=[
        Step("s1", "click", "click", {}, [Locator("css", "#legit")])
    ])
    sign_procedure(proc)
    d = proc.to_dict()

    # Tamper with the goal
    d["goal"] = "Malicious Goal (Inject)"
    with pytest.raises(ValueError, match="Tampered procedure bundle"):
        Procedure.from_dict(d)


# =====================================================================
# 5. Lead A — Self-Healing Web Tests & Reports
# =====================================================================
def test_locator_drift_and_self_rewriting():
    proc = Procedure(goal="Test Drift", steps=[
        Step("s1", "click target", "click", {}, [Locator("css", "#broken"), Locator("css", "#winning_fallback")])
    ])
    sign_procedure(proc)

    # Mock an execution result where locator[1] won
    class MockExec:
        healed_steps = [{"step": "s1", "action": "click", "note": "locator[1] used (self-heal from broken primary)"}]

    drift = analyze_drift(proc, MockExec())
    assert drift.drifted_steps == 1
    assert drift.records[0].healed is True

    # Upgrade into self-rewriting procedure
    rewritten = self_rewrite_procedure(proc, drift)
    # Winning locator must now be ranked first
    assert rewritten.steps[0].locators[0].value == "#winning_fallback"
    # Procedure must be re-signed
    valid, _ = verify_procedure(rewritten)
    assert valid is True


def test_junit_and_html_reports():
    runs = [
        {"name": "proc_1", "success": True, "wall_s": 1.23, "checks_passed": 2, "checks_total": 2, "error": ""},
        {"name": "proc_2", "success": False, "wall_s": 0.45, "checks_passed": 0, "checks_total": 1, "error": "element missing"},
    ]
    xml = generate_junit_xml("ci_suite", runs)
    assert '<testsuite name="ci_suite" tests="2" failures="1"' in xml
    assert '<testcase name="proc_1"' in xml
    assert '<failure message="element missing">' in xml

    report = generate_html_report("ci_suite", runs)
    assert "StepProof Test Suite Report: ci_suite" in report
    assert "proc_1" in report and "proc_2" in report


# =====================================================================
# 6. Lead B — Proof & Audit Evidence (Independent Verifier)
# =====================================================================
def test_standalone_verifier(tmp_path):
    spine = AuditSpine(sink_dir=tmp_path / "audit")
    ev_file = tmp_path / "evidence_shot.jpg"
    ev_file.write_bytes(b"\xff\xd8\xff\xe0mock_jpeg_bytes")

    spine.append("run-verify", "PASS",
                 checks=[{"name": "text_visible", "passed": True, "evidence": str(ev_file)}],
                 steps=[{"id": "s1", "action": "click"}],
                 evidence_paths=[str(ev_file)])

    bundle_zip = spine.package_run("run-verify", out_path=tmp_path / "verified_bundle.zip")
    verdict = verify_bundle(bundle_zip)

    assert verdict.verified is True
    assert verdict.verdict == "PASS"
    assert verdict.chain_valid is True
    assert verdict.manifest_valid is True
    assert verdict.evidence_valid is True
    assert verdict.checks_reverified == 1
    assert verdict.checks_failed == 0


def test_standalone_verifier_catches_tampered_bundle(tmp_path):
    spine = AuditSpine(sink_dir=tmp_path / "audit")
    ev_file = tmp_path / "evidence_shot.jpg"
    ev_file.write_bytes(b"original")

    spine.append("run-tamper", "PASS",
                 checks=[{"name": "c", "passed": True, "evidence": str(ev_file)}],
                 evidence_paths=[str(ev_file)])
    bundle_zip = spine.package_run("run-tamper", out_path=tmp_path / "tamper_bundle.zip")

    # Tamper with the zip file by replacing evidence with different content
    bad_zip = tmp_path / "corrupted_bundle.zip"
    with zipfile.ZipFile(bundle_zip, "r") as zin:
        with zipfile.ZipFile(bad_zip, "w") as zout:
            for item in zin.infolist():
                if item.filename == "evidence/evidence_shot.jpg":
                    zout.writestr(item, b"maliciously_altered_data")
                else:
                    zout.writestr(item, zin.read(item.filename))

    verdict = verify_bundle(bad_zip)
    assert verdict.verified is False
    assert "Corrupted file" in verdict.error


# =====================================================================
# 7. Lead C — Operator Skill Compiler
# =====================================================================
def test_skill_compiler_describe_to_signed_skill():
    skill = describe_skill(
        goal="File claim for {vendor}",
        site="http://127.0.0.1:8011/expense/",
        step_descriptions=[
            "Type vendor Acme",
            "Type amount 42",
            "Select category office",
            "Submit claim"
        ],
        parameters={"vendor": "Acme", "amount": "42", "category": "office"}
    )
    assert len(skill.steps) == 4
    assert skill.signature != ""
    assert skill.provenance.get("vision_on_real_footage") == SKILL_DISCLOSURE

    # Ensure parameter slots are substituted
    assert skill.steps[0].arg["text"] == "{vendor}"
    assert skill.steps[1].arg["text"] == "{amount}"
    valid, _ = verify_procedure(skill)
    assert valid is True


def test_gated_reteach_flow():
    skill = describe_skill(
        goal="Inventory restock",
        site="http://127.0.0.1:8011/inventory/",
        step_descriptions=["Click restock button"]
    )
    # Refused without operator approval
    _, ok_refused, msg_refused = gated_reteach(skill, "s1", {"locators": [{"kind": "css", "value": "#new_btn"}]}, approved=False)
    assert ok_refused is False
    assert "approval is required" in msg_refused

    # Approved with operator confirmation
    updated_skill, ok_approved, msg_approved = gated_reteach(skill, "s1", {"locators": [{"kind": "css", "value": "#new_btn"}]}, approved=True)
    assert ok_approved is True
    assert updated_skill.steps[0].locators[0].value == "#new_btn"
    # Cryptographically re-signed
    valid, _ = verify_procedure(updated_skill)
    assert valid is True

