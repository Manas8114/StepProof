# StepProof — Post-Freeze Product Prompt

Paste everything below the line into your coding agent from the repo root (`stepproof/`).
This prompt **follows on from** `STEPPROOF_COMPLETION_PROMPT.md` (T1–T10, P0–P3,
model-fallback, and the genuine human-run recorder are already committed and green —
do NOT rebuild them). It defines the post-freeze product phase: a **trust spine**
(budget tripwire, signed portable artifacts, hash-chained audit + evidence bundles)
on top of which three product modes are built: **A self-healing web tests**,
**B proof & audit evidence**, **C operator skill compiler**.

## Design decisions already made (do not re-litigate)

- **Local-first.** Everything lives on the user's machine: browser, SAM cache,
  procedures, recordings, audit log, evidence. Only the model APIs are remote.
  No hosted service in this prompt.
- **Trust spine first.** Every mode reads from the same audit log and signs with
  the same artifact format. Tasks I1–I3 precede A/B/C and A/B/C build on them.
- **No new framework dependencies.** Stdlib + the existing `requirements.txt`
  only (`meta-sam-parser` remains the one permitted optional dep). Signing =
  stdlib `hashlib`/`hmac`/`uuid`. JUnit/HTML reports = stdlib `xml`/string
  templates. Scheduling = OS-native (Task Scheduler / cron / launchd), documented
  not built.
- **PII redaction before the API is deliberately DEFERRED** (it was on the table,
  not chosen for this phase). If a task in this prompt makes it trivial
  (<30 lines) to add a redaction pass over outbound screenshots, add it and mark
  it clearly; otherwise leave it to the next phase.
- **Honesty rules are load-bearing.** Every "real" claim needs a dated evidence
  path. A zero result is a finding, never a redaction.

## Ground rules (non-negotiable, inherited from AGENT_PROMPT.md)

1. Never fabricate results. No invented metrics, clips, API responses, model
   names, or "recorded" numbers that were not recorded. If a model call cannot be
   verified, stop and report the exact error.
2. Verify API shapes against the Meta docs before changing a call
   (`dev.meta.ai/docs` — Responses API, structured output, image understanding,
   SAM). Record what you verified in `docs/VERIFIED.md`.
3. Models perceive, code decides. Pass/fail, safety, signing, and audit logic
   live in deterministic code and stay free of model calls.
4. Secrets only in `.env` (`MODEL_API_KEY`). Device signing keys live in
   `data/keys/` (gitignored). No new framework dependencies.
5. Commit after each task. Offline `pytest` must stay green at every commit
   (suite is 101 tests as of this prompt).
6. The synthetic dataset demonstrates mechanics only — it must never be reported
   as model performance.
7. Model substitutions must be disclosed (the 1.3→1.1 fallback already does this
   in `/api/v2/health` and run reports — keep it extended, never silent).
8. Offline tests never hit the API: use wire fixtures, the fake meter, and the
   fake client pattern already in `tests/test_model_fallback.py`.

## Context (what exists — do not re-build; verify signatures from source before editing)

- **v1 pipeline** (`stepproof/pipeline.py` `run_inspection`, `rules.py` `Params`,
  `providers/sam_api.py` + `wire.py`, `video.py`, `optimize.py` preprocessors
  with ablation flags) — SAM 3.1 video verify, cached/replayable.
- **v2 browser agent** (`stepproof/agent/` `AgentLoop` + `Budgets(max_steps,
  max_wall_s, max_model_calls)` + `MuseAgentModel` (records `active_model`,
  `fell_back`); `browser/session.py` TinyBrowser worker-thread Playwright with
  `click_box`/`fill_at`; `browser/vision_heal.py` `MuseVisionHealer` +
  `SamVisionHealer` + `make_selfheal`; `learn/recorder.py` + `learn/compile.py`
  Monitor recording → compiled Procedure; `proc.py` `Procedure`/`Step`/`Locator`
  with a `parameters: dict` field that is **not yet wired** (that is task C2);
  `checks.py` deterministic `text_visible`/`element_state` checks + `all_pass`).
- **Metering & fallback** — `stepproof/usage.py` (`UsageMeter`, `set_meter`,
  `meter.summary()`, `meter.cumulative()` → `{calls, billed_frames,
  total_tokens}`); `stepproof/model_fallback.py`
  (`responses_with_fallback(client, model, **kw) -> (resp, model_used, fell_back)`);
  `/api/v2/cost` endpoint + live UI cost readout in `stepproof/static/index_v2.html`.
