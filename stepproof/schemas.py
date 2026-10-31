from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field

Verdict = Literal["pass", "fail", "review"]


class Step(BaseModel):
    id: str
    description: str
    concept: str = Field(description="Short concrete noun phrase naming ONE visible object type, e.g. 'red connector'")
    min_count: int = 1
    max_count: Optional[int] = None
    after: list[str] = Field(default_factory=list, description="ids of steps that must be satisfied earlier")
    state_question: Optional[str] = Field(default=None, description="Yes/no question about a visible state, e.g. 'Is the lid closed?'")
    persist: bool = True


class ProcedureSpec(BaseModel):
    name: str
    steps: list[Step]


class Detection(BaseModel):
    frame: int
    obj_id: int
    box: tuple[int, int, int, int]
    conf: Optional[float] = None
    w: int = 0
    h: int = 0
    mask: Optional[str] = None  # raw wire payload; decoded lazily (see AGENT_PROMPT P1)


class StateCheck(BaseModel):
    answer: Literal["yes", "no", "uncertain"]
    confidence: float
    rationale: str


class StepResult(BaseModel):
    step_id: str
    verdict: Verdict
    reasons: list[str] = Field(default_factory=list)
    first_frame: Optional[int] = None
    first_time_s: Optional[float] = None
    evidence_frame: Optional[int] = None
    evidence_image: Optional[str] = None
    count_at_end: Optional[int] = None
    min_conf: Optional[float] = None
    state: Optional[StateCheck] = None
    state_frame: Optional[int] = None
    state_image: Optional[str] = None


class Report(BaseModel):
    inspection_id: str
    procedure: ProcedureSpec
    video: str
    fps: float
    n_frames: int
    width: int
    height: int
    overall: Verdict
    results: list[StepResult]
    stride: int
    counts: dict[str, list[int]]
    overlay: dict[str, dict[int, list[list[int]]]]
    latency_s: float
    models: dict[str, str]
    reviews: list[dict] = Field(default_factory=list)
