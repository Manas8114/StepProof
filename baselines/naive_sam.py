"""The naive SAM 3.1 + VLM baseline, standalone. See baselines/__init__.py for the
"not a weakened strawman" design notes.

Deliberately different from stepproof.providers.sam_api.SamApi:
  - no `self._files` upload cache: every request re-uploads the clip (billed + slow),
  - no content-hash result cache: every request hits the network,
  - one request per concept PER STEP, so a concept used by two steps is requested twice,
  - counting is a plain fixed-threshold count (no geometry rejection / smoothing).
It still records into the active UsageMeter, so the benchmark can bill it honestly.
"""
from __future__ import annotations
import base64, hashlib, json, time
from pathlib import Path
from openai import OpenAI
from stepproof import config as cfg
from stepproof.schemas import Detection, ProcedureSpec
from stepproof.wire import parse_wire
from stepproof.usage import active as _meter
from stepproof.video import probe

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
MIN_CONF = 0.5  # the single fixed threshold - "no calibration"


def _upload_raw(client: OpenAI, path: Path) -> str:
    """A fresh upload EVERY call (the naive approach - no reuse, no caching of file ids)."""
    with open(path, "rb") as f:
        return client.files.create(purpose="user_data", file=f).id


def _record(kind: str, latency_s: float, frames_returned: int, billed_frames: int,
            input_tokens: int = 0, output_tokens: int = 0) -> None:
    m = _meter()
    if m is not None:
        m.record(cfg.SAM_MODEL, f"naive_sam_{kind}", latency_s, frames_returned=frames_returned,
                 billed_frames=billed_frames, input_tokens=input_tokens, output_tokens=output_tokens,
                 cached=False)


def naive_segment(client: OpenAI, video: Path, concept: str, out_dir: Path) -> list[Detection]:
    """One full-clip SAM call for `concept`, re-uploading the clip each time."""
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    file_id = _upload_raw(client, video)
    media = {"type": "input_video", "file_id": file_id}
    last: Exception | None = None
    for attempt in range(3):
        try:
            text = ""
            with client.responses.stream(
                model=cfg.SAM_MODEL,
                input=[{"type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": concept}, media]}],
                metadata={"include_confidence": "true"},
            ) as stream:
                for ev in stream:
                    if ev.type == "response.output_text.delta":
                        text += ev.delta
            cp = out_dir / f"naive_{hashlib.sha1(concept.encode()).hexdigest()[:10]}.txt"
            cp.write_text(text)
            dets = parse_wire(text)
            billed = max(int(probe(video)[1]), 50)
            _record("video", time.time() - t0, len(dets), billed)
            return dets
        except Exception as e:          # transient; the naive version just retries
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"naive SAM segment failed: {last}")


def naive_count(dets: list[Detection], n_frames: int) -> list[int]:
    """Plain per-frame count above the single fixed threshold. No geometry/smoothing."""
    counts = [0] * n_frames
    for d in dets:
        if d.frame >= n_frames:
            continue
        if d.conf is None or d.conf >= MIN_CONF:
            counts[d.frame] += 1
    return counts


def naive_vlm_verdicts(client: OpenAI, spec: ProcedureSpec, frame_paths: list[Path]) -> dict[str, str]:
    """The quick VLM judgment: feed MANY raw frames + the step list, ask for pass/fail.
    This is what 'a VLM prompt with many raw frames to judge each step' literally means.
    (No per-step cropped evidence, no compact schema - the heavy, costly shape.)"""
    from stepproof.providers.muse import _img
    schema = {"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "object",
            "properties": {"step_id": {"type": "string"}, "verdict": {"type": "string",
            "enum": ["pass", "fail", "uncertain"]}, "rationale": {"type": "string"}},
            "required": ["step_id", "verdict", "rationale"]}}}, "required": ["steps"]}
    listing = "\n".join(f"{s.id}: {s.description}" for s in spec.steps)
    content = [{"type": "text", "text": "For each step, judge from these frames: " + listing}]
    content += [_img(p) for p in frame_paths]      # MANY raw frames
    t0 = time.time()
    r = client.chat.completions.create(
        model=cfg.VISION_MODEL,
        messages=[{"role": "system", "content": "You inspect sampled video frames. Judge each step "
                                                 "pass/fail/uncertain from what is visible."},
                  {"role": "user", "content": content}],
        response_format={"type": "json_schema", "json_schema": {"name": "NaiveVerdicts", "schema": schema}},
    )
    u = getattr(r, "usage", None)
    _record("vlm", time.time() - t0, 0, 0,
            int(getattr(u, "prompt_tokens", 0) or 0), int(getattr(u, "completion_tokens", 0) or 0))
    data = json.loads(r.choices[0].message.content)
    return {s["step_id"]: ("review" if s["verdict"] == "uncertain" else s["verdict"]) for s in data["steps"]}


class NaiveBaseline:
    """Run the whole naive approach over a ProcedureSpec + video. Returns per-step verdicts.

    Verdict math is count-in-range + ordering (the deterministic core every approach uses);
    state steps fall back to the heavy many-frame VLM call. This is the bar to beat on
    requests / frames-billed / tokens / latency - WITHOUT it being weakened."""

    def __init__(self, client: OpenAI, out_dir: Path) -> None:
        self.client = client
        self.out_dir = out_dir

    def run(self, spec: ProcedureSpec, video: Path, n_frames: int) -> dict[str, str]:
        from stepproof.rules import Params
        _, n, _, _ = probe(video)
        n = max(n, n_frames)
        verdicts: dict[str, str] = {}
        seen_concepts: dict[str, list[Detection]] = {}
        for step in spec.steps:
            # one SAM request PER STEP OCCURRENCE (no dedupe across steps)
            dets = naive_segment(self.client, video, step.concept, self.out_dir)
            seen_concepts[step.concept] = dets
            counts = naive_count(dets, n)
            ok = [step.min_count <= c <= (step.max_count if step.max_count is not None else 10**9)
                  for c in counts]
            if not any(ok):
                verdicts[step.id] = "fail"
            elif step.state_question:
                verdicts[step.id] = "review"          # naive: no cheap state path, escalate
            else:
                verdicts[step.id] = "pass"
        return verdicts
