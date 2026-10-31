"""Offline mock providers for tests, UI development and the synthetic dataset.

``MockSam`` / ``MockMuse`` read per-clip "sidecar" JSON files (written by
``scripts/make_dataset.py``) that hold the ground-truth detections, state answers
and baseline verdicts. They let the pipeline, API, UI and eval harness run **fully
offline and deterministically**, with no network and no real model calls.

.. warning:: Everything these providers return is *synthetic*. They must **never**
   produce reported metrics. Activate with ``STEPPROOF_PROVIDER=mock``.
"""
from __future__ import annotations
import json, re
from pathlib import Path
from ..schemas import Detection, ProcedureSpec, StateCheck


def _sidecar(path: Path) -> dict:
    """Locate the sidecar JSON next to a clip or a sampled frame.

    A frame is named ``<video_stem>_<i>.jpg`` sitting in the clip's directory, so
    we strip a trailing ``_<int>`` to recover the clip stem, then read
    ``<stem>.dets.json``. A bare clip path reads its own sidecar directly.
    """
    stem = re.sub(r"_\d+$", "", path.stem)
    sc = path.parent / f"{stem}.dets.json"
    if not sc.exists():
        raise FileNotFoundError(f"offline mock: no dataset sidecar {sc.name} for {path.name}")
    return json.loads(sc.read_text())


class MockSam:
    """Offline SegmentationProvider: detections come from the clip sidecar."""
    name = "mock-sam (synthetic, offline)"

    def segment_video(self, path: Path, concept: str) -> list[Detection]:
        return self._dets(path, concept)

    def segment_image(self, path: Path, concept: str) -> list[Detection]:
        return self._dets(path, concept)

    @staticmethod
    def _dets(path: Path, concept: str) -> list[Detection]:
        spec = _sidecar(path).get("concepts", {}).get(concept)
        if not spec:
            return []
        box = spec.get("box", (0, 0, 40, 30))
        conf = spec.get("conf", 0.9)
        objs = spec.get("obj_ids", [spec.get("obj_id", 0)])
        out = []
        for f in spec.get("present_frames", []):
            for o in objs:  # one detection per tracked object id per frame
                out.append(Detection(frame=int(f), obj_id=o,
                                     box=(int(box[0]), int(box[1]), int(box[2]), int(box[3])), conf=conf))
        return out


class MockMuse:
    """Offline VisionProvider: state answers and baseline verdicts from the clip sidecar;
    procedure compilation from an explicit local table (text -> ProcedureSpec dict).

    Deterministic and stateless — no mutable class state, safe to share.
    """
    name = "mock-muse (synthetic, offline)"

    def __init__(self, compile_table: dict[str, dict] | None = None,
                 state_table: dict[str, dict] | None = None) -> None:
        self.compile_table = compile_table or {}
        self.state_table = state_table or {}

    def compile_procedure(self, text: str) -> ProcedureSpec:
        if text in self.compile_table:
            return ProcedureSpec.model_validate(self.compile_table[text])
        raise LookupError(f"offline mock: no compiled spec for {text!r}; add it to MockMuse.compile_table")

    def check_state(self, image_path: Path, question: str) -> StateCheck:
        if question in self.state_table:
            v = self.state_table[question]
            return StateCheck(answer=v["answer"], confidence=v.get("confidence", 0.9),
                              rationale=v.get("rationale", "synthetic (offline)"))
        return StateCheck(answer="yes", confidence=0.9, rationale="synthetic default (offline)")

    def baseline_verdicts(self, spec: ProcedureSpec, frame_paths: list[Path]) -> dict[str, str]:
        got = _sidecar(frame_paths[0]).get("baseline", {})
        return {s.id: ("review" if got.get(s.id) == "uncertain" else got.get(s.id, "pass")) for s in spec.steps}
