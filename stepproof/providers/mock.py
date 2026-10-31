"""Deterministic offline providers for tests and UI development. Never used to produce reported metrics."""
from __future__ import annotations
from pathlib import Path
from ..schemas import Detection, ProcedureSpec, StateCheck


class MockSegmentation:
    name = "mock-segmentation"

    def __init__(self, tracks: dict[str, list[Detection]]) -> None:
        self.tracks = tracks

    def segment_video(self, path: Path, concept: str) -> list[Detection]:
        return self.tracks.get(concept, [])

    segment_image = segment_video


class MockVision:
    name = "mock-vision"

    def __init__(self, spec: ProcedureSpec | None = None, answers: dict[str, StateCheck] | None = None) -> None:
        self.spec, self.answers = spec, answers or {}

    def compile_procedure(self, text: str) -> ProcedureSpec:
        assert self.spec is not None
        return self.spec

    def check_state(self, image_path: Path, question: str) -> StateCheck:
        return self.answers.get(question, StateCheck(answer="yes", confidence=0.95, rationale="mock"))

    def baseline_verdicts(self, spec: ProcedureSpec, frame_paths: list[Path]) -> dict[str, str]:
        return {s.id: "pass" for s in spec.steps}
