# StepProof v2 — Learn · Execute · Verify

> A browser procedure companion powered by **Meta Muse Spark** and **SAM 3.1**: watches you do a task, does it better with you in charge, self-heals broken locators visually, and proves the outcome with deterministic code.

StepProof operates on a core safety invariant: **Models perceive, code decides.** The model proposes; deterministic rules, domain allowlists, and approval gates enforce safety before execution.

---

## Quick Start (v2 Companion)

One command boots the v2 companion app, local demo sites, and the sandboxed browser:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # one-time: download headless browser
cp .env.example .env                    # add MODEL_API_KEY
uvicorn stepproof.api_v2:app --port 8011 # open http://localhost:8011
pytest -q                               # 121 tests (unit, integration, safety & E2E)
```

---

## Real Mode: Tripwire, Signed Artifacts, Audit Spine & Three Leads

StepProof "Real Mode" elevates the system from an experimental prototype to enterprise-ready production:

### 1. Pre-Flight PII Redaction
- **Irreversible local sanitization**: outbound screenshots and DOM accessibility trees pass through regex-based PII redaction (`stepproof/redact.py`) before touching SAM or Muse Spark.
- **Protected patterns**: email addresses, credit card numbers, phone numbers, SSNs, account numbers, and custom regexes.
- **Visual masking**: draws solid redaction rectangles over sensitive input bounding boxes on JPEG screenshots.
- **Dry-run audit**: `/api/v2/redaction/dry_run` shows exactly what would be sent vs redacted.

### 2. Append-Only Hash-Chained Audit Spine
- **Tamper-evident chain**: every execution verdict, check result, evidence screenshot, and model disclosure is hashed into an append-only SHA-256 chain (`stepproof/audit.py`), stored in SQLite and JSONL.
- **Portable evidence bundles**: `package_run()` exports a self-contained `.zip` bundle containing `manifest.json`, `audit_entries.json`, and all raw evidence screenshots with verified checksums.

### 3. Tripwire & Pre-Flight Cost Estimator
- **Guardrail in front of the meter**: `estimate_procedure_cost()` estimates SAM billed frames (50-frame minimum rule) and tokens before a run begins.
- **Aborts before billing**: a pathological procedure or runaway agent halts at action boundaries and before vision calls if caps are breached, logging a `BLOCKED` audit entry. Configurable via `STEPPROOF_COST_CAP_FRAMES` and `STEPPROOF_COST_CAP_TOKENS`.

### 4. Signed, Portable Procedure Artifacts
- **Canonical manifest**: byte-deterministic JSON serialization pins field ordering. Replay on another machine yields identical SHA-256 digests (`stepproof/signing.py`).
- **Cryptographic signatures**: signed via HMAC-SHA256 (`Procedure.signature` and `Procedure.manifest`). `Procedure.from_dict()` rejects tampered steps, locators, or checks.
- **CLI helper**: `python -m scripts.sign_procedure <proc.json> [--verify]`.

### 5. Lead A — Self-Healing Web Tests
- **Locator-drift reporting**: tracks which steps required secondary locators or vision-healing (`stepproof/harness/drift.py`).
- **Self-rewriting procedures**: when vision heal finds an element, the winning locator is synthesized, prepended to the procedure's locator list, and re-signed so subsequent runs require **0 vision/model calls**.
- **CI Suite Reports**: outputs standard JUnit XML (`<testsuite>`) and dark-themed HTML dashboards (`stepproof/harness/reports.py`).

### 6. Lead B — Proof & Audit Evidence (Independent Verifier)
- **Zero-server verifier**: `python -m stepproof.verifier.verify <bundle.zip>` independently confirms manifest digests, walks hash chains, and re-validates deterministic checks offline without live models or servers.
- **Real-footage adapter**: `verify_v1_clip()` connects physical assembly footage directly to the frozen v1 SAM video-verification pipeline.

### 7. Lead C — Operator Skill Compiler
- **Describe-or-demo onboarding**: compiles ~30s demonstrations or natural-language step descriptions into parameterised `{slot}` skills (`stepproof/skills/compiler.py`).
- **Human-gated re-teach flow**: when a parameter variant fails, the system requires operator approval before merging corrections and re-signing (never silent retraining).
- **Honesty guardrail**: explicitly marks vision variant understanding on physical footage as **NOT YET MEASURED** per submission rules X1–X5.

---

## Seven UI Modes (`http://localhost:8011`)

