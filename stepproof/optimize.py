"""Local, FREE preprocessing that cuts SAM's per-frame bill (UNIBOT P1.2c).

Meta SAM bills per frame (50-frame minimum), so every frame you keep costs. These are
pure OpenCV transforms - no model calls - that reduce the frame count SAM is asked to
process WITHOUT losing the detections you need:
  * static_head_tail_trim - drop frames (and the head/tail static run) that never move,
  * cap_fps - resample to a target fps (slow-moving parts need ~8-10),
  * downscale - shrink to the smallest resolution that still segments the objects,
  * activity_windows - a cheap coarse-to-fine gate: which time windows contain motion,
    so a higher-fidelity pass only re-runs around pick/place events.
Each is ablatable (on/off) so the benchmark reports the saving + accuracy delta per one.
"""
from __future__ import annotations
import numpy as np
from pathlib import Path
import cv2


def _read_all(path: Path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    return fps, frames


def _write(frames, fps: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    h, w = frames[0].shape[:2]
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    for f in frames:
        vw.write(f)
    vw.release()
    return out


def _motion(cur: np.ndarray, prev: np.ndarray | None) -> float:
    """Frame-difference motion score between `cur` and `prev` (mean abs diff, grayscale).
    0.0 when there is no previous frame (the first frame is, by construction, static)."""
    if prev is None:
        return 0.0
    a = cv2.cvtColor(cv2.resize(cur, (64, 48)), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(cv2.resize(prev, (64, 48)), cv2.COLOR_BGR2GRAY)
    return float(np.mean(cv2.absdiff(a, b)))


def static_head_tail_trim(video: Path, out: Path, threshold: float = 1.0) -> dict:
    """Drop the static head + tail runs and any fully-static interior frame.
    Returns {"kept": int, "dropped": int} so the ablation reports the saving."""
    fps, frames = _read_all(video)
    kept_idx: list[int] = []
    for i, f in enumerate(frames):
        m = _motion(f, frames[i - 1] if i else None)
        if m > threshold:
            kept_idx.append(i)
    if kept_idx:
        a, b = kept_idx[0], kept_idx[-1]
        sel = [i for i in range(a, b + 1)]
    else:
        sel = list(range(len(frames)))     # nothing moved - keep all (don't hide content)
    _write([frames[i] for i in sel], fps, out)
    return {"kept": len(sel), "dropped": len(frames) - len(sel)}


def cap_fps(video: Path, out: Path, target_fps: float, keep_duration: bool = True) -> dict:
    """Resample to `target_fps` by keeping one frame per 1/target_fps source frames.
    With `keep_duration` the kept frames are written at `target_fps` AND trimmed so the
    output covers the same time span (redundant frames drop off the end, never the
    timeline) - re-encoding at a lower fps WITHOUT this would silently stretch the clip,
    which would shift every frame index and make the verdicts uncomparable."""
    fps, frames = _read_all(video)
    if target_fps >= fps:
        _write(frames, fps, out)
        return {"kept": len(frames), "dropped": 0}
    step = max(1, int(round(fps / target_fps)))
    sel = frames[::step]
    if keep_duration:
        orig_dur = len(frames) / fps
        sel = sel[:max(1, int(round(orig_dur * target_fps)))]   # same time span, redundant tail off
    _write(sel, target_fps, out)
    return {"kept": len(sel), "dropped": len(frames) - len(sel)}


def downscale(video: Path, out: Path, max_w: int = 640, max_h: int = 480) -> dict:
    """Shrink to the largest dimension that fits (aspect preserved). Fewer pixels per
    frame; call SAM on the smaller frames. Returns the output dims."""
    fps, frames = _read_all(video)
    h, w = frames[0].shape[:2]
    scale = min(1.0, max_w / w, max_h / h)
    resized = [cv2.resize(f, (max(1, int(w * scale)), max(1, int(h * scale)))) for f in frames]
    _write(resized, fps, out)
    oh, ow = resized[0].shape[:2]
    return {"width": ow, "height": oh, "scale": round(scale, 3)}


def activity_windows(video: Path, max_windows: int = 4, threshold: float = 1.0) -> list[dict]:
    """Coarse-to-fine gate: find the time windows containing motion, so a higher-fidelity
    SAM pass only re-runs around events. Returns [{"start","end"}] frame ranges (in
    ORIGINAL frame indices). Deterministic, no model."""
    fps, frames = _read_all(video)
    motion = [0.0] + [_motion(frames[i], frames[i - 1]) for i in range(1, len(frames))]
    hot = [i for i, m in enumerate(motion) if m > threshold]
    if not hot:
        return []
    # group consecutive hot frames into windows, each padded by one frame (an event has
    # some duration; re-running SAM on [start-1, end+1] must not hide it), then merge
    # touching windows
    windows, start, prev = [], hot[0], hot[0]
    for i in hot[1:]:
        if i == prev + 1:
            prev = i
        else:
            windows.append([start, prev])
            start, prev = i, i
    windows.append([start, prev])
    padded, merged = [[max(0, s - 1), min(len(frames) - 1, e + 1)] for s, e in windows], []
    for s, e in padded:
        if merged and s <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [{"start": s, "end": e} for s, e in merged[:max_windows]]
