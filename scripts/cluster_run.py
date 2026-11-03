"""CLI runner for StepProof Distributed Cloud Cluster Execution.

Runs procedure test suites in parallel across multiple local or remote CDP workers,
aggregating execution telemetry into enterprise JUnit XML and HTML reports.

Example usage:
  python scripts/cluster_run.py --workers 4 --procedures data/procedures/*.json --out reports/cluster_suite.xml
  python scripts/cluster_run.py --cdp-urls wss://grid-1.internal:9222,wss://grid-2.internal:9222 --procedures data/procedures/stripe_refund.json --out reports/cdp_run.html --format html
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path when invoked directly as a script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stepproof.cluster.manager import ClusterManager


def main() -> int:
    parser = argparse.ArgumentParser(description="StepProof Distributed Cluster Test Runner")
    parser.add_argument("--workers", type=int, default=2, help="Number of local Chromium worker nodes (default: 2)")
    parser.add_argument("--cdp-urls", type=str, default="", help="Comma-separated list of remote CDP endpoint URLs")
    parser.add_argument("--base-url", type=str, default="", help="Base URL for resolving relative procedure routes")
    parser.add_argument("--procedures", nargs="+", required=True, help="List or glob of procedure JSON file paths")
    parser.add_argument("--out", type=str, default="reports/cluster_run.xml", help="Output path for aggregated report")
    parser.add_argument("--format", choices=["junit", "html"], default="junit", help="Report format (junit or html)")
    parser.add_argument("--timeout", type=float, default=180.0, help="Total execution timeout in seconds")

    args = parser.parse_args()

    # Collect procedure files
    proc_files: list[Path] = []
    for pat in args.procedures:
        matches = glob.glob(pat)
        if matches:
            proc_files.extend(Path(m) for m in matches if m.endswith(".json"))
        else:
            p = Path(pat)
            if p.exists() and p.suffix == ".json":
                proc_files.append(p)

    if not proc_files:
        print("[ClusterRunner] Error: No valid procedure JSON files matched.", file=sys.stderr)
        return 1

    print(f"\n========================================================")
    print(f" StepProof Distributed Cluster Runner")
    print(f"========================================================")
    print(f"Procedures to run: {len(proc_files)}")

    # Initialize ClusterManager
    cm = ClusterManager(auto_start_worker=False)

    # Register local workers
    cdp_list = [u.strip() for u in args.cdp_urls.split(",") if u.strip()]
    if cdp_list:
        for i, cdp_url in enumerate(cdp_list):
            node_id = f"cdp-worker-{i+1}"
            cm.register_node(node_id=node_id, node_type="cdp", cdp_url=cdp_url, base_url=args.base_url or None)
            print(f"Registered remote CDP worker: {node_id} ({cdp_url[:40]}...)")
    else:
        for i in range(args.workers):
            node_id = f"local-worker-{i+1}"
            cm.register_node(node_id=node_id, node_type="local", base_url=args.base_url or None)
            print(f"Registered local worker: {node_id}")

    # Submit batch
    job_ids = cm.submit_batch([p for p in proc_files])
    print(f"Submitted {len(job_ids)} jobs to the cluster queue.\n")

    # Monitor until completion or timeout
    t0 = time.time()
    deadline = t0 + args.timeout
    all_done = False

    while time.time() < deadline:
        status = cm.get_status()
        jobs = status["jobs"]
        completed = jobs["completed"] + jobs["failed"]
        print(f"\rProgress: [{completed}/{jobs['total']}] completed ({jobs['running']} active, {jobs['queued']} queued)...", end="", flush=True)

        if completed >= jobs["total"]:
            all_done = True
            break
        time.sleep(0.5)

    print()
    elapsed = time.time() - t0

    if not all_done:
        print(f"[ClusterRunner] Warning: Execution timed out after {elapsed:.1f}s.")

    # Generate aggregate report
    report_content = cm.generate_aggregate_report(job_ids=job_ids, format=args.format)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_content, encoding="utf-8")
    print(f"\nAggregated {args.format.upper()} report written to: {out_path.resolve()}")

    # Summary
    st = cm.get_status()
    total = st["jobs"]["total"]
    passed = st["jobs"]["completed"]
    failed = st["jobs"]["failed"]
    print(f"Total: {total} | Passed: {passed} | Failed: {failed} | Time: {elapsed:.2f}s")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