- **Safety (already shipped)** — `companion/advisor_a.py` file-delete advisor;
  `robot/supervisor.py` + `robot/mcp_server.py` (Supervisor is the only path to
  any adapter; e-stop measured); `demo_sites/` (expense, inventory, hostile,
  mutated, public).
- **Eval & benchmarks** — `eval/run_eval_v2.py` conditions A (live goal-only
  agent), B (learned-procedure replay), C (**reads `data/human_runs/<task>.json`
  written by `scripts/record_human_run.py`; SKIPPED honestly when absent —
  the old hardcoded 42.0s/28.0s are gone**); `scripts/benchmark.py` (live
  benchmark on held-out clips; the committed result is an **honest null** —
  every SAM call returned 0 boxes on the synthetic clips, all conditions tie on
  accuracy, the differentiator measured is 83% fewer billed frames + latency).
- **Docs** — `docs/ROBOT_BRIDGE.md` (sim-only robot, hardware suggestions
  marked unverified); `docs/VERIFIED.md` **does not exist yet** (task G2).

---

## Task order: G → I → A → B → C.  Commit after each.  TDD for every task.

### G. Close the known honesty gaps (do these FIRST — reviewers read these first)

- **G1 — Regenerate `eval/results_v2.json` with honest condition C.** The
  committed artifact still carries the pre-recorder *hardcoded* C numbers
  ("42.0s / 28.0s") labeled "recorded human baseline". Re-run
  `python -m eval.run_eval_v2` (C will now be SKIPPED unless
  `data/human_runs/` has genuine recordings — if the human has recorded, the
  numbers are theirs; if not, the skip line is the honest state). Update
  `eval/RESULTS.md` to match, including the skip/reason text. *No human
  recordings may be invented to fill the gap.*
- **G2 — `docs/VERIFIED.md`.** Record, dated: SAM billing model (per-frame,
  50-frame minimum — verified from Meta pricing docs or explicitly "assumed,
  not verified"), the Responses API shapes used (tool shape, `tool_choice`,
  image input), the 1.3→1.1 fallback + disclosure, and whether Muse Spark
  consumes MCP directly or via a function-calling bridge (check the docs; if
  unknowable, say so and mark the bridge "unverified").
- **G3 — README v2-first flip + stale counts.** Lead with the browser
  companion/learn-execute-verify story (v2), keep the SAM video-verify section
  (v1) honest about the null benchmark result. Fix every stale test count
  ("35 tests" in README, "22 tests" in `SUBMISSION_CHECKLIST.md` → actual).
  Keep every model/host disclosure current; note the gateway substitution
  (muse-spark-1.1) where it can occur.
- **G4 — A3 no-safety injection baseline.** Add a fourth condition to
  `eval/run_eval_v2.py`: `injection_no_safety` — the goal-only agent run on
  the **hostile** demo site with the approval gate *disabled* and the sandbox
  auto-approver removed, reporting an injection-follow rate (count-based,
  small sample — counts not percentages). Live API; SKIPPED honestly when down.
  Pair it with an **offline mechanics test** (ScriptedModel, deterministic):
  gates ON blocks a scripted dangerous action; gates OFF lets it execute.
  The mechanics are tested, the rate is measured live, both labeled.
- **G5 — `brag-output/` → `docs/media/`** with all reference updates
  (README, docs, any render target in the composition source).

### I. Trust spine (the shared substrate — A/B/C all read from this)

- **I1 — Pre-flight cost estimate + budget tripwire** (`stepproof/budget.py`).
  - `estimate_run(...) -> {"sam_frames_billed": int, "tokens_estimate": int,
    "wall_s_estimate": float}`: SAM frames billed = frames after the free
    preprocessors (the `optimize.py` ablations already compute this), clamped
    to the 50-frame minimum; tokens are labeled **ESTIMATES** (step count ×
    fixed context budget), never billing.
  - `BudgetCap(max_frames, max_tokens, max_wall_s)` — per-run, from `.env`/CLI.
  - `tripwire(meter, cap)` — hooked after every metered call in BOTH the v1
    pipeline and the v2 agent loop; on breach, abort with an explicit
    `aborted_budget` status (a distinct state, not a generic error, not a
    success) and record the abort to the I3 audit log.
  - Tests: fake meter overshoot → abort state recorded; estimate on a known
    procedure/clip → expected N; estimate function is pure (no I/O).
