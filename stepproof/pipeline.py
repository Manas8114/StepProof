from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable
import cv2
from . import config as cfg
from .rules import Params, count_series, evaluate, overall
from .schemas import Report, ProcedureSpec, Step
from .video import crop_union, draw_boxes, probe, read_frame


def run_inspection(video: Path, spec: ProcedureSpec, seg, vis, inspection_id: str,
                   on_progress: Callable[[str], None] = lambda s: None, params: Params = Params()) -> Report:
    t0 = time.time()
    fps, n, w, h = probe(video)
    concepts = sorted({s.concept for s in spec.steps})
    on_progress(f"Segmenting {len(concepts)} object type(s) with SAM 3.1")
    with ThreadPoolExecutor(max_workers=max(1, min(4, len(concepts)))) as ex:
        futs = {c: ex.submit(seg.segment_video, video, c) for c in concepts}
        dets = {c: f.result() for c, f in futs.items()}
    n = max([n] + [d.frame + 1 for ds in dets.values() for d in ds])
    ev_dir = cfg.EVIDENCE / inspection_id
    ev_dir.mkdir(parents=True, exist_ok=True)

    def boxes_at(concept: str, frame: int):
        return [d.box for d in dets.get(concept, []) if d.frame == frame and (d.conf is None or d.conf >= params.min_conf)]

    state_meta: dict[str, tuple[int, str]] = {}

    def state_fn(step: Step, frame: int):
        on_progress(f"Checking state for {step.id} with Muse Spark")
        crop = crop_union(read_frame(video, frame), boxes_at(step.concept, frame))
        p = ev_dir / f"{step.id}_state_f{frame}.jpg"
        cv2.imwrite(str(p), crop)
        state_meta[step.id] = (frame, p.name)
        return vis.check_state(p, step.state_question)

    on_progress("Applying deterministic rules")
    results = evaluate(spec, dets, fps, n, state_fn, params)
    by_id = {s.id: s for s in spec.steps}
    for r in results:
        if r.evidence_frame is not None:
            c = by_id[r.step_id].concept
            img = draw_boxes(read_frame(video, r.evidence_frame), {c: boxes_at(c, r.evidence_frame)})
            name = f"{r.step_id}_f{r.evidence_frame}.jpg"
            cv2.imwrite(str(ev_dir / name), img)
            r.evidence_image = name
        if r.step_id in state_meta:
            r.state_frame, r.state_image = state_meta[r.step_id]

    stride = max(1, n // 600)
    overlay: dict[str, dict[int, list[list[int]]]] = {}
    counts: dict[str, list[int]] = {}
    for c in concepts:
        by_frame: dict[int, list[list[int]]] = {}
        for d in dets[c]:
            if d.frame % stride == 0 and (d.conf is None or d.conf >= params.min_conf):
                by_frame.setdefault(d.frame, []).append(list(d.box))
        overlay[c] = by_frame
        counts[c] = count_series(dets[c], n, params.min_conf)[0][::stride]

    return Report(
        inspection_id=inspection_id, procedure=spec, video=video.name, fps=fps, n_frames=n, width=w, height=h,
        overall=overall(results), results=results, stride=stride, counts=counts, overlay=overlay,
        latency_s=round(time.time() - t0, 1), models={"segmentation": seg.name, "reasoning": vis.name},
    )
