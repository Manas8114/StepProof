# StepProof — Usage

## 0. Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # set MODEL_API_KEY (Meta Model API)
```

Access check (run first — it stops and reports the exact status if the key/region is wrong):
```bash
python -m scripts.smoke_test            # minimal: models.list + Muse compile
```

## 1. Run the app (one command)
```bash
uvicorn stepproof.api_v2:app --port 8011     # open http://localhost:8011
```
This serves the UI, the two demo sites (`/site/expense`, `/site/inventory`, `/site/hostile`),
the live event stream (`/events`), and the API. The tiny browser is sandboxed to `localhost:8011`.

## 2. The four UI modes

### Monitor (learn)
Click **Start recording**, then do the task yourself in the live view. Each click/typing is
captured as multi-locators + an optional narration line. Type a **goal**, then **Compile → Procedure**
to turn your demo into a reusable, editable `Procedure`.

### Execute (do)
Type (or record) a goal, pick a site, **Start agent**. Muse Spark drives the browser with a live
overlay. You can **Pause / take over** at any moment, act in the live view, and **Hand back**.
**Kill switch** stops everything immediately.

### Coach
Run the detectors + compare against your recorded human baseline. The panel shows where the run
is faster/slower and the measured savings. The model only *phrases* the suggestion; the code measured it.

### Tour (the showcase)
**Run guided tour** walks all four beats — Learn, Execute+approval-gate, Takeover, Prove — and
streams them onto the event feed. **Beat 2** waits for you to click **Allow/Deny**; **Beat 3**
waits for you to act and hand back. When done, it writes a dated, **replayable** trace
(`data/tour_runs/<date>.json`). **Replay** re-watches any recording offline with a "REPLAY <date>"
label (no network, no model).

## 3. Run it without a UI (scripts / headless)
```bash
# guided tour, unattended (auto-answers gates, labeled in the trace)
python -m scripts.run_tour

# offline, deterministic evaluation (3 conditions + safety cases; no API key needed for B/C)
python -m eval.run_eval_v2 --no-live

# live goal-only agent condition (needs the key)
python -m eval.run_eval_v2

# one dated live agent trace
python -m scripts.capture_live_trace --task expense
```

## 4. Evaluation conditions
`run_eval_v2.py` measures per task:
- **learned** — replay the compiled Procedure (deterministic, offline)
- **human_demo** — the recorded human baseline
- **goal_only_agent** — open-ended Muse agent from a goal (live; **skipped + disclosed** if the API is down)
Plus the safety cases: `gate_denied` (a denied irreversible action leaves the page intact) and
`injection_hold` (hostile page text cannot push navigation off the allowlist).
Efficiency is reported **learned vs the recorded demo** only — we never claim against a number we
didn't record. See `eval/RESULTS.md` and `eval/results_v2.json`.

## 5. Voice
- **Output:** browser `speechSynthesis` (no dependency). Every spoken line has a text equivalent.
- **Input:** push-to-talk. Prefers Meta `muse-voice-transcribe-1.0`; if unreachable, it falls back
  to the browser Web Speech API and **discloses** which one it used in the UI.

## 6. Offline / synthetic (no key, no network)
```bash
python -m scripts.make_dataset          # synthetic clips + sidecars
STEPPROOF_PROVIDER=mock STEPPROOF_DATA=data python -m eval.run_eval --manifest data/manifest/manifest.json --mode pipeline
```
**Label it synthetic** — it demonstrates mechanics, not measured model performance.

## 7. Tests
```bash
python -m pytest -q        # Hermetic unit & integration test suite (deselected -m "not e2e" by default)
python -m pytest -m e2e tests/e2e/test_button_audit.py -v  # E2E Playwright button & HUD audit
```

> **Note on Port 8011 Parity**: Tests run cleanly whether or not the companion app is running. When the app is active, `site_server` automatically reuses the running instance on port 8011; if port 8011 is bound to an unrecognized service, tests requiring it will gracefully skip without false errors.
