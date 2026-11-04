# StepProof — Method

This document explains *how* StepProof works and *why* each design choice exists, so the claims in `eval/RESULTS.md` can be analyzed rather than taken on trust. Diagrams: [`docs/ARCHITECTURE_DIAGRAMS.md`](ARCHITECTURE_DIAGRAMS.md).

## 1. Thesis

A procedure that humans repeat can be captured once as a **Procedure** — ordered steps, how to find each target, and a check that proves completion. If a language model is used only to *perceive and propose*, and deterministic code is used to *decide, enforce safety and verify*, then the same model becomes:

- **cheaper** — after the first run, execution needs no model;
- **more repeatable** — replay is deterministic; variance comes only from the environment;
- **safer** — untrusted page content has no path into control flow;
- **more accurate** — success is measured by code against the page, not reported by the model.

StepProof is that architecture, implemented for the browser (v2) and for physical-world procedure verification from video (v1).

## 2. The invariant: models perceive, code decides

Every model call in StepProof produces a *proposal* in a strict schema. Three pieces of code sit between any proposal and any effect:

1. **Validator** — rejects malformed or vacuous output (e.g. a success check that would pass on any page). Rejected output is an error, never a guess.
2. **Safety gate** — classifies each proposed action as `safe`, `reversible` or `irreversible`; checks the target domain against the allowlist; checks per-run and per-session budgets (tokens, frames). Irreversible actions pause for human approval. The model may *request* approval; it can never relax a class, add a domain, or raise a budget.
3. **Verifier** — runs the Procedure's success checks (`url`, `text_visible`, `element_state`, `extracted_value`) against the live page and emits pass/fail with before/after evidence.

The consequence is an auditable boundary: a judge can read the gate and verifier code and know the full set of ways the system can act, independent of model behaviour.

## 3. Learning a Procedure

**Sources.** (a) A human demonstration recorded by the Monitor — clicks, inputs, navigations — with optional spoken narration (Muse Voice Transcribe, browser speech as fallback). (b) The agent's own successful trace from a goal-only run.

**Compilation.** Muse Spark 1.3 receives the recorded events and narration and returns a Procedure as schema-constrained JSON: steps with action type, multiple locators per target (id, visible text, role, CSS, XPath), parametrised **slots** (e.g. vendor, amount) and success checks. The compiler is asked for structure, not judgment; code then:

- de-duplicates and orders steps, drops no-op events;
- keeps every locator that uniquely resolved during recording (recorded confidence stored);
- rejects vacuous checks and steps without a resolvable target;
- signs the Procedure with a device key so the executor only runs what was compiled here or explicitly imported.

**Why multiple locators.** UI drift is the dominant failure of replay-based automation. Several independent locators per element give the executor a fall-through chain before any model is consulted (standard practice in self-healing test automation).

**Learning from the agent's own run** turns the open-ended agent into a one-time compiler: run 1 pays tokens; runs 2…N replay for free. This is the mechanism behind the token numbers in the results.

## 4. Executing

**Learned replay** walks the Procedure deterministically: resolve target via locator chain → act → verify step postcondition → next. Zero model calls unless healing is needed. Slots are filled from the run request; a small model call may fill a slot only when the request leaves it open.

**Goal-only agent** (for tasks without a Procedure): observe → propose → gate → act → verify, one tool call per step. Observation is a *compact element list* (interactive elements with role, text, state) rather than raw DOM or screenshots — this is where most web-agent tokens go, and it is the main lever for cost. Budgets, an anti-stagnation breaker and a kill switch bound every run.

**Human in charge.** At any point the operator can pause, take the browser, perform a step manually, and resume; the run log records who did what. Approval requests are explicit state transitions (`AWAITING_APPROVAL`) visible in the UI and the SSE stream.

## 5. Healing

When a step's target cannot be found:

1. **Locator fall-through** (code, free).
2. **Visual grounding** — one Muse Spark 1.3 call with a screenshot asks for the target's coordinates; code then re-checks that the element at those coordinates matches the expected role/text before acting.
3. **SAM 3.1 segmentation** — text-prompted mask → bounding box, same code re-check; masks rendered via `meta_sam_parser` for evidence.
4. **Human review** — never guess.

