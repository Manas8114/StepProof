"""Thin adapter connecting real recorded video clips to the frozen v1 SAM video-verify pipeline.
Runs the clip through v1 inspection rules and records the outcome as an audited proof artifact.
"""
from __future__ import annotations
import json, time
from pathlib import Path
from typing import Optional, Any

from .. import config as cfg
from ..pipeline import run_inspection
from ..rules import Params
from ..schemas import ProcedureSpec, Report
from ..audit import get_spine


def verify_v1_clip(video_path: Path | str, procedure_path: Optional[Path | str] = None,
                   wire_client: Optional[Any] = None, state_checker: Optional[Any] = None) -> dict:
    """Takes a video clip, executes the frozen v1 inspection rules, and links the result
    into the audit spine as a verifiable proof entry."""
    v_path = Path(video_path)
    if not v_path.exists():
        raise FileNotFoundError(f"Video clip not found: {video_path}")

    # Load procedure spec (defaults to standard synthetic board)
    p_path = Path(procedure_path) if procedure_path else (cfg.DATA_DIR / "procedures" / "board.json")
    if not p_path.exists():
        # Fallback to demo board procedure
        p_path = cfg.BASE / "data" / "procedures" / "board.json"

    spec = ProcedureSpec.model_validate_json(p_path.read_text(encoding="utf-8"))

    # Execute frozen v1 inspection pipeline
    t0 = time.time()
    report: Report = run_inspection(spec, v_path, wire_client=wire_client, state_checker=state_checker)
    wall_s = round(time.time() - t0, 2)

    # Derive verdict
    passed = (report.status == "pass")
    verdict_str = "PASS" if passed else "FAIL"

    checks = []
    evidence_paths = []
    for step in report.steps:
        chk_passed = (step.status == "pass")
        checks.append({
            "name": f"v1_step_{step.step_id}",
            "passed": chk_passed,
            "detail": f"count={step.count_observed}/{step.expected_count}, state={step.state_result}",
            "evidence": str(step.evidence_frame or "")
        })
        if step.evidence_frame:
            evidence_paths.append(str(step.evidence_frame))

    # Append to AuditSpine
    run_id = f"v1-clip-{int(t0*1000)}"
    entry = get_spine().append(
        run_id=run_id,
        verdict=verdict_str,
        checks=checks,
        steps=[{"id": s.step_id, "name": s.name, "status": s.status} for s in report.steps],
        evidence_paths=evidence_paths,
        cost={"video_clip": v_path.name, "wall_s": wall_s},
        model_disclosure={
            "pipeline": "v1_sam_video_verify",
            "footage_type": "physical_clip" if "real" in v_path.name.lower() else "synthetic_mjpg",
            "sam_status": "mock_wire" if wire_client else "production_sam_3.1"
        }
    )

    return {
        "run_id": run_id,
        "status": report.status,
        "passed": passed,
        "wall_s": wall_s,
        "audit_seq": entry.seq,
        "entry_hash": entry.entry_hash,
        "report": report.model_dump(),
    }

