"""Vision self-heal: when every recorded DOM locator for a step has failed, re-locate the
target element visually.

Order (per the v2 master prompt: try Muse vision grounding first, SAM as fallback):
  1. `MuseVisionHealer` - Muse Spark sees the (password-masked) screenshot and returns the
     target element's bounding box in image pixels; click its centre.
  2. `SamVisionHealer`  - SAM 3.1 open-vocabulary segmentation on the same screenshot with a
     one-noun-phrase concept; click the top box.

Healers return `{"x", "y"}` (click_box args for execute_action) or None. No DOM access,
no credentials - only what is visible on the screen.
"""
from __future__ import annotations
import json, time
from pathlib import Path
from typing import Any
from .. import config as cfg

LOCATE_TOOL = {"type": "function", "name": "locate_element",
               "description": "Locate a visible UI element in the screenshot.",
               "parameters": {"type": "object", "properties": {
                   "x": {"type": "integer", "description": "left edge, pixels in the screenshot"},
                   "y": {"type": "integer"}, "w": {"type": "integer"}, "h": {"type": "integer"},
                   "confidence": {"type": "number", "description": "0..1 certainty it is the right element"}},
                   "required": ["x", "y", "w", "h", "confidence"]}}


class MuseVisionHealer:
    """Muse Spark grounding: screenshot + target description -> element box (live model)."""
    name = "muse-spark-1.3 vision grounding"

    def __init__(self, min_confidence: float = 0.6) -> None:
        from openai import OpenAI
        self.client = OpenAI(base_url=cfg.META_BASE_URL, api_key=cfg.MODEL_API_KEY or "missing",
                             timeout=90, max_retries=0)
        self.min_confidence = min_confidence
        # model-404 fallback disclosure (AGENT_PROMPT rule 5): which grounding model
        # actually answered + whether we substituted. Surfaced in /api/v2/health.
        self.active_model = cfg.VISION_MODEL
        self.fell_back = False

    def heal(self, screenshot: str, target: Any) -> dict | None:
        """screenshot = data URL (masked). target = Step or short description of the element to find."""
        if hasattr(target, "description") and target.description:
            target_str = target.description
        elif hasattr(target, "vision_concept") and target.vision_concept:
            target_str = target.vision_concept
        else:
            target_str = str(target)
        msgs = [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text":
                "You see a screenshot of a web app. Locate the element described below. "
                "Return its bounding box in screenshot pixel coordinates (top-left origin). "
                "If it is not visible, set confidence to 0.\nTARGET: " + target_str},
            {"type": "input_image", "image_url": screenshot},
        ]}]
        from ..model_fallback import responses_with_fallback
        r, model_used, fell_back = responses_with_fallback(self.client, cfg.VISION_MODEL,
                                                            input=msgs, tools=[LOCATE_TOOL],
                                                            tool_choice="auto")
        self.active_model, self.fell_back = model_used, self.fell_back or fell_back
        for item in r.output:
            if getattr(item, "type", "") == "function_call" and item.name == "locate_element":
                a = json.loads(item.arguments) if isinstance(item.arguments, str) else dict(item.arguments or {})
                w, h = int(a.get("w", 0)), int(a.get("h", 0))
                conf = float(a.get("confidence", 0) or 0)
                if conf <= 0 or w <= 0 or h <= 0:
                    continue
                if conf >= self.min_confidence:
                    cx = int(a.get("x", 0)) + w // 2
                    cy = int(a.get("y", 0)) + h // 2
                    return {"x": cx, "y": cy, "grounded_by": "muse", "box": a, "conf": conf}



        return None


