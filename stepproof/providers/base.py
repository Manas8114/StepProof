from __future__ import annotations
from pathlib import Path
from typing import Protocol
from ..schemas import Detection, ProcedureSpec, StateCheck


class SegmentationProvider(Protocol):
    name: str
    def segment_video(self, path: Path, concept: str) -> list[Detection]: ...
    def segment_image(self, path: Path, concept: str) -> list[Detection]: ...


class VisionProvider(Protocol):
    name: str
    def compile_procedure(self, text: str) -> ProcedureSpec: ...
    def check_state(self, image_path: Path, question: str) -> StateCheck: ...
    def baseline_verdicts(self, spec: ProcedureSpec, frame_paths: list[Path]) -> dict[str, str]: ...
