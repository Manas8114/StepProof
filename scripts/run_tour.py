"""Run the guided showcase tour (4 beats) and print its recorded trace.

Usage:
    python -m scripts.run_tour                 # unattended (auto-answers gates; labeled)
    python -m scripts.run_tour --interactive   # waits for a human to click Allow/Deny + Hand back
"""
from __future__ import annotations
import argparse, http.server, os, socketserver, threading, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(BASE, "demo_sites")


def _serve():
    try:
        socketserver.TCPServer.allow_reuse_address = True
        httpd = socketserver.TCPServer(("127.0.0.1", 8011),
                                       lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a,
                                                                                            directory=DEMO, **k))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        time.sleep(0.4)
        return httpd
    except OSError:
        # Port 8011 is already bound (e.g. uvicorn app is running)
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interactive", action="store_true",
                    help="wait for a real human to click Allow/Deny and Hand back")
    a = ap.parse_args()

    from stepproof.browser import TinyBrowser
    from stepproof.agent.model import MuseAgentModel
    from stepproof.agent.executor import execute_procedure
    from stepproof.learn import Recorder
    from demo import Tour

    httpd = _serve()
    tb = TinyBrowser(allowlist={"127.0.0.1:8011"})
    tour = Tour(tb, MuseAgentModel(), Recorder(tb), execute_procedure,
                 mode="interactive" if a.interactive else "unattended")
    trace = tour.run()

    print("=== TOUR TRACE (%s mode, dated %s) ===" % (tour.mode, trace["date"]))
    for r in trace["records"]:
        d = r["detail"]
        show = {k: v for k, v in d.items() if k in
                ("success", "steps", "state", "stayed_on_allowlist", "gate_answered_by",
                 "locators_kept", "by", "actions", "reason")}
        print("  [%-8s] %-20s -> %s" % (r["beat"], r["step"], show))
    print("recorded to:", getattr(tour, "records_path", None))
    tb.stop()
    if httpd:
        httpd.shutdown()


if __name__ == "__main__":
    main()
