# Master prompt for the coding agent (Muse Code, Claude Code, or similar)

Paste everything below the line into the agent from the repo root.

---

You are the lead engineer on **StepProof**, a hackathon project due in under four days. Read `PRD.md` and `README.md` fully, then inspect the repo. The repo already contains a working, tested skeleton (`pytest` is green). Your job is to make it work end to end against the real Meta Model API, polish it, and produce honest evaluation results. Do not rewrite what works.

## Ground rules
1. **Never fabricate results.** Do not invent metrics, clip results, API responses or model names. If something cannot be verified, say so and stop for guidance.
2. **Verify against the docs before changing any API call.** Official docs: `https://dev.meta.ai/docs/` (Responses API, SAM: `/docs/sam/overview`, `/docs/sam/segmenting`, `/docs/sam/reading-segmentation`, `/docs/sam/client-libraries`; Structured output: `/docs/structured-output`; Image understanding: `/docs/image-understanding`).
3. **Models perceive, code decides.** Pass/fail logic lives only in `stepproof/rules.py` and must stay free of model calls.
4. **Secrets** only in `.env`. Never print or commit keys.
5. **Disclose substitutions.** If the Muse Spark endpoint must be swapped for a gateway, keep it visible in `/api/health`, the report and the README.
6. Keep dependencies minimal. No new frameworks. No Celery/Redis/Postgres/Docker unless the PRD is amended.

## Verified API facts (from Meta's docs)
- Base URL `https://api.meta.ai/v1`, Bearer key; OpenAI-compatible.
- SAM: model `sam-3.1`, `POST /v1/responses`, `input` = one user message with an `input_text` (ONE short noun phrase) plus an `input_image` (`image_url`, URL or data URL) or `input_video` (`video_url` or `file_id` from `POST /v1/files` with `purpose=user_data`). Stream recommended. Optional `metadata`: `include_confidence: "true"` (string), `mask_encoding: "one_bit"`.
- SAM output (special-token text, one line per frame): `<Nf>id<|box;x1;y1;x2;y2;w;h[;c]|><|mask;...;data=H,W,<enc>payload|>,id...`. Frames may skip or be unordered; ids are sparse and stable per object; payload is base85; empty output = zero matches (valid).
- Python parser exists: `pip install meta-sam-parser` (module `meta_sam_parser`; has `decode_mask_to_raster`, `decode_mask_to_rle`, `decode_mask_to_svg_path`, `build_object_prompt`).
- Muse Spark: model `muse-spark-1.3`; structured output via Chat Completions `response_format={"type":"json_schema","json_schema":{"name":...,"schema":...}}` (Responses API uses `text.format`).
- SAM limits: video MP4/MOV (H.264/H.265/MPEG-4), up to 15,000 frames, 16 tracked objects/frame, billed per frame (min 50).

## Task order (do not skip ahead; commit after each)
**T0. Access.** Run `python -m scripts.smoke_test path/to/image.jpg "<concept>"`. Fix real problems (auth, model ids, request shape). If any model is unreachable, STOP and report the exact status code and error body.
**T1. Real image run.** Segment a real assembly photo; confirm boxes parse, confidences present, counts sensible. Save the raw wire text as a test fixture.
**T2. Real video run.** Run a 10-20 s clip through `run_inspection`; verify frame indices align with OpenCV frames (watch rotation and variable frame rate). Fix `probe`/frame mapping if needed.
**T3. Procedure compiler.** Test 5 realistic sentences. Tighten `COMPILE_SYSTEM` prompt and `sanitize` until specs are consistently valid. Add tests with recorded outputs.
**T4. Rules calibration.** Using a *dev* subset of clips only, tune `Params` (min_conf, review_conf, stable_frames). Record the chosen values and why in `README.md`. Keep a held-out subset untouched.
**T5. UI pass.** Walk through the whole flow in a browser. Fix overlay alignment, error states and empty states. Keep it dependency-free.
**T6. Evaluation.** Create `eval/procedure*.json` and `eval/manifest.json` for both domains from the clips actually filmed. Run `--mode pipeline` and `--mode baseline`. Write `eval/RESULTS.md` with the tables, the review rate, latency, and an honest failure analysis (each failure with a one-line cause).
**T7. Replay.** Populate the cache by running the demo clips live once; confirm `PROVIDER_MODE=replay` reproduces the demo offline.
**P1 (stretch, only if T0-T7 are green).** Mask overlays: decode masks with `meta_sam_parser` (verify the Python call signatures from its docstrings first), return SVG paths or RLE in `overlay`, and draw them in `index.html`. Keep box overlays as the fallback.

## Definition of done
- `pytest` green; `python -m scripts.smoke_test` green; one-command run (`uvicorn stepproof.api:app`).
- Demo works in replay mode with the network disabled.
- `eval/RESULTS.md` contains real numbers from real clips, including failures.
- README documents setup, parameters, model/provider disclosure and known limitations.

## Working style
Small commits. After each task, print: what changed, how you verified it, what is still uncertain. When blocked on something only the human can provide (API access, clips, a rules question), stop and ask one precise question.
