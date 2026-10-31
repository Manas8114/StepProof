import cv2, numpy as np
from stepproof import config as cfg
from stepproof.compiler import sanitize
from stepproof.pipeline import run_inspection
from stepproof.providers.mock import MockSegmentation, MockVision
from stepproof.schemas import Detection, ProcedureSpec, Step


def _video(path, n=60, w=96, h=64):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (w, h))
    for i in range(n):
        vw.write(np.full((h, w, 3), i * 3 % 255, np.uint8))
    vw.release()


def _d(frames, concept_id=0):
    return [Detection(frame=f, obj_id=concept_id, box=(5, 5, 40, 30), conf=0.9) for f in frames]


def test_end_to_end_with_mocks(tmp_path):
    v = tmp_path / "clip.avi"
    _video(v)
    spec = ProcedureSpec(name="demo", steps=[
        Step(id="s1", description="connector in", concept="red connector"),
        Step(id="s2", description="cover on", concept="black cover", after=["s1"], state_question="Is the cover closed?"),
        Step(id="s3", description="screw in", concept="silver screw"),
    ])
    seg = MockSegmentation({"red connector": _d(range(5, 60)), "black cover": _d(range(20, 60))})
    rep = run_inspection(v, spec, seg, MockVision(), "t1")
    by = {r.step_id: r for r in rep.results}
    assert by["s1"].verdict == "pass" and by["s2"].verdict == "pass" and by["s3"].verdict == "fail"
    assert rep.overall == "fail"
    assert (cfg.EVIDENCE / "t1" / by["s1"].evidence_image).exists()
    assert by["s2"].state is not None and by["s2"].state_image
    assert set(rep.overlay) == {"red connector", "black cover", "silver screw"}


def test_sanitize_reduces_list_concepts_and_drops_bad_prereqs():
    sp = ProcedureSpec(name="x", steps=[Step(id="s1", description="", concept="Screws, nuts", after=["s9"])])
    sp, warn = sanitize(sp)
    assert sp.steps[0].concept == "screws" and sp.steps[0].after == [] and len(warn) == 2
