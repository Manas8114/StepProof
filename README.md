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

## Disclosure
`/api/health` and every report list the exact models and hosts used. If the Muse Spark endpoint is replaced by a gateway (`VISION_BASE_URL`), say so in your submission. SAM has no fallback in this repo.

## Known limits
Fixed camera and large, distinct parts work best; SAM takes one concept per request; masks are parsed but not yet drawn (boxes only, see PRD stretch P1); phone videos may need re-encoding to H.264 without rotation flags.
