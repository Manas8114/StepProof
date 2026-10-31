"""Real SAM 3.1 wire output (Meta Model API, live run 2026-10-31, concept 'wheel' on a real
photo), pinned as a regression fixture. Not synthetic: these tokens came from the API."""
from pathlib import Path
from stepproof.wire import parse_wire

FIX = Path(__file__).parent / "fixtures" / "wire_image_real.txt"


def test_real_wire_has_detections_with_confidence_and_mask():
    d = parse_wire(FIX.read_text())
    assert len(d) == 2
    assert all(x.frame == 0 for x in d)  # image request -> single frame 0
    assert [x.obj_id for x in d] == [0, 1]
    assert all(isinstance(x.conf, float) and 0 < x.conf <= 1 for x in d)
    assert all(x.box[2] > x.box[0] and x.box[3] > x.box[1] for x in d)
    assert all(x.mask and x.mask.strip() for x in d)


def test_real_wire_box_scale_is_image_pixels():
    d = parse_wire(FIX.read_text())
    x1, y1, x2, y2 = d[0].box
    assert 0 <= x1 < x2 and 0 <= y1 < y2 and x2 <= 800 and y2 <= 534  # photo is 800x534


VFIX = Path(__file__).parent / "fixtures" / "wire_video_real.txt"


def test_real_video_wire_tracks_stable_object_across_frames():
    d = parse_wire(VFIX.read_text())
    assert len(d) == 60  # one detection per frame of the 60-frame clip
    frames = sorted({x.frame for x in d})
    assert frames[0] == 0 and frames[-1] == 59
    assert all(0 <= x.frame < 60 for x in d)
    assert all(x.box[2] <= 640 and x.box[3] <= 360 for x in d)  # clip is 640x360
    assert {x.obj_id for x in d} == {0}  # single tracked object, stable id
    assert all(isinstance(x.conf, float) and x.conf > 0.5 for x in d)
    assert all(x.mask for x in d)


def test_box_migrates_with_pan_not_static():
    d = parse_wire(VFIX.read_text())
    x1 = [b.box[0] for b in d]  # left edge of the tracked car as the clip pans
    assert min(x1) < max(x1)  # the box moves; proves video tracking, not a static tile
