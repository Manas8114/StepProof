"""Offline dataset tests: MockSam/MockMuse serve scripts.make_dataset sidecars;
the synthetic dataset satisfies the eval harness fully offline. Synthetic —
never used for reported metrics."""
import json, os
from pathlib import Path
import pytest

from stepproof.schemas import ProcedureSpec
from stepproof.providers.mock import MockSam, MockMuse


@pytest.fixture()
def dataset(tmp_path, monkeypatch):
    """Build the synthetic dataset into tmp_path (no repo data/, no network)."""
    from scripts import make_dataset
    out = tmp_path / "data"
    make_dataset.main(out=str(out))
    return out


def test_sidecars_cover_every_clip(dataset):
    for clip in (dataset / "clips").glob("*.mp4"):
        sc = json.loads(clip.with_suffix(".dets.json").read_text())
        assert "baseline" in sc and "expected" in sc and "concepts" in sc
        for c, d in sc["concepts"].items():
            assert d["present_frames"] is not None  # empty presence is a valid result
            assert 0 <= min(d["box"]) and max(d["box"]) <= 400


def test_mock_sam_serves_sidecar_tracks(dataset):
    clip = dataset / "clips" / "p1_ok.mp4"
    sc = json.loads(clip.with_suffix(".dets.json").read_text())
    dets = MockSam().segment_video(clip, "red connector")
    assert len(dets) == len(sc["concepts"]["red connector"]["present_frames"])
    assert dets[0].box == tuple(sc["concepts"]["red connector"]["box"])
    assert MockSam().segment_video(clip, "unknown concept") == []


def test_mock_muse_compiles_and_state(dataset):
    cfg_data = json.loads((dataset / "stepproof_mock.json").read_text())
    muse = MockMuse(compile_table=cfg_data["compile_table"], state_table=cfg_data["state_table"])
    spec = muse.compile_procedure("Attach the red connector, close the cover, insert two screws")
    assert spec.steps[1].after == ["s1"] and spec.steps[2].min_count == 2
    st = muse.check_state(Path("data/evidence/x/s2_state_f90.jpg"), "Is the gold latch engaged?")
    assert st.answer == "yes" and st.confidence >= 0.7


def test_full_pipeline_runs_offline(dataset, monkeypatch):
    """run_inspection on a synthetic clip with mock providers, zero network."""
    from stepproof.pipeline import run_inspection
    from stepproof.rules import Params
    import stepproof.config as cfg
    monkeypatch.setattr(cfg, "EVIDENCE", dataset / "evidence")

    spec = ProcedureSpec.model_validate_json((dataset / "procedures" / "board.json").read_text())
    muse = MockMuse()
    rep = run_inspection(dataset / "clips" / "p1_ok.mp4", spec, MockSam(), muse, "off1", params=Params())
    assert {r.step_id: r.verdict for r in rep.results} == {"s1": "pass", "s2": "pass", "s3": "pass"}

    spec2 = ProcedureSpec.model_validate_json((dataset / "procedures" / "fastening.json").read_text())
    muse2 = MockMuse(state_table={"Is the gold latch engaged?": {"answer": "yes", "confidence": 0.9}})
    rep2 = run_inspection(dataset / "clips" / "p2_missing_latch.mp4", spec2, MockSam(), muse2, "off2", params=Params())
    assert {r.step_id: r.verdict for r in rep2.results}["s2"] == "fail"
