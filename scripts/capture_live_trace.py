"""Capture ONE live Muse Spark agent run on a demo site, as a dated, re-runnable trace.

Runs the real AgentLoop (MuseAgentModel) against the locally-served demo sites and records
every observe/decide/act/state event off the event bus into a JSON trace. The approval gate
is answered by an auto-approving supervisor (the sandbox equivalent of a human clicking
Allow) and this is disclosed in the trace. If the model errors or stalls, that is captured
as a MEASURED outcome, not hidden.

Usage:
    python -m scripts.capture_live_trace                # expense task, writes eval/live_agent_trace.json
    python -m scripts.capture_live_trace --task inventory
"""
from __future__ import annotations
import argparse, datetime, http.server, json, os, socketserver, threading, time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEMO = BASE / "demo_sites"
PORT = 8011
SITE = f"http://127.0.0.1:{PORT}"

GOALS = {
    "expense": "File an expense claim: type vendor 'Acme', amount 42, choose category office, "
               "then click submit. Done when you see 'Claim filed'.",
    "inventory": "Restock SKU WS-1042 by 5. Type WS-1042 into the SKU box, 5 into quantity, "
                 "then click Restock. Done when the log says 'restocked by 5'.",
}
CHECKS = {
    "expense": [{"kind": "text_visible", "spec": {"text": "Claim filed"}}],
    "inventory": [{"kind": "text_visible", "spec": {"text": "restocked by 5"}}],
}


def _serve() -> socketserver.TCPServer:
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT),
                                   lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(DEMO), **k))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    return httpd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=list(GOALS), default="expense")
    ap.add_argument("--out", default="eval/live_agent_trace.json")
    ap.add_argument("--max-steps", type=int, default=16)
    ap.add_argument("--cap-s", type=int, default=240)
    a = ap.parse_args()

    from stepproof import config as cfg
    from stepproof.browser import TinyBrowser
    from stepproof.agent.model import MuseAgentModel
    from stepproof.agent.loop import AgentLoop, Budgets
    from stepproof.checks import all_pass
    from stepproof.events import BUS

    # clean bus so the trace is only this run
    BUS.reset()
    events: list[dict] = []
    sub = BUS.subscribe()

    httpd = _serve()
    tb = TinyBrowser(allowlist={"127.0.0.1:8011"})
    tb.start_site(f"{SITE}/expense/" if a.task == "expense" else f"{SITE}/inventory/")

    loop = AgentLoop(tb, MuseAgentModel(), Budgets(max_steps=a.max_steps, max_wall_s=a.cap_s,
                                                    max_model_calls=a.max_steps + 2))

    def supervisor():
        while True:
            ev = sub.get()
            if ev["type"] == "approval_gate":
                time.sleep(0.05); loop.approve(True)   # sandbox auto-approve (disclosed)
            elif ev["type"] == "ask_human":
                time.sleep(0.05); loop.answer_human("proceed")

    def recorder():
        while True:
            ev = sub.get()
            events.append(ev)
            if ev["type"] == "done":
                break

    threading.Thread(target=supervisor, daemon=True).start()
    threading.Thread(target=recorder, daemon=True).start()

    loop.start(GOALS[a.task])
    for _ in range(a.cap_s + 30):
        if loop.machine.state.value in ("DONE", "ERROR"):
            break
        time.sleep(1)

    ok, res = all_pass(tb, CHECKS[a.task])
    out = {
        "label": f"live Muse Spark agent run on {a.task} demo site",
        "date": datetime.date.today().isoformat(),
        "model": MuseAgentModel().name,
        "goal": GOALS[a.task],
        "disclosures": [
            "approval gate answered by an auto-approving supervisor (sandbox; a person clicks Allow in the UI)",
            "deterministic success check is code, not the model",
        ],
        "state": loop.machine.state.value,
        "metrics": loop.log.metrics(),
        "success_check_passed": bool(ok),
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in res],
        "final_summary": loop.log.result.get("summary", loop.log.result.get("detail", "")),
        "trace": events,
    }
    p = BASE / a.out
    p.write_text(json.dumps(out, indent=2))
    print(json.dumps({k: out[k] for k in ("label", "date", "state", "metrics", "success_check_passed")},
                     indent=2))
    print(f"wrote {a.out} ({len(events)} events)")
    tb.stop(); httpd.shutdown()


if __name__ == "__main__":
    main()
