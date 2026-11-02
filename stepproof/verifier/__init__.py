"""Standalone independent verifier: zero-server, zero-API proof validation.
Recomputes SHA-256 manifests, validates hash chains, reverifies evidence screenshots,
and provides a thin adapter for v1 video verification.
"""
from .verify import ProofVerdict, verify_bundle
from .v1_adapter import verify_v1_clip

