"""Muse Spark via the OpenAI-compatible Chat Completions endpoint with schema-constrained JSON
(response_format json_schema; see dev.meta.ai/docs/structured-output). Responses are cached for replayable demos."""
from __future__ import annotations
import base64, hashlib, json, time
from pathlib import Path
from urllib.parse import urlparse
from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from .. import config as cfg
from ..schemas import ProcedureSpec, StateCheck

COMPILE_SYSTEM = """You convert a plain-English description of a manual procedure into a verification spec for a video checker.
Rules:
- Every step must be checkable by LOOKING at the video from outside.
- `concept` is a SHORT CONCRETE NOUN PHRASE (max 5 words) naming ONE visible object type (e.g. 'red connector', 'silver screw'). Never a verb phrase, list, question or negation.
- Use min_count/max_count for how many must be visible at the same time (min_count 0 is valid: 'no <x> present').
- Express ordering ONLY through `after` (ids of earlier steps).
- A step counts as DONE when its concept is still visible in the video's final frames. `persist` stays true unless the object is legitimately removed or covered afterwards (used-up tools, packaging) — set persist=false only in that case.
- Use `state_question` ONLY when the step depends on a state that presence/count cannot show (e.g. 'Is the lid closed?'); phrase it as a yes/no question about the visible scene.
- Do not invent steps the user did not describe."""

STATE_SYSTEM = """You verify one visible state in an image. Answer ONLY from what is visible.
If the relevant region is occluded, blurry or ambiguous, answer 'uncertain'. Never infer or assume."""

BASELINE_SYSTEM = """You are inspecting frames sampled in time order from one video of a manual procedure.
For each step decide pass (clearly done correctly), fail (clearly missing or wrong) or uncertain. Judge only what is visible."""


def _img(path: Path) -> dict:
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()}}


class MuseSpark:
    def __init__(self) -> None:
        self.client = OpenAI(base_url=cfg.VISION_BASE_URL, api_key=cfg.VISION_API_KEY or "missing", timeout=180, max_retries=0)
        self.name = f"{cfg.VISION_MODEL} @ {urlparse(cfg.VISION_BASE_URL).netloc}"
        (cfg.CACHE / "muse").mkdir(parents=True, exist_ok=True)

    def _json(self, messages: list[dict], name: str, schema: dict) -> dict:
        key = hashlib.sha256(json.dumps([cfg.VISION_MODEL, name, messages], sort_keys=True).encode()).hexdigest()[:24]
        cp = cfg.CACHE / "muse" / f"{key}.json"
        if cfg.USE_CACHE and cp.exists():
            return json.loads(cp.read_text())
        if cfg.PROVIDER_MODE == "replay":
            raise FileNotFoundError(f"replay mode: no cached Muse result ({name}, {key})")
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.client.chat.completions.create(
                    model=cfg.VISION_MODEL, messages=messages,
                    response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
                )
                data = json.loads(r.choices[0].message.content)
                cp.write_text(json.dumps(data))
                return data
            except (json.JSONDecodeError, RateLimitError, APIConnectionError, APITimeoutError) as e:
                last = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Muse request failed after retries: {last}")

    def compile_procedure(self, text: str) -> ProcedureSpec:
        data = self._json(
            [{"role": "system", "content": COMPILE_SYSTEM}, {"role": "user", "content": text}],
            "ProcedureSpec", ProcedureSpec.model_json_schema(),
        )
        return ProcedureSpec.model_validate(data)

    def check_state(self, image_path: Path, question: str) -> StateCheck:
        data = self._json(
            [{"role": "system", "content": STATE_SYSTEM},
             {"role": "user", "content": [{"type": "text", "text": question}, _img(image_path)]}],
            "StateCheck", StateCheck.model_json_schema(),
        )
        return StateCheck.model_validate(data)

    def baseline_verdicts(self, spec: ProcedureSpec, frame_paths: list[Path]) -> dict[str, str]:
        schema = {"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "object", "properties": {
            "step_id": {"type": "string"}, "verdict": {"type": "string", "enum": ["pass", "fail", "uncertain"]},
            "rationale": {"type": "string"}}, "required": ["step_id", "verdict", "rationale"]}}}, "required": ["steps"]}
        listing = "\n".join(f"{s.id}: {s.description}" + (f" (after {','.join(s.after)})" if s.after else "") for s in spec.steps)
        content = [{"type": "text", "text": f"Procedure steps:\n{listing}"}] + [_img(p) for p in frame_paths]
        data = self._json([{"role": "system", "content": BASELINE_SYSTEM}, {"role": "user", "content": content}], "BaselineVerdicts", schema)
        return {s["step_id"]: ("review" if s["verdict"] == "uncertain" else s["verdict"]) for s in data["steps"]}
