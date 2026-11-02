# StepProof — Completion & Showcase Prompt (master)

Paste everything below the line into your coding agent from the repo root (`stepproof/`).
This prompt **supersedes and consolidates** `SAM_VISION_UPGRADE_PROMPT.md` and `SAM_UPGRADE_PROMPT.md` (you may delete those two once this one runs green).

## Ground rules (from AGENT_PROMPT.md — non-negotiable)
1. Never fabricate results. No invented metrics, clips, API responses, or model names. If a model call cannot be verified, stop and report the exact error.
2. Verify API shapes against the Meta docs before changing a call (`dev.meta.ai/docs` — Responses API, structured output, image understanding, SAM).
3. Models perceive, code decides. Pass/fail and safety logic live in `rules.py` / `actions.py` / `checks.py` and stay free of model calls.
4. Secrets only in `.env`. No new framework dependencies (only `meta-sam-parser` for masks).
5. Commit after each task. Offline `pytest` must stay green at every commit.
6. The synthetic dataset (`scripts/make_dataset.py`) demonstrates mechanics only — it must never be reported as model performance.

## Context (what exists — do not re-build)
- `providers/sam_api.py` + `wire.py` + `pipeline.py` — SAM 3.1 v1 video verify, working, cached/replayable.
- `browser/vision_heal.py` — `MuseVisionHealer` (primary) + `SamVisionHealer` (SAM 3.1 fallback) + `make_selfheal(browser)`. Measured: SAM 5/12 (41.7%), Muse grounding 0 usable (`tool_choice` 400) — `eval/vision_heal_results.json`, recorded as CUT in README/RESULTS.
- `agent/executor.py:execute_procedure(..., vision_selfheal=None)` — the hook exists but **`api_v2.py` never passes it**, so the live UI never self-heals visually.
- `browser/actions.py` — click supports `x,y` (`click_box`); **type/fill require a DOM selector**.
- `browser/session.py` — worker-thread Playwright; has `click_box`, **no `fill_at`**.
- `proc.py` — v2 `Procedure`/`Step`/`Locator` (Step has `description`, `action`, `arg`, `locators` — **no concept field yet**).
- `learn/recorder.py` + `learn/compile.py` — Monitor recording → compiled Procedure.
- `demo/tour.py` — 4-beat guided tour (learn / approve+gate / takeover / prove) with dated offline replay in `data/tour_runs/`.
- `demo_sites/` — expense, inventory, hostile.
- PRD: physical/autonomous robots are **out of scope**; SAM "dynamic" = open-vocab perception + cross-frame tracking. P1 stretch = mask overlays.

## Task order (do not skip ahead; commit after each)

### T1. Fix Muse grounding (unblocks the primary healer)
Reproduce the 400 in `MuseVisionHealer.heal`: `tool_choice="locate_element"` is rejected by the Responses API. Check the structured-output / image-understanding docs, use the correct shape (function-object form of `tool_choice`, or `auto` + parse the call), keep the `LOCATE_TOOL` schema, and treat confidence-0 / no-box as "not visible". Unit test against the cached-wire harness where possible; the live check is `python -m scripts.test_vision_heal --muse-only` — report the real number.

### T2. Raise SAM concept quality (the main lever on 41.7%)
Add `vision_concept: str = ""` to `proc.py:Step` (backward compatible: `from_dict` default, `to_dict` included). In `learn/compile.py` + `learn/recorder.py`: derive one short noun phrase per step from the recorded element (e.g. element labelled "Vendor" → `vision_concept: "Vendor text input"`; `#submit` → `"Submit claim button"`). `SamVisionHealer.heal`: use `step.vision_concept` when present, else `step.description` (executor passes the step, not just the description). Document in README that SAM wants one noun phrase, not sentences.

### T3. Visual fill (make "UI changed, still fills the form" true)
- `browser/session.py`: add op `fill_at {x, y, text, enter=False}` → `mouse.click(x, y); keyboard.type(text); [press Enter]`. Password-masked fields: the element-at lookup (below) must refuse to type into `input[type=password]` — never type blindly into an unknown field.
- `browser/actions.py`: for `type`/`fill`, when `arg` has `x,y` and no `selector`, route to `fill_at`; detail string marks it vision-healed.
- `agent/executor.py` heal path: for type/fill steps, merge the step's recorded `text`/`value` into the healed `{x,y}` arg before `execute_action`.

