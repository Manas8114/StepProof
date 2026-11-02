"""Local nightly/watch scheduler: runs configured procedures on interval or demand,
records drift, self-rewrites when safe, and emits JUnit XML + HTML reports.
"""
from __future__ import annotations
import threading, time
from pathlib import Path
from typing import Optional, Callable

from .. import config as cfg
from ..events import BUS
from ..proc import Procedure
from ..agent.executor import execute_procedure
from .drift import analyze_drift, self_rewrite_procedure
from .reports import generate_junit_xml, generate_html_report


class TestScheduler:
    """Manages scheduled and on-demand procedure test suite runs."""

    def __init__(self, browser_factory: Optional[Callable] = None,
                 report_dir: Optional[Path] = None) -> None:
        self.browser_factory = browser_factory
        self.report_dir = report_dir or (cfg.DATA_DIR / "reports")
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.registered_procedures: list[Procedure] = []
        self._running = False
        self._interval_s = 3600  # 1 hour default
        self._thread: Optional[threading.Thread] = None
        self.last_results: list[dict] = []

    def register(self, proc: Procedure) -> None:
        self.registered_procedures.append(proc)

    def run_suite(self, suite_name: str = "nightly_suite",
                  auto_rewrite: bool = False,
                  tb_instance: Optional[Any] = None) -> dict:
        """Run all registered procedures, record drift, emit reports."""
        results = []
        BUS.publish("suite_start", {"suite": suite_name, "count": len(self.registered_procedures)})

        for proc in self.registered_procedures:
            t0 = time.time()
            tb = tb_instance or (self.browser_factory() if self.browser_factory else None)
            if tb is None:
                continue

            try:
                # Ensure on site
                if proc.site:
                    tb.start_site(proc.site)

                res = execute_procedure(tb, proc, approve_fn=lambda a, x: True)
                drift = analyze_drift(proc, res)

                if auto_rewrite and drift.drifted_steps > 0:
                    self_rewrite_procedure(proc, drift, tb=tb)

                results.append({
                    "name": proc.goal,
                    "success": res.success,
                    "drifted": drift.drifted_steps > 0,
                    "wall_s": round(time.time() - t0, 2),
                    "checks_passed": sum(1 for c in res.check_results if c.passed),
                    "checks_total": len(res.check_results),
                    "error": res.error,
                    "drift_report": drift.to_dict(),
                })
            except Exception as e:
                results.append({
                    "name": proc.goal,
                    "success": False,
                    "drifted": False,
                    "wall_s": round(time.time() - t0, 2),
                    "checks_passed": 0,
                    "checks_total": len(proc.success_checks),
                    "error": str(e),
                })
            finally:
                if not tb_instance and tb:
                    tb.stop()

        self.last_results = results

        # Generate and save JUnit XML & HTML reports
        junit_xml = generate_junit_xml(suite_name, results)
        html_report = generate_html_report(suite_name, results)

        junit_path = self.report_dir / f"{suite_name}_junit.xml"
        html_path = self.report_dir / f"{suite_name}_report.html"

        junit_path.write_text(junit_xml, encoding="utf-8")
        html_path.write_text(html_report, encoding="utf-8")

        summary = {
            "suite_name": suite_name,
            "total": len(results),
            "passed": sum(1 for r in results if r["success"]),
            "failed": sum(1 for r in results if not r["success"]),
            "drifted": sum(1 for r in results if r["drifted"]),
            "junit_path": str(junit_path),
            "html_path": str(html_path),
            "results": results,
        }
        BUS.publish("suite_done", summary)
        return summary


_GLOBAL_SCHEDULER: Optional[TestScheduler] = None


def get_scheduler() -> TestScheduler:
    global _GLOBAL_SCHEDULER
    if _GLOBAL_SCHEDULER is None:
        _GLOBAL_SCHEDULER = TestScheduler()
    return _GLOBAL_SCHEDULER

