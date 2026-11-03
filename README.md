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
pytest -q                               # 134 tests (unit, integration, safety & E2E)
```

---

## The Three Product Modes & Enterprise Scenario

StepProof delivers three core operational modes built upon a shared cryptographic trust spine:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   TRUST SPINE: "Models Perceive, Code Decides"         │
│  • Local Device Key (data/keys/device.key)                             │
│  • Canonical Manifest SHA-256 + HMAC Signing (stepproof/artifact.py)   │
│  • Append-Only Hash-Chained Audit Spine (stepproof/audit.py)           │
│  • Pre-Flight Estimator & Cost Tripwire (stepproof/budget.py)          │
└──────────────┬─────────────────────────┬───────────────────────────────┘
               │                         │
               ▼                         ▼
  ┌────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
  │ MODE A: WEB TESTS      │  │ MODE B: PROOF EVIDENCE │  │ MODE C: SKILL FAMILIES │
  │ • stepproof.testmode   │  │ • scripts.bundle_run   │  │ • stepproof.skill      │
  │ • Pre-flight budget    │  │ • scripts.verify_bundle│  │ • Slots ({vendor})     │
  │ • JUnit XML + HTML     │  │ • Zero-network audit   │  │ • Per-value safety     │
  │ • Exit codes 0/1/2/3   │  │ • Deterministic checks │  │ • Gated re-teach       │
  └────────────────────────┘  └────────────────────────┘  └────────────────────────┘
```

### End-to-End Walkthrough: "The Monthly UI Redesign"
Run the complete 5-Act enterprise walkthrough from the prompt:
```bash
python -m scripts.walk_enterprise_scenario
```
- **Act 1 — Learn Once (Mode C)**: Demo the task on `/expense/` $\to$ `compile_family` proposes slots $\to$ human confirms $\to$ device key generated $\to$ signed `data/skills/expense_family.artifact`.
- **Act 2 — Nightly Self-Healing Test (Mode A)**: `python -m stepproof.testmode.suite --procs data/procedures/expense.acme.json --once`. Pre-flight estimate printed, tripwire verified, deterministic checks pass, exit code 0.
- **Act 3 — Redesign Lands (Money Shot)**: Shuffled DOM IDs on `/mutated/` exhaust DOM locators $\to$ visual healing recovers elements $\to$ test survives $\to$ drift report generated $\to$ human-gated re-harvest re-signs artifact.
- **Act 4 — Prove It Off-Machine (Mode B)**: `python -m scripts.bundle_run <run_id>` packages evidence bundle. Manager runs `python -m scripts.verify_bundle bundle.zip` on Machine B with **zero network access** $\to$ 100% verified verdict.
- **Act 5 — The Family Pays Rent**: Instantiate family with Contoso ($310) $\to$ per-value safety classification dynamically gates high-risk/irreversible requests.

---

## Live Copilot & Next-Step Suggestion Box

StepProof includes an interactive multimodal copilot for live web exploration:
- **Next-Step Prediction**: `POST /api/v2/copilot/suggest` analyzes page DOM, form states, and goals to predict the next logical step with confidence score and safety risk level.
- **One-Click Actuation**: `POST /api/v2/copilot/apply` (or the UI `[⚡ Apply Step]` button) executes the suggested step immediately on the live browser.
- **Interactive Q&A**: `POST /api/v2/copilot/ask` answers contextual questions ("What can I do here?", "Why is submit disabled?", "Is this page safe to automate?") grounded in deterministic live page inspection.
- **Any Site Learning**: Teach any web workflow (including public sites like YouTube, SauceDemo, etc.) directly via Monitor recording or the Copilot dock.

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

### 5. Lead A — Self-Healing Web Tests & Suite Runner
- **CLI Suite Runner**: `python -m stepproof.testmode.suite --procs data/skills/expense_family.artifact [--once] [--live] [--watch]` runs procedures through the executor with pre-flight cost verification and armed tripwires.
- **CI Suite Reports**: outputs standard JUnit XML (`reports/junit_*.xml`) and single-file HTML reports (`reports/index.html`). Exit codes: `0` (pass), `1` (fail), `2` (`aborted_budget`), `3` (infra/error).
- **Locator-Drift & Gated Re-harvest**: `stepproof/testmode/drift_report.py` identifies DOM mutations and vision healing events. Operator confirms re-harvest with `--yes` or interactive confirmation, prepending healed locators and cryptographically re-signing the artifact.

#### Scheduled Nightly Execution (OS-Native: Task Scheduler / cron / launchd)
StepProof does not run an unconstrained daemon. Scheduled execution is delegated to battle-tested OS-native schedulers, ensuring a deterministic lifecycle, bounded budgets, zero idle resource consumption, and full audit traceability.

