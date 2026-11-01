# StepProof — Consolidated Hardening, Metrics & Submission Design

Date: 2026-11-01 · Status: approved (full consolidated set; genuine human run recorded Nov 2 by team)
Repo: `stepproof/stepproof` · 35/35 tests green · Chromium present · live Meta API reachable

## Context

Three inputs drive this spec: (a) the external review's 7 ranked risks, (b) a live self-review
that **ran** the system and found the unattended tour ending in ERROR plus gate/allowlist holes,
(c) the "real talk" metrics brief (Voyager/AWM memoization, τ-bench pass^k, CaMeL control-flow
isolation, WebArena-style evaluators). Everything below is measured in the harness, not asserted.

## Verified defects (this spec fixes all of them)

| # | Defect | Evidence |
|---|--------|----------|
| D1 | Unattended tour beat-3 (takeover) → `ERROR: time budget 60s` (2/2 runs + captured trace) | `Tour` uses **live** `MuseAgentModel` in both modes (demo/tour.py:115); beat budget `Budgets(max_wall_s=60)` (tour.py:116) |
| D2 | Selector clicks escape the code-first approval gate | `classify_action` (actions.py:41-47) inspects `arg["name"]` only; agent tool schema exposes `selector` (model.py:15); click branch is selector-first (actions.py:58-61) |
| D3 | `start_site` bypasses the domain allowlist | session.py:33-36 calls worker `goto` directly; reachable via api_v2.py:261 (saved JSON) and recorder.py:35 |
| D4 | Condition C "recorded human baseline" is a hardcoded constant | run_eval_v2.py:57,64 |
| D5 | No 1.3→1.1 model fallback on 404 | model.py:80-87 catches rate/connect/timeout only |
| D6 | No usage/token accounting, no pass^k, no overclaim-rate, no learn-from-own-run, no A3 no-safety baseline | absent |
| D7 | Evidence screenshots land in CWD-relative `media/` (demo_sites/media when run from eval) | executor.py:95-101 |
| D8 | Stale claims: README "14 offline tests" / SUBMISSION_CHECKLIST "22" (actual 35); per-run budgets untested | README.md:12, SUBMISSION_CHECKLIST A4 |

## Workstreams (ordered; each lands with tests; suite must stay green)

### WS-0 — Code fixes (precondition for everything else)
1. **Tour offline determinism.** `Tour.__init__` gains `model_offline: bool`. In unattended
   mode the takeover beat's `AgentLoop` uses `ScriptedModel([type #qty, click Restock, finish])`
   — the documented "stands in for the human" behavior, actually honored. Interactive mode keeps
   the live model. `scripts/run_tour.py` (default unattended) and `api_v2` unattended path switch.
   Re-run the tour; the recorded trace must show all beats `success/DONE`. Add test: unattended
   tour runs with `STEPPROOF_PROVIDER` mock / no API key (ScriptedModel path is key-free).
2. **Selector clicks gate correctly.** `classify_action("click", arg)` resolves the selector's
   label via `tb.observe()` when `arg` has `selector` and no `name`: extract the element text, run
   `classify_element_text`. Unknown selector → escalate to human (never downgrade — the ground
   rule). No-browser-call variant (pure) takes a `label` hint for tests. New tests: `#submit`
   click gates; `#qty` fill doesn't; unknown selector asks.
3. **`start_site` = gated `goto`.** session.py:33-36 routes through the same allowlist check as
   `goto()` (single implementation). Behavior identical for localhost; off-allowlist now refused.
   Test both entry points.
4. **Model fallback + disclosure.** On `APIStatusError` 404/model-not-found from
   `cfg.META_BASE_URL`, retry the call with `MUSE_FALLBACK_MODEL` (default `muse-spark-1.1`,
   env-overridable); record `model_active` + `model_fallback_used` on the client; surface in
   `/api/v2/health` and in run reports (AGENT_PROMPT rule 5). Covers `decide()`, `suggest()`,
   vision-heal grounding. Test with a mocked 404.
5. **Evidence screenshots rooted** (not CWD-relative): `data/evidence/` via `cfg.EVIDENCE`
   (executor.py:95-101); cleanup `demo_sites/media/*` artifacts.
