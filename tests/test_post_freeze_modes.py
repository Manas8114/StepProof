"""Tests for Post-Freeze Product Phase:
  - Trust Spine & Artifact Signing (I1, I2, I3)
  - Mode A: Self-healing web tests, Suite runner, Drift reports, Gated re-harvest
  - Mode B: Independent offline verifier, Bundler, Zero-network verification
  - Mode C: Skill Compiler, Task Families, Slots, Per-value safety classification
  - Copilot: Live suggestion engine & interactive Q&A
"""
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
import pytest

from stepproof.proc import Procedure, Step, Locator
from stepproof.signing import get_device_key, compute_procedure_hash
from stepproof.artifact import sign_procedure, verify_artifact, save_artifact, load_artifact
from stepproof.audit import AuditSpine, AuditEntry, GENESIS_HASH
from stepproof.budget import BudgetConfig, BudgetTripwire, estimate_procedure_cost, CostEstimate
from stepproof.testmode.suite import run_single_procedure, run_suite_once
from stepproof.testmode.drift_report import re_harvest_gated
from stepproof.verify_bundle import verify_bundle_offline
from stepproof.skill.compile_family import (
    compile_family,
    propose_slots,
    instantiate,
    verify_family,
    classify_value_safety,
    re_teach_step,
    SlotDef,
    ProcedureFamily,
)
from stepproof.skill.from_demo import from_demo_file, from_describe


@pytest.fixture
def sample_procedure():
    return Procedure(
        goal="File an Acme office expense of $42",
        site="http://127.0.0.1:8011/expense/",
        steps=[
            Step(id="s1", description="Type Acme into vendor", action="type", arg={"text": "Acme"},
                 locators=[Locator("css", "#vendor")]),
            Step(id="s2", description="Type 42 into amount", action="type", arg={"text": "42"},
                 locators=[Locator("css", "#amount")]),
            Step(id="s3", description="Select category office", action="select", arg={"value": "office"},
                 locators=[Locator("css", "#category")]),
            Step(id="s4", description="Click submit", action="click", arg={},
                 locators=[Locator("css", "#submit")]),
        ],
        success_checks=[
            {"type": "text_visible", "text": "Claim filed"},
        ],
    )


# -----------------------------------------------------------------------------
# I2: Signed Portable Artifacts
# -----------------------------------------------------------------------------
def test_artifact_sign_and_verify_roundtrip(sample_procedure, tmp_path):
    device_key = "test-device-key-32bytes-secret!!"
    manifest = sign_procedure(sample_procedure, device_key=device_key)
    assert manifest["procedure_hash"]
    assert sample_procedure.signature

    valid, err = verify_artifact(sample_procedure, device_key=device_key)
    assert valid is True
    assert err is None


def test_artifact_rejects_tampered_body(sample_procedure):
    device_key = "test-device-key-32bytes-secret!!"
    sign_procedure(sample_procedure, device_key=device_key)

    # Tamper with a step action
    sample_procedure.steps[0].action = "dangerous_click"
    valid, err = verify_artifact(sample_procedure, device_key=device_key)
    assert valid is False
    assert "Tampered procedure body" in err


def test_artifact_rejects_wrong_key(sample_procedure):
    device_key_1 = "key-machine-alpha-001"
    device_key_2 = "key-machine-beta-002"
    sign_procedure(sample_procedure, device_key=device_key_1)

    valid, err = verify_artifact(sample_procedure, device_key=device_key_2)
    assert valid is False
    assert "Signature mismatch" in err


def test_artifact_file_persistence(sample_procedure, tmp_path):
    art_file = tmp_path / "expense.artifact"
    device_key = "my-local-device-key"
    save_artifact(sample_procedure, art_file, device_key=device_key)
    assert art_file.exists()

    loaded = load_artifact(art_file, device_key=device_key)
    assert loaded.goal == sample_procedure.goal
    assert len(loaded.steps) == len(sample_procedure.steps)


# -----------------------------------------------------------------------------
# I1: Cost Estimate & Tripwire
# -----------------------------------------------------------------------------
def test_preflight_cost_estimate_pure(sample_procedure):
    est = estimate_procedure_cost(sample_procedure)
    # When all steps have locators, estimated SAM frames is 0
    assert est.estimated_sam_frames == 0
    assert est.estimated_tokens == 0

    # If steps lack locators, each estimates 50 SAM frames
    proc_no_locs = copy.deepcopy(sample_procedure)
    proc_no_locs.steps[0].locators = []
    proc_no_locs.steps[1].locators = []
    est2 = estimate_procedure_cost(proc_no_locs)
    assert est2.estimated_sam_frames == 100
    assert est2.estimated_tokens == 1700


