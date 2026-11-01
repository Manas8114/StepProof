# StepProof - Submission Checklist

Deadlines (PRD sections 14/15): internal cutoff Nov 4, 2:00 PM ET; official due Nov 4, 9:00 PM ET (= Nov 5, 7:30 AM IST).
This checklist separates what is done and verified from what still requires real filmed footage.

Status 2026-10-31 (end of day): live API access is confirmed and working (B1-B3 plumbing verified against the live Meta Model API on real photos/footage). The remaining gap is real filmed clips + labels, not API access.

## A. Verified in this repo (offline, reproducible now)
| # | Item | Evidence |
|---|---|---|
| A1 | Deterministic rules engine (models perceive, code decides) | `pytest` - `tests/test_rules.py` |
| A2 | SAM wire parser, including real live wire fixtures | `tests/test_wire.py` + `tests/test_wire_real_fixture.py` |
| A3 | End-to-end pipeline + evidence + overlay | `tests/test_pipeline.py` |
| A4 | All 22 tests green | `python -m pytest -q` -> `22 passed` |
| A5 | Synthetic dataset on disk (7 clips + 7 sidecars + 2 procedures + manifest + mock config) | `data/clips/`, `data/procedures/`, `data/manifest/`, `data/stepproof_mock.json`; regenerate: `python -m scripts.make_dataset` |
| A6 | Offline eval, both modes, no API key needed | `STEPPROOF_PROVIDER=mock STEPPROOF_DATA=data python -m eval.run_eval --manifest data/manifest/manifest.json --mode pipeline` (and `--mode baseline`) |
| A7 | Web UI boots and compiles offline | `STEPPROOF_PROVIDER=mock uvicorn stepproof.api:app` -> http://localhost:8000 |
| A8 | Calibration flags (--min-conf, --review-conf, --stable-frames) | `eval/run_eval.py` |
| A9 | `.env` / `data/` gitignored; key never committed | `git check-ignore .env` |
| A10 | README documents the offline dataset and labels it synthetic | `README.md` -> "Offline synthetic dataset" |

## B. Live API work
| # | Item | Status / command |
|---|---|---|
| B1 | Working key in `.env` (`MODEL_API_KEY`), 401s cleared | DONE (Oct 31) - `models.list`, Muse compile + image state check all live; `python -m scripts.smoke_test` -> `ALL OK` |
| B2 | Real image run: boxes + confidences sane; raw wire text pinned | DONE (Oct 31) - SAM `car` -> 1 det (conf 0.97), `wheel` -> 2 dets (conf 0.91/0.93), boxes within image pixels; `tests/fixtures/wire_image_real.txt` + regression tests |
| B3 | Real video run; frame-index alignment | DONE (Oct 31, panned real-photo clip) - live SAM video: 60/60 frames detected, stable object id, boxes migrate with the pan; `tests/fixtures/wire_video_real.txt` + regression tests. STILL TO DO: swap in filmed assembly clips (ffmpeg command in C2) and re-run |
| B4 | Seed the replay cache with filmed-clip live outputs, then prove `PROVIDER_MODE=replay` reproduces the demo with network disabled | FR-8; cache already holds live outputs for the image + panned clip; filmed clips add theirs automatically (live mode caches on write) |
| B5 | Run the real evaluation on filmed clips; OVERWRITE `eval/results_*.json` (current files: pipeline + baseline = synthetic mock numbers; see D2) | both modes |
| B6 | Write `eval/RESULTS.md`: per-step strict + escalated P/R, review rate, latency, pipeline-vs-baseline, one-line cause for every failure | PRD section 11 |
| B7 | Tune `Params` on a dev subset only; record values + why in README; keep 6+ clips held out | PRD section 11 rule |
| B8 | If Muse Spark must run through a gateway: set `VISION_BASE_URL`/`VISION_API_KEY`, disclose in README + `/api/health` | NOT needed today - live access to Muse Spark confirmed on `api.meta.ai` |

## C. Submission packaging (team, no code)
| # | Item |
|---|---|
| C1 | Read the Official Rules; pick the track they require |
| C2 | Film demo clips: 2 procedures x ~10 clips (correct / missing part / wrong order / wrong placement / ambiguous), 10-20 s each, fixed camera, large colour-distinct parts; re-encode phone footage: `ffmpeg -i in.mov -c:v libx264 -crf 20 -pix_fmt yuv420p -movflags +faststart out.mp4` |
| C3 | Record the 90-second demo per PRD section 12 script |
| C4 | Push the public GitHub repo; verify in a logged-out browser: no `.env`, no keys, no `data/`; all README links resolve |
| C5 | Model/provider disclosure statement (exact model ids + hosts: `sam-3.1`, `muse-spark-1.3` @ `api.meta.ai`; any gateway used) |
| C6 | Attach `eval/RESULTS.md` (real numbers, failures included) |
| C7 | Submit by Nov 4, 14:00 ET (internal cutoff) |