- **I2 — Signed, portable procedure artifacts** (`stepproof/artifact.py`).
  - `sign_procedure(proc, device_key) -> manifest`: SHA-256 of the procedure
    bytes + provenance `{source: monitor|live|learn, recorded_ts, models +
    fallback disclosure, dataset/checksums}` + device id + HMAC-SHA256.
    Stdlib only. Device key: generated on first use into `data/keys/`
    (gitignored); one per machine.
  - `verify_artifact(payload, device_key)`: HMAC + SHA-256 + optional
    deterministic re-check. "Replay on another machine" = the other machine's
    key verifies against the signed manifest (deterministic, no model).
  - Tests: sign/verify round-trip across two distinct keys (two "machines"
    in one process); one-byte flip → rejected; procedure edit after signing
    → SHA mismatch; provenance fields present on a live-learned procedure.
- **I3 — Hash-chained audit log + evidence bundles** (`stepproof/audit.py`,
  `scripts/bundle_run.py`, `scripts/verify_bundle.py`).
  - Append-only JSONL (`data/audit/runs.jsonl`): one record per run/abort/
    heal/fallback, each `{seq, prev_hash, ts, kind, verdict, checks[],
    evidence_paths[], model, fell_back, budget_status}` with
    `hash = sha256(prev_hash + canonical(record))`; `verify_chain(path)`
    detects any tamper or gap.
  - `bundle_run(run_id, out_path) -> tar`: evidence files + manifest + I2
    signature + a self-contained `verify_bundle.py` inside the tar.
    Commands: `python -m scripts.bundle_run <id>`; `python -m scripts.verify_bundle <tar>`.
  - Evidence must be SELF-CONTAINED (screenshots + DOM snapshots from the
    run — B1 re-runs checks against saved evidence, not a live page).
  - Tests: chain verifies clean; one-line tamper → detected; bundle
    round-trips and verifies with no network access (assert zero API calls
    in the verify path).

### A. Self-healing web tests (mode A — the nightly "test that survives a UI redesign")

Package: `stepproof/testmode/`. All of it runs LOCALLY (no server).

- **A1 — Suite runner + CI reports.** `python -m stepproof.testmode.suite
  --procs a.json b.json [--live]` runs each procedure through the v2 executor
  (vision-selfheal armed per `.env`, I1 budget tripwire armed, every run I3
  logged) and writes **JUnit XML** (`reports/junit_*.xml`, stdlib) + a
  single-file **HTML** suite report (`reports/index.html`). Exit codes:
  0 pass / 1 fail / 2 `aborted_budget` / 3 infra (site down).
  Tests: fixture procedure → JUnit XML shape + exit codes (ScriptedModel for
  the fail/infra paths so tests stay offline).
- **A2 — Scheduling (local, OS-native).** The runner supports `--once`,
  `--interval N`, and `--watch` (fs-poll the procedure/JSON + optional
  interval). Document per-OS native scheduling (Windows Task Scheduler /
  cron / launchd) in the README; do NOT build a daemon.
- **A3 — Locator-drift report + gated re-harvest.** From run events
  (the `vision_heal` SSE events already name the healer, box, confidence):
  `stepproof/testmode/drift_report.py` writes `data/drift/<proc>_drift.json`
  (per step: DOM-locators-exhausted?, which healer, conf, box) and
  `python -m stepproof.testmode.drift_report <run_id>` prints the drifted
  steps. `--re-harvest` re-opens the Monitor recorder for ONLY the drifted
  steps, diffs new vs old locators, and **gates the update**: a human
  confirms the new locator set, it re-signs the artifact (I2) and logs the
  re-harvest to the audit chain (I3). No auto-rewrite of selectors, ever.
  Tests: drift JSON shape from a fixture run; re-harvest without confirmation
  changes nothing; confirmed re-harvest produces a new signature + audit
  entry.

### B. Proof & audit evidence (mode B — "proof the procedure was performed, without the original machine")

