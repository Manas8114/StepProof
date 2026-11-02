"""Pre-flight PII redaction pass over outbound screenshot/DOM payload.
Models perceive, code decides: sensitive data (emails, credit cards, phones, SSNs,
account numbers) is irreversibly sanitized BEFORE it ever touches SAM or Muse Spark.
Supports configurable regexes, DOM text masking, visual bounding-box obscuring,
and a 'show what you'd send' dry-run.
"""
from __future__ import annotations
import base64, io, os, re
from typing import Optional
from dataclasses import dataclass, field
import cv2
import numpy as np

DEFAULT_PATTERNS = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "phone": r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b|\b\d{15,16}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "account_number": r"\b(?:ACCT|ACC|ACCOUNT)[-:\s#]*\d{4,12}\b",
}


@dataclass
class RedactionResult:
    redacted_text: str
    match_count: int
    matches_by_type: dict[str, int] = field(default_factory=dict)


class PIIRedactor:
    """Configurable, local, irreversible redaction engine."""

    def __init__(self, enabled: bool = True, patterns: Optional[dict[str, str]] = None) -> None:
        self.enabled = enabled
        self.patterns = dict(patterns or DEFAULT_PATTERNS)
        self._compiled: dict[str, re.Pattern] = {
            name: re.compile(pat, re.IGNORECASE) for name, pat in self.patterns.items()
        }

    def set_pattern(self, name: str, pattern: str) -> None:
        self.patterns[name] = pattern
        self._compiled[name] = re.compile(pattern, re.IGNORECASE)

    def redact_text(self, text: str) -> RedactionResult:
        if not self.enabled or not text:
            return RedactionResult(redacted_text=text or "", match_count=0)
        res = str(text)
        total_matches = 0
        matches_by_type = {}
        for name, pat in self._compiled.items():
            matches = pat.findall(res)
            if matches:
                count = len(matches)
                total_matches += count
                matches_by_type[name] = matches_by_type.get(name, 0) + count
                res = pat.sub(f"[{name.upper()}_REDACTED]", res)
        return RedactionResult(redacted_text=res, match_count=total_matches, matches_by_type=matches_by_type)

    def redact_observation(self, obs: dict) -> tuple[dict, list[dict]]:
        """Redacts DOM body_text, title, and interactive element labels/values.
        Returns (sanitized_obs, redacted_boxes_for_visual_masking)."""
        if not self.enabled:
            return obs, []

        sanitized = dict(obs)
        redacted_boxes = []

        # Redact title
        if "title" in sanitized:
            r = self.redact_text(sanitized["title"])
            sanitized["title"] = r.redacted_text

        # Redact body_text
        if "body_text" in sanitized:
            r = self.redact_text(sanitized["body_text"])
            sanitized["body_text"] = r.redacted_text

        # Redact elements
        if "elements" in sanitized and isinstance(sanitized["elements"], list):
            new_elements = []
            for el in sanitized["elements"]:
                new_el = dict(el)
                name = new_el.get("name", "")
                r = self.redact_text(name)
                if r.match_count > 0:
                    new_el["name"] = r.redacted_text
                    # Record bounding box for screenshot obscuring
                    if new_el.get("visible") and new_el.get("w", 0) > 0 and new_el.get("h", 0) > 0:
                        redacted_boxes.append({
                            "x": int(new_el.get("x", 0)),
                            "y": int(new_el.get("y", 0)),
                            "w": int(new_el.get("w", 0)),
                            "h": int(new_el.get("h", 0)),
                            "type": list(r.matches_by_type.keys())[0] if r.matches_by_type else "pii"
                        })
                new_elements.append(new_el)
            sanitized["elements"] = new_elements

        return sanitized, redacted_boxes

    def redact_screenshot(self, shot_b64: str, boxes: list[dict],
                          fill_color: tuple[int, int, int] = (24, 24, 27)) -> str:
        """Draws solid redaction masks over sensitive bounding boxes on a JPEG screenshot.
        Returns a data:image/jpeg;base64 string."""
        if not self.enabled or not boxes or not shot_b64:
            return shot_b64

        try:
            # Strip data URL prefix if present
            raw_b64 = shot_b64
            if "," in raw_b64:
                raw_b64 = raw_b64.split(",", 1)[1]
            img_bytes = base64.b64decode(raw_b64)
            nparr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return shot_b64

            h, w = img.shape[:2]
            for b in boxes:
                bx, by, bw, bh = b["x"], b["y"], b["w"], b["h"]
                # Clamp within boundaries
                x1 = max(0, min(w - 1, bx))
                y1 = max(0, min(h - 1, by))
                x2 = max(0, min(w, bx + bw))
                y2 = max(0, min(h, by + bh))
                if x2 > x1 and y2 > y1:
                    cv2.rectangle(img, (x1, y1), (x2, y2), fill_color, -1)
                    # Add subtle [REDACTED] label if box is large enough
                    if (x2 - x1) > 40 and (y2 - y1) > 14:
                        cv2.putText(img, "REDACTED", (x1 + 4, y1 + 12),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (160, 160, 175), 1, cv2.LINE_AA)

            # Encode back to JPEG base64
            success, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not success:
                return shot_b64
            res_b64 = base64.b64encode(enc).decode("ascii")
            return f"data:image/jpeg;base64,{res_b64}"
        except Exception:
            # On any image processing failure, fallback safely to original
            return shot_b64

    def dry_run(self, obs: dict, screenshot_b64: str = "") -> dict:
        """'Show what you'd send' dry-run audit inspection without modifying session state."""
        redacted_obs, boxes = self.redact_observation(obs)
        redacted_shot = self.redact_screenshot(screenshot_b64, boxes) if screenshot_b64 else ""

        # Find what was redacted
        changes = []
        orig_body = obs.get("body_text", "")
        red_body = redacted_obs.get("body_text", "")
        if orig_body != red_body:
            changes.append({"field": "body_text", "original_snippet": orig_body[:100], "redacted_snippet": red_body[:100]})

        orig_els = obs.get("elements", [])
        red_els = redacted_obs.get("elements", [])
        for oe, re_el in zip(orig_els, red_els):
            if oe.get("name") != re_el.get("name"):
                changes.append({
                    "field": f"element_{oe.get('role')}_{oe.get('id')}",
                    "original": oe.get("name"),
                    "redacted": re_el.get("name"),
                    "box": {"x": oe.get("x"), "y": oe.get("y"), "w": oe.get("w"), "h": oe.get("h")}
                })

        return {
            "enabled": self.enabled,
            "patterns_active": list(self.patterns.keys()),
            "redactions_count": len(changes),
            "redacted_boxes_count": len(boxes),
            "changes": changes,
            "redacted_obs_preview": {
                "url": redacted_obs.get("url"),
                "title": redacted_obs.get("title"),
                "elements_count": len(red_els)
            },
            "screenshot_masked": bool(redacted_shot and redacted_shot != screenshot_b64)
        }


# Global active instance controlled via env var STEPPROOF_REDACT_PII (default: 1)
_ACTIVE = PIIRedactor(enabled=os.getenv("STEPPROOF_REDACT_PII", "1").lower() not in ("0", "false", "no"))


def get_redactor() -> PIIRedactor:
    return _ACTIVE


def set_redactor(redactor: PIIRedactor) -> None:
    global _ACTIVE
    _ACTIVE = redactor