class SamVisionHealer:
    """SAM 3.1 open-vocabulary fallback: segment the screenshot by a one-noun-phrase concept."""
    name = "sam-3.1 visual grounding"

    def __init__(self, concept_map: dict | None = None) -> None:
        from ..providers.sam_api import SamApi
        self.sam = SamApi()
        # concept_map: {"target description": "one noun phrase"} - SAM needs a short noun phrase
        self.concept_map = concept_map or {}
        self._tmp = cfg.DATA_DIR / "vision_heal"
        self._tmp.mkdir(parents=True, exist_ok=True)

    def heal(self, screenshot: str, target: Any) -> dict | None:
        """screenshot = data URL (masked). target = Step or noun phrase / description."""
        if hasattr(target, "vision_concept") and target.vision_concept:
            concept = target.vision_concept
        elif hasattr(target, "description") and target.description:
            concept = self.concept_map.get(target.description, target.description)
        else:
            concept = self.concept_map.get(str(target), str(target))
        import base64
        m = screenshot.split(",", 1)
        if len(m) != 2:
            return None
        p = self._tmp / f"{int(time.time()*1000)}.jpg"
        p.write_bytes(base64.b64decode(m[1]))
        dets = self.sam.segment_image(p, concept)
        if not dets:
            return None
        best = max(dets, key=lambda d: (d.conf or 0))
        x1, y1, x2, y2 = best.box
        out = {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2, "grounded_by": "sam",
               "conf": best.conf, "concept": concept, "box": {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}}
        ev_path = self._render_mask_overlay(p, best, concept)
        if ev_path:
            out["evidence_path"] = str(ev_path)
            out["mask_path"] = str(ev_path)
        return out

    def _render_mask_overlay(self, image_path: Path, det, concept: str) -> Path | None:
        """Decode SAM one_bit mask with meta_sam_parser and composite onto the evidence
        screenshot in data/evidence/. Box outline is fallback when decode fails."""
        try:
            from PIL import Image, ImageDraw
            import numpy as np
            import re
            img = Image.open(image_path).convert("RGBA")
            iw, ih = img.size
            x1, y1, x2, y2 = det.box
            mask_applied = False
            if getattr(det, "mask", None):
                try:
                    from meta_sam_parser import SegmentationMask, decode_mask_to_raster
                    m = re.search(r"data=(\d+),(\d+),(.*)", det.mask)
                    if m:
                        mh, mw, payload = int(m.group(1)), int(m.group(2)), m.group(3)
                        sm = SegmentationMask(encoding="one_bit", payload=payload, width=mw, height=mh)
                        raster = decode_mask_to_raster(sm)
                        mask_arr = np.frombuffer(raster, dtype=np.uint8).reshape((mh, mw))
                        overlay = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
                        color_mask = np.zeros((mh, mw, 4), dtype=np.uint8)
                        color_mask[mask_arr == 1] = [59, 130, 246, 120]  # translucent blue
                        mask_img = Image.fromarray(color_mask, "RGBA")
                        overlay.paste(mask_img, (x1, y1), mask_img)
                        img = Image.alpha_composite(img, overlay)
                        mask_applied = True
                except Exception:
                    mask_applied = False
            rgb_img = img.convert("RGB")
            draw = ImageDraw.Draw(rgb_img)
            draw.rectangle([x1, y1, x2, y2], outline=(37, 99, 235), width=2)
            ev_dir = cfg.EVIDENCE
            ev_dir.mkdir(parents=True, exist_ok=True)
            out_path = ev_dir / f"sam_mask_{int(time.time()*1000)}.jpg"
            rgb_img.save(out_path, quality=85)
            return out_path
        except Exception:
            return None


def chain(ms, sam, target: Any, screenshot: str):
    """Muse vision grounding first; SAM 3.1 open-vocab fallback; None when neither grounds it.
    Returns a click_box arg dict for `execute_action`."""
    try:
        hit = ms.heal(screenshot, target)
        if hit:
            return hit
    except Exception:
        pass  # Muse unreachable / failed -> fall through to SAM
    if sam is not None:
        try:
            return sam.heal(screenshot, target)
        except Exception:
            pass
    return None


def make_selfheal(ms, sam, browser):
    """Build the `vision_selfheal(target) -> arg|None` hook the executor calls; it grabs the
    current (password-masked) screenshot from the live browser, tries Muse then SAM."""
    def vision_selfheal(target: Any):
        shot = browser.take_screenshot()
        return chain(ms, sam, target, shot)
    return vision_selfheal
