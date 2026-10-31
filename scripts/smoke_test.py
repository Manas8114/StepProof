"""Access validation (run FIRST). Usage: python -m scripts.smoke_test path/to/assembly.jpg [concept]
Checks: model catalog, Muse text->schema JSON, Muse image state check, SAM image segmentation + wire parsing."""
from __future__ import annotations
import sys
from pathlib import Path
from openai import OpenAI
from stepproof import config as cfg
from stepproof.providers.muse import MuseSpark
from stepproof.providers.sam_api import SamApi


def step(name, fn):
    try:
        out = fn()
        print(f"[ok]   {name}: {out}")
        return True
    except Exception as e:
        print(f"[FAIL] {name}: {type(e).__name__}: {str(e)[:300]}")
        return False


def main() -> int:
    img = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    concept = sys.argv[2] if len(sys.argv) > 2 else "screw"
    ok = []
    client = OpenAI(base_url=cfg.META_BASE_URL, api_key=cfg.MODEL_API_KEY or "missing")
    ok.append(step("models.list", lambda: [m.id for m in client.models.list().data][:20]))
    vis, sam = MuseSpark(), SamApi()
    ok.append(step("muse compile", lambda: vis.compile_procedure("Put the red connector on the board, then close the black cover.").model_dump()["steps"]))
    if img:
        ok.append(step("muse image", lambda: vis.check_state(img, "Is there at least one object visible?")))
        ok.append(step(f"sam image '{concept}'", lambda: f"{len(sam.segment_image(img, concept))} detection(s)"))
    else:
        print("[skip] image tests (pass an image path)")
    print("ALL OK" if all(ok) else "SOME CHECKS FAILED: fix access before building anything else")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
