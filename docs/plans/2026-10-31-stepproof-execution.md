# StepProof Execution Plan (2026-10-31)

## Context

StepProof (Meta Global AI Developer Hackathon, due Nov 4 9:00 PM ET; internal cutoff Nov 4 2:00 PM ET) verifies manual procedures from video: Muse Spark compiles a sentence into a checkable `ProcedureSpec`, SAM 3.1 segments/tracks each concept, `rules.py` makes the deterministic pass/fail/review call, and a FastAPI + dependency-free UI presents evidence-backed reports. The repo already contains a tested skeleton (14/14 tests green as of this plan). This plan executes `AGENT_PROMPT.md` task order T0–T7 + stretch P1 against the **real Meta Model API**, ending with honest evaluation results and a reproducible offline demo.

### Ground rules (from AGENT_PROMPT.md — binding)

1. **Never fabricate results** — no invented metrics, clips, responses, or model names.
2. **Verify against docs** (`dev.meta.ai/docs/`) before changing any API call.
3. **Models perceive, code decides** — pass/fail logic stays in `rules.py`, model-call-free.
4. **Secrets** only in `.env` (gitignored).
5. **Disclose substitutions** (e.g. gateway for Muse Spark) in `/api/health`, report `models`, and README.
6. Minimal dependencies; no new frameworks.

### Tech stack (existing — do not add)

Python 3.13 · FastAPI/uvicorn · OpenAI SDK (Meta Model API, OpenAI-compatible) · OpenCV + numpy · pydantic v2 · SQLite · vanilla JS UI · pytest · ffmpeg (available on this machine, for re-encoding phone clips).

### Repo map (what exists)

- `stepproof/rules.py` — deterministic engine + `Params` (min_conf 0.5, review_conf 0.7, stable_frames 5)
- `stepproof/pipeline.py` — `run_inspection`: probe → SAM (parallel per concept) → rules → optional Muse state check → `Report` (counts, box overlay, evidence JPEGs)
- `stepproof/providers/{sam_api,muse}.py` — live API clients with disk cache (`data/cache`), bounded retries (429/5xx/network only); `mock.py` for tests
- `stepproof/wire.py` — SAM special-token parser (tested)
- `stepproof/{api,store,compiler,config,schemas,video}.py` — API, SQLite, NL compiler + sanitizer
- `stepproof/static/index.html` — full UI: compile → save → upload → live box overlay + swimlanes + evidence cards + reviewer confirm
- `eval/run_eval.py` — `pipeline` / `baseline` modes, strict + escalated P/R, review rate, latency → `eval/results_<mode>.json`
- `scripts/smoke_test.py` — access check
- Not yet present: git repo, `.env`, real clips, `data/`, `eval/procedure*.json` + `eval/manifest.json` + `eval/RESULTS.md`, `tests/fixtures/`

### Execution model

- **Inline execution** in one session, task by task, **one commit per task** (task 0 creates the git repo; `AGENT_PROMPT.md` mandates working from repo root with per-task commits, so no worktree/branch ceremony). Each commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **Blockers stop the plan and surface exactly one question** (the rule that only the human can answer: API key, a clip to film, a rules question).
- Do not start task N+1 until task N's verification passes.

---

## Task 0 — Workspace setup (no user input needed)

`git init`, first commit; confirm ignore rules keep `.env`/`data/`/uploads out.

```bash
git init -b main && git add -A && git status
git commit -m "skeleton: tested pipeline, rules, UI, eval harness"
```

**Verify:** `git log --oneline` shows 1 commit; `git status` clean; `git check-ignore .env data/x` both exit 0.
**Commit:** task 0 commit.

## Task 1 — API access (T0) — **needs user: `MODEL_API_KEY` in `.env`**

Copy `.env.example` to `.env` and add the key. Minimal check (no image): `models.list` + Muse compile; then full check once a real photo is available.

```bash
cp .env.example .env   # user adds MODEL_API_KEY
python -m scripts.smoke_test                        # minimal: models.list + muse compile
python -m scripts.smoke_test data/images/photo.jpg "screw"   # full: + muse image + SAM image
```

**Verify:** output ends `ALL OK`.
**On failure: STOP and report the exact status code + error body** (e.g. 401 = bad key, 404 model = wrong id/region). If `muse-spark-1.3` is unreachable but SAM works, ask user about the documented gateway fallback (`.env` `VISION_BASE_URL`/`VISION_API_KEY`, e.g. OpenRouter `meta/muse-spark-1.3`) — only if they have an alternative account; otherwise ask on hackathon Discord.
**Commit:** none (`.env` is gitignored; note any config decisions in README later).

## Task 2 — Real image run (T1) — **needs user: one real assembly photo in `data/images/`**

