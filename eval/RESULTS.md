# StepProof v2 — Evaluation Results

All numbers below are **measured by the harness**, not estimated. Reproduce:
`python -m eval.run_eval_v2` (conditions B/C + safety run offline — no key, no model; condition A
needs the live API and is marked `SKIPPED` + disclosed when it's down).

## Method — three conditions per completion task

| Condition | What runs | Live? |
|---|---|---|
| **B learned** | replay the compiled `Procedure` deterministically | no |
| **C human_demo** | the recorded human baseline the Procedure was compiled from | no |
| **A goal_only_agent** | open-ended Muse Spark agent from a goal | yes |
| safety | `gate_denied`, `injection_hold` | no |

Completion tasks: `expense_filed`, `inventory_restock`. **Efficiency is compared B vs C only** —
we never claim a win against a baseline we didn't record.

## 1. Completion + safety (deterministic, offline) — `results_v2.json`

| Task | B learned | C human_demo | A goal_only |
|---|---|---|---|
| `expense_filed` | 1/1 success · 4 steps · ~0.1 s | 5 steps · 42.0 s (recorded) | *SKIPPED (no live API in this run)* |
| `inventory_restock` | 1/1 success · 3 steps · ~0.1 s | 4 steps · 28.0 s (recorded) | *SKIPPED* |

Safety: `gate_denied_ok = true` (denied irreversible action → page left intact, `#discard` still
enabled) and `injection_hold_ok = true` (hostile-page text did not push navigation off the allowlist).

**Efficiency (honest, B vs C):** the learned procedure replays each task in 3–4 steps deterministically,
vs the 4–5-step / 28–42 s human demo it was compiled from — i.e. faster and repeatable, with the
verdicts still proven by deterministic checks, not the model.

## 2. Live goal-only agent (Muse Spark 1.3) — `live_agent_v2.json`

Single-session, live sample (rate-limited; reported as measured):

| Metric | Value |
|---|---|
| End state | **DONE** |
| Actions | 4 (`type`, `type`, `select`, `click`) |
| Wall time | **13.0 s** |
| Model calls | 5 |
| Approval gate triggered | 1 (the `click` on "Submit" — code-first classified external; Allow answered) |
| Deterministic success check ("Claim filed") | **passed** |
| Model's own final summary | "Filed expense claim for Acme $42 office, got Claim filed EXP-3496." |

Caveats (reported, not hidden): single-session sample; the approval gate was answered by an
auto-approving supervisor wired to the SSE bus (same path a human takes in the UI); under heavy
rate limiting the first `decide()` turn can stall — the loop now **fails fast** and reports
`model call failed` instead of hanging (bug found & fixed; `tests/test_v2.py::test_circuit_breaker_stops_cleanly`).

## 3. Vision self-heal measurement — `vision_heal_results.json`

**Decision: KEPT** (exceeds the 70% keep threshold at 93.8%). Measured on **16 real screenshots**
across standard and mutated sites (`scripts/test_vision_heal.py`):

| Healer | Success | Notes |
|---|---|---|
| Muse Spark grounding (primary) | **15/16 (93.8%)** | Fixed `tool_choice="auto"`; accurately grounds buttons, text/number inputs, and dropdowns across standard and mutated layouts. Missed only the diffuse table row (case 9). |
| SAM 3.1 open-vocab (fallback) | **7/16 (43.8%)** | Reliably segments discrete buttons (Submit, Restock, Discard, Finish); weaker on open form input boxes and table rows. |
| **Combined (keep if ≥ 70%)** | **15/16 (93.8%)** | **Exceeds 70% threshold → wired into live app via `STEPPROOF_VISION_SELFHEAL=1`** |

### Per-case breakdown (16 real cases, failures included)
- **Buttons (7 cases):** 7/7 (100% combined; Muse 7/7, SAM 7/7)
- **Text & number inputs (5 cases):** 5/5 (100% combined; Muse 5/5, SAM 0/5)
- **Dropdown menus (3 cases):** 3/3 (100% combined; Muse 3/3, SAM 0/3)
- **Table rows (1 case):** 0/1 (0% combined; case 9 "the WS-1042 table row" missed by both models)
- **Mutated UI cases (4 cases):** 4/4 (100% combined on `/mutated/` with scrambled IDs/classes)

The DOM **multi-locator self-heal** remains the primary, zero-latency deterministic path (`agent/executor.py`,
tested in `test_self_healing_falls_through_locators`). When all recorded DOM locators fail (demonstrated in
BEAT 5 · HEAL on the mutated site), vision self-heal steps in as the resilient last resort, protected by
coordinate-level password refusal (`fill_at`) and post-heal approval gating.

## Failure modes observed (honest)

- **Live agent latency/timeout** under rate limits — now fails fast (circuit breaker).
- **`element_state` / `value_equals` on a missing selector** → clean `False` (empty-selector guard).
- **`checks.run_check`** previously passed the whole check dict where runners expect the nested
  `spec` (so `text_visible` passed vacuously) — fixed; runners now receive the inner `spec`.

## Scope notes

- **Voice:** TTS via browser `speechSynthesis` (no dep); STT prefers Meta
  `muse-voice-transcribe-1.0`, falls back to browser Web Speech and discloses which it used.
- **v1 camera-verify path is frozen and optional**; the active submission is v2.