def test_tripwire_aborts_budget_before_execution(sample_procedure, tmp_path):
    proc_file = tmp_path / "runaway.json"
    p = copy.deepcopy(sample_procedure)
    p.steps[0].locators = []  # 50 frames
    p.steps[1].locators = []  # 50 frames
    p.steps[2].locators = []  # 50 frames -> total 150 frames
    proc_file.write_text(json.dumps(p.to_dict()), encoding="utf-8")

    # Set strict cap of 100 frames via env
    os.environ["STEPPROOF_COST_CAP_FRAMES"] = "100"
    try:
        spine = AuditSpine(sink_dir=tmp_path / "audit", use_global_db=False)
        res = run_single_procedure(proc_file, spine=spine)
        assert res["status"] == "aborted_budget"
        assert res["success"] is False
        assert "exceeds per-run cap" in res["error"]

        entries = spine.get_entries(res["run_id"])
        assert len(entries) == 1
        assert entries[0].verdict == "ABORTED_BUDGET"
    finally:
        os.environ.pop("STEPPROOF_COST_CAP_FRAMES", None)


# -----------------------------------------------------------------------------
# Mode B: Offline Verification & Evidence Bundler
# -----------------------------------------------------------------------------
def test_bundle_creation_and_offline_verification(tmp_path):
    audit_dir = tmp_path / "audit"
    spine = AuditSpine(sink_dir=audit_dir, use_global_db=False)
    run_id = "test_run_offline_proof_123"

    # Create dummy evidence file
    ev_dir = tmp_path / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    ev_file = ev_dir / "shot_0.jpg"
    ev_file.write_bytes(b"dummy image bytes 1234567890")

    # Append valid audit entry
    spine.append(
        run_id=run_id,
        verdict="PASS",
        checks=[{"name": "text_visible", "passed": True, "evidence": str(ev_file)}],
        steps=[{"step": "s1", "success": True}],
        evidence_paths=[str(ev_file)],
        model_disclosure={"active_model": "test-model", "fell_back": False},
        cost={"status": "ok"},
    )

    bundle_zip = spine.package_run(run_id, out_path=tmp_path / "bundle.zip")
    assert bundle_zip.exists()

    # Verify completely offline (zero network, zero API calls)
    report = verify_bundle_offline(bundle_zip)
    assert report["verified"] is True
    assert report["run_id"] == run_id
    assert report["manifest_hash_valid"] is True
    assert report["chain_integrity_valid"] is True
    assert report["checks_passed"] == 1
    assert report["checks_failed"] == 0


