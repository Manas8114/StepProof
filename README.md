# StepProof

Describe a manual procedure in plain English. StepProof compiles it into a checkable spec, verifies a video of it with **SAM 3.1** (open-vocabulary segmentation and tracking), uses **Muse Spark** only for language compilation and ambiguous state checks, and lets **deterministic rules** make the pass / fail / needs-review decision. No per-part training data.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add MODEL_API_KEY
python -m scripts.smoke_test path/to/image.jpg "red connector"   # access check, run this first
uvicorn stepproof.api:app --reload                               # http://localhost:8000
pytest -q                                                        # 14 offline tests
```

## How a verdict is made
1. Muse Spark turns your sentence into steps (`concept`, count range, `after`, optional `state_question`).
2. One SAM 3.1 request per concept returns boxes, confidences and tracked ids per frame.
3. `rules.py` decides: stable count range, still true at the end, ordering, confidence; anything doubtful becomes **needs review**.
4. Muse Spark answers a yes/no state question only when a step needs one, on a cropped evidence frame.

## Evaluate
```bash
python -m eval.run_eval --manifest eval/manifest.json --mode pipeline
python -m eval.run_eval --manifest eval/manifest.json --mode baseline   # Muse Spark alone on 8 sampled frames
```
See `eval/manifest.example.json`. Report failures, not just wins.

## Reproducible demo
Raw SAM text and Muse JSON are cached under `data/cache`. `PROVIDER_MODE=replay` serves the demo from cache with no network. Cached results are real API outputs from earlier runs.

## Offline synthetic dataset (no API key, no network)
When the Meta Model API is unreachable, a fully synthetic dataset lets the whole system run offline and deterministically:
```bash
python -m scripts.make_dataset                       # writes data/clips, data/procedures, data/manifest, mock config
STEPPROOF_PROVIDER=mock STEPPROOF_DATA=data python -m eval.run_eval --manifest data/manifest/manifest.json --mode pipeline
STEPPROOF_PROVIDER=mock STEPPROOF_DATA=data python -m eval.run_eval --manifest data/manifest/manifest.json --mode baseline
```
Each clip is a short MJPG video with coloured parts on authored schedules, plus a `<clip>.dets.json` sidecar holding ground-truth detections (concept -> present frames, box, confidence, object ids), the Muse-alone baseline verdicts and the expected per-step verdicts. `MockSam`/`MockMuse` serve these sidecars; the pipeline, rules engine, API and UI are exercised exactly as in live mode. **The dataset is synthetic - its numbers demonstrate mechanics, not measured model performance, and must never be reported as such.**

## Disclosure
`/api/health` and every report list the exact models and hosts used. If the Muse Spark endpoint is replaced by a gateway (`VISION_BASE_URL`), say so in your submission. SAM has no fallback in this repo.

## StepProof v2 — Learn · Execute · Verify (browser companion + voice)
One command starts the v2 companion app, the two demo sites and the tiny browser:
```bash
uvicorn stepproof.api_v2:app --port 8011      # open http://localhost:8011
python -m pytest -q                            # 32 tests incl. 10 v2 integration tests
```
Three modes in the UI: **Monitor** (do the task yourself in the live view - the app records
multi-locator actions + your narration and compiles a reusable, editable Procedure),
**Execute** (an aim, typed or via push-to-talk; Muse Spark drives the same tiny browser
with a kill switch, pause/takeover at any moment, and approval gates before irreversible or
external actions), **Coach** (deterministic detectors measure where you can go faster;
the model only phrases it). **Verify** is always code, never the model: success =
deterministic checks (URL / visible text / element state / extracted value) over browser
state, each verdict linked to before/after screenshots.

Safety (enforced in code, tested): domain allowlist, approval gates, credentials are never
read/stored/logged, per-run budgets, full action log, and page text is treated as
untrusted data (hostile-page injection test in `tests/test_v2.py` + `eval/run_eval_v2.py`).

Live-agent numbers: `eval/RESULTS.md` (done in 13 s, 4 actions, 5 model calls, gate
triggered on Submit - measured, single session). The v2 evaluation is deterministic +
offline: `python -m eval.run_eval_v2` (no API key).

**Disclosures:** reasoning = `muse-spark-1.3` via `api.meta.ai` Responses API (flat tool
shape - Meta variant); computer-use observe/act loop follows Meta's docs; STT = Meta
`muse-voice-transcribe-1.0` when reachable, else browser Web Speech (disclosed in UI);
TTS = browser `speechSynthesis` (no dependency). The v1 camera-verify path is frozen and
optional.

## Known limits
Fixed camera and large, distinct parts work best; SAM takes one concept per request; masks are parsed but not yet drawn (boxes only, see PRD stretch P1); phone videos may need re-encoding to H.264 without rotation flags.
