"""Mode A: Self-healing web test suite runner.
CLI: python -m stepproof.testmode.suite --procs a.json b.json [--once] [--interval N] [--watch] [--live]

Exit codes:
  0 - All passed
  1 - One or more tests failed (deterministic checks failed)
  2 - aborted_budget (cost tripwire breached before or during run)
  3 - Infra error (site down, network unreachable, browser crashed)
"""
from __future__ import annotations
import argparse
import os
import sys
import time
import json
from pathlib import Path
from typing import Optional, Any

from .. import config as cfg
from ..proc import Procedure
from ..agent.executor import execute_procedure
from ..audit import AuditSpine
from ..budget import BudgetConfig, BudgetTripwire, estimate_procedure_cost, CostEstimate
from ..harness.reports import generate_junit_xml, generate_html_report
from ..harness.drift import analyze_drift


def run_single_procedure(proc_path: Path, live: bool = False,
                         tb_instance: Optional[Any] = None,
                         spine: Optional[AuditSpine] = None) -> dict:
    """Run a single procedure through pre-flight tripwire and executor."""
    t0 = time.time()
    p_dict = json.loads(proc_path.read_text(encoding="utf-8"))
    proc = Procedure.from_dict(p_dict)
    run_id = f"test_{proc_path.stem}_{int(t0)}"
    spine = spine or AuditSpine()

    # 1. Pre-flight Cost Estimation & Tripwire
    est = estimate_procedure_cost(proc)
    cap = BudgetConfig.from_env()
    print(f"\n[Pre-flight] {proc.goal}")
    print(f"  Estimated: ~ {est.estimated_sam_frames} SAM frames (50-frame min clamp), ~ {est.estimated_tokens} tokens (estimate)")
    print(f"  Caps: frames={cap.cap_frames_per_run if not cap.unlimited else 'unlimited'}, tokens={cap.cap_tokens_per_run if not cap.unlimited else 'unlimited'}")

    tripwire = BudgetTripwire(cap)
    ok, breach_err = tripwire.check_preflight(est)
    if not ok:
        print(f"  [ABORTED_BUDGET] {breach_err}")
        # Log to audit spine
        spine.append(
            run_id=run_id,
            verdict="ABORTED_BUDGET",
            checks=[],
            steps=[],
            model_disclosure={"estimated_frames": est.estimated_sam_frames, "estimated_tokens": est.estimated_tokens},
            cost={"status": "aborted_budget", "reason": breach_err},
        )
        return {
            "name": proc.goal,
            "path": str(proc_path),
            "run_id": run_id,
            "status": "aborted_budget",
            "success": False,
            "drifted": False,
            "wall_s": round(time.time() - t0, 3),
            "checks_passed": 0,
            "checks_total": len(proc.success_checks),
            "error": breach_err,
        }

    # 2. Execution (Live or Mock/Test)
    tb = tb_instance
    owns_browser = False
    if tb is None:
        try:
            from ..browser import TinyBrowser
            tb = TinyBrowser()
            owns_browser = True
        except Exception as e:
            err_msg = f"Infra error starting browser: {e}"
            print(f"  [INFRA ERROR] {err_msg}")
            return {
                "name": proc.goal,
                "path": str(proc_path),
                "run_id": run_id,
                "status": "infra_error",
                "success": False,
                "drifted": False,
                "wall_s": round(time.time() - t0, 3),
                "checks_passed": 0,
                "checks_total": len(proc.success_checks),
                "error": err_msg,
            }

    try:
        # Navigate if needed
        if proc.site:
            try:
                tb.start_site(proc.site)
            except Exception as e:
                err_msg = f"Infra error connecting to {proc.site}: {e}"
                print(f"  [INFRA ERROR] {err_msg}")
                return {
                    "name": proc.goal,
                    "path": str(proc_path),
                    "run_id": run_id,
                    "status": "infra_error",
                    "success": False,
                    "drifted": False,
                    "wall_s": round(time.time() - t0, 3),
                    "checks_passed": 0,
                    "checks_total": len(proc.success_checks),
                    "error": err_msg,
                }

        res = execute_procedure(tb, proc, approve_fn=lambda a, x: True)
        drift = analyze_drift(proc, res)

        print(f"  [Result] success={res.success}, error={res.error!r}, checks={[(c.name, c.passed, c.detail) for c in res.check_results]}")
        status = "passed" if res.success else "failed"
        verdict = "PASS" if res.success else "FAIL"
        passed_checks = sum(1 for c in res.check_results if c.passed)
        tot_checks = len(res.check_results)

        # Write drift artifact if drifted
        if drift.drifted_steps > 0:
            drift_dir = cfg.DATA_DIR / "drift"
            drift_dir.mkdir(parents=True, exist_ok=True)
            drift_file = drift_dir / f"{proc_path.stem}_drift.json"
            drift_file.write_text(json.dumps(drift.to_dict(), indent=2), encoding="utf-8")
            print(f"  [DRIFT DETECTED] {drift.drifted_steps} steps healed -> {drift_file}")

        # Append to audit spine
        spine.append(
            run_id=run_id,
            verdict=verdict,
            checks=[{"name": getattr(c, "name", "check"), "passed": c.passed, "detail": getattr(c, "detail", "")} for c in res.check_results],
            steps=[{"step": s.get("step"), "success": s.get("success")} for s in getattr(res, "healed_steps", [])],
            cost={"estimated_tokens": est.estimated_tokens, "status": "executed"},
        )

        return {
            "name": proc.goal,
            "path": str(proc_path),
            "run_id": run_id,
            "status": status,
            "success": res.success,
            "drifted": drift.drifted_steps > 0,
            "wall_s": round(time.time() - t0, 3),
            "checks_passed": passed_checks,
            "checks_total": tot_checks,
            "error": res.error or "",
            "drift_report": drift.to_dict(),
        }

    except Exception as e:
        err_msg = f"Infra/runtime execution failure: {e}"
        print(f"  [INFRA ERROR] {err_msg}")
        return {
            "name": proc.goal,
            "path": str(proc_path),
            "run_id": run_id,
            "status": "infra_error",
            "success": False,
            "drifted": False,
            "wall_s": round(time.time() - t0, 3),
            "checks_passed": 0,
            "checks_total": len(proc.success_checks),
            "error": err_msg,
        }
    finally:
        if owns_browser and tb:
            try:
                tb.close()
            except Exception:
                pass