A successful heal appends the new locator to the Procedure, so the Procedure improves with use. Measured on 16 real screenshots including mutated layouts: 15/16 (93.8% recovery). Both numbers are in [`eval/RESULTS.md`](../eval/RESULTS.md).

## 6. Proving

Each run ends with: per-step verdicts, the success-check results, before/after screenshots, a hash-chained audit of actions (who/what/when, PII-redacted), the models actually used (including any fallback), and usage (tokens, calls, frames, wall time) read from the API's `usage` field. The model's own `finish` message is recorded but **never** used to decide success; the gap between the two is reported as the *overclaim rate*.

## 7. Safety model

- **Allowlist** of domains; navigation off-list is denied in code.
- **Risk classes** per action type and target (submit/pay/delete ⇒ irreversible ⇒ approval).
- **Injection boundary** — page text is data. For learned Procedures the plan was fixed before the page was read, so there is no path from content to control flow (the CaMeL design pattern). For the goal agent, proposals derived from page text still pass through the same gate; the hostile demo page tests this (`injection_hold`).
- **Budgets** — a tripwire caps frames and tokens per run and per session *before* calls are issued.
- **Fail-closed PII redaction** in logs and audit.
- **Model fallback with disclosure** — `muse-spark-1.3` → `muse-spark-1.1` on 404, surfaced in `/api/v2/health` and every report. 429/5xx get bounded retries; 4xx auth/validation errors are surfaced, never retried.

## 8. Evaluation protocol

- **Tasks:** `expense_filed`, `inventory_restock` on local demo sites, plus a public practice-site run.
- **Conditions:** A goal-only agent (Spark 1.3 + safety layer); B learned replay; C recorded human baseline; D Procedure learned from the agent's own trace.
- **Runs:** N = 5 live per condition per task where live is required; otherwise replay/offline.
- **Metrics:** success by code check; pass@1; pass^k reported only when N ≥ k; tokens and calls from `usage`; wall time; overclaim rate; `gate_denied` and `injection_hold` on the hostile page.
- **Honesty rules:** thresholds are not tuned on reported runs; cut experiments stay in the report with their numbers; every non-pass has a cause; raw JSON is committed next to the summary.

Headline (details in [`eval/RESULTS.md`](../eval/RESULTS.md)): learned replay 10/10, 0 tokens, 0.10 s per run; goal-only agent 10/10, 152,139 tokens over 10 runs, 12.6–26.4 s per run; overclaims 0/10; injection hold true. Because both A and B succeeded on every run, the measured advantage is **cost and latency with equal success**, not reliability; the tasks were not hard enough to separate reliability.

## 9. v1 — physical procedure verification

A filmed clip is probed with OpenCV; SAM 3.1 video tracks each concept named in a `ProcedureSpec` (one request per concept, parallel, cached), returning per-frame boxes, confidences and stable object IDs parsed from the real wire format (fixtures pinned in [`tests/fixtures/`](../tests/fixtures/)). Deterministic rules decide each step — stable count over N frames, persistence to the end unless `persist=false`, ordering via `after`, flicker or low confidence ⇒ `review`. Muse Spark answers a state question only where the spec asks for one, on a cropped evidence frame, as yes/no/uncertain. An eval harness reports strict and escalated precision/recall, review rate and latency. The engine is tested end to end.

## 10. Limitations

- Run 1 is not cheaper: it costs a demonstration or a full agent run.
- Replay is brittle beyond locator drift and visual grounding; a redesigned page defeats it and escalates to review.
- Tasks requiring runtime judgment still call the model; slots reduce but do not remove this.
- Benchmarks use two tasks on controlled sites plus one public practice site; this is not a web-scale claim.
- v1 benchmark numbers on synthetic clips are a frame-budget comparison; SAM returned no detections on synthetic MJPG frames, so accuracy was not measurable there.

## 11. Relation to prior work

StepProof combines known ideas rather than inventing a new one, and says so: skill reuse from agent trajectories (Voyager; Agent Workflow Memory), control-flow isolation from untrusted data (CaMeL), reliability measured as pass^k (τ-bench), functional success evaluation outside the model (WebArena-style evaluators), and self-healing locators from test automation. The contribution is the integrated system — human-taught and self-taught Procedures, a code-owned safety boundary, tiered healing with code re-checks, and a measured cost/safety comparison on the same model.