def test_bundle_rejects_tampered_evidence(tmp_path):
    import zipfile
    audit_dir = tmp_path / "audit"
    spine = AuditSpine(sink_dir=audit_dir, use_global_db=False)
    run_id = "test_run_tamper_999"

    ev_file = tmp_path / "orig_shot.jpg"
    ev_file.write_bytes(b"original data")

    spine.append(
        run_id=run_id,
        verdict="PASS",
        checks=[{"name": "check1", "passed": True, "evidence": str(ev_file)}],
        evidence_paths=[str(ev_file)],
    )
    bundle_zip = spine.package_run(run_id, out_path=tmp_path / "bundle_clean.zip")

    # Tamper with the zip contents
    tampered_zip = tmp_path / "bundle_tampered.zip"
    with zipfile.ZipFile(bundle_zip, "r") as zin:
        with zipfile.ZipFile(tampered_zip, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if "orig_shot.jpg" in item.filename:
                    data = b"TAMPERED IMAGE BYTES"
                zout.writestr(item, data)

    res = verify_bundle_offline(tampered_zip)
    assert res["verified"] is False
    assert "Tampered evidence file" in res["error"]


# -----------------------------------------------------------------------------
# Mode C: Task Families, Slots & Per-Value Safety
# -----------------------------------------------------------------------------
def test_slot_proposals_and_family_compilation(sample_procedure):
    proposals = propose_slots(sample_procedure)
    assert "vendor" in proposals
    assert "amount" in proposals
    assert "category" in proposals

    family = compile_family(sample_procedure, confirmed_slots=["vendor", "amount", "category"])
    assert isinstance(family, ProcedureFamily)
    assert len(family.slots) == 3
    assert family.signature

    valid, err = verify_family(family)
    assert valid is True
    assert err is None


def test_instantiate_per_value_safety_classification(sample_procedure):
    family = compile_family(sample_procedure, confirmed_slots=["vendor", "amount", "category"])

    # Normal safe values
    proc_safe, safety_safe = instantiate(family, {"vendor": "Acme", "amount": "42", "category": "office"})
    assert safety_safe["highest_risk"] == "SAFE"
    assert safety_safe["approval_required"] is False
    assert proc_safe.steps[0].arg["text"] == "Acme"
    assert proc_safe.steps[1].arg["text"] == "42"

    # High amount (>500) escalates to DANGEROUS
    proc_high, safety_high = instantiate(family, {"vendor": "Acme", "amount": "850", "category": "office"})
    assert safety_high["highest_risk"] == "DANGEROUS"
    assert safety_high["approval_required"] is True

    # Dangerous action keyword ("Discard") escalates to IRREVERSIBLE
    proc_danger, safety_danger = instantiate(family, {"vendor": "Discard Old Claims", "amount": "42", "category": "office"})
    assert safety_danger["highest_risk"] == "IRREVERSIBLE"
    assert safety_danger["approval_required"] is True


def test_instantiate_rejects_invalid_type(sample_procedure):
    family = compile_family(sample_procedure, confirmed_slots=["amount"])
    with pytest.raises(TypeError, match="does not match numeric pattern"):
        instantiate(family, {"amount": "not_a_number_at_all"})


def test_re_teach_step_flow(sample_procedure):
    """Mode C3: Gated re-teach flow produces new signature and provenance tracking."""
    family = compile_family(sample_procedure, confirmed_slots=["vendor", "amount"])
    old_sig = family.signature
    assert old_sig

    # Replacement step demonstrated by human operator
    new_step = Step(
        id="s4",
        description="Click modern submit button",
        action="click",
        locators=[Locator("css", "button.healed-submit-v2"), Locator("xpath", "//button[@type='submit']")],
        vision_concept="Healed submit button",
    )

    updated_fam = re_teach_step(
        family=family,
        step_id="s4",
        updated_step=new_step,
        triggering_run_id="run_drift_failure_404",
    )

    # Signature must be new and distinct
    assert updated_fam.signature != old_sig
    # Provenance audit fields must be populated
    assert updated_fam.provenance["action"] == "re_teach"
    assert updated_fam.provenance["step_id"] == "s4"
    assert updated_fam.provenance["triggering_run_id"] == "run_drift_failure_404"
    assert updated_fam.provenance["previous_signature"] == old_sig

    # Step in updated procedure must reflect the newly taught step
    s4 = next(s for s in updated_fam.procedure.steps if s.id == "s4")
    assert s4.locators[0].value == "button.healed-submit-v2"
    assert s4.vision_concept == "Healed submit button"

    # Signature must pass verification
    ok, err = verify_family(updated_fam)
    assert ok is True
    assert err is None

    # Invalid step id must raise KeyError
    with pytest.raises(KeyError, match="not found"):
        re_teach_step(family, "nonexistent_step", new_step, "run_id")


# -----------------------------------------------------------------------------
# Mode A: Gated Re-harvest
# -----------------------------------------------------------------------------
def test_gated_reharvest_confirmation(sample_procedure, tmp_path):
    proc_file = tmp_path / "proc_to_reharvest.json"
    sign_procedure(sample_procedure)
    save_artifact(sample_procedure, proc_file)

    drift_data = {
        "procedure_goal": sample_procedure.goal,
        "total_steps": 4,
        "drifted_steps": 1,
        "vision_healed_steps": 1,
        "records": [
            {
                "step_id": "s4",
                "step_description": "Click submit",
                "primary_locator": {"kind": "css", "value": "#submit"},
                "winning_locator": {"kind": "css", "value": "button.mutated-submit-btn"},
                "healed": True,
                "needed_vision": True,
                "vision_note": "Visual self-healing recovered button @ (450, 320)",
            }
        ]
    }

    # Run re-harvest with programmatic confirmation
    ok = re_harvest_gated(drift_data, proc_file, yes_confirm=True)
    assert ok is True

    # Check updated artifact has new locator and valid signature
    updated_proc = load_artifact(proc_file)
    s4 = next(s for s in updated_proc.steps if s.id == "s4")
    assert s4.locators[0].value == "button.mutated-submit-btn"
    assert s4.locators[1].value == "#submit"


# -----------------------------------------------------------------------------
# Copilot: Next-Step Suggestion & Interactive Ask
# -----------------------------------------------------------------------------
def test_copilot_suggest_and_ask_api():
    from fastapi.testclient import TestClient
    from stepproof.api_v2 import app

    client = TestClient(app)

    # 1. Test Copilot Suggestion
    r = client.post("/api/v2/copilot/suggest", json={"goal": "File expense claim"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "suggestion" in data

    # 2. Test Copilot Ask Anything
    r_ask = client.post("/api/v2/copilot/ask", json={"question": "What can I do on this page?"})
    assert r_ask.status_code == 200
    data_ask = r_ask.json()
    assert data_ask["ok"] is True
    assert "answer" in data_ask
    assert len(data_ask["answer"]) > 10

    # 3. Test Copilot Ask Safety
    r_safe = client.post("/api/v2/copilot/ask", json={"question": "Is this page safe to automate?"})
    assert r_safe.status_code == 200
    assert "Safety Status" in r_safe.json()["answer"]


def test_monitor_recording_and_compilation_workflow():
    """Verify that monitor recording and compilation workflow retains actions, returns steps > 0,
    and supports rich element-at locators including fallback box coordinates."""
    from fastapi.testclient import TestClient
    from stepproof.api_v2 import app

    client = TestClient(app)

    # 1. Test element-at locator lookup
    el_res = client.get("/api/v2/browser/element-at?x=50&y=50")
    assert el_res.status_code == 200
    el_data = el_res.json()
    assert "locators" in el_data
    assert len(el_data["locators"]) >= 1
    assert any(l.get("kind") == "box" for l in el_data["locators"])

    # 2. Record 4 actions
    client.post("/api/v2/monitor/start", json={"site": ""})
    client.post("/api/v2/monitor/record", json={"tool": "type", "text": "Acme", "locators": [{"kind": "css", "value": "#vendor"}]})
    client.post("/api/v2/monitor/record", json={"tool": "type", "text": "42", "locators": [{"kind": "css", "value": "#amount"}]})
    client.post("/api/v2/monitor/record", json={"tool": "select", "text": "Travel", "locators": [{"kind": "css", "value": "#category"}]})
    client.post("/api/v2/monitor/record", json={"tool": "click", "text": "", "locators": [{"kind": "box", "value": "200,300"}]})

    # 3. Compile procedure
    comp_res = client.post("/api/v2/monitor/compile", json={"goal": "File Acme travel expense", "add_checks": []})
    assert comp_res.status_code == 200
    c_data = comp_res.json()
    assert c_data["steps"] == 4
    assert len(c_data["procedure"]["steps"]) == 4
    assert not any("no recorded actions" in w for w in c_data.get("warnings", []))
    assert c_data["procedure"]["manifest"]["step_count"] == 4
    assert c_data["procedure"]["signature"]


def test_endpoint_deduplication_and_token_matching():
    """Verify that generic container IDs (#endpoint) are filtered out from concepts and locators,
    and fuzzy token matching works for complex punctuation names like '[AMV] Yes & No'."""
    from stepproof.learn.compile import derive_vision_concept
    from stepproof.browser.actions import _click_by_name

    # 1. derive_vision_concept filters out #endpoint and generic container names
    concept = derive_vision_concept("click", element_name="endpoint", locators=[{"kind": "css", "value": "#endpoint"}], narration="click the video")
    assert "Endpoint" not in concept
    assert "video" in concept.lower()

    # 2. derive_vision_concept preserves real video title
    v_concept = derive_vision_concept("click", element_name="Cartoon Anime Version [AMV] Yes & No", locators=[{"kind": "box", "value": "100,200"}])
    assert "Cartoon Anime Version" in v_concept

    # 3. _click_by_name matches tokens despite punctuation differences
    class MockBrowser:
        def __init__(self):
            self.clicked = None
        def observe(self):
            return {
                "elements": [
                    {
                        "visible": True,
                        "name": "Cartoon Anime Version AMV Yes and No official video",
                        "kind": "a",
                        "role": "link",
                        "x": 100, "y": 200, "w": 300, "h": 50
                    }
                ]
            }
        def act(self, op, arg):
            if op == "click_box":
                self.clicked = arg
            return {"ok": True}

    mb = MockBrowser()
    _click_by_name(mb, "Cartoon Anime Version [AMV] Yes & No")
    assert mb.clicked is not None
    assert mb.clicked["x"] == 250
    assert mb.clicked["y"] == 225