- **B1 — Independent verifier.** `stepproof/verify_bundle.py` (the same
  module shipped inside every I3 tar): opens a bundle → verifies the
  I2 signature → verifies the I3 hash chain → **re-runs the deterministic
  checks against the SAVED evidence** (DOM snapshots/screenshots, no live
  page, no model by default) → prints a one-page PASS/FAIL + provenance
  report (which model answered, any fallback disclosure, budget status,
  chain intact). A `--live` flag MAY re-run model grounding over the saved
  screenshots and MUST disclose that it did.
  Tests: tamper any of {procedure, evidence, chain, signature} → bundle
  rejected for that specific reason; clean bundle → PASS; verify makes
  zero API calls in default mode.
- **B2 — Real-footage entry point** (`scripts/real_clip.py`). One real
  clip of a procedure (user-provided; **never** the synthetic dataset)
  through the v1 pipeline with the I1 estimate printed BEFORE the run and
  the tripwire armed. Report honestly: zero detections = a published
  finding (the `benchmark.py` findings pattern), not a redaction. This is
  how the footage story gets its first real number; the claim stays
  scoped until it exists.

### C. Operator skill compiler (mode C — "learn a task family once")

Package: `stepproof/skill/`.

- **C1 — From-demo/describe onboarding.** `python -m stepproof.skill.from_demo
  --demo data/recordings/x.json` (or `--describe "file an Acme office
  expense of $42"` → the existing recorder/compile path) → compiled
  Procedure → **I2-signed** artifact in `data/skills/<name>.artifact` + I3
  audit entry. Describe-path output is labeled "unconfirmed until a
  verification run passes its checks."
- **C2 — Slots: wire the dormant `proc.parameters` field into real
  task families.** `compile_family(proc) -> ProcedureFamily =
  {procedure, slots: {name: {type, pattern, safety_class}}}`. Slot
  PROPOSALS are generated from the concrete recorded values (vendor "Acme",
  SKU "WS-1042") but slot selection is **human-gated** (propose, human
  confirms which values are slots — not auto-inferred). `instantiate(family,
  values)` type-validates AND **re-runs the safety hint classification
  per value** (a "Discard"-class value for a slot is a different risk class
  than "File" — per-value, never per-family). Result re-signed (I2).
  Tests: slot inference proposal from a fixture; per-value safety
  re-classification flips risk on a danger value; instantiate with a
  bad-typed value is rejected before execution; signed family round-trip.
- **C3 — Gated re-teach flow.** When a new slot value fails its checks or
  drifts (A3 signal): the recorder re-opens for that STEP VARIANT only →
  family entry updated → re-signed → audit-logged with the triggering
  run id. No silent family mutation; every family version is a new
  signature + chain entry.

## Honesty guardrails (apply to every task above)

- Every new claim in docs/README points at a dated artifact
  (`data/audit/…`, `reports/…`, `eval/…`). "Real-world" claims without one
  are written as *unverified*, with the exact command that would produce it.
- Estimates are labeled ESTIMATE; billed/measured numbers come from
  `UsageMeter` only.
- `aborted_budget` is a first-class run status, never folded into
  pass/fail.
- Update `docs/VERIFIED.md` in the same commit that relies on a verified
  fact; update README disclosures in the same commit that changes a model
  or host.

## Cut line (timebox, if time runs out)

Order: **G > I > A > B > C**, and within each: **safety > honesty > speed**.
If you can only deliver 20 %: G1, G2, I1, I3 (the spine without the
verifier), A1. B1 and C2 are the two that make the spine *pay*; if A
lands, prefer B1 over C.

## Definition of done

1. Offline `pytest` green at every commit; live conditions honestly SKIPPED
   when the API is down.
2. A bundle made on machine A verifies on machine B with **zero network
   access**, rejecting any tamper (procedure, evidence, chain, signature).
3. A runaway procedure aborts with `aborted_budget` BEFORE exceeding its cap
   (test-asserted with the fake meter; live cap honored via the tripwire in
   both v1 and v2).
4. A UI-redesign run (the mutated site) produces: a JUnit + HTML report, a
   drift report naming the exact steps, and a gated re-harvest that
   re-signs the artifact — with every step audit-logged.
5. No new framework dependencies; every model/host/substitution disclosed;
   `docs/VERIFIED.md` current; no synthetic number reported as model
   performance anywhere.