- **Windows Task Scheduler**:
  ```powershell
  schtasks /create /tn "StepProofNightlyTest" `
    /tr "C:\Users\msgok\AppData\Local\Programs\Python\Python313\python.exe -m stepproof.testmode.suite --procs data/skills/expense_family.artifact --once" `
    /sc daily /st 02:00
  ```
- **Linux / macOS cron**:
  ```bash
  0 2 * * * cd /opt/stepproof && /usr/bin/python3 -m stepproof.testmode.suite --procs data/skills/expense_family.artifact --once >> /var/log/stepproof_nightly.log 2>&1
  ```
- **macOS launchd**:
  Create `~/Library/LaunchAgents/com.stepproof.nightly.plist`:
  ```xml
  <?xml version="1.0" encoding="UTF-8"?>
  <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
  <plist version="1.0">
  <dict>
      <key>Label</key>
      <string>com.stepproof.nightly</string>
      <key>ProgramArguments</key>
      <array>
          <string>/usr/local/bin/python3</string>
          <string>-m</string>
          <string>stepproof.testmode.suite</string>
          <string>--procs</string>
          <string>data/skills/expense_family.artifact</string>
          <string>--once</string>
      </array>
      <key>StartCalendarInterval</key>
      <dict>
          <key>Hour</key>
          <integer>2</integer>
          <key>Minute</key>
          <integer>0</integer>
      </dict>
      <key>StandardOutPath</key>
      <string>/tmp/stepproof_nightly.log</string>
      <key>StandardErrorPath</key>
      <string>/tmp/stepproof_nightly.err</string>
  </dict>
  </plist>
  ```
  Load with `launchctl load ~/Library/LaunchAgents/com.stepproof.nightly.plist`.

### 6. Lead B — Proof & Audit Evidence (Independent Verifier)
- **Zero-Network Independent Verifier**: `python -m scripts.verify_bundle <bundle.zip>` independently confirms SHA-256 digests, validates device key signatures, walks the audit hash chain, and re-evaluates deterministic checks on an isolated machine with **zero network access** and **zero API calls**.
- **Run Bundler**: `python -m scripts.bundle_run <run_id> [--out bundle.zip]` packages run manifests, chain entries, and evidence screenshots into a self-contained verifiable zip bundle.
- **Real-Footage Entry Point**: `python -m scripts.real_clip --clip data/videos/enterprise_redesign_scenario.mp4 [--no-live]` evaluates authentic camera recordings through the SAM 3.1 video pipeline with pre-flight cost estimation printed before execution and tripwires armed. Reports findings honestly (zero detections is published as a real empirical finding, establishing baseline physical footage behavior without synthetic fabrication).

### 7. Lead C — Operator Skill Compiler & Task Families
- **Describe-or-Demo Onboarding**: `python -m stepproof.skill.from_demo --demo <trace.json>` compiles recorded workflows into signed portable artifacts (`data/skills/<name>.artifact`).
- **Slot Proposal & Human Confirmation**: `compile_family()` proposes `{slot}` parameters from concrete values (e.g. vendor, amount, category), human operator selects which to parameterize.
- **Per-Value Safety Classification**: `instantiate(family, values)` type-validates values and dynamically elevates risk to `DANGEROUS` (amount > $500) or `IRREVERSIBLE` ("Discard" keyword), enforcing approval gates deterministically per-value.
- **Gated Re-Teach Flow**: `re_teach_step()` updates drifted step variants upon human demonstration, generates a new cryptographic signature and audit entry, and maintains provenance without silent mutations.

### 8. Universal Browser & Copilot (Every Website)
- **Universal Navigation**: Operates on any public or internal website (`STEPPROOF_ALLOW_ALL_SITES=1` or wildcard allowlist), automatically dismissing GDPR cookie consent banners and overlays.
- **Live Copilot Suggestion Box**: Real-time next-step recommendations and interactive Q&A grounded in live DOM structure, page text, and code-first safety invariants.
- **Enterprise Redesign Walkthrough**: Reproducible 5-Act scenario (`python -m scripts.walk_enterprise_scenario`) and video recorder (`python -m scripts.record_enterprise_scenario_video`).

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

## Cloudflare Turnstile & Anti-Bot CAPTCHA Handling

StepProof provides enterprise-grade detection and automated solving for Cloudflare Turnstile, hCaptcha, Google reCAPTCHA, and Cloudflare interstitial challenges:

