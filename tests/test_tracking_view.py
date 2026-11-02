from fastapi.testclient import TestClient
from stepproof.api_v2 import app

client = TestClient(app)


def test_tracking_demo_endpoint():
    res = client.get("/api/v2/tracking/demo")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["video_url"] == "/video/pan.mp4"
    assert data["fps"] == 10.0
    assert data["width"] == 640
    assert data["height"] == 360
    assert data["total_frames"] == 60
    assert data["detections_count"] == 60
    frames = data["frames"]
    assert len(frames) == 60
    # Frame 0 check
    f0 = frames.get("0") or frames.get(0)
    assert f0 and len(f0) == 1
    det = f0[0]
    assert det["obj_id"] == 0
    assert det["conf"] >= 0.95
    assert len(det["box"]) == 4
    x1, y1, x2, y2 = det["box"]
    assert 0 <= x1 < x2 <= 640
    assert 0 <= y1 < y2 <= 360
    # Tracking consistency check: all frames have obj_id=0
    for frame_id, dlist in frames.items():
        assert len(dlist) >= 1
        assert dlist[0]["obj_id"] == 0


def test_tracking_video_file_served():
    res = client.get("/video/pan.mp4")
    assert res.status_code == 200
    assert "video/mp4" in res.headers.get("content-type", "") or len(res.content) > 10000
