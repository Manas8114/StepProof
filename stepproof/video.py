from __future__ import annotations
from pathlib import Path
import cv2
import numpy as np

_PALETTE = [(87, 139, 46), (30, 120, 200), (60, 60, 180), (200, 90, 60), (160, 60, 140)]  # BGR


def probe(path: Path) -> tuple[float, int, int, int]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n, w, h = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return float(fps), n, w, h


def read_frame(path: Path, idx: int) -> np.ndarray:
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise ValueError(f"Cannot read frame {idx} of {path}")
    return frame


def draw_boxes(frame: np.ndarray, boxes_by_label: dict[str, list[tuple[int, int, int, int]]]) -> np.ndarray:
    out = frame.copy()
    for i, (label, boxes) in enumerate(boxes_by_label.items()):
        col = _PALETTE[i % len(_PALETTE)]
        for x1, y1, x2, y2 in boxes:
            cv2.rectangle(out, (x1, y1), (x2, y2), col, 2)
            cv2.putText(out, label, (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 2, cv2.LINE_AA)
    return out


def crop_union(frame: np.ndarray, boxes: list[tuple[int, int, int, int]], pad: float = 0.5) -> np.ndarray:
    if not boxes:
        return frame
    h, w = frame.shape[:2]
    x1, y1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x2, y2 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    px, py = int((x2 - x1) * pad) + 24, int((y2 - y1) * pad) + 24
    return frame[max(0, y1 - py):min(h, y2 + py), max(0, x1 - px):min(w, x2 + px)]