def run_suite_once(proc_paths: list[Path], live: bool = False,
                   report_dir: Optional[Path] = None,
                   tb_instance: Optional[Any] = None) -> tuple[int, list[dict]]:
    """Run all given procedures once, generate reports, and return (exit_code, results)."""
    spine = AuditSpine()
    reports_p = report_dir or (Path(__file__).resolve().parent.parent.parent / "reports")
    reports_p.mkdir(parents=True, exist_ok=True)

    results = []
    for p in proc_paths:
        res = run_single_procedure(p, live=live, tb_instance=tb_instance, spine=spine)
        results.append(res)

    ts = int(time.time())
    junit_xml = generate_junit_xml("stepproof_testmode", results)
    junit_path = reports_p / f"junit_{ts}.xml"
    junit_path.write_text(junit_xml, encoding="utf-8")

    html_report = generate_html_report("stepproof_testmode", results)
    html_path = reports_p / "index.html"
    html_path.write_text(html_report, encoding="utf-8")

    print(f"\n[Reports Generated]")
    print(f"  JUnit: {junit_path}")
    print(f"  HTML:  {html_path}")

    # Determine exit code:
    # 2 if any aborted_budget
    # 3 if any infra_error
    # 1 if any failure
    # 0 if all pass
    statuses = [r["status"] for r in results]
    if "aborted_budget" in statuses:
        return 2, results
    if "infra_error" in statuses:
        return 3, results
    if any(not r["success"] for r in results):
        return 1, results
    return 0, results


def main() -> None:
    parser = argparse.ArgumentParser(description="StepProof Mode A: Self-healing web test runner")
    parser.add_argument("--procs", nargs="+", required=True, help="Procedure JSON paths to run")
    parser.add_argument("--once", action="store_true", default=True, help="Run once and exit (default)")
    parser.add_argument("--interval", type=int, default=0, help="Loop interval in seconds (0 = run once)")
    parser.add_argument("--watch", action="store_true", help="Watch procedures for file changes")
    parser.add_argument("--live", action="store_true", help="Arm live browser execution")
    parser.add_argument("--report-dir", type=str, default="", help="Directory for JUnit/HTML reports")

    args = parser.parse_args()
    paths = [Path(p) for p in args.procs]
    for p in paths:
        if not p.is_file():
            print(f"Error: procedure file not found: {p}", file=sys.stderr)
            sys.exit(3)

    r_dir = Path(args.report_dir) if args.report_dir else None

    if args.watch:
        print(f"[Watch Mode] Watching {len(paths)} procedures for modifications...")
        mtimes = {p: p.stat().st_mtime for p in paths}
        try:
            while True:
                time.sleep(2)
                changed = [p for p in paths if p.stat().st_mtime > mtimes[p]]
                if changed:
                    print(f"\n[Change Detected] {len(changed)} file(s) changed. Executing suite...")
                    for c in changed:
                        mtimes[c] = c.stat().st_mtime
                    run_suite_once(paths, live=args.live, report_dir=r_dir)
        except KeyboardInterrupt:
            print("\nStopped watch mode.")
            sys.exit(0)

    if args.interval > 0:
        print(f"[Scheduled Mode] Running every {args.interval}s...")
        try:
            while True:
                code, _ = run_suite_once(paths, live=args.live, report_dir=r_dir)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped scheduled mode.")
            sys.exit(0)

    code, _ = run_suite_once(paths, live=args.live, report_dir=r_dir)
    sys.exit(code)


if __name__ == "__main__":
    main()
