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
