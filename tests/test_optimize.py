"""Offline, deterministic tests for the P1.2c preprocessors (the free, model-less frame
cutters each ablatable in BENCHMARK.md). No API, no network - pure OpenCV on a clip."""
from pathlib import Path

import cv2
import numpy as np

from stepproof import optimize
from stepproof.video import probe

CLIP = (Path(__file__).resolve().parent.parent / "data" / "clips" / "p1_ok.mp4")   # synthetic MJPG, 100 frames @ 10 fps


def _write_tmp_clip(path: Path, n: int = 24, move_every: int = 3) -> Path:
    """A tiny moving-object clip: static bg, a square sliding right every `move_every`
    frames - motion + static runs both present, so the trimmer has something to find."""
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
    for i in range(n):
        f = np.full((120, 160, 3), 40, np.uint8)
        x = 10 + (i // move_every) * 12
        cv2.rectangle(f, (x, 40), (x + 24, 80), (200, 60, 60), -1)
        vw.write(f)
    vw.release()
    return path


def test_cap_fps_reduces_frame_count(tmp_path):
    out = tmp_path / "capped.mp4"
    info = optimize.cap_fps(CLIP, out, target_fps=5.0)
    fps, n, _, _ = probe(out)
    assert abs(fps - 5.0) < 0.6, f"expected ~5 fps, got {fps}"
    assert n < 100 and info["dropped"] > 0, info


def test_static_head_tail_trim_drops_static(tmp_path):
    src = _write_tmp_clip(tmp_path / "src.mp4")
    out = tmp_path / "trimmed.mp4"
    # threshold 1.0 (the default): on compressed MJPG the motion peaks are ~1.7-1.9,
    # so 2.0 would drop everything and the fallback would keep all frames - a silent no-op
    info = optimize.static_head_tail_trim(src, out, threshold=1.0)
    _, n, _, _ = probe(out)
    # the object moves every 3 frames out of 24 -> most frames carry motion; the static
    # ones (frame 0, repeats) must be dropped, and content preserved in order
    assert 0 < n < 24, f"kept {n} of 24"
    assert info["kept"] == n and info["dropped"] == 24 - n


def test_downscale_shrinks_dimensions(tmp_path):
    out = tmp_path / "small.mp4"
    info = optimize.downscale(CLIP, out, max_w=160, max_h=120)
    assert (info["width"], info["height"]) == (160, 120)
    assert info["scale"] < 1.0


def test_activity_windows_find_motion(tmp_path):
    src = _write_tmp_clip(tmp_path / "src.mp4")
    wins = optimize.activity_windows(src, threshold=1.0)
    assert wins, "a moving square must produce at least one activity window"
    assert all(w["start"] < w["end"] for w in wins)
    # deterministic: same input -> same windows
    assert wins == optimize.activity_windows(src, threshold=1.0)


def test_ablations_are_noops_on_static_video(tmp_path):
    """A fully static video must not lose content: trim keeps all frames (fallback),
    windows is empty - so 'dropping static frames' can never hide a defect."""
    vw = cv2.VideoWriter(str(tmp_path / "s.mp4"), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    for _ in range(12):
        vw.write(np.full((48, 64, 3), 80, np.uint8))
    vw.release()
    src = tmp_path / "s.mp4"
    out = tmp_path / "t.mp4"
    assert optimize.static_head_tail_trim(src, out)["dropped"] == 0
    assert optimize.activity_windows(src) == []
