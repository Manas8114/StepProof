"""Voice companion. TTS is browser `speechSynthesis` (no dependency, verified path) - the
server only produces short spoken lines. STT prefers Meta's `muse-voice-transcribe-1.0`
file endpoint; if it is not reachable, the browser Web Speech API is used and disclosed.
Every spoken line also has a text equivalent (accessibility + noisy-room demos).
"""
from __future__ import annotations
import io, json, time
from dataclasses import dataclass
from typing import Optional
import httpx
from .. import config as cfg

MAX_SPOKEN_WORDS = 12  # keep spoken lines short


@dataclass
class SpokenLine:
    text: str          # the authoritative text equivalent
    spoken: str        # what TTS says (== text, trimmed to MAX_SPOKEN_WORDS)
    kind: str          # suggestion | question | handoff | status


def browser_speak(line: SpokenLine) -> str:
    """Return JS that makes the browser speak `line` via speechSynthesis (no server audio)."""
    text = line.spoken
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    return (f'if(window.speechSynthesis){{var u=new SpeechSynthesisUtterance("{safe}");'
            f'u.lang="en-US";u.rate=1.0;window.speechSynthesis.speak(u);}}')


def phrase(line_kind: str, message: str, context: dict | None = None) -> SpokenLine:
    """Turn a suggestion/question into a short spoken line + full text equivalent."""
    full = message.strip()
    words = full.split()
    spoken = " ".join(words[:MAX_SPOKEN_WORDS]) + ("..." if len(words) > MAX_SPOKEN_WORDS else "")
    return SpokenLine(text=full, spoken=spoken, kind=line_kind)


class SpeechToText:
    """Meta `muse-voice-transcribe-1.0` file transcribe. `available` is set after the first
    reachable call; when False, callers must fall back to browser Web Speech (disclosed)."""

    MODEL = "muse-voice-transcribe-1.0"
    URL = "https://api.meta.ai/v1/asr/transcribe"

    def __init__(self) -> None:
        self.available: bool | None = None
        self._client = httpx.Client(base_url=cfg.META_BASE_URL, timeout=30)

    def transcribe_wav(self, wav_bytes: bytes, sample_rate: int = 16000) -> Optional[str]:
        """POST a 16-bit mono WAV; return the transcript, or None (unreachable -> use browser STT)."""
        headers = {"Authorization": f"Bearer {cfg.MODEL_API_KEY}"}
        files = {"audio": ("audio.wav", io.BytesIO(wav_bytes), "audio/wav")}
        data = {"request": json.dumps({"model": self.MODEL, "audioEncoding": "WAV", "sampleRate": sample_rate})}
        try:
            r = self._client.post("/asr/transcribe", headers=headers, files=files, data=data)
            r.raise_for_status()
            self.available = True
            j = r.json()
            return j.get("transcript") or ""
        except Exception:
            self.available = False
            return None


class VoiceCompanion:
    """High-level: produce spoken lines for a run. TTS via browser_speak; STT via Meta or browser."""

    def __init__(self) -> None:
        self.stt = SpeechToText()
        self.lines: list[SpokenLine] = []

    def on_suggestion(self, sugg: dict) -> SpokenLine:
        l = phrase("suggestion", sugg.get("what", ""), {"risk": sugg.get("risk")})
        self.lines.append(l)
        return l

    def on_question(self, q: str, options: list[str]) -> SpokenLine:
        l = phrase("question", q + (" Options: " + ", ".join(options) if options else ""), {})
        self.lines.append(l)
        return l

    def on_handoff(self, reason: str) -> SpokenLine:
        l = phrase("handoff", f"Handing off: {reason}", {})
        self.lines.append(l)
        return l

    def transcribe(self, wav: bytes) -> tuple[str | None, str]:
        """Return (text, source). source is 'meta' or 'browser' (disclosed when browser)."""
        t = self.stt.transcribe_wav(wav)
        return (t, "meta") if t is not None else (None, "browser")