## D. Honesty guardrails (non-negotiable)
| # | Rule |
|---|---|
| D1 | The dataset was generated locally by `scripts/make_dataset.py` - it was NOT downloaded. No labelled real-world clip set exists for this problem. Nothing in the repo claims otherwise (README states it). |
| D2 | `eval/results_pipeline.json` / `results_baseline.json` currently contain synthetic numbers (mock providers, `models` field says `mock-sam (synthetic, offline)`). They demonstrate mechanics only; the submission must report B5's real numbers. |
| D3 | `MockSam`/`MockMuse` (`STEPPROOF_PROVIDER=mock`) and `PROVIDER_MODE=replay` are for development/demos; no synthetic number may appear in `eval/RESULTS.md` without an explicit "synthetic, offline" label. |
| D4 | `tests/fixtures/wire_*.txt` are real live API outputs (pinned 2026-10-31) - fine to reference; do not confuse with D2's synthetic eval results. |

## V. v2 (browser companion) - submission state
| # | Item | Status / evidence |
|---|---|---|
| V1 | Tiny browser (Playwright), screenshot stream, input forwarding, kill switch | `stepproof/browser/session.py`; `tests/test_v2.py` |
| V2 | Agent loop: observe -> Muse tool-call -> code-first gate -> act -> log | `stepproof/agent/loop.py`; circuit breaker tested |
| V3 | Takeover protocol (pause at action boundary, hand-back w/ note) | `state.py` + `loop.py`; `tests/test_v2.py::test_*takeover*` |
| V4 | Approval gates (irreversible/external, code-classified first) | `browser/actions.py::classify_action`; `test_approval_gate_blocks_irreversible` |
| V5 | Monitor -> compile -> execute from a learned Procedure (self-healing locators) | `learn/`, `agent/executor.py`; `test_monitor_compile_execute_procedure`, `test_self_healing_falls_through_locators` |
| V6 | Deterministic success checks + evidence screenshots (verdict = code, not model) | `checks.py`; every verdict links a before/after JPEG |
| V7 | Coach: deterministic detectors + agent-vs-human compare (model only phrases) | `coach/efficiency.py`; `test_coach_detects_redundant_navigation` |
| V8 | Voice: TTS browser `speechSynthesis`; STT Meta->browser fallback (disclosed) | `coach/voice.py` |
| V9 | 4-beat guided tour + dated offline replay | `demo/tour.py`; `tests/test_v2.py::test_tour_runs_all_four_beats...`; `data/tour_runs/<date>.json` |
| V10 | Eval matrix: learned / human-demo / goal-only + safety (injection + gate-denied) | `eval/run_eval_v2.py`, `eval/results_v2.json`; `gate_denied_ok=true`, `injection_hold_ok=true` |
| V11 | Live goal-only agent measured | `eval/live_agent_v2.json` (DONE, 4 actions, 5 model calls, 13.0 s, gate on Submit) |
| V12 | Vision self-heal experiment (Muse-first, SAM fallback) | **CUT - 5/12 (41.7%) < 70%**; `eval/vision_heal_results.json`; DOM multi-locator self-heal stays primary |
| V13 | Safety: injection defence + allowlist + credentials masked | `demo_sites/hostile/`; `test_injection_page_text_cannot_change_goal` |
| V14 | Docs | `docs/ARCHITECTURE.md`, `docs/USAGE.md`, `README.md` (v2 + tour + vision-heal + launch video) |

## W. Launch video (/brag)
| # | Item | Status |
|---|---|---|
| W1 | `/brag` plan + storyboard + share copy | DONE - `brag-output/brag-plan.md`, `brag-output/share-copy.txt` |
| W2 | Rendered `.mp4` | **BLOCKED** - `npx hyperframes` not available in this environment; render with `cd brag-output && npx hyperframes check && npx hyperframes render` where the tool exists |

## X. v2 honesty guardrails
| # | Rule |
|---|---|
| X1 | Condition A (goal-only agent) is live/rate-limited; when the API is down the harness marks it `SKIPPED` and discloses it - never report a number we did not run. |
| X2 | Efficiency claims are **learned-procedure vs the recorded human demo only** - we do not claim a win against an unrecorded baseline. |
| X3 | Vision self-heal is reported as a **negative result** (41.7% < 70%, cut); it is not presented as a working feature. |
| X4 | Tour approval/takeover clicks: interactive mode waits for a real human; unattended/auto mode labels itself in the trace. |
| X5 | `live_agent_trace.json` and tour records are dated; replayed ones carry a `REPLAY <date>` label and are not live runs. |
