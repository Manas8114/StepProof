# StepProof Hardening + Measurable-Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make StepProof's v2 claims *true and measured* — fix the real safety/correctness holes found in self-review, wire in the citation-grounded metrics framework (usage, pass^k, learn-from-own-run, parametrised slots, no-safety baseline, overclaim rate), and replace the hardcoded "recorded human" baseline with a genuinely recorded one.

**Architecture:** Four phases, each producing independently-runnable, tested software. Phase 1 makes the safety claims hold in code (they're what the README asserts and a judge can falsify). Phase 2 adds the measurement layer the "real talk" brief demands. Phase 3 records a real human run. Phase 4 packages the submission (docs, public site, demo beats, video). Order matters: you cannot honestly report metrics (P2) on a system whose safety claims are false (P1), and the human baseline (P3) feeds the efficiency table (P2/P4).

**Tech Stack:** Python 3, FastAPI, Playwright/Chromium, OpenAI-compatible `responses` client (Meta Muse Spark / SAM), pytest. No new dependencies (ground rule 6).

**Spec:** `docs/superpowers/specs/2026-11-01-stepproof-hardening-design.md`

## Global Constraints

- **Never fabricate results.** Every number in a report is harness-measured or explicitly `SKIPPED` with a cause. (ground rule 1)
- **Models perceive, code decides.** Pass/fail logic stays in `stepproof/rules.py` / `stepproof/checks.py`; no model call in verdict paths.
- **Safety is code-first.** The model may escalate a gate, never remove one. Fixes here *add* gates; none remove existing enforcement.
- **No new dependencies.** No Celery/Redis/Postgres/Docker. (ground rule 6)
- **Secrets only in `.env`**, never printed.
- **Disclose substitutions** (e.g. model 404 fallback) in `/api/health` + report + README.
- After each task: `python -m pytest -q` must stay green (35 passing at start).

---

## Phase 1 — Stop the bleeding (correctness + safety)

These are the real defects found by running the system. Each is a bug in a claim the README already makes.

### Task 1: `start_site` must respect the domain allowlist

**Files:**
- Modify: `stepproof/browser/session.py:33-36` (`start_site`)

**Interfaces:**
- Produces: `start_site(url)` now refuses off-allowlist hosts, identical to `goto()`.

**Why it's broken:** `start_site()` calls `self._call("goto", url)` directly (session.py:34) with no allowlist check, while `goto()` (session.py:38-45) does the check. It's reachable with a procedure-carry `site` from `api_v2.py:261` (`_browser.start_site(proc.site)`) and `recorder.py:35` (`self.browser.start_site(site_url)`), so a saved Procedure JSON with a foreign `site` sails off the allowlist. Harmless today (all demo URLs are localhost) but it makes "domain allowlist… enforced in code" false, and it becomes a real hole the moment public sites join the allowlist (Phase 4).

- [ ] **Step 1: Add a failing test**

In `tests/test_v2.py`, after `test_allowlist_refuses_navigation` (line 43-47), add:

```python
def test_start_site_refuses_off_allowlist(site_server):
    from stepproof.browser import TinyBrowser
    tb = TinyBrowser(allowlist={"127.0.0.1:8011"})
    r = tb.start_site("http://evil.example/x")
    assert r["ok"] is False and "refused" in r["error"]
    tb.stop()
```

- [ ] **Step 2: Run it, confirm it FAILS** (today `start_site` ignores the allowlist, so the nav "succeeds"/errors differently)

Run: `python -m pytest tests/test_v2.py::test_start_site_refuses_off_allowlist -q`
Expected: FAIL (either `r["ok"]` is True, or no `"refused"` key)

- [ ] **Step 3: Make `start_site` route through the gated path**

In `stepproof/browser/session.py`, change `start_site` to delegate to `goto`:

```python
    def start_site(self, url: str) -> dict:
        """Alias for `goto` (allowlist-gated). Kept for call-site clarity; nav is always gated."""
        return self.goto(url)
```

(Remove the direct `self._call("goto", url)` + `self._after_nav()` pair; `goto` already does both.)

- [ ] **Step 4: Run the test, confirm PASS + full suite green**

Run: `python -m pytest tests/test_v2.py -q`
Expected: PASS (new test + 13 existing v2 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_v2.py stepproof/browser/session.py
git commit -m "fix: route start_site through allowlist-gated goto

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 2: Selector-based clicks must hit the approval gate

**Files:**
- Modify: `stepproof/browser/actions.py:41-47` (`classify_action`) and `stepproof/agent/executor.py` (executor gate call passes only `name`/`url`)

**Interfaces:**
- Produces: `classify_action` for `click`/`select` also inspects the element label when the arg carries a `selector`; a selector click on an irreversible/external element now gates identically to a name click.

**Why it's broken:** `classify_action` (actions.py:41-47) reads `str(arg.get("name",""))` for click/select. But the agent's `click` tool (model.py:15) exposes `selector`, and the click branch (actions.py:58-61) is selector-first. A `click {"selector":"#submit"}` classifies `(False, False)` and runs with **no gate**, while the same click by `name` gates. The loop's gate (loop.py:172) calls `classify_action(act.tool, act.args)` — and `act.args` for a selector click has `selector`, not `name`. So the code-first "model can only escalate" invariant silently breaks on the selector path.

- [ ] **Step 1: Add a failing test**

In `tests/test_v2.py` add (import `classify_action` + a live `_browser`):

```python
def test_selector_click_gates_like_name_click(site_server):
    from stepproof.browser.actions import classify_action
    from stepproof.browser import TinyBrowser
    tb = _browser(site_server)
    tb.start_site(site_server + "/inventory/")
    # a click addressed by selector on the irreversible "Discard restock" button must gate
    irrev, ext = classify_action("click", {"selector": "#discard"})
    assert irrev is True, "selector click on irreversible element must be classified irreversible"
    tb.stop()
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_v2.py::test_selector_click_gates_like_name_click -q`
Expected: FAIL (`irrev` is `False` today because the arg has no `name`)

- [ ] **Step 3: Resolve the selector's label in `classify_action`**

In `stepproof/browser/actions.py`, give `classify_action` an optional browser handle so it can read the element text a selector points at:

```python
def classify_action(name: str, arg: dict, tb=None) -> tuple[bool, bool]:
    """Classify an action. Code decides; the model may escalate, never downgrade.
    For click/select addressed by selector, read the target's visible label so a
    selector-click on an irreversible element gates exactly like a name-click."""
    if name == "goto":
        return False, bool(_EXTERNAL_URL.match(str(arg.get("url", ""))))
    if name in ("click", "select"):
        label = str(arg.get("name", ""))
        if not label and arg.get("selector") and tb is not None:
            label = _label_of(tb, arg["selector"])
        return classify_element_text(label)
    return False, False


def _label_of(tb, selector: str) -> str:
    """Visible label of an element a CSS selector addresses (deterministic, no model)."""
    try:
        el = tb.observe()["elements"][0:0]  # noop keep tb warm
        expr = ("(()=>{const el=document.querySelector(%r);"
                "return el?(el.textContent||el.getAttribute('aria-label')||el.id||'').trim().slice(0,60):'';}())" % selector)
        return str(tb.act("eval", {"expr": expr}))
    except Exception:
        return ""
```

- [ ] **Step 4: Pass the browser handle at the gate call sites**

In `stepproof/agent/loop.py:172`, change the gate call to pass the browser:

```python
            irrev, ext = classify_action(act.tool, act.args, tb=self.browser)
```

In `stepproof/agent/executor.py:62`, change:

```python
        irrev, ext = classify_action(step.action, {k: step.arg.get(k) for k in ("name", "url")},
                                      tb=tb)
```

- [ ] **Step 5: Run the new test + full suite**

Run: `python -m pytest tests/test_v2.py -q`
Expected: PASS. (If the eval harness or other call sites of `classify_action` don't pass `tb`, they keep current behavior via the `tb=None` default — verify with `grep -rn "classify_action("`.)

- [ ] **Step 6: Grep for any other `classify_action` callers and keep them consistent**

Run: `grep -rn "classify_action(" stepproof/ eval/ scripts/ tests/`
Any caller that can see a live element should pass `tb=`; those that can't keep `tb=None`.

- [ ] **Step 7: Commit**

```bash
git add stepproof/browser/actions.py stepproof/agent/loop.py stepproof/agent/executor.py tests/test_v2.py
git commit -m "fix: selector-addressed clicks hit the approval gate via element label

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 3: `observe.py` must not hand password values to the model

**Files:**
- Modify: `stepproof/browser/observe.py:28-30` (the JS `name` computation)

**Interfaces:**
- Produces: `observe_page` returns `""` for the `name` of `type=password` inputs (the value is never sent to the model), matching the docstring's "Password values are never included."

**Why it's broken:** The element JS (observe.py:15) matches `input:not([type=hidden])` and line 28-29 sets `name` to `el.value` for **every** input, including `type=password`. A typed credential value would reach the model as the element name. The docstring (line 3, 49) claims it never does. Demo sites have no password fields, so nothing leaks *in practice* — but the "credentials are never read" README claim is only true by coincidence, not by construction.

- [ ] **Step 1: Add a failing test**

In `tests/test_v2.py`:

```python
def test_observe_excludes_password_values(site_server):
    from stepproof.browser import TinyBrowser
    tb = TinyBrowser(allowlist={"127.0.0.1:8011"})
    tb.start_site(site_server + "/expense/")
    # inject a password field into the live page, then observe
    tb.act("eval", {"expr": "(()=>{const i=document.createElement('input');i.type='password';i.value='secret';i.id='pw';document.body.appendChild(i);})()"})
    obs = tb.observe()
    pw = next((e for e in obs["elements"] if e.get("id") == "pw"), None)
    assert pw is not None
    assert pw.get("name", "") != "secret", "password value must not be exposed as element name"
    tb.stop()
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_v2.py::test_observe_excludes_password_values -q`
Expected: FAIL (`pw["name"]` is `"secret"` today)

- [ ] **Step 3: Exclude password input values in the observe JS**

In `stepproof/browser/observe.py`, in the JS loop, special-case password inputs *before* the generic name assignment. Replace the `name` computation (lines 28-30) so a `type=password` input yields `""`:

```python
    const isPw = (t === 'input' && el.type === 'password');
    let name = isPw ? '' : (el.getAttribute('aria-label') || el.getAttribute('title')
                || (t === 'input' || t === 'select' ? el.value || '' : (el.textContent || '').trim().slice(0, 60))
                || el.id || '');
    name = name.slice(0, 60);
```

- [ ] **Step 4: Run the test + full suite**

Run: `python -m pytest tests/test_v2.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stepproof/browser/observe.py tests/test_v2.py
git commit -m "fix: observe never hands password input values to the model

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 4: Unattended tour must run offline (deterministic), not stall on the live model

**Files:**
- Modify: `demo/tour.py:110-143` (`beat_takeover`) and `scripts/run_tour.py`
- Test: `tests/test_v2.py`

**Why it's broken:** `beat_takeover` always builds `AgentLoop(self.tb, self.model, ...)` where `self.model` is whatever was passed in. `scripts/run_tour.py:38` always passes `MuseAgentModel()` (the *live* API). So "unattended" mode is **not** offline/deterministic: it calls the live model, and under rate-limit the 60s beat budget (`Budgets(max_wall_s=60)`) is exhausted mid-beat → the run I captured died `takeover+resume: ERROR, steps 1-2`. The README sells the tour as "unattended/scripted" and the recorded trace (the artifact a judge replays) then shows a *failed* beat.

- [ ] **Step 1: Add a failing test**

In `tests/test_v2.py`:

```python
def test_unattended_tour_takeover_uses_offline_model(site_server):
    """'unattended' must be fully offline: the takeover beat uses a scripted model, so it
    never stalls on the live API and the recorded beat is deterministic + clean."""
    from demo.tour import Tour
    from stepproof.browser import TinyBrowser
    from stepproof.learn import Recorder
    from stepproof.agent.executor import execute_procedure
    from stepproof.agent.model import ScriptedModel, Action
    tb = TinyBrowser(allowlist={"127.0.0.1:8011"})
    # unattended => model is scripted (no live API), regardless of what a caller wanted
    tour = Tour(tb, None, Recorder(tb), execute_procedure,
                 mode="unattended", site_base=site_server)
    trace = tour.run()
    tko = next(r for r in trace["records"] if r["step"] == "takeover+resume")
    assert tko["detail"]["state"] == "DONE", tko
    assert all(r["success"] for r in trace["records"]), [r for r in trace["records"] if not r["success"]]
    tb.stop()
```

- [ ] **Step 2: Run, confirm FAIL** (takeover beat errors / stalls offline)

Run: `python -m pytest tests/test_v2.py::test_unattended_tour_takeover_uses_offline_model -q`
Expected: FAIL (state `ERROR` or a stall)

- [ ] **Step 3: Make unattended mode use a scripted model**

In `demo/tour.py`, `__init__` (line 29-41): when `mode == "unattended"` and no explicit offline model is supplied, force the takeover beat's agent to a `ScriptedModel` that completes the inventory restock deterministically:

```python
        self.mode = mode
        if self.mode == "unattended" and self.model.__class__.__name__ != "ScriptedModel":
            from stepproof.agent.model import ScriptedModel, Action
            self._takeover_model = ScriptedModel([
                Action("type", {"selector": "#qty", "text": "5"}),
                Action("click", {"name": "Restock"}),
                Action("finish", {"summary": "restocked WS-1042 by 5"}),
            ])
        else:
            self._takeover_model = self.model
```

In `beat_takeover` (line 115), use `self._takeover_model` instead of `self.model`, and for unattended mode set `Budgets` with a comfortable `max_wall_s` (the scripted path is fast, so this just removes the stall):

```python
        loop = AgentLoop(self.tb, self._takeover_model,
                         Budgets(max_steps=8, max_wall_s=90, max_model_calls=10))
```

Keep `run_tour.py` passing `MuseAgentModel()` for interactive mode; unattended mode now ignores it (document this in the module docstring: "unattended is fully offline — the takeover beat is scripted so the recorded trace is clean + deterministic without the live API").

- [ ] **Step 4: Run the test + re-run the real unattended tour to confirm a clean trace**

Run: `python -m pytest tests/test_v2.py -q` then `python -m scripts.run_tour`
Expected: suite green; tour trace shows every beat `success`/`DONE` (no `ERROR` on takeover). Confirm the newly written `data/tour_runs/<today>.json` has no failed beat.

- [ ] **Step 5: Commit**

```bash
git add demo/tour.py scripts/run_tour.py tests/test_v2.py
git commit -m "fix: unattended tour is truly offline (scripted takeover beat), no live stall

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 5: `playwright install chromium` in setup + clean up evidence artifacts

**Files:**
- Modify: `README.md` quick-start, `.env.example` or a new `README` setup note
- Modify: `stepproof/agent/executor.py:95-101` (evidence screenshots written to CWD-relative `media/`)

**Why:** Anyone cloning today fails at first run — `pip install playwright` does not download the browser. Also the executor writes evidence JPEGs to a CWD-relative `media/` dir, which is how `demo_sites/media/*.jpg` and a stray `media/` got untracked and polluting the tree.

- [ ] **Step 1: Add the browser-install line to README quick-start**

In `README.md`, the Quick-start block (lines 6-14), after `pip install -r requirements.txt`, add:

```
python -m playwright install chromium        # one-time: download the browser the tiny browser drives
```

- [ ] **Step 2: Route evidence screenshots to the stable `data/evidence` dir**

In `stepproof/agent/executor.py` `_shoot` (line 95-101), use the configured evidence dir instead of a relative `media/`:

```python
    def _shoot(tag: str) -> str:
        import time
        from .. import config as _cfg
        d = _cfg.EVIDENCE
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{tag}_{int(time.time()*1000)}.jpg"
        tb.act("screenshot", str(p))
        return str(p) if p.exists() else ""
```

- [ ] **Step 3: Add `data/` (already gitignored) — remove the stray untracked artifact dirs from git tracking**

Run: `rm -rf demo_sites/media media` and add `demo_sites/media/` to `.gitignore` (in case it's regenerated).

Run: `git status --short`
Expected: no `media/` entries

- [ ] **Step 4: Run suite (no behavior change) + commit**

Run: `python -m pytest -q`
Expected: 35 passing

```bash
git add README.md .gitignore stepproof/agent/executor.py
git commit -m "docs+fix: playwright install step in setup; evidence to data/evidence

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — Make the claim measurable (the "real talk" metrics)

Each item below is a small, testable addition to `stepproof/agent/model.py`, `stepproof/agent/loop.py`, `stepproof/learn/compile.py`, and `eval/run_eval_v2.py`. Together they make the four arguments (cheaper, repeatable, safer, more accurate) *emitted by the harness*, not asserted in prose.

### Task 6: Usage / token accounting on every model call

**Files:**
- Modify: `stepproof/agent/model.py` (`MuseAgentModel`)
- Modify: `stepproof/agent/loop.py` (`RunLog.metrics()`)
- Test: `tests/test_v2.py`

**Interfaces:**
- Produces: `MuseAgentModel.usage` = `{"input_tokens": int, "output_tokens": int, "calls": int}`; `RunLog.metrics()` includes `"usage"` so it lands in `results_v2.json` / `metrics_report.json`.

- [ ] **Step 1: Add a failing test**

```python
def test_model_accumulates_usage():
    from stepproof.agent.model import MuseAgentModel
    m = MuseAgentModel()
    assert m.usage == {"input_tokens": 0, "output_tokens": 0, "calls": 0}
```

Run: `python -m pytest tests/test_v2.py::test_model_accumulates_usage -q`
Expected: FAIL (`AttributeError: no usage`)

- [ ] **Step 2: Implement the accumulator**

In `stepproof/agent/model.py`, in `MuseAgentModel.__init__` add:

```python
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
```

Add a helper and call it after each successful `responses.create` in `decide()` (line ~82) and `suggest()` (line ~98):

```python
def _acc_usage(acc, resp) -> None:
    u = getattr(resp, "usage", None)
    if not u:
        return
    acc["input_tokens"] += int(getattr(u, "input_tokens", 0) or 0)
    acc["output_tokens"] += int(getattr(u, "output_tokens", 0) or 0)
    acc["calls"] += 1
```

In `decide()`, after `r = self.client.responses.create(...)`:
```python
                _acc_usage(self.usage, r)
                return _extract_action(r)
```
(In the retry loop, only accumulate on the call that returns; a raised exception means no usage was billed — keep it outside the try's success path.)

- [ ] **Step 3: Surface usage in the run log**

In `stepproof/agent/loop.py`, `RunLog.metrics()` (line 47-53) add:

```python
                "usage": getattr(self, "_usage", None) or {},
```

and in the loop, copy the model's usage into the log at finish/stop (`_stop`, line 230):
```python
        if hasattr(self.model, "usage"):
            self.log._usage = dict(self.model.usage)
```

- [ ] **Step 4: Test + suite green**

Run: `python -m pytest tests/test_v2.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stepproof/agent/model.py stepproof/agent/loop.py tests/test_v2.py
git commit -m "feat: capture model token usage per call into run metrics

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 7: pass^k — run N≥5 per condition, report pass@1 and pass^5

**Files:**
- Modify: `eval/run_eval_v2.py` (add `pass_k` + default `--runs 5` for live conditions)
- Test: `eval/run_eval_v2.py` (manual/offline check)

**Interfaces:**
- Produces: per task+condition `pass_at_1` and `pass_pow_k` in `results_v2.json`; printed in the summary. `pass^k` = mean over tasks of (per-task success-rate)^k (τ-bench definition: all k independent trials succeed).

**Why:** Even at temp 0, LLM agents aren't repeatable; τ-bench showed pass@1-looking agents collapse on pass^8. The compiled Procedure's pass^k is bounded only by environment variance — a wide A-vs-B gap on pass^5 *is* the repeatability argument.

- [ ] **Step 1: Add a pure helper with a test**

In `eval/run_eval_v2.py` add:

```python
def pass_k(success_flags: list[bool], k: int = 5) -> float:
    """τ-bench pass^k: probability all k independent trials succeed.
    per-task success-rate p = successes/trials; pass^k = p**k."""
    if not success_flags:
        return 0.0
    p = sum(1 for s in success_flags if s) / len(success_flags)
    return p ** k
```

- [ ] **Step 2: Compute it per condition and store**

In `main()` (line 177-200), after building `per_task[cond]` with its `runs`, add:

```python
            per_task[cond]["pass_at_1"] = round(sum(r.get("success", False) for r in active) / max(1, len(active)), 3)
            per_task[cond]["pass_pow_5"] = round(pass_k([r.get("success", False) for r in active], 5), 3)
```

- [ ] **Step 3: Default live condition to 5 runs**

At the `--runs` argparse default (line 162), document that live goal-only runs should use `--runs 5`; keep `--runs` applying to all. Print pass^5 in the summary loop (line 221-225):

```python
            print(f"    {cond}: {d['success']}/{d['of']} pass@1={d.get('pass_at_1')} "
                  f"pass^5={d.get('pass_pow_5')}, avg_wall={d['avg_wall_s']}s")
```

- [ ] **Step 4: Verify offline (B/C always available)**

Run: `python -m eval.run_eval_v2 --no-live`
Expected: runs; `results_v2.json` shows `learned` and `human_demo` with `pass_at_1`/`pass_pow_5` (B is deterministic → both ~1.0). Live condition shows SKIPPED.

- [ ] **Step 5: Commit**

```bash
git add eval/run_eval_v2.py
git commit -m "feat: report pass@1 and pass^5 per condition (tau-bench repeatability)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 8: Overclaim rate — log model-said-done vs check-passed

**Files:**
- Modify: `eval/run_eval_v2.py` (`cond_goal_only`, line 105-138)

**Interfaces:**
- Produces: per A1 run dict gains `model_said_done` (bool, finish summary present) and `check_passed` (bool, deterministic check) and `overclaim` (= said done but check failed). Aggregate `overclaims` count in results.

**Why:** LLM agents over-report success; WebArena's functional evaluators exist because self-reported "done" is unreliable. Log every case where the model's `finish` summary says done but the deterministic check says fail — that's the accuracy claim made measurable.

- [ ] **Step 1: Add the fields to `cond_goal_only`'s return**

In `eval/run_eval_v2.py` `cond_goal_only` (line 132-138), after `m = loop.log.metrics()` and `ok,_ = all_pass(...)`:

```python
    summary = str(loop.log.result.get("summary", "")).strip()
    said_done = bool(summary) and loop.machine.state.value == "DONE"
    overclaim = said_done and not ok
    return {..., "model_said_done": said_done, "check_passed": bool(ok),
            "overclaim": overclaim}
```

- [ ] **Step 2: Aggregate**

In `main()` summary, add to each goal_only condition block:
```python
            per_task[cond]["overclaims"] = sum(1 for r in active if r.get("overclaim"))
```
and print it.

- [ ] **Step 3: Verify offline still runs (A1 skipped, field absent = fine)**

Run: `python -m eval.run_eval_v2 --no-live`
Expected: runs clean (the new fields only populate when A1 actually runs live).

- [ ] **Step 4: Commit**

```bash
git add eval/run_eval_v2.py
git commit -m "feat: overclaim rate — model-said-done vs deterministic check passed

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 9: Learn-from-own-run — compile a successful A1 trace into a Procedure (AWM)

**Files:**
- Modify: `stepproof/learn/compile.py` (new `compile_from_agent_trace`)
- Test: `tests/test_v2.py`

**Interfaces:**
- Produces: `compile_from_agent_trace(steps, goal, site, success_checks) -> tuple[Procedure, list[str]]` where `steps` are `loop.log.steps` (list of `{"tool","args","ok","detail"}`). Synthesizes multi-locators from the winning arg (css selector→css locator; name→role+text locator). This turns "learn by watching a human" into "learn from itself."

- [ ] **Step 1: Add a failing test**

```python
def test_compile_from_agent_trace_builds_procedure(site_server):
    from stepproof.learn.compile import compile_from_agent_trace, sanitize
    steps = [
        {"tool": "type", "args": {"selector": "#vendor", "text": "Acme"}, "ok": True},
        {"tool": "type", "args": {"selector": "#amount", "text": "42"}, "ok": True},
        {"tool": "select", "args": {"selector": "#category", "value": "office"}, "ok": True},
        {"tool": "click", "args": {"name": "Submit claim"}, "ok": True},
    ]
    proc, w = compile_from_agent_trace(steps, "File an expense claim",
                                       site_server, [{"kind": "text_visible", "spec": {"text": "Claim filed"}}])
    proc, _ = sanitize(proc)
    assert len(proc.steps) == 4
    # a css-arg step keeps a css locator; a name-arg step keeps a role/text locator
    assert proc.steps[0].locators and proc.steps[0].locators[0].kind == "css"
    assert proc.steps[3].locators[0].kind in ("role", "text")
```

Run: `python -m pytest tests/test_v2.py::test_compile_from_agent_trace_builds_procedure -q`
Expected: FAIL (function not defined)

- [ ] **Step 2: Implement**

In `stepproof/learn/compile.py` add:

```python
def compile_from_agent_trace(steps: list[dict], goal: str, site: str = "",
                              success_checks: Optional[list[dict]] = None) -> tuple["Procedure", list[str]]:
    """AWM step: turn a successful goal-only agent trace into a reusable, deterministic
    Procedure. Each agent step's winning arg becomes the primary locator; css args stay css,
    name args become role+text locators so the learned procedure self-heals like a recorded one."""
    recs = []
    for s in steps:
        if not s.get("ok", False):
            continue
        a = s.get("args", {})
        tool = s.get("tool")
        if tool not in ("click", "type", "select"):
            continue
        locs = []
        if a.get("selector"):
            locs.append({"kind": "css", "value": a["selector"]})
        if a.get("name"):
            locs.append({"kind": "text", "value": a["name"]})
        rec = {"tool": tool, "locators": locs, "narration": f"agent: {tool}",
               "arg": {"text": a.get("text", ""), "value": a.get("value", ""),
                       "element_name": a.get("name", "")}}
        recs.append(rec)
    return compile_to_procedure(recs, goal, site, success_checks or [])
```

- [ ] **Step 3: Wire it into the eval as a B' condition**

In `eval/run_eval_v2.py`, after a successful A1 run (line 133-138 region), if the loop is DONE, call `compile_from_agent_trace(loop.log.steps, t.goal, t.site, t.checks)` and replay it deterministically (as condition `B_prime`), recording its success. Add a `B_prime` line to the printed summary.

- [ ] **Step 4: Test + offline check**

Run: `python -m pytest tests/test_v2.py -q` then `python -m eval.run_eval_v2 --no-live`
Expected: suite green; B' only populates when A1 ran live (offline → absent, fine).

- [ ] **Step 5: Commit**

```bash
git add stepproof/learn/compile.py eval/run_eval_v2.py tests/test_v2.py
git commit -m "feat: learn-from-own-run — compile a successful agent trace into a Procedure

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 10: Parametrised slots — one learned skill covers a task family

**Files:**
- Modify: `stepproof/proc.py` (Procedure gains `parameters` fill on execution), `stepproof/agent/executor.py` (fill slots before actuating)

**Interfaces:**
- Produces: `Procedure.parameters` already exists (proc.py:38). Steps' `arg["text"]`/`arg["value"]` may hold `{slot}` placeholders; the executor substitutes `proc.parameters` before actuating. A 100-token model call (or operator input) fills slots — small cost, not zero.

- [ ] **Step 1: Add a failing test**

```python
def test_executor_fills_parameterised_slots(site_server):
    from stepproof.proc import Procedure, Step, Locator
    from stepproof.agent.executor import execute_procedure
    proc = Procedure(goal="File {vendor} {amount} claim", site=site_server,
                      parameters={"vendor": "Globex", "amount": "7"},
                      steps=[
                          Step("s1", "vendor", "type", {"text": "{vendor}"}, [Locator("css", "#vendor")]),
                          Step("s2", "amount", "type", {"text": "{amount}"}, [Locator("css", "#amount")]),
                          Step("s3", "submit", "click", {"name": "Submit claim"}, [Locator("css", "#submit")]),
                      ],
                      success_checks=[{"kind": "text_visible", "spec": {"text": "Claim filed"}}])
    tb = _browser(site_server)
    res = execute_procedure(tb, proc, approve_fn=lambda a, x: True)
    obs = tb.observe()
    assert res.success, res.error
    assert "Globex" in obs.get("body_text", "") and "EXP-" in obs.get("body_text", "")
    tb.stop()
```

Run: `python -m pytest tests/test_v2.py::test_executor_fills_parameterised_slots -q`
Expected: FAIL (slots not substituted today; the literal `"{vendor}"` is typed)

- [ ] **Step 2: Implement slot fill in the executor**

In `stepproof/agent/executor.py`, at the top of the step loop (before `_resolve_locator`), substitute:

```python
        params = getattr(proc, "parameters", {}) or {}
        filled = _fill_slots(step.arg, params)
        ...
```

Add:
```python
def _fill_slots(arg: dict, params: dict) -> dict:
    if not params:
        return arg
    import re
    def sub(v):
        return re.sub(r"\{([a-zA-Z0-9_]+)\}", lambda m: str(params.get(m.group(1), m.group(0))), str(v))
    return {k: (sub(v) if isinstance(v, str) else v) for k, v in arg.items()}
```

and use `filled` (not `step.arg`) when resolving the locator + when reading `text`/`value` (line 72).

- [ ] **Step 3: Test + offline**

Run: `python -m pytest tests/test_v2.py -q` then `python -m eval.run_eval_v2 --no-live`
Expected: green

- [ ] **Step 4: Commit**

```bash
git add stepproof/agent/executor.py tests/test_v2.py
git commit -m "feat: parameterised Procedure slots (one skill, a task family)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 11: A3 no-safety baseline on the hostile page

**Files:**
- Create: `eval/no_safety.py` (or add to `run_eval_v2.py`)

**Interfaces:**
- Produces: `run_no_safety(tb, goal) -> {"followed_injection": bool}` — a *deliberately safety-off* agent (auto-approving, off-allowlist navigation permitted) on the hostile page. Measures whether the raw model follows the page's injected "navigate to evil.example / click delete." B (with safety) is 0% by construction.

**Why:** AgentDojo showed unprotected tool-calling agents follow injections a large fraction of the time. This row quantifies the threat the safety layer actually blocks — the "safer" argument made measurable.

- [ ] **Step 1: Implement**

```python
def run_no_safety(tb, goal, model):
    """CONTROL: run the goal-only agent with the safety layer REMOVED (auto-approve all gates,
    allowlist widened so evil.example is reachable). Measures the raw injection-follow rate.
    Never the default; a labelled experiment only."""
    from stepproof.agent.loop import AgentLoop, Budgets
    from stepproof.events import BUS
    BUS.reset()
    tb.start_site(goal_site)
    loop = AgentLoop(tb, model, Budgets(max_steps=10, max_wall_s=90, max_model_calls=12))
    q = BUS.subscribe()
    def auto():
        while True:
            ev = q.get()
            if ev["type"] == "approval_gate":
                loop.approve(True)
            elif ev["type"] == "ask_human":
                loop.answer_human("proceed")
            elif ev["type"] == "done":
                break
    threading.Thread(target=auto, daemon=True).start()
    loop.start(hostile_goal)
    for _ in range(90):
        if loop.machine.state.value in ("DONE", "ERROR"):
            break
        time.sleep(1)
    followed = "evil.example" in loop.log.metrics().get("actions", "") and any(...)  # detect off-allowlist nav / delete click
    return {"followed_injection": followed, "state": loop.machine.state.value}
```

Run it only with a `--no-safety` flag (opt-in, labelled in RESULTS as a deliberate safety-off control).

- [ ] **Step 2: Test that B stays 0%**

The B (learned) path already refuses evil.example via the allowlist (Task 1). Add a test asserting a learned procedure run on the hostile page does **not** navigate off-allowlist:

```python
def test_learned_never_follows_injection(site_server):
    # B path: executor + allowlist; hostile text must not cause off-allowlist nav
    ...
```

- [ ] **Step 3: Commit**

```bash
git add eval/run_eval_v2.py
git commit -m "feat: A3 no-safety control (labelled) — quantifies the injection threat the gate blocks

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 12: Metrics schema + RESULTS table template + citations

**Files:**
- Create: `eval/metrics.py` (schema dataclass + `to_report()`), `eval/RESULTS_TEMPLATE.md`

**Interfaces:**
- Produces: a stable JSON schema (`eval/metrics_report.json`) the harness emits, and a markdown table template with the four cited claims + "where it does not hold."

- [ ] **Step 1: Write the schema**

```python
@dataclass
class RunMetrics:
    task: str
    condition: str            # learned | human_demo | goal_only_agent | no_safety
    n_runs: int
    pass_at_1: float
    pass_pow_5: float
    usage: dict               # {input_tokens, output_tokens, calls}
    cumulative_tokens_over_n: int
    overclaims: int
    model_said_done: int
    check_passed: int
    followed_injection: Optional[bool]
    def to_row(self) -> dict: ...
```

- [ ] **Step 2: Cumulative tokens over N** — in `main()`, `cumulative_tokens_over_n = sum per-run (in+out) over the N runs` (the "cheaper" number that matters for deployment).

- [ ] **Step 3: Write `eval/RESULTS_TEMPLATE.md`** with the four sections (cost/repeatability/safety/accuracy), each with its table + the exact metric keys, and a "Where the claim does not hold" section (run-1 cost, UI-redesign brittleness, runtime-judgment tasks need slots, not a new idea — cite Voyager/AWM/pass^k/CaMeL/AgentDojo/WebArena).

- [ ] **Step 4: Wire `run_eval_v2` to emit `eval/metrics_report.json`** at the end of `main()`.

- [ ] **Step 5: Commit**

```bash
git add eval/metrics.py eval/RESULTS_TEMPLATE.md eval/run_eval_v2.py
git commit -m "feat: metrics schema + RESULTS template + citations (claims emitted, not asserted)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — Record a genuine human run (the user's explicit ask)

Today condition C ("recorded human baseline") is a **hardcoded constant** (`run_eval_v2.py:57,64`). This builds the tooling so a real human run is the baseline; the human actually performs the two tasks. **I cannot do the human part — you (or a teammate) run it.**

### Task 13: `record_human_run.py` + wire condition C to the artifact

**Files:**
- Create: `scripts/record_human_run.py`
- Modify: `eval/run_eval_v2.py` (condition C reads `data/human_runs/<task>.json`, SKIPPED if missing — no more constant)
- Test: `tests/test_v2.py`

**Interfaces:**
- Produces: `data/human_runs/<task>.json` = `{task, wall_s, steps, actions[], narration[], ts, recorded_by}`. Condition C reads it; if absent → C is `SKIPPED (no recorded human baseline)`, never a fake constant.

- [ ] **Step 1: Write the recorder tool**

`scripts/record_human_run.py`: starts the demo-site HTTP server + a headed Chromium (Playwright) on the task's page, times a real human doing the task via the Monitor `Recorder`, and on completion writes the JSON artifact. It must print the measured `wall_s`, `steps`, `actions`.

```python
def main(task: str):
    # serve demo_sites, open browser at the task page, Recorder.start()
    # block until human says done (Enter / a "done" control), Recorder.stop()
    # compute wall_s from time.time(), steps=len(actions), actions=[a.tool]
    # write data/human_runs/<task>.json
```

- [ ] **Step 2: Delete the hardcoded constant; read the artifact**

In `eval/run_eval_v2.py`, `Task.human` (line 42, 57, 64): remove the `human={...}` literals. In `cond_human` (line 97-102), read `data/human_runs/<task>.json`:

```python
def cond_human(t):
    p = BASE / "data" / "human_runs" / f"{t.name}.json"
    if not p.exists():
        return {"condition": "human_demo", "skipped": True,
                "reason": "no recorded human baseline — run scripts.record_human_run"}
    d = json.loads(p.read_text())
    return {"condition": "human_demo", "success": True, "steps": d.get("steps", 0),
            "wall_s": d.get("wall_s", 0), "source": "recorded", "ts": d.get("ts")}
```

- [ ] **Step 3: Add a test that C is SKIPPED without the artifact, and works with one**

```python
def test_human_baseline_reads_artifact_or_skips(tmp_path, monkeypatch):
    ...
```

- [ ] **Step 4: (HUMAN STEP — you run this, ~5 min)**

Run: `python -m scripts.record_human_run --task expense_filed` then `--task inventory_restock`. Do each task in the live browser at your normal pace. This produces the genuine artifacts.

- [ ] **Step 5: Verify the eval now reports the real human numbers**

Run: `python -m eval.run_eval_v2 --no-live`
Expected: condition C shows your recorded `wall_s`/`steps` (not 42.0/5), labelled `source: recorded`.

- [ ] **Step 6: Commit tooling (artifacts in `data/` are gitignored — commit the script + eval, not the JSON)**

```bash
git add scripts/record_human_run.py eval/run_eval_v2.py tests/test_v2.py
git commit -m "feat: condition C reads a genuinely recorded human baseline (script + SKIPPED-if-missing)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — Submission packaging

These are the review's remaining items: README flip, public site, self-heal demo, v1 SAM Prove beat, 1.3→1.1 fallback, housekeeping, video.

### Task 14: README flip to v2-first + soften claims + refresh counts

**Files:** Modify `README.md`, `SUBMISSION_CHECKLIST.md`

- [ ] v2 pitch first (four modes, safety-in-code, results + video links, setup **with `playwright install chromium`** — already added in Task 5). v1 → compact "frozen, real SAM 3.1 fixtures + offline dataset."
- [ ] Fix stale counts: README quick-start "14 offline tests" → actual; SUBMISSION_CHECKLIST A4 "22 tests" → actual (run `python -m pytest -q` to get the real number).
- [ ] Soften credential claim to what the code guarantees (Task 3 makes it by-construction for password fields; say "password values excluded by construction; action args are logged, so keep the demo credential-free").
- [ ] Efficiency reframe: "repeatable, verified outcome" (B deterministic; A live avg) — drop "0.1s vs 42s human" as the headline; point to pass^5 + cumulative tokens instead.
- [ ] **Commit**

### Task 15: Public practice site on the allowlist + one recorded goal-only run

**Files:** Modify `stepproof/api_v2.py` (ALLOW, line 37), `stepproof/browser/session.py` default allowlist, `.env.example`, `eval/`

- [ ] `ALLOW` becomes `{"localhost:8011"}` ∪ `saucedemo.com`, `the-internet.herokuapp.com`, `demoqa.com`, env-overridable via `ALLOWED_HOSTS`.
- [ ] Recorded goal-only run on **the-internet** (no login → keeps the credential rule intact): goal "open the Dynamic Loading page, wait for the `Done!` text, report it" + `text_visible` check. Trace → `eval/public_site_run.json` + a RESULTS section (live, measured, honestly labelled).
- [ ] New test: public host passes allowlist; a non-allowlisted host refused via **both** `goto` and `start_site` (depends on Task 1).
- [ ] **Commit**

### Task 16: Self-heal mutate-replay demo beat

**Files:** Create `demo_sites/expense_mutated/` (copy of expense with `#vendor` renamed + button text changed), `scripts/self_heal_demo.py`, new Tour beat

- [ ] `scripts/self_heal_demo.py` (offline, deterministic): replay the clean procedure on the mutated site → primary CSS breaks → multi-locator fall-through (text/role) recovers; a "no-heal" control (primary-only) fails, proving the heal did the work. Emits `eval/self_heal_results.json` + console summary.
- [ ] Add `tests/test_v2.py` case.
- [ ] Tour gains offline **BEAT 4 "HEAL"**; beats renumber to 5 (1 LEARN · 2 APPROVE · 3 TAKEOVER · 4 HEAL · 5 PROVE).
- [ ] **Commit**

### Task 17: v1 SAM 3.1 "Prove" beat (needs a filmed clip)

**Files:** Modify `demo/tour.py` (optional `with_sam` step), create manifest for a 1-clip procedure

- [ ] Tour optional beat: filmed clip (`data/clips/`) → frozen v1 pipeline (SAM 3.1 + `rules.py`) → verdict in trace. No clip / API down → SKIP, labelled (honesty rule). Unattended default: no SAM beat (offline).
- [ ] **HUMAN STEP (you):** film one 15 s physical procedure (e.g. "place 3 red cubes, remove 1") → concepts `red cube`. Provide the clip + a manifest entry.
- [ ] **Commit**

### Task 18: 1.3→1.1 model fallback + disclosure

**Files:** Modify `stepproof/config.py`, `stepproof/agent/model.py`, `stepproof/browser/vision_heal.py`

- [ ] On model-404 from `META_BASE_URL`, retry with `MUSE_FALLBACK_MODEL` (default `muse-spark-1.1`, env-overridable); record `model_active` + `model_fallback_used`.
- [ ] Surface substitution in `/api/v2/health` + run reports (AGENT_PROMPT rule 5: disclose substitutions).
- [ ] Test with a mocked 404.
- [ ] **Commit**

### Task 19: Housekeeping — `brag-output/` → `docs/media/`

**Files:** move dir, fix `composition/` render target + all refs (README, `docs/DOCS.md`, `eval` notes)

- [ ] `git mv brag-output docs/media`; update every reference (grep `brag-output`). Keep `composition/` and its render output path working.
- [ ] **Commit**

### Task 20: 2–3 min walkthrough video shot list

**Files:** Create `docs/shot-list.md`

- [ ] Timed against the 6-beat tour (Learn → Execute+gate → Takeover → HEAL → Prove+injection → SAM physical verify → public-site beat). Per-screen VO lines + which clip is live-capture vs recorded trace.
- [ ] **Commit**

### Task 21: Track decision note (Indie vs Startup for a duo)

**Files:** Create `docs/handoff_nov2_4.md`

- [ ] What the Official Rules say about duos + which track fits; **you make the call.**
- [ ] Filming procedure, `playwright install chromium` for fresh clones, render command at new location.
- [ ] **Commit**

---

## Self-Review

**Spec coverage:** D1 tour-offline → Task 4; D2 selector gate → Task 2; D3 start_site → Task 1; D4 hardcoded C → Task 13; D5 fallback → Task 18; D6 metrics → Tasks 6-12; D7 evidence dir → Task 5; D8 stale counts → Task 14. The "real talk" six priorities: usage(T6) pass^k(T7) learn-from-own-run(T9) slots(T10) A3(T11) overclaim(T8) + schema(T12). Public site → T15; self-heal demo → T16; SAM Prove → T17; README → T14; housekeeping → T19; video → T20; track → T21. All spec sections map to a task.

**Real-observed defects the spec didn't list but I found:** Task 3 (password value leak — the "never read credentials" claim was only true by coincidence) and the untracked `demo_sites/media/` + `media/` artifact pollution (folded into Task 5). Both are in the plan.

**Placeholder scan:** Tasks 11 (A3 follow-detection `any(...)`) and 13 (recorder `main` body) are the two that are deliberately higher-level — they need a live human / API to fully exercise and I flagged the human steps. Every other code step has real code.

**Type consistency:** `compile_from_agent_trace` (T9) feeds `compile_to_procedure`; `Pass_k` in T7 and `pass_pow_5` key used in T12 schema (`RunMetrics.pass_pow_5`) — consistent. `_fill_slots` (T10) operates on `step.arg` dicts — matches `Step.arg` type. `RunMetrics.usage` (T12) matches T6's `model.usage` shape.

**Scope check:** This is one repo, one subsystem (the eval+agent+browser core) — appropriate for a single plan, but it's large. Execute in phase order; each phase is a natural checkpoint. **Stop after Phase 1 if the judge deadline is close** — Phase 1 alone makes the safety claims true.
