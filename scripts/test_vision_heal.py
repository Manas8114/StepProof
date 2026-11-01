"""Timeboxed vision self-heal test (v2 master prompt, 90-min box, cut if < ~70%).

Captures >=10 real screenshots of the demo sites, each with a DOM ground-truth box for a
target element. For every screenshot it tries the healers (Muse vision grounding FIRST,
SAM 3.1 open-vocab as fallback) and scores whether the returned click point lands inside
the DOM-truth box (with tolerance). Reports per-healer and combined success; the combined
number is the keep/cut decision.

Usage:
    python -m scripts.test_vision_heal            # both healers, offline screenshots + live models
    python -m scripts.test_vision_heal --muse-only
    python -m scripts.test_vision_heal --sam-only
"""
from __future__ import annotations
import argparse, http.server, json, os, socketserver, threading, time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEMO = BASE / "demo_sites"
PORT = 8011
SITE = "http://127.0.0.1:%d" % PORT


def _serve():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT),
                                   lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a,
                                                                                        directory=str(DEMO), **k))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    return httpd


# (site path, setup [(selector,value)], target description, css truth selector, sam concept)
CASES = [
    ("/expense/", [], "the Submit claim button", "#submit", "submit button"),
    ("/expense/", [], "the Vendor text input", "#vendor", "text input box"),
    ("/expense/", [], "the category dropdown", "#category", "dropdown menu"),
    ("/expense/", [], "the Amount input", "#amount", "number input"),
    ("/inventory/", [], "the Restock button", "#restock", "button"),
    ("/inventory/", [], "the Discard restock button", "#discard", "red button"),
    ("/inventory/", [], "the SKU input", "#sku", "text input"),
    ("/inventory/", [], "the quantity input", "#qty", "number input"),
    ("/inventory/", [], "the WS-1042 table row", "#t tbody tr", "table row"),
    ("/hostile/", [], "the Finish task button", "#legit", "button"),
    ("/expense/", [("#vendor", "Acme"), ("#amount", "42")], "the Submit claim button", "#submit", "submit button"),
    ("/inventory/", [("#sku", "WS-1042")], "the Restock button", "#restock", "button"),
]


def _prep(tb, setup):
    for sel, val in setup:
        tb.act("fill", {"selector": sel, "text": val})
        tb.observe()
    time.sleep(0.2)


def _truth_box(tb, sel):
    expr = ("(() => { const el = document.querySelector(%r); if (!el) return null; "
            "const r = el.getBoundingClientRect(); "
            "return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; })()"
            % sel)
    return tb.act("eval", {"expr": expr})


def _hits(truth, point, tol=24):
    """True when the returned click point lands in/around the DOM-truth box."""
    if not truth or not point:
        return False
    x, y = point["x"], point["y"]
    x0, y0 = truth["x"] - tol, truth["y"] - tol
    x1, y1 = truth["x"] + truth["w"] + tol, truth["y"] + truth["h"] + tol
    return x0 <= x <= x1 and y0 <= y <= y1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--muse-only", action="store_true")
    ap.add_argument("--sam-only", action="store_true")
    a = ap.parse_args()

    from stepproof.browser import TinyBrowser
    httpd = _serve()
    tb = TinyBrowser(allowlist={"127.0.0.1:%d" % PORT})

    muse = sam = None
    use_muse = not a.sam_only
    use_sam = not a.muse_only
    if use_muse:
        from stepproof.browser.vision_heal import MuseVisionHealer
        muse = MuseVisionHealer(min_confidence=0.5)
    if use_sam:
        from stepproof.browser.vision_heal import SamVisionHealer
        concept_map = {c[2]: c[4] for c in CASES}   # target description -> clean SAM noun phrase
        sam = SamVisionHealer(concept_map=concept_map)

    results = []
    for (path, setup, target, sel, concept) in CASES:
        tb.start_site(SITE + path)
        _prep(tb, setup)
        truth = _truth_box(tb, sel)
        shot = tb.take_screenshot()
        row = {"target": target, "truth": truth, "muse": None, "sam": None}
        if use_muse:
            try:
                h = muse.heal(shot, target)
                row["muse"] = {"hit": _hits(truth, h), "point": h}
            except Exception as e:
                row["muse"] = {"hit": False, "error": "%s: %s" % (type(e).__name__, str(e)[:100])}
        if use_sam:
            try:
                h = sam.heal(shot, target)
                row["sam"] = {"hit": _hits(truth, h), "point": h}
            except Exception as e:
                row["sam"] = {"hit": False, "error": "%s: %s" % (type(e).__name__, str(e)[:100])}
        results.append(row)

    tb.stop(); httpd.shutdown()

    def rate(key):
        r = [x for x in results if key in x and x[key] and "error" not in x[key]]
        ok = sum(1 for x in r if x[key]["hit"])
        return (round(ok / len(r), 3) if r else None, len(r))

    mus_rate, mus_n = rate("muse")
    sam_rate, sam_n = rate("sam")
    comb = []
    for x in results:
        ok = (x.get("muse") or {}).get("hit") or (x.get("sam") or {}).get("hit")
        comb.append(bool(ok))
    comb_rate = round(sum(comb) / len(comb), 3) if comb else None

    out = {"n_cases": len(results),
           "muse": {"success": mus_rate, "of": mus_n},
           "sam": {"success": sam_rate, "of": sam_n},
           "combined": {"success": comb_rate, "of": len(comb)},
           "cut_threshold": 0.7,
           "per_case": results}
    p = BASE / "eval" / "vision_heal_results.json"
    p.write_text(json.dumps(out, indent=2))
    print(json.dumps({k: out[k] for k in ("n_cases", "muse", "sam", "combined")}, indent=2))
    verdict = "KEEP" if (comb_rate or 0) >= 0.7 else "CUT (< 0.7)"
    print("verdict: %s (combined %s)" % (verdict, comb_rate))
    print("wrote", p)


if __name__ == "__main__":
    main()