Segment a real photo with SAM; confirm boxes/confidence parse; save the **raw wire text as a regression fixture**.

```bash
python -m scripts.smoke_test data/images/assembly.jpg "red connector"   # expect: N detection(s), N >= 1
ls -t data/cache/sam/*.txt | head -1     # newest = this run's raw wire text
```

Pick the newest cache file, save a copy: `mkdir tests/fixtures && cp <newest> tests/fixtures/wire_image_real.txt`.

Add `tests/test_wire.py::test_real_image_fixture` — parse the fixture and assert: it yields ≥1 `Detection` with `frame == 0`, integer box, `conf` is float in [0,1] or None, and `mask` payload (if present) is a non-empty string. (If the live output differs in shape from `wire.py`'s assumptions — that's the whole point of T1 — fix the parser **against the fixture**, re-run all tests, note the fix in the commit message.)

**Verify:** `pytest -q` → 15 passed, including the new fixture test.
**Stop condition:** SAM returns boxes that are clearly wrong-scale (off by ~image dims) → report before proceeding; frame-index mapping risk is exactly T2.

## Task 3 — Real video run (T2) — **needs user: one real 10–20 s clip (re-encoded H.264 MP4)**

Re-encode phone footage (rotation stripped, H.264):

```bash
ffmpeg -i clips/in.mov -c:v libx264 -crf 20 -pix_fmt yuv420p -movflags +faststart data/clips/ok_01.mp4
```

Run through the real pipeline via the eval harness (drives `run_inspection` end to end):

```bash
python -m eval.run_eval --manifest eval/manifest.example.json --mode pipeline --limit 1
```

