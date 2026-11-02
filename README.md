# StepProof

Describe a manual procedure in plain English. StepProof compiles it into a checkable spec, verifies a video of it with **SAM 3.1** (open-vocabulary segmentation and tracking), uses **Muse Spark** only for language compilation and ambiguous state checks, and lets **deterministic rules** make the pass / fail / needs-review decision. No per-part training data.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # one-time: download the browser the tiny browser drives
cp .env.example .env            # add MODEL_API_KEY
python -m scripts.smoke_test path/to/image.jpg "red connector"   # access check, run this first
uvicorn stepproof.api:app --reload                               # http://localhost:8000
pytest -q                                                        # offline tests (v1 pipeline + wire + rules)
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
python -m pytest -q                            # 35 tests incl. 13 v2 integration tests
```
Four modes in the UI: **Monitor** (do the task yourself in the live view - the app records
multi-locator actions + your narration and compiles a reusable, editable Procedure),
**Execute** (an aim, typed or via push-to-talk; Muse Spark drives the same tiny browser
with a kill switch, pause/takeover at any moment, and approval gates before irreversible or
external actions), **Coach** (deterministic detectors measure where you can go faster;
the model only phrases it), and **Tour** (a one-click, 4-beat guided showcase that streams
learn / execute+gate / takeover / prove onto the live event feed, then records a dated,
replayable trace you can re-watch offline). **Verify** is always code, never the model:
success = deterministic checks (URL / visible text / element state / extracted value) over
browser state, each verdict linked to before/after screenshots.

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

## Guided tour + launch video
- Run the 4-beat showcase (real approval-gate + takeover clicks, then a dated offline replay):
```bash
uvicorn stepproof.api_v2:app --port 8011   # open http://localhost:8011 -> Tour tab -> Run guided tour
```
  Unattended/scripted: `python -m scripts.run_tour` (writes `data/tour_runs/<date>.json`).
- **Launch video: rendered.** `brag-output/brag.mp4` (20 s, 1920x1080@30, music + SFX, idle
  thumbnail = the baked PASS poster) with `brag-output/brag.jpg` as its frame-0 poster. Built
  from the `/brag` plan: `brag-output/brag-plan.md` (storyboard), `composition-brief.md`,
  and `share-copy.txt` (the caption). Re-render any time with:
```bash
cd brag-output/composition && npx hyperframes check && npx hyperframes render
```

## Vision self-heal (measured & KEPT — 93.8% combined)
When every recorded DOM locator for a step fails, a visual fallback re-locates the target
on a fresh screenshot (`stepproof/browser/vision_heal.py`): Muse Spark grounding first,
SAM 3.1 open-vocabulary as the fallback. Measured on 16 real screenshots across standard,
hostile, and mutated sites (`eval/vision_heal_results.json`): Muse grounding 15/16 (93.8%),
SAM 3.1 7/16 (43.8%), combined **15/16 (93.8%)** — exceeding the 70% keep threshold.

Wired into the live app via `STEPPROOF_VISION_SELFHEAL=1` (default stays off in offline tests for determinism):
- **Visual Fill:** `fill_at` types visually into fields, with strict refusal on password fields (`input[type=password]`).
- **Safety Gate:** Re-evaluates visible label at clicked coordinates; irreversible/external hints (`Submit`, `Discard`) or unresolvable labels escalate to the approval gate before execution.
- **Mutated UI Showcase:** BEAT 5 · HEAL in `demo/tour.py` runs against `/mutated/` where all DOM IDs/classes are regenerated and DOM order is shuffled on every load, proving locator fallthrough → visual grounding → gated healed click → fill_at on renamed inputs → deterministic verification.

## Known limits
Fixed camera and large, distinct parts work best; SAM takes one concept per request (short noun phrases like `Vendor text input` or `Submit claim button`, not sentences or instructions — carried in `proc.py:Step.vision_concept`); masks are parsed but not yet drawn (boxes only, see PRD stretch P1); phone videos may need re-encoding to H.264 without rotation flags.
