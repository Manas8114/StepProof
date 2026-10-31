"""Deterministic verification engine. Pure functions: models perceive, this code decides pass/fail/review."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional
from .schemas import Detection, ProcedureSpec, StateCheck, Step, StepResult, Verdict

_RANK = {"pass": 0, "review": 1, "fail": 2}


@dataclass
class Params:
    min_conf: float = 0.5      # detections below this are ignored
    review_conf: float = 0.7   # satisfied-but-below this -> human review
    stable_frames: int = 5     # a condition must hold this many consecutive frames
    tail_frac: float = 0.1     # "still true at the end" window
    state_conf: float = 0.7


def count_series(dets: list[Detection], n_frames: int, min_conf: float):
    counts = [0] * n_frames
    confs: dict[int, list[float]] = {}
    seen: dict[int, set[int]] = {}
    for d in dets:
        if d.frame >= n_frames or (d.conf is not None and d.conf < min_conf):
            continue
        ids = seen.setdefault(d.frame, set())
        if d.obj_id in ids:
            continue
        ids.add(d.obj_id)
        counts[d.frame] += 1
        if d.conf is not None:
            confs.setdefault(d.frame, []).append(d.conf)
    return counts, confs


def first_stable(ok: list[bool], k: int) -> Optional[int]:
    run = 0
    for i, v in enumerate(ok):
        run = run + 1 if v else 0
        if run >= k:
            return i - k + 1
    return None


def _bump(r: StepResult, v: Verdict) -> None:
    if _RANK[v] > _RANK[r.verdict]:
        r.verdict = v


def overall(results: list[StepResult]) -> Verdict:
    return max((r.verdict for r in results), key=lambda v: _RANK[v], default="pass")


def evaluate(
    spec: ProcedureSpec,
    dets_by_concept: dict[str, list[Detection]],
    fps: float,
    n_frames: int,
    state_fn: Optional[Callable[[Step, int], Optional[StateCheck]]] = None,
    params: Params = Params(),
) -> list[StepResult]:
    k = max(1, min(params.stable_frames, n_frames))
    done: dict[str, StepResult] = {}
    out: list[StepResult] = []
    for step in spec.steps:
        counts, confs = count_series(dets_by_concept.get(step.concept, []), n_frames, params.min_conf)
        hi = step.max_count if step.max_count is not None else 10**9
        ok = [step.min_count <= c <= hi for c in counts]
        r = StepResult(step_id=step.id, verdict="pass")
        first = first_stable(ok, k)
        rng = f"[{step.min_count}, {step.max_count if step.max_count is not None else 'inf'}]"
        if not any(ok):
            r.verdict = "fail"
            r.reasons.append(f"'{step.concept}' never seen with count in {rng} (max seen: {max(counts, default=0)}).")
        elif first is None:
            r.verdict = "review"
            r.reasons.append(f"Detection of '{step.concept}' flickers; never stable for {k} frames.")
        else:
            r.first_frame, r.evidence_frame = first, first
            r.first_time_s = round(first / fps, 2) if fps else None
            fc = confs.get(first, [])
            r.min_conf = min(fc) if fc else None
            r.count_at_end = counts[-1]
            tail = ok[-max(k, int(n_frames * params.tail_frac)):]
            if step.persist and sum(tail) < len(tail) / 2:
                r.verdict = "fail"
                r.reasons.append(f"Not satisfied at the end of the video (count at end: {counts[-1]}).")
            if r.min_conf is not None and r.min_conf < params.review_conf:
                _bump(r, "review")
                r.reasons.append(f"Low detector confidence ({r.min_conf:.2f}).")
            for dep in step.after:
                d = done.get(dep)
                if d is None or d.first_frame is None:
                    _bump(r, "review")
                    r.reasons.append(f"Prerequisite {dep} never satisfied; order cannot be verified.")
                elif first < d.first_frame:
                    _bump(r, "fail")
                    r.reasons.append(f"Occurred before prerequisite {dep} ({r.first_time_s}s < {d.first_time_s}s).")
                elif first == d.first_frame:
                    _bump(r, "review")
                    r.reasons.append(f"Simultaneous with prerequisite {dep}; order cannot be proven.")
            if step.state_question and state_fn and r.verdict != "fail":
                last_ok = max(i for i, v in enumerate(ok) if v)
                sc = state_fn(step, last_ok)
                if sc is not None:
                    r.state = sc
                    if sc.answer == "no":
                        _bump(r, "fail")
                        r.reasons.append(f"State check failed: {sc.rationale}")
                    elif sc.answer == "uncertain" or sc.confidence < params.state_conf:
                        _bump(r, "review")
                        r.reasons.append(f"State check uncertain: {sc.rationale}")
        done[step.id] = r
        out.append(r)
    return out
