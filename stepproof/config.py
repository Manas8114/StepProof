from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def _e(name: str, default: str = "") -> str:
    return os.getenv(name, default)

DATA_DIR = Path(_e("STEPPROOF_DATA", "data")).resolve()
UPLOADS, EVIDENCE, CACHE = DATA_DIR / "uploads", DATA_DIR / "evidence", DATA_DIR / "cache"
for _d in (UPLOADS, EVIDENCE, CACHE):
    _d.mkdir(parents=True, exist_ok=True)

META_BASE_URL = _e("META_BASE_URL", "https://api.meta.ai/v1")
MODEL_API_KEY = _e("MODEL_API_KEY")
SAM_MODEL = _e("SAM_MODEL", "sam-3.1")

VISION_BASE_URL = _e("VISION_BASE_URL", META_BASE_URL)
VISION_API_KEY = _e("VISION_API_KEY", MODEL_API_KEY)
VISION_MODEL = _e("VISION_MODEL", "muse-spark-1.3")

PROVIDER_MODE = _e("PROVIDER_MODE", "live")  # live | replay
USE_CACHE = _e("STEPPROOF_CACHE", "1") == "1"
VISION_SELFHEAL = _e("STEPPROOF_VISION_SELFHEAL", "0") == "1"
