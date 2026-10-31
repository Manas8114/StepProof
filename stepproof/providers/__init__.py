from __future__ import annotations
import os


def get_providers():
    """Real API providers by default. STEPPROOF_PROVIDER=mock switches to the offline
    cache-serving providers (seeded by scripts.make_dataset) — for UI work and offline
    eval runs only; never for reported metrics."""
    if os.environ.get("STEPPROOF_PROVIDER") == "mock":
        from .mock import MockSam, MockMuse
        return MockSam(), MockMuse()
    from .muse import MuseSpark
    from .sam_api import SamApi
    return SamApi(), MuseSpark()