### T4. Wire self-heal into the live app (it is dead code today)
- `config.py`: `VISION_SELFHEAL = _e("STEPPROOF_VISION_SELFHEAL", "0") == "1"`.
- `api_v2.py`: at startup, build `ms = MuseVisionHealer()`, `sam = SamVisionHealer(...)` only when the flag is on (and `MODEL_API_KEY` present); pass `vision_selfheal=make_selfheal(ms, sam, _browser)` to **every** `execute_procedure` call (the Tour at ~line 46/313 and `/api/v2/procedure/run` at ~262). Publish a `vision_heal` event on the SSE bus naming which healer grounded, the box, and confidence — the UI event feed must visibly show "locators exhausted → SAM 3.1 grounded 'Submit button' @ (x,y) conf 0.8 → click landed".
- `/api/v2/health`: report the flag + active healer models/hosts (disclosure rule).
- Default stays OFF for the unattended tour and tests (determinism); the live app enables it via `.env`.

### T5. Gate healed actions (code-first safety — current hole)
Today the approval gate classifies the *original* `step.arg`; a vision-healed click lands ungated. In `executor.py`, after a heal succeeds, re-classify the *healed* target: for click/select, resolve the element's visible label at the clicked point (a read-only `eval` op, or the existing element-at lookup) and run it through `classify_element_text` (`IRREVERSIBLE_HINTS`/`EXTERNAL_HINTS`). If the step's original arg/description already matches a hint token, or the label is unresolvable → treat as external/irreversible and require `approve_fn` to approve the healed execution; never run ungated. Tests: a vision-healed click on a Submit/Discard-class target is blocked without approval; an unresolvable label escalates.

### T6. UI-mutation demo site + 5th tour beat (the showcase centerpiece)
- New `demo_sites/mutated/`: same expense flow (vendor, category, amount, Submit) but on every load JS regenerates element ids/classes and shuffles DOM order, so **all recorded CSS/role/text locators break by design**. `?STABLE=1` restores canonical selectors (the "before" run).
- `demo/tour.py`: add **BEAT 5 · HEAL** — record the expense procedure on the stable site, run it against the mutated site with self-heal armed; stream the fallthrough exhaustion → visual grounding → gated healed click → fill_at on renamed inputs → deterministic success check passing. Record the healed-step metrics into `data/tour_runs/<date>.json` so the offline replay covers beat 5 too (replay uses the recorded coordinates + labels, no live model).
- Labels must be precise: DOM multi-locator self-heal stays the primary path; vision is the last resort.
- Mount the site in `api_v2.py` and add its host to the browser allowlist.

### T7. Re-measure honestly
Extend `scripts/test_vision_heal.py` CASES: 4 mutated-site cases (inputs + button), pass `vision_concept` phrases, run both healers + combined. Update `eval/vision_heal_results.json`, rewrite the `eval/RESULTS.md` §3 table **failures included**, keep the 0.7 keep/cut threshold, and rewrite the README "Vision self-heal" section to match the new measured state (CUT → KEPT, or stay CUT with the reason).

### T8. Mask evidence overlay (P1 stretch, "show the proof")
For the winning detection, decode SAM's `one_bit` mask with `meta_sam_parser` (`decode_mask_to_rle` / `decode_mask_to_svg_path` — verify signatures from docstrings first), composite it onto the evidence screenshot in `data/evidence/`, and attach the path to the `vision_heal` event so the UI shows exactly which pixels the model saw. Box outline is the fallback when mask decode fails.

### T9. Animated tracking view (dynamic story, stretch)
The v1 pipeline already gets per-frame tracked object IDs. Add a read-only UI mode (v1 app or a tour beat, your call) that animates the tracked boxes over a short clip: stable IDs, per-frame positions, confidence-tinted outlines, no new model calls (serve from cache). This is the "SAM 3.1 tracks moving objects with zero training data" proof.

### T10. Close-out
- `pytest` fully green with self-heal OFF; online tour green with it ON.
- README: rewrite the Vision self-heal section, add the mutated site + beat 5 to the tour docs, keep every model/host disclosure current, note any gateway substitution.
- `SUBMISSION_CHECKLIST.md`: add the new items (health disclosure, gate test, results file).

## Definition of done
1. Live app with `STEPPROOF_VISION_SELFHEAL=true`: a procedure with dead locators heals itself end-to-end — click **and** fill — on the mutated site, with the gating test in place.
2. Beat 5 runs in the unattended tour and replays offline from its trace.
3. `eval/vision_heal_results.json` + `eval/RESULTS.md` carry the fresh, honest numbers (per-healer, per-site, failures included).
4. Muse grounding either works (report the hit-rate) or is documented broken with the exact error — no silent 0%.
5. No new framework deps; commit-per-task history; offline tests never hit the API.

## Cut line (timebox)
Priority if time runs out: **T5 (safety) > T1 > T4 > T3 > T6 > T7**, then stretch T8/T9. If combined grounding still measures < 0.5 after T1+T2, keep the wiring (it's the safe design), re-mark it in the README as documented fallback, and lead the showcase with DOM self-heal + the mutation beat, with vision healing framed as "when even the DOM is hostile, SAM 3.1 catches it". Never report synthetic numbers as model performance.
