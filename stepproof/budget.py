"""Pre-flight cost estimation and budget breaker tripwire (guardrail in front of the meter).
Models perceive, code decides: a pathological procedure or runaway agent aborts
BEFORE issuing any billing-triggering API calls (e.g. SAM 50-frame minimums).
Pre-flight estimates and live usage are continuously checked against configurable caps.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional, Any

from .events import BUS
from .usage import active as get_active_meter, UsageMeter


class BudgetBreachError(RuntimeError):
    """Raised when an operation would breach the configured cost cap."""
    pass


@dataclass
class CostEstimate:
    estimated_sam_frames: int
    estimated_tokens: int
    estimated_latency_s: float
    model_calls: int
    vision_calls: int
    formula_explanation: str

    def to_dict(self) -> dict:
        return {
            "estimated_sam_frames": self.estimated_sam_frames,
            "estimated_tokens": self.estimated_tokens,
            "estimated_latency_s": round(self.estimated_latency_s, 2),
            "model_calls": self.model_calls,
            "vision_calls": self.vision_calls,
            "formula_explanation": self.formula_explanation,
        }


@dataclass
class BudgetConfig:
    cap_frames_per_run: int = 300       # Meta bills 50 frames min per video call (supports up to 6 self-heals per run)
    cap_tokens_per_run: int = 40000
    cap_frames_session: int = 1500
    cap_tokens_session: int = 150000
    unlimited: bool = False

    @classmethod
    def from_env(cls) -> "BudgetConfig":
        unlim_raw = os.getenv("STEPPROOF_COST_UNLIMITED", "0").lower()
        unlim = unlim_raw in ("1", "true", "yes", "unlimited")

        def _int_env(k: str, default: int) -> int:
            v = os.getenv(k, "").strip().lower()
            if not v:
                return default
            if v == "unlimited":
                return -1
            try:
                return int(v)
            except ValueError:
                return default

        cap_f_run = _int_env("STEPPROOF_COST_CAP_FRAMES", 300)
        cap_t_run = _int_env("STEPPROOF_COST_CAP_TOKENS", 40000)
        cap_f_sess = _int_env("STEPPROOF_COST_CAP_FRAMES_SESSION", 1500)
        cap_t_sess = _int_env("STEPPROOF_COST_CAP_TOKENS_SESSION", 150000)

        if cap_f_run <= 0 and cap_t_run <= 0:
            unlim = True

        return cls(
            cap_frames_per_run=cap_f_run,
            cap_tokens_per_run=cap_t_run,
            cap_frames_session=cap_f_sess,
            cap_tokens_session=cap_t_sess,
            unlimited=unlim,
        )


def estimate_procedure_cost(proc: Any) -> CostEstimate:
    """Pre-flight estimator for a Procedure.
    - Deterministic steps with locators: 0 frames, 0 tokens (local Playwright).
    - Steps without locators: unconditionally require 1 vision call (SAM 50 billed frames or Muse ~850 tokens).
    - Success checks (text/url/dom): 0 frames, 0 tokens.
    """
    steps = getattr(proc, "steps", []) or []
    vision_steps = sum(1 for s in steps if not getattr(s, "locators", None))

    # Meta SAM billing rule: 50 billed frames minimum per call
    est_frames = vision_steps * 50
    # Muse Spark tool-calling: ~850 tokens per multimodal decision
    est_tokens = vision_steps * 850
    est_latency = len(steps) * 0.15 + vision_steps * 1.8

    explanation = (
        f"{len(steps)} steps total ({vision_steps} require vision fallback). "
        f"Deterministic DOM steps cost 0. Vision steps estimate 50 billed frames (SAM min) or ~850 tokens (Muse)."
    )
    return CostEstimate(
        estimated_sam_frames=est_frames,
        estimated_tokens=est_tokens,
        estimated_latency_s=est_latency,
        model_calls=vision_steps,
        vision_calls=vision_steps,
        formula_explanation=explanation,
    )


def estimate_agent_goal_cost(max_steps: int = 15) -> CostEstimate:
    """Pre-flight estimator for a goal-only AgentLoop run."""
    # Each turn consumes ~950 tokens (system + obs elements + history + decision)
    est_tokens = max_steps * 950
    # Assume 1 potential vision grounding recovery
    est_frames = 50
    est_latency = max_steps * 2.2
    explanation = f"Goal-only agent up to {max_steps} steps: ~950 tokens/turn + potential 1x 50-frame SAM/vision call."
    return CostEstimate(
        estimated_sam_frames=est_frames,
        estimated_tokens=est_tokens,
        estimated_latency_s=est_latency,
        model_calls=max_steps,
        vision_calls=1,
        formula_explanation=explanation,
    )


class BudgetTripwire:
    """Guardrail enforcing cost caps before and during execution."""

    def __init__(self, config: Optional[BudgetConfig] = None) -> None:
        self.config = config or BudgetConfig.from_env()

    def check_preflight(self, estimate: CostEstimate,
                        session_meter: Optional[UsageMeter] = None) -> tuple[bool, Optional[str]]:
        """Verify that pre-flight estimate does not exceed run or session caps."""
        if self.config.unlimited:
            return True, None

        if self.config.cap_frames_per_run > 0 and estimate.estimated_sam_frames > self.config.cap_frames_per_run:
            err = (f"Pre-flight tripwire: estimated {estimate.estimated_sam_frames} SAM frames exceeds "
                   f"per-run cap of {self.config.cap_frames_per_run}")
            BUS.publish("budget_breach", {"phase": "preflight", "type": "frames", "detail": err})
            return False, err

        if self.config.cap_tokens_per_run > 0 and estimate.estimated_tokens > self.config.cap_tokens_per_run:
            err = (f"Pre-flight tripwire: estimated {estimate.estimated_tokens} tokens exceeds "
                   f"per-run cap of {self.config.cap_tokens_per_run}")
            BUS.publish("budget_breach", {"phase": "preflight", "type": "tokens", "detail": err})
            return False, err

        # Check session cumulative if meter available
        meter = session_meter or get_active_meter()
        if meter:
            cum = meter.cumulative()
            if (self.config.cap_frames_session > 0 and
                    cum["billed_frames"] + estimate.estimated_sam_frames > self.config.cap_frames_session):
                err = (f"Pre-flight tripwire: session frames ({cum['billed_frames']} + {estimate.estimated_sam_frames}) "
                       f"would exceed session cap of {self.config.cap_frames_session}")
                BUS.publish("budget_breach", {"phase": "preflight", "type": "session_frames", "detail": err})
                return False, err

            if (self.config.cap_tokens_session > 0 and
                    cum["total_tokens"] + estimate.estimated_tokens > self.config.cap_tokens_session):
                err = (f"Pre-flight tripwire: session tokens ({cum['total_tokens']} + {estimate.estimated_tokens}) "
                       f"would exceed session cap of {self.config.cap_tokens_session}")
                BUS.publish("budget_breach", {"phase": "preflight", "type": "session_tokens", "detail": err})
                return False, err

        return True, None

    def check_before_vision_call(self, current_run_frames: int = 0,
                                 expected_frames: int = 50) -> tuple[bool, Optional[str]]:
        """Checked immediately before dispatching a SAM / vision API call."""
        if self.config.unlimited:
            return True, None

        if self.config.cap_frames_per_run > 0 and (current_run_frames + expected_frames) > self.config.cap_frames_per_run:
            err = (f"Tripwire abort before vision call: {current_run_frames} + {expected_frames} billed frames "
                   f"exceeds per-run cap {self.config.cap_frames_per_run}")
            BUS.publish("budget_breach", {"phase": "before_vision", "type": "frames", "detail": err})
            return False, err

        meter = get_active_meter()
        if meter and self.config.cap_frames_session > 0:
            cum_frames = meter.cumulative()["billed_frames"]
            if (cum_frames + expected_frames) > self.config.cap_frames_session:
                err = (f"Tripwire abort before vision call: cumulative session {cum_frames} + {expected_frames} "
                       f"exceeds session cap {self.config.cap_frames_session}")
                BUS.publish("budget_breach", {"phase": "before_vision", "type": "session_frames", "detail": err})
                return False, err

        return True, None

    def health_disclosure(self) -> dict:
        """Surfaced in /api/v2/health."""
        if self.config.unlimited:
            return {
                "tripwire_status": "unlimited (warning: unguarded)",
                "caps": "unlimited",
                "disclosure": "Budget breaker is disabled via STEPPROOF_COST_UNLIMITED=1 or non-positive caps."
            }
        return {
            "tripwire_status": "active",
            "caps": {
                "frames_per_run": self.config.cap_frames_per_run,
                "tokens_per_run": self.config.cap_tokens_per_run,
                "frames_session": self.config.cap_frames_session,
                "tokens_session": self.config.cap_tokens_session,
            },
            "disclosure": (f"Tripwire enforces max {self.config.cap_frames_per_run} SAM frames & "
                           f"{self.config.cap_tokens_per_run} tokens per run before issuing calls.")
        }


_GLOBAL_TRIPWIRE: Optional[BudgetTripwire] = None


def get_tripwire() -> BudgetTripwire:
    global _GLOBAL_TRIPWIRE
    if _GLOBAL_TRIPWIRE is None:
        _GLOBAL_TRIPWIRE = BudgetTripwire()
    return _GLOBAL_TRIPWIRE

