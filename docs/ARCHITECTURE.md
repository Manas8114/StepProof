# StepProof — Architecture

Two generations live in one repo. **v1 (frozen)** is a camera-verify pipeline; **v2 (active)**
is a browser "procedure companion" — learn a task by watching, do it with you in charge,
prove the outcome. This page describes v2 (the submission) and how v1 relates.

## The core idea, in one line
A natural-language **goal** or a **watched demonstration** becomes a checkable
**Procedure**. The system *executes* it in a sandboxed browser, and **deterministic code —
never the model — decides pass/fail**. The model only *perceives* (reads the screen,
proposes the next action). Everything is logged and linked to evidence screenshots.

## Two execution paths (both verified)

```
                 goal (typed / spoken)                 watched demo (Monitor)
                        │                                      │
                        ▼                                      ▼
              Muse agent loop                          Recorder (multi-locator + narration)
            (perceive → propose)        ── compiles to ──►   Procedure (JSON, editable)
                        │                                      │
                        │   safety gate (code-first)           │
                        ▼                                      ▼
              open-ended agent            learned / manual Procedure
                        │                                      │
                        └──────────────►  deterministic executor
                                           (self-healing locators,
                                            approval gates,
                                            success checks + evidence)
```

- **Open-ended** (`agent/loop.py`): Muse Spark sees a compact element list + a
  password-masked screenshot, returns *one* tool call per turn (Meta's flat tool shape).
  Code classifies each action *first*; irreversible/external actions hit an approval gate.
- **Deterministic** (`agent/executor.py`): replay a `Procedure` step by step. If a DOM
  locator breaks, it **self-heals** by falling through the recorded multi-locators, and
  (optionally) by **vision grounding** (`browser/vision_heal.py`).

Both paths end in **success checks** (`checks.py`) — pure code over browser state:
`url_contains`, `text_visible`, `element_state`, `value_equals`. A verdict is linked to an
evidence screenshot. The model is **not** in this decision.

## Component map

| Path | Responsibility | Notes |
|---|---|---|
| `browser/session.py` | `TinyBrowser` — Playwright Chromium in a worker thread | one page; JPEG screenshot stream; human-input forwarding; kill switch; password fields masked; allowlist-gated `goto` |
| `browser/observe.py` | compact interactive-element list (role/name/box) from the DOM/aria tree | what the model reads; password values excluded by construction |
| `browser/actions.py` | `execute_action` (click/type/select/scroll/goto/wait) + **code-first safety** classification (`classify_action`) | model may only *escalate* a gate, never remove one |
| `browser/vision_heal.py` | visual re-locate when DOM locators fail — Muse grounding first, SAM fallback | **experiment: CUT (41.7% < 70%)**; kept as an honest result |
| `agent/loop.py` | `AgentLoop` — observe → model tool-call → gate → act → log | budgets (steps/wall/model calls), **circuit breaker** on consecutive model errors, action-recovery retry |
| `agent/state.py` | explicit `StateMachine` (IDLE/PLANNING/RUNNING/PAUSED_HUMAN/AWAITING_APPROVAL/DONE/ERROR) | pause honoured at the next action boundary |
| `agent/executor.py` | `execute_procedure` — deterministic, self-healing, evidence-linked | the "learned" condition of the eval |
| `agent/model.py` | `MuseAgentModel` (live, flat tools) + `ScriptedModel` (offline tests) | the model is *pluggable* — tests run with no API |
| `learn/recorder.py` | `Recorder` — captures human actions as **multi-locators + timestamped narration** | each action records css / role / text locators for self-healing |
| `learn/compile.py` | `compile_to_procedure` + `sanitize` — trace → editable `Procedure` | code sanitises; the model (optional) phrases intent |
| `proc.py` | `Procedure` / `Step` / `Locator` data model | pure data, no model calls |
| `checks.py` | deterministic success checks; every verdict gets an evidence screenshot | the "Verify" pillar |
| `coach/efficiency.py` | `run_detectors` (redundant nav, loops, extra steps vs human) + `compare_runs` | **code measures; the model only phrases** the suggestion |
| `coach/voice.py` | TTS via browser `speechSynthesis` (no dep); STT via Meta `muse-voice-transcribe-1.0` → browser Web Speech fallback (disclosed) | short spoken lines + a text equivalent always |
| `events.py` | typed `EventBus` → **SSE** stream (`/events`) | replaces polling; drives the live UI + tour |
| `api_v2.py` | FastAPI app: serves demo sites (`/site/*`), `/events`, `/api/v2/*`, and the **tour** endpoints | one command: `uvicorn stepproof.api_v2:app --port 8011` |
| `demo/tour.py` | 4-beat guided showcase (Learn / Approve / Takeover / Prove) + dated offline replay | records `data/tour_runs/<date>.json` |
| `demo_sites/` | `expense`, `inventory`, `hostile` | deterministic local targets — repeatable, safe, measurable |

## The safety model (judges test this)
- **Allowlist:** `goto` outside the sandbox is *refused and explained* (code, not model).
- **Approval gates:** irreversible/external actions (`submit`, `pay`, `delete`, …) are
  classified **code-first**; the model can only *add* a gate. In the UI a human clicks Allow/Deny.
- **Credentials:** password fields are masked in the screenshot stream and never read, stored, logged.
- **Budgets + circuit breaker:** step / wall-time / model-call budgets; consecutive model errors
  stop the run cleanly instead of hanging.
- **Audit:** full action log with before/after state + evidence screenshots; secrets redacted.
- **Injection defence:** page text is treated as untrusted data — it cannot change the goal,
  the allowlist, or the safety rules. Proven by the `hostile` demo site and `injection_hold` eval.

## v1 ↔ v2 relationship
- **v1 (frozen, optional):** `rules.py`, `wire.py`, `pipeline.py`, `providers/{sam_api,muse}.py`,
  `store.py`, `api.py` — the camera-verify path. Kept green and importable; **not** the main flow.
- **Shared:** `config.py` (env), `events.py`, `checks.py`, `coach/`, and the provider
  interfaces. v2 reuses SAM 3.1 only in the (cut) vision-self-heal experiment.

## Data / artifact locations
| Artifact | Location |
|---|---|
| learned procedures | `data/procedures/*.json` |
| tour recordings (dated, replayable) | `data/tour_runs/<date>.json` |
| evidence screenshots | `media/` |
| eval outputs | `eval/results_v2.json`, `eval/live_agent_v2.json`, `eval/vision_heal_results.json` |
| live trace | `eval/live_agent_trace.json` |
