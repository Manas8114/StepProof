# StepProof — Submission Checklist

**Deadlines (PRD §14/§15):** internal cutoff **Nov 4, 2:00 PM ET**; official due **Nov 4, 9:00 PM ET** (= Nov 5, 7:30 AM IST).
This checklist separates what is **done and verified** from what still requires **live API access** (a valid key — the 1-day key has expired).

## A. Verified in this repo (offline, reproducible now)
| # | Item | Evidence |
|---|---|---|
| A1 | Deterministic rules engine (models perceive, code decides) | `pytest` — `tests/test_rules.py` |
| A2 | SAM wire parser (incl. real-format fixtures) | `tests/test_wire.py` |
| A3 | End-to-end pipeline + evidence + overlay | `tests/test_pipeline.py` |
| A4 | **All 18 tests green** | `python -m pytest -q` → `18 passed` |
| A5 | **Synthetic dataset present on disk** (7 clips + 7 sidecars + 2 procedures + manifest + mock config) | `data/clips/`, `data/procedures/`, `data/manifest/`, `data/stepproof_mock.json`; regenerate any time: `python -m scripts.make_dataset` |
| A6 | Offline eval, both modes, runnable with **no API key** | `STEPPROOF_PROVIDER=mock STEPPROOF_DATA=data python -m eval.run_eval --manifest data/manifest/manifest.json --mode pipeline` (and `--mode baseline`) |
| A7 | Web UI boots and compiles offline | `STEPPROOF_PROVIDER=mock uvicorn stepproof.api:app` → http://localhost:8000 |
| A8 | Calibration flags (`--min-conf`, `--review-conf`, `--stable-frames`) | `eval/run_eval.py` |
| A9 | `.env` / `data/` gitignored; key never committed | `git check-ignore .env` |
| A10 | README documents the offline dataset and labels it **synthetic** | `README.md` → "Offline synthetic dataset" |

## B. Requires a valid API key (the only open technical gap)
| # | Item | Command / note |
|---|---|---|
| B1 | Working key in `.env` (`MODEL_API_KEY`), 401s cleared | `python -m scripts.smoke_test` must print `ALL OK` |
| B2 | Real image run → boxes + confidences sane; save raw wire text to `tests/fixtures/` | `python -m scripts.smoke_test <photo> "<concept>"` |
| B3 | Real video run (re-encode phone footage: `ffmpeg -i in.mov -c:v libx264 -crf 20 -pix_fmt yuv420p -movflags +faststart out.mp4`); verify frame-index alignment | one real clip through `run_inspection` |
| B4 | **Seed the replay cache with real outputs**, then prove `PROVIDER_MODE=replay` reproduces the demo with the network disabled | FR-8; currently the cache holds *no live* outputs yet |
| B5 | Run the real evaluation on real clips; **overwrite** `eval/results_*.json` (today's files contain synthetic numbers — see D3) | both modes |
| B6 | Write `eval/RESULTS.md`: per-step strict + escalated P/R, review rate, latency, pipeline-vs-baseline, one-line cause for every failure | PRD §11 |
| B7 | Tune `Params` on a **dev** subset only; record values + why in README; keep ≥6 clips held out | PRD §11 rule |
| B8 | If Muse Spark must run through a gateway: set `VISION_BASE_URL`/`VISION_API_KEY` and **disclose** in README + `/api/health` | PRD §7 |

## C. Submission packaging (team, no code)
| # | Item |
|---|---|
| C1 | Read the Official Rules; pick the track they require |
| C2 | Record the 90-second demo per PRD §12 script |
| C3 | Push the public GitHub repo; verify in a **logged-out browser**: no `.env`, no keys, no `data/`; all links in the README resolve |
| C4 | Model/provider disclosure statement in the submission (exact model ids + hosts; any gateway) |
| C5 | Attach `eval/RESULTS.md` (real numbers, failures included) |
| C6 | Submit by **Nov 4, 14:00 ET** (internal cutoff) |

## D. Honesty guardrails (non-negotiable)
| # | Rule |
|---|---|
| D1 | **The dataset is synthetic, generated locally by `scripts/make_dataset.py` — it was NOT downloaded.** No labelled real-world clip set exists for this problem, and the live API was unavailable (401). Nothing in the repo claims otherwise (README states it). |
| D2 | `eval/results_pipeline.json` / `results_baseline.json` currently contain **synthetic** numbers (mock providers, labeled `mock-sam (synthetic, offline)` in their `models` field). They are valid for demonstrating mechanics only; the submission must report B5's real numbers. |
| D3 | `MockSam`/`MockMuse` (via `STEPPROOF_PROVIDER=mock`) and `PROVIDER_MODE=replay` are for development and demos; **no synthetic number may appear in `eval/RESULTS.md`** without an explicit "synthetic, offline" label. |
