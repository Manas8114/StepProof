"""Cloudflare Turnstile, hCaptcha, reCAPTCHA detection and automated/pluggable solving."""
from __future__ import annotations

from .detector import detect_challenge, ChallengeInfo
from .solver import (
    BaseCaptchaSolver,
    LocalTurnstileSolver,
    RemoteProviderSolver,
    CaptchaHandler,
    SolveResult
)

__all__ = [
    "detect_challenge",
    "ChallengeInfo",
    "BaseCaptchaSolver",
    "LocalTurnstileSolver",
    "RemoteProviderSolver",
    "CaptchaHandler",
    "SolveResult",
]