6. **Budgets test**: `Budgets.exceeded` stops a run with `error: budget` (closes D8's half).

### WS-1 — Genuine human baseline (tooling now; capture Nov 2)
- `scripts/record_human_run.py`: serves demo sites, drives the Monitor recorder against a task
  (expense filing / inventory restock), times the real run, writes `data/human_runs/<task>.json`
  `{task, wall_s, steps, actions[], narration[], ts}`.
- `run_eval_v2` condition C reads that artifact; **if missing → C is `SKIPPED (no recorded
  human baseline)`**, never a constant. Delete the hardcoded `human=` dicts (run_eval_v2.py:57,64);
  RESULTS.md + SUBMISSION_CHECKLIST D1 reworded to match.
- Handoff (Nov 2): `python -m scripts.record_human_run --task expense_filed` — one pass each,
  ~5 min total.

### WS-2 — Metrics framework (the "measurable claim")
- **Usage accounting**: `usage` from every `responses.create` (agent/vision/coach/SAM) into
  `RunLog` (`tokens_in/out`, per-call); report per-run and **cumulative-over-N** (harness emits
  it; no cost numbers unless we disclose rates — then optional `rate` fields).
- **pass^k**: live conditions run N≥5 (`--runs 5`); report pass@1 and **pass^5** = probability a
  task succeeds on all 5 (τ-bench definition), per condition A/A3/B. B is deterministic → its
  pass^5 ≈ 1 by construction; that gap is the repeatability argument.
- **Overclaim rate**: every A1 run logs `model_said_done` (finish summary present) vs
  `check_passed` (deterministic check) → `overclaims` count in results.
- **Learn-from-own-run**: `learn/compile.compile_from_agent_trace(history, goal, site, checks)`
  → Procedure (reuses the existing compiler; AWM in one function). After a successful A1 run,
  the harness compiles its trace and replays it (B') — B' success proves the learned procedure
  generalizes without re-reasoning.
- **Parametrized slots**: `Procedure.params: dict` (e.g. `{vendor: "Acme", amount: "42"}`);
  step args use `{slot}`; executor fills from `params` (operator-supplied) — a 100-token model
  call only when the operator doesn't. One learned skill covers the task family.
- **A3 no-safety condition**: hostile-page task with gates + allowlist *disabled* (sandbox flag),
  measured injection-followed rate; B shows 0% by construction (CaMeL/AgentDojo framing).
- **Emission**: `eval/metrics.py` dataclass schema; `run_eval_v2` writes
  `eval/results_v2.json` (existing) + `eval/metrics_report.json`; RESULTS.md table template with
  citations (Voyager, AWM, τ-bench pass^k, CaMeL, AgentDojo, WebArena evaluators).

### WS-3 — README flip + setup + docs (review items 4, 5, 7)
- v2 leads: pitch → 4(+2) modes → safety-in-code → results + video → setup **with
  `playwright install chromium`**; v1 section: "frozen, real SAM 3.1 fixtures + offline dataset."
- Move `brag-output/` → `docs/media/` (fix `composition/` render target + all refs).
- Fix stale test counts (D8). Soften credential-logging claim to the code-guaranteed form.
- Efficiency reframe: "repeatable, verified outcome" (B deterministic; A live avg); drop
  "0.1s vs 42s human" as the headline.

### WS-4 — Public sites (review item 2)
- `ALLOW` += `saucedemo.com`, `the-internet.herokuapp.com`, `demoqa.com` (env `ALLOWED_HOSTS`
  override). Recorded goal-only run on **the-internet** (no login → credential rule intact):
  "open Dynamic Loading, wait for `Done!`, report it" + `text_visible` check; trace →
  `eval/public_site_run.json` + RESULTS section. Test: public host passes allowlist;
  non-allowlisted host refused via both `goto` and `start_site` (after WS-0.3).

### WS-5 — Self-heal mutate-replay demo (review item 3)
- `demo_sites/expense_mutated/` (renamed id + changed button text).
- `scripts/self_heal_demo.py` (offline, deterministic): replay clean procedure on mutated site →
  primary CSS breaks → multi-locator fall-through recovers; control (primary-only) fails,
  proving the heal did the work. Emits `eval/self_heal_results.json`; test in test_v2.
- Tour gains offline **BEAT 4 "HEAL"** (record → mutate → replay survives); final numbering:
  1 LEARN · 2 APPROVE · 3 TAKEOVER · 4 HEAL · 5 PROVE (coach + injection, + optional SAM beat inside PROVE).

### WS-6 — SAM 3.1 "Prove" beat + N≥5 live runs (review items 1, 5)
- Tour optional beat: filmed clip (`data/clips/`) → frozen v1 pipeline (SAM 3.1 + rules.py) →
  verdict in trace. No clip / API down → SKIP, labeled (honesty rule). Unattended default: no SAM
  beat (offline).
- **N≥5**: `run_eval_v2 --runs 5` live (key works today) → RESULTS regenerated with pass^5.
- Handoff (you): film one 15 s physical procedure + manifest entry.

### WS-7 — Video + track decision
- `docs/shot-list.md`: 2–3 min walkthrough timed to the 6-beat tour (incl. HEAL + SAM beats),
  VO per screen, clip sources (live capture vs recorded trace).
- `docs/handoff_nov2_4.md`: filming procedure, `playwright install chromium` for fresh clones,
  render command at new location, **Indie vs Startup** note for a duo (rules-cited; you decide).

## Acceptance criteria
- 35/35 + all new tests green; unattended tour trace shows every beat success/DONE.
- `run_eval_v2 --no-live` fully offline; `--runs 5` live emits pass^5 + usage + overclaim.
- No hardcoded human baseline anywhere; missing artifact → SKIPPED.
- README/setup: fresh-clone path (`playwright install chromium`) documented; v2 first.
- 1.3→1.1 fallback observable in `/api/v2/health`; substitution disclosed in reports.
- `docs/media/` is the only location of video assets; `demo_sites/media/` gone.

## Out of scope
- Robot-mode roadmap (one README sentence at most). No new frameworks/deps (ground rule 6);
  the-internet/saucedemo/demoqa are targets, not dependencies. Cost-rate display is optional.

## Guardrails
- No fabricated metrics: every number harness-measured or SKIP-labeled with cause.
- Synthetic-dataset labeling untouched; public-site/SAM/human results labeled live/measured.
- Code-first safety invariant: model escalates, never downgrades (WS-0.2 is the audit for it).
