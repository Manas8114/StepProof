"""SAM 3.1 on Meta Model API: POST /v1/responses (streaming), model 'sam-3.1'.
Concept prompt = ONE short noun phrase per request. Zero matches = empty output (valid, not an error).
Raw wire text is cached on disk so demos are reproducible and credits are not burned twice."""
from __future__ import annotations
import base64, hashlib, threading, time
from pathlib import Path
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from .. import config as cfg
from ..schemas import Detection
from ..wire import parse_wire

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _record_sam(kind: str, latency_s: float, frames_returned: int, cached: bool,
                path: Path | None = None) -> None:
    """Record a SAM call into the active meter (no-op unless one is set). Billed frames are
    estimated from the uploaded media - Meta bills per frame (50-frame minimum): a video
    uploads every native-fps frame, so billed_frames = the clip's frame count (the exact
    quantity our preprocessors reduce). Cached calls bill nothing."""
    if cached or path is None:
        billed = 0
    else:
        try:
            from ..video import probe
            billed = max(int(probe(path)[1]), 50) if kind == "video" else 1
        except Exception:
            billed = 0
    from .. import usage
    if usage.active() is not None:
        usage.active().record(cfg.SAM_MODEL, f"sam_{kind}", latency_s,
                              frames_returned=frames_returned, billed_frames=billed, cached=cached)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()[:20]


class SamApi:
    name = "sam-3.1 (Meta Model API)"

    def __init__(self) -> None:
        self.client = OpenAI(base_url=cfg.META_BASE_URL, api_key=cfg.MODEL_API_KEY or "missing", timeout=900, max_retries=0)
        self._files: dict[str, str] = {}
        self._lock = threading.Lock()
        (cfg.CACHE / "sam").mkdir(parents=True, exist_ok=True)

    def _media(self, path: Path, kind: str) -> dict:
        if kind == "image":
            b64 = base64.b64encode(path.read_bytes()).decode()
            return {"type": "input_image", "image_url": f"data:{_MIME.get(path.suffix.lower(), 'image/jpeg')};base64,{b64}"}
        h = _file_hash(path)
        with self._lock:  # upload once, reuse for every concept
            if h not in self._files:
                with open(path, "rb") as f:
                    self._files[h] = self.client.files.create(purpose="user_data", file=f).id
            return {"type": "input_video", "file_id": self._files[h]}

    def _stream(self, concept: str, media: dict) -> str:
        last: Exception | None = None
        for attempt in range(4):
            try:
                text = ""
                with self.client.responses.stream(
                    model=cfg.SAM_MODEL,
                    input=[{"type": "message", "role": "user", "content": [{"type": "input_text", "text": concept}, media]}],
                    metadata={"include_confidence": "true", "mask_encoding": "one_bit"},
                ) as stream:
                    for ev in stream:
                        if ev.type == "response.output_text.delta":
                            text += ev.delta
                return text
            except (RateLimitError, APIConnectionError, APITimeoutError) as e:
                last = e
            except APIStatusError as e:
                if e.status_code < 500:
                    raise  # 400/401/403/404 are permanent; do not retry
                last = e
            time.sleep(2 ** attempt)
        raise RuntimeError(f"SAM request failed after retries: {last}")

    def _segment(self, path: Path, concept: str, kind: str) -> list[Detection]:
        key = f"{_file_hash(path)}-{kind}-{hashlib.sha1(concept.encode()).hexdigest()[:10]}"
        cp = cfg.CACHE / "sam" / f"{key}.txt"
        if cfg.USE_CACHE and cp.exists():
            dets = parse_wire(cp.read_text())
            _record_sam(kind, 0.0, len(dets), cached=True, path=path)
            return dets
        if cfg.PROVIDER_MODE == "replay":
            raise FileNotFoundError(f"replay mode: no cached SAM result for {concept!r} ({key})")
        t0 = time.time()
        text = self._stream(concept, self._media(path, kind))
        cp.write_text(text)
        dets = parse_wire(text)
        _record_sam(kind, time.time() - t0, len(dets), cached=False, path=path)
        return dets

    def segment_video(self, path: Path, concept: str) -> list[Detection]:
        return self._segment(path, concept, "video")

    def segment_image(self, path: Path, concept: str) -> list[Detection]:
        return self._segment(path, concept, "image")
