from __future__ import annotations
import json, os
from .. import config as cfg


def get_providers():
    """Real API providers by default. ``STEPPROOF_PROVIDER=mock`` switches to the offline,
    deterministic dataset providers (``scripts.make_dataset``) — for UI work, offline demos
    and offline eval runs only. NEVER for reported metrics."""
    if os.environ.get("STEPPROOF_PROVIDER") == "mock":
        from .mock import MockSam, MockMuse
        cfg_path = cfg.DATA_DIR / "stepproof_mock.json"
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text())
            return MockSam(), MockMuse(compile_table=data.get("compile_table", {}),
                                       state_table=data.get("state_table", {}))
        return MockSam(), MockMuse()
    from .muse import MuseSpark
    from .sam_api import SamApi
    return SamApi(), MuseSpark()