```
┌────────────────────────────────────────────────────────────────────────┐
│               ANTI-BOT CHALLENGE RESOLUTION PIPELINE                   │
│                                                                        │
│   Page Navigation / Perception                                         │
│                │                                                       │
│                ▼                                                       │
│   [detect_challenge(page)] ──── (No Challenge) ───► Continue Run       │
│                │                                                       │
│                ▼ (Challenge Detected: Turnstile / hCaptcha / reCAPTCHA) │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │ 1. Local Turnstile Solver (DOM checkbox locating, coordinate   │   │
│   │    jitter actuation, token resolution polling)                 │   │
│   │ 2. Remote Provider Solver (Pluggable 2Captcha, CapSolver,      │   │
│   │    AntiCaptcha, offline Mock)                                  │   │
│   └────────────────────────┬───────────────────────────────────────┘   │
│                            │                                           │
│            ┌───────────────┴───────────────┐                           │
│            ▼ (Solved)                      ▼ (Unresolved / Hostile)    │
│     Resume Execution                 Graceful Takeover:                │
│                                      PAUSED_HUMAN + UI Notification    │
└────────────────────────────────────────────────────────────────────────┘
```

- **Built-in Local Turnstile Solver**: Automatically locates Turnstile container/iframe, computes center coordinates, actuates with human-like jittered movement, and awaits token verification.
- **Pluggable Remote Solvers**: Built-in HTTP adapter for 2Captcha, CapSolver, and Anti-Captcha (`CAPTCHA_PROVIDER`, `CAPTCHA_API_KEY`).
- **Graceful Fallback**: If an anti-bot challenge cannot be bypassed automatically, the engine transitions to `PAUSED_HUMAN` and notifies the operator.
- **REST Endpoints**:
  - `GET /api/v2/browser/captcha/detect`: Active page challenge audit.
  - `POST /api/v2/browser/captcha/solve`: Automated or remote challenge resolution.

> **Dual-Use & Safety Policy Disclosure**:
> Automated CAPTCHA/Turnstile resolution is an **opt-in operator capability** intended exclusively for authorized internal enterprise portals, staging environments, and allowlisted vendor sites. All actuations remain strictly subject to StepProof's host allowlist, cryptographic audit spine, and human-in-the-loop safety gates. When encountering hostile, unknown, or unresolvable challenges, StepProof does not attempt brute-force evasion; it immediately transitions to `PAUSED_HUMAN` to defer to human judgment.

---

## Distributed Cloud Cluster Execution

Scale from a single local browser to 100+ concurrent headless workers across AWS, GCP, or managed browser grids (Browserbase, Playwright Grid, Browserless.io, Docker Swarm):

- **Remote CDP Connection**: Connect workers to remote browser grids via `connect_over_cdp` using standard WebSocket CDP URLs (`wss://...`).
- **ClusterManager Pool**: Dynamic registration of local and remote CDP workers (`POST /api/v2/cluster/nodes`), worker health monitoring, and asynchronous job queuing.
- **Parallel CLI Runner**:
  ```bash
  python scripts/cluster_run.py --workers 4 --procedures data/procedures/*.json --out reports/cluster_suite.xml
  python scripts/cluster_run.py --cdp-urls wss://grid-1.corp:9222,wss://grid-2.corp:9222 --procedures data/procedures/*.json --format html --out reports/cluster_report.html
  ```

> **Remote Grid & Host Allowlist**: When connecting workers to remote browser grids or corporate intranets via `--cdp-urls` and `--base-url`, make sure target domains are listed in the `ALLOWED_HOSTS` environment variable (e.g. `export ALLOWED_HOSTS="app.workday.com,salesforce.com,intranet.corp"`). StepProof enforces the allowlist boundary across all cluster nodes, immediately reporting `INFRA_ERROR: navigation refused` if an untrusted host is requested.
- **Enterprise Reporting**: Generates aggregated JUnit XML (for Jenkins, GitHub Actions, GitLab CI) and rich dark-mode HTML dashboards.
- **REST Endpoints**:
  - `GET /api/v2/cluster/status`: Cluster capacity and job queue depth.
  - `GET /api/v2/cluster/nodes` / `POST /api/v2/cluster/nodes`: Worker pool lifecycle.
  - `POST /api/v2/cluster/jobs` / `GET /api/v2/cluster/jobs`: Batch job dispatch.
  - `GET /api/v2/cluster/report`: Download aggregated JUnit XML or HTML reports.

---

## Automated Scheduling (A2)

Run continuous verification on recurring schedules:

- **Linux / macOS (Cron)**:
  ```bash
  # Run nightly verification at 2:00 AM
  0 2 * * * cd /opt/stepproof && .venv/bin/python -m stepproof.testmode.suite --procs data/procedures/*.json --once >> /var/log/stepproof_nightly.log 2>&1
  ```
- **Windows Task Scheduler**:
  ```powershell
  schtasks /Create /SC DAILY /TN "StepProof\NightlySuite" /TR "powershell -Command cd C:\stepproof; .\.venv\Scripts\python.exe -m stepproof.testmode.suite --procs data\procedures\*.json --once" /ST 02:00
  ```
- **macOS (launchd)**:
  Configure `~/Library/LaunchAgents/com.stepproof.suite.plist` with `StartCalendarInterval` and program arguments pointing to `stepproof.testmode.suite`.

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