(First pass uses `procedure.example.json`'s concepts; the manifest clip label may not match — expected verdicts will likely be "wrong"; **the deliverable here is plumbing, not accuracy**: boxes align, timestamps plausible, no crash.)

Checks:
1. `probe` reports fps/n matching the ffmpeg-encoded clip; SAM detection `frame` indices stay within `[0, n_frames)`.
2. Open the evidence JPEGs in `data/evidence/eval-0/` — drawn boxes sit on the intended objects.
3. `eval/results_pipeline.json` written with a latency (report it; target <90 s/clip is tracked, not promised).

If indices don't align (SAM skipped/renumbered frames, or fps mismatch from variable frame rate): fix `pipeline.py`/`video.py` mapping and add a unit test with the recorded wire text.

**Verify:** `pytest -q` green; evidence frames visually correct.
**Commit:** `real video run: SAM frame mapping verified` (+ fixes if any).

## Task 4 — Procedure compiler (T3)

Test **5 realistic sentences** across the two demo domains (e.g. hardware assembly ×3, kit-packing or lab protocol ×2). For each: run live `vis.compile_procedure(...)`, record the raw JSON to `tests/fixtures/compile/<i>.json`, and confirm `ProcedureSpec.model_validate` + `sanitize` produce a clean spec. Tighten `COMPILE_SYSTEM` (in `providers/muse.py`) and/or `compiler.sanitize` until 5/5 specs are valid with no unexpected warnings, then freeze the prompt.

Add `tests/test_compiler.py`: for each recorded fixture, validate the JSON into `ProcedureSpec`, run `sanitize`, assert the recorded step ids/concepts/counts survive (this pins today's compiler behavior; rerun-and-re-record only after a deliberate prompt change).

**Verify:** `pytest -q` → all pass; print the 5 recorded specs in the commit message.
**Commit:** `compiler: prompt v2 + recorded-output tests`.

## Task 5 — Rules calibration (T4) — **needs user: dev clips (~6–10) + held-out clips (~6), each labelled with expected per-step verdicts**

Prereq plumbing: add `--min-conf`, `--review-conf`, `--stable-frames` args to `eval/run_eval.py` (thread into `run_inspection(params=...)`); add one mock-based unit test proving the args flow through.

Then:
1. Create `eval/procedure1.json` (real compiled specs from Task 4, sanitized), `eval/manifest_dev.json` (dev clips + expected verdicts + tags), `eval/manifest_heldout.json` (held-out, **untouched during tuning**).
2. Sweep a small grid on the **dev manifest only** (e.g. min_conf {0.4, 0.5, 0.6}, review_conf {0.6, 0.7, 0.8}, stable_frames {3, 5}); run `run_eval` per combo and log (combo → strict P/R, review rate).
3. Pick the combo that maximizes escalated recall while keeping review rate sane; set the winners as `Params` defaults in `rules.py` **and** record the values + one-line why in a new `README.md` "Calibration" section.

**Verify:** `pytest -q` green; README section exists; held-out manifest never ran during tuning (state this in RESULTS later).
**Commit:** `rules: calibrated Params (dev-set sweep) + README note`.

## Task 6 — UI pass (T5)

Run `uvicorn stepproof.api:app` and walk the whole flow in a browser (live mode if cheap, otherwise replay a Task 3 report):
- compile → steps render; save → enabled Run button after file pick; progress text updates; report banner/lanes/cards render.
- **Overlay alignment:** with a report showing boxes, scrub the video and confirm boxes track objects (check `draw()` scaling: canvas = video client box; boxes scale from `report.width/height`; letterbox only if the stage outgrows the video aspect — fix by sizing canvas to the video element box).
- **Error states:** `#status`/`#warn` show readable errors (simulate: compile with `MODEL_API_KEY=` unset, or upload an `.avi`); failed inspection banner.
- **Empty states:** no procedure compiled → Run disabled; a step with zero detections still shows a card with its fail reason.
- No new dependencies (UI must stay dependency-free).

**Verify:** 2-minute manual walkthrough per FR-7 without stuck states.
**Commit:** `ui: overlay alignment + error/empty states`.

## Task 7 — Evaluation (T6) — **needs user: all clips filmed + labels**

Build the real eval set: `eval/procedure1.json`, `eval/procedure2.json`, `eval/manifest.json` (both domains; every clip filmed, expected per-step verdicts, tags: `correct|missing_part|wrong_order|wrong_placement|ambiguous`). **Held-out clips only appear here** — they are graded, never tuned.

```bash
python -m eval.run_eval --manifest eval/manifest.json --mode pipeline
python -m eval.run_eval --manifest eval/manifest.json --mode baseline
```

Write `eval/RESULTS.md`: per-step strict **and** escalated precision/recall, review rate, avg latency, pipeline vs Muse-alone baseline; every failure with a one-line cause; state which clips were dev-tuned vs held-out. **No invented numbers** — copy from `results_*.json`.

**Commit:** `eval: real results for N clips (both modes) + RESULTS.md`.

## Task 8 — Replay (T7)

Demo clips' cache is already populated by the live runs. Prove offline reproducibility:

```bash
# with network off (or air-gapped machine):
# .env: PROVIDER_MODE=replay STEPPROOF_CACHE=1
uvicorn stepproof.api:app   # re-run demo clip; or:
python -m eval.run_eval --manifest eval/manifest.json --mode pipeline
```

**Verify:** same verdicts as the live run of the same clips (diff `results_pipeline.json` excluding `latency_s`); zero outbound calls (replay raises `FileNotFoundError` if a clip lacks cache → that's the tripwire, not a bug to silence).
**Commit:** `replay: offline demo verified`.

## Task 9 (stretch, P1) — Mask overlays, **only if Tasks 1–8 are green**

```bash
pip install meta-sam-parser
```

Read `meta_sam_parser` docstrings **first** to confirm signatures (`decode_mask_to_svg_path`, `decode_mask_to_rle`). Decode mask payloads from the cached wire text → add per-frame SVG paths (or RLE) to `report.overlay` entries (boxes stay as fallback); render filled paths on the UI canvas, scaled by the `data=H,W` dims into video dimensions. Add a fixture test on a recorded wire line that contains a mask payload.

**Verify:** `pytest -q` green; browser shows filled mask + box fallback both.
**Commit:** `p1: SVG mask overlays (boxes as fallback)`.

## Task 10 — Submission prep (user checkpoints)

- README: setup, calibration values, **model/provider disclosure** (exact model ids + hosts, any gateway), known limits, how to run eval + replay.
- 90-s demo recording per PRD §12 script.
- Push public GitHub repo (user creates the repo; `git push` with remote) — verify `.env`/`data/` never uploaded (`git check-ignore` + logged-out browser check of the repo).
- Run the PRD §15 checklist top-to-bottom.

---

## Checkpoints where the plan stops and asks exactly one question

| Before task | Need from user |
|---|---|
| 1 | `MODEL_API_KEY` in `.env` (and key for gateway if fallback needed) |
| 2 | One real assembly photo → `data/images/` |
| 3 | One real 10–20 s clip → re-encoded MP4 |
| 5 | Dev clips (~6–10) + held-out (~6) with per-step expected verdicts |
| 7 | All clips filmed and labelled |
| 10 | Push to GitHub, demo recording |

## Definition of done (from AGENT_PROMPT.md)

- `pytest` green; `python -m scripts.smoke_test` green; one-command run (`uvicorn stepproof.api:app`).
- Demo works in replay mode with the network disabled.
- `eval/RESULTS.md` has real numbers from real clips, **including failures**.
- README documents setup, parameters, model/provider disclosure, known limitations.
