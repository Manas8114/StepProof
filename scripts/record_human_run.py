"""Record a GENUINE human run of a demo task - the source-of-truth for eval condition C.

Serves demo_sites on 8011, opens a HEADED Chromium, and YOU perform the task at your own
pace (real clicks, real typing). Completion is detected by the task's own DETERMINISTIC
success checks (the site's own success text / element state) - never by a model - and the
measured run is written to data/human_runs/<task>.json. eval.run_eval_v2 reads that artifact
for condition C and is SKIPPED when it is absent: no recording, no number - no fabricated
"recorded human baseline" (the old 42.0s/28.0s constants are gone).

Usage:
    python -m scripts.record_human_run --task expense_filed            # headed (default)
    python -m scripts.record_human_run --task inventory_restock
    python -m scripts.record_human_run --task expense_filed --headless # smoke-test the flow
    python -m scripts.record_human_run --task expense_filed --reset   # start from a fresh page
"""
from __future__ import annotations
import argparse, datetime, http.server, json, socketserver, threading, time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEMO = BASE / "demo_sites"
RUNS_DIR = BASE / "data" / "human_runs"
PORT = 8011

# the same deterministic success checks the eval uses per task (code, never the model)
TASKS = {
    "expense_filed": {
        "site": "/expense/", "goal": "File an Acme office expense of $42",
        "checks": [
            {"kind": "text_visible", "spec": {"text": "Claim filed"}},
            {"kind": "element_state", "spec": {"selector": "#submit", "state": "disabled"}},
        ],
    },
    "inventory_restock": {
        "site": "/inventory/", "goal": "Restock WS-1042 by 5",
        "checks": [
            {"kind": "text_visible", "spec": {"text": "stock 8"}},
            {"kind": "text_visible", "spec": {"text": "Total value: $731.00"}},
        ],
    },
}

# Records the human's real interactions on the live page (click / field typing / select).
# Pure JS, no model, no network - just evidence of what the human actually did.
RECORDER_JS = """
window.__sp_actions = [];
(() => {
  let typeTimer = 0;
  document.addEventListener('click', e => {
    const t = e.target; if (!t || !t.closest) return;
    const el = t.closest('button, select, input, a[href], [role=button]');
    if (!el) return;
    const tag = el.tagName.toLowerCase();
    const tool = tag === 'select' ? 'select' : (tag === 'input' ? 'type' : 'click');
    window.__sp_actions.push({tool, el: el.id || el.name || (el.textContent || '').trim().slice(0, 30), tag});
  }, true);
  document.addEventListener('input', e => {
    if (e.target && e.target.tagName === 'INPUT') {
      clearTimeout(typeTimer);
      typeTimer = setTimeout(() => {
        window.__sp_actions.push({tool: 'type', el: e.target.id || e.target.name || 'input', tag: 'input'});
      }, 500);   // one record per pause, not per keystroke
    }
  }, true);
  document.addEventListener('change', e => {
    if (e.target && e.target.tagName === 'SELECT')
      window.__sp_actions.push({tool: 'select', el: e.target.id || e.target.name || 'select', tag: 'select'});
  }, true);
})();
"""


def _serve() -> http.server.HTTPServer:
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT),
                                    lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(DEMO), **k))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)
    return httpd


def _check_js(check: dict) -> str:
    """The task's deterministic check, as a page-side JS predicate (same semantics as
    stepproof.checks - success is decided by code inspecting page state, never a model)."""
    kind, spec = check.get("kind"), check.get("spec", {})
    if kind == "text_visible":
        return f"document.body.innerText.toLowerCase().includes({spec.get('text', '').lower()!r})"
    if kind == "element_state":
        prop = {
            "visible": "el.getBoundingClientRect().width>2&&el.getBoundingClientRect().height>2",
            "hidden": "!(el.getBoundingClientRect().width>2&&el.getBoundingClientRect().height>2)",
            "enabled": "!el.disabled", "disabled": "!!el.disabled",
            "checked": "!!el.checked", "unchecked": "!el.checked",
        }.get(spec.get("state", "visible"))
        return (f"(()=>{{const el=document.querySelector({spec.get('selector', '')!r});"
                f"return el?{prop}:null;}})() === true")
    raise ValueError(f"unsupported check kind {kind!r} for human-run detection")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, choices=sorted(TASKS))
    ap.add_argument("--headless", action="store_true", help="no window (smoke-test only)")
    ap.add_argument("--timeout", type=int, default=600, help="seconds to wait for a human run")
    a = ap.parse_args()
    t = TASKS[a.task]

    print(f"serving demo sites on :{PORT} ...")
    httpd = _serve()
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    page = pw.chromium.launch(headless=a.headless).new_page(viewport={"width": 1024, "height": 640})
    page.add_init_script(RECORDER_JS)               # recorder survives any in-page nav
    page.goto(f"http://127.0.0.1:{PORT}{t['site']}", wait_until="load")

    preds = [_check_js(c) for c in t["checks"]]
    print(f"\n=== HUMAN RUN: {a.task} ===\nGoal: {t['goal']}\n"
          f"Complete every check by the site's own success state; timing starts NOW.\n"
          f"({len(preds)} deterministic check(s) must all hold before the run is counted.)\n")
    t0 = time.time()
    done, elapsed = False, 0.0
    while time.time() - t0 < a.timeout:
        # evaluate each deterministic predicate directly in the page
        results = [page.evaluate(f"() => {{ {p} }}") for p in preds]
        if all(results):
            done, elapsed = True, time.time() - t0
            break
        time.sleep(0.5)

    if not done:
        print(f"timed out after {a.timeout}s - nothing written (no fabrication).")
        page.close(); pw.stop(); httpd.shutdown()
        return

    actions = page.evaluate("() => window.__sp_actions || []")
    run = {
        "task": a.task, "goal": t["goal"],
        "recorded_by": "scripts.record_human_run (human, headed browser)",
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "wall_s": round(elapsed, 1), "steps": len(actions), "actions": actions,
        "url": page.url,
        "checks": [{"kind": c["kind"], "passed": True} for c in t["checks"]],
        "headless": a.headless,
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"{a.task}.json"
    out.write_text(json.dumps(run, indent=2))
    print(f"\nDONE in {run['wall_s']}s, {run['steps']} recorded interaction(s).\n"
          f"wrote {out}  <- eval condition C now reads this (SKIPPED when absent).")
    page.close(); pw.stop(); httpd.shutdown()


if __name__ == "__main__":
    main()