1. **Monitor (Learn)**: Perform a task in the live view. StepProof captures multi-locator actions (`role+name`, `text`, `css`, `box`), merges user narration, and compiles an editable, parameterised **Procedure** (`{slot}` substitutions supported).
2. **Execute (Do)**: Enter an intent via text or spoken push-to-talk. Muse Spark drives the browser with a kill switch, pause/takeover at any action boundary, and code-first approval gates before any irreversible or external action.
3. **Thoughts (Deliberation Trace)**: Live structured Chain-of-Thought (CoT) tracking every phase (`PERCEPTION`, `DELIBERATION`, `SAFETY_GATE`, `ACTUATION`, `RETRY_HEAL`, `COMPLETION`) with model latency, rationale, and exportable Markdown logs.
4. **Telemetry (Backend Bridge)**: Real-time gauges for step, time, and model call budgets, live token accounting, SAM frames billed, and active allowlist status.
5. **Coach (Compare & Suggest)**: Deterministic detectors compare agent runs against genuine human baselines; Muse Spark phrases actionable suggestions without inventing savings.
6. **Tour (Guided Showcase)**: A one-click, 5-beat showcase (learn $\to$ execute+gate $\to$ takeover $\to$ prove $\to$ visual heal) streaming to the live event feed, writing a dated offline replay.
7. **Tracking (SAM 3.1)**: Zero-shot video tracking via SAM 3.1 video segmentation with stable object IDs and confidence overlays across 60 frames.

---

## Safety Architecture (Code-First)

- **Domain Allowlist**: `TinyBrowser.goto()` and `start_site()` enforce allowlists in Python code before navigation begins; off-allowlist URLs (e.g. `evil.example`) are refused before firing network requests.
- **Approval Gates**: Irreversible actions (e.g. `#submit`, `#discard`, `#restock`) require explicit human confirmation. Selector-based clicks inspect DOM labels so `#submit` gates identically to a named button.
- **Prompt Injection Defense**: All page text is treated as untrusted data (`demo_sites/hostile/`). Verified in `tests/test_v2.py`.
- **Parameterised Slots**: `Procedure.parameters` substitutes `{slot}` variables (e.g. `{vendor}`, `{amount}`) at execution time, enabling one learned procedure to cover a task family.
- **Credential Protection**: Observation trees exclude `input[type=password]` values by construction; visual fill refuses password fields.

---

## Vision Self-Heal (Measured 93.8% Recovery)

When recorded DOM locators fail due to page mutation or re-rendering (`stepproof/browser/vision_heal.py`):
1. **Multi-locator fall-through**: `role+name` $\to$ `text` $\to$ `css` $\to$ `box`.
2. **Visual Grounding Fallback**: Muse Spark visual grounding locates target coordinates on a screenshot, falling back to SAM 3.1 open-vocabulary segmentation.
3. **Measured Performance**: Evaluated across 16 screenshots on standard, hostile, and mutated sites (`eval/vision_heal_results.json`): **15/16 (93.8%)** recovery rate.
4. **Visual Fill**: `fill_at` types visually into fields while preserving password protections.

---

## Evaluation & Metrics

StepProof evaluates three distinct conditions:
- **Condition B (Learned Replay)**: Deterministic execution of a saved Procedure (offline, no model calls, $pass^5 = 1.0$).
- **Condition C (Human Baseline)**: Measured from genuine recordings via `python -m scripts.record_human_run` into `data/human_runs/` (SKIPPED if missing; no fake constants).
- **Condition A (Live Agent)**: Open-ended Muse Spark goal-only agent (measured live, tracking token costs and overclaim rates).
- **A3 No-Safety Control**: Hostile page evaluation with safety gates off (`python -m eval.run_eval_v2 --no-safety`), quantifying the injection threat the safety layer prevents.

Run the evaluation:
```bash
python -m eval.run_eval_v2 --no-live   # offline B + C + safety cases
python -m eval.run_eval_v2             # includes live condition A if API reachable
```

---

## Verification & Disclosures

- **Verification Record**: See [`docs/VERIFIED.md`](docs/VERIFIED.md) for full verification against Meta documentation (SAM pricing/billing, Responses API shapes, MCP supervisor consumption).
- **Model Disclosures**:
  - Reasoning: `muse-spark-1.3` via `api.meta.ai` Responses API (flat tool calling). Auto-fallback to `muse-spark-1.1` on HTTP 404 with full disclosure in `/api/v2/health`.
  - Segmentation & Tracking: `sam-3.1` (open-vocabulary video/image segmentation).
  - Speech-to-Text: Meta `muse-voice-transcribe-1.0` when reachable, falling back to browser Web Speech.
  - Text-to-Speech: Browser native `speechSynthesis`.

---

## Launch Video & Media

- **Launch video**: Rendered at [`docs/media/brag.mp4`](docs/media/brag.mp4) (20s, 1080p@30, SFX + music) with poster [`docs/media/brag.jpg`](docs/media/brag.jpg).
- Storyboard and plan: [`docs/media/brag-plan.md`](docs/media/brag-plan.md) and [`docs/media/share-copy.txt`](docs/media/share-copy.txt).
- Re-render composition:
  ```bash
  cd docs/media/composition && npx hyperframes check && npx hyperframes render
  ```

---

## StepProof v1 (Physical Assembly Verification)

The v1 camera-verification pipeline verifies physical manual procedures from video clips using SAM 3.1 and Muse Spark:
```bash
python -m scripts.smoke_test path/to/image.jpg "red connector"
uvicorn stepproof.api:app --port 8000
python -m eval.run_eval --manifest eval/manifest.json --mode pipeline
```
Synthetic offline datasets (`scripts/make_dataset.py`) allow complete offline development without network or API keys.
