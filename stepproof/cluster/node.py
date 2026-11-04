"""Cluster execution node wrapping either local Playwright Chromium or remote CDP endpoint."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ..proc import Procedure
from ..agent import executor
from ..agent.executor import execute_procedure
from ..audit import AuditSpine


@dataclass
class NodeMetrics:
    total_runs: int = 0
    passed_runs: int = 0
    failed_runs: int = 0
    total_duration_sec: float = 0.0
    last_error: Optional[str] = None


class ClusterNode:
    """A worker node in the StepProof execution cluster.
    
    Can be backed by:
    1. 'local': Local ephemeral or headless Playwright Chromium worker.
    2. 'cdp': Remote CDP connection (Browserbase, Playwright Grid, Browserless, Docker Swarm).
    """

    def __init__(
        self,
        node_id: Optional[str] = None,
        node_type: str = "local",  # "local" | "cdp"
        cdp_url: Optional[str] = None,
        concurrency: int = 1,
        capabilities: Optional[list[str]] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.node_id = node_id or f"node-{uuid.uuid4().hex[:8]}"
        self.node_type = node_type
        self.cdp_url = cdp_url
        self.base_url = base_url
        self.concurrency = max(1, concurrency)
        self.capabilities = capabilities or ["chromium", "turnstile_solver", "v2_executor"]
        self.status: str = "idle"  # "idle" | "busy" | "offline" | "error"
        self.current_job_id: Optional[str] = None
        self.metrics = NodeMetrics()
        self.registered_at = time.time()
        self.last_heartbeat = time.time()

    def heartbeat(self) -> None:
        self.last_heartbeat = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "cdp_url": self.cdp_url,
            "base_url": self.base_url,
            "concurrency": self.concurrency,
            "capabilities": self.capabilities,
            "status": self.status,
            "current_job_id": self.current_job_id,
            "metrics": {
                "total_runs": self.metrics.total_runs,
                "passed_runs": self.metrics.passed_runs,
                "failed_runs": self.metrics.failed_runs,
                "total_duration_sec": round(self.metrics.total_duration_sec, 2),
                "last_error": self.metrics.last_error,
            },
            "registered_at": self.registered_at,
            "last_heartbeat": self.last_heartbeat,
        }

    def execute_procedure(self, procedure_data: dict, live: bool = False, timeout_sec: float = 60.0) -> dict[str, Any]:
        """Execute a procedure on this node and record telemetry/metrics."""
        self.status = "busy"
        self.heartbeat()
        t0 = time.time()
        try:
            from ..browser.session import TinyBrowser
            proc = Procedure.from_dict(procedure_data) if isinstance(procedure_data, dict) else procedure_data

            # Initialize isolated worker browser for this execution
            tb = TinyBrowser(cdp_url=self.cdp_url)
            try:
                # If procedure specifies a start url or site, navigate
                steps = getattr(proc, "steps", [])
                start_url = getattr(proc, "site", None) or getattr(proc, "url", None)
                if not start_url and steps and hasattr(steps[0], "arg") and isinstance(steps[0].arg, dict):
                    start_url = steps[0].arg.get("url") or steps[0].arg.get("site")
                if start_url:
                    base = self.base_url or ("http://localhost:8011" if self.node_type == "local" else None)
                    nav = tb.start_site(start_url, base=base)
                    if isinstance(nav, dict) and not nav.get("ok", True):
                        elapsed = time.time() - t0
                        self.metrics.total_runs += 1
                        self.metrics.failed_runs += 1
                        err_msg = nav.get("error", "navigation refused")
                        self.metrics.last_error = err_msg
                        self.status = "idle"
                        self.current_job_id = None
                        return {
                            "node_id": self.node_id,
                            "ok": False,
                            "verdict": "INFRA_ERROR",
                            "steps_run": 0,
                            "healed_steps": [],
                            "error": err_msg,
                            "duration_sec": round(elapsed, 3),
                        }

                res = executor.execute_procedure(tb, proc)
                elapsed = time.time() - t0
                self.metrics.total_runs += 1
                self.metrics.total_duration_sec += elapsed

                success = bool(getattr(res, "success", False))
                if success:
                    self.metrics.passed_runs += 1
                else:
                    self.metrics.failed_runs += 1

                self.status = "idle"
                self.current_job_id = None
                return {
                    "node_id": self.node_id,
                    "ok": success,
                    "verdict": "PASS" if success else "FAIL",
                    "steps_run": getattr(res, "steps_run", 0),
                    "healed_steps": getattr(res, "healed_steps", []),
                    "error": getattr(res, "error", ""),
                    "duration_sec": round(elapsed, 3),
                }
            finally:
                try:
                    tb.act("close", {})
                except Exception:
                    pass
        except Exception as e:
            elapsed = time.time() - t0
            self.metrics.total_runs += 1
            self.metrics.failed_runs += 1
            self.metrics.last_error = str(e)
            self.status = "idle"
            self.current_job_id = None
            return {
                "node_id": self.node_id,
                "ok": False,
                "verdict": "INFRA_ERROR",
                "error": str(e),
                "duration_sec": round(elapsed, 3),
            }
