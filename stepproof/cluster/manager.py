"""Cluster manager orchestrating concurrent distributed executions across worker nodes."""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .node import ClusterNode
from ..harness.reports import generate_junit_xml, generate_html_report


@dataclass
class ClusterJob:
    job_id: str
    procedure_data: dict
    procedure_name: str
    status: str = "queued"  # "queued" | "running" | "completed" | "failed"
    assigned_node_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "procedure_name": self.procedure_name,
            "status": self.status,
            "assigned_node_id": self.assigned_node_id,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_sec": round(self.completed_at - self.started_at, 3) if (self.completed_at and self.started_at) else None,
            "result": self.result,
            "error": self.error,
        }


class ClusterManager:
    """Multi-worker cluster manager and scheduler."""

    def __init__(self, auto_start_worker: bool = True) -> None:
        self._nodes: dict[str, ClusterNode] = {}
        self._jobs: dict[str, ClusterJob] = {}
        self._job_queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._dispatcher_thread: Optional[threading.Thread] = None

        # Seed with default local worker node
        if auto_start_worker:
            self.register_node("local-worker-0", node_type="local", concurrency=1)

        self._start_dispatcher()

    def _start_dispatcher(self) -> None:
        if self._dispatcher_thread and self._dispatcher_thread.is_alive():
            return
        self._dispatcher_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._dispatcher_thread.start()

    def register_node(
        self,
        node_id: Optional[str] = None,
        node_type: str = "local",
        cdp_url: Optional[str] = None,
        concurrency: int = 1,
        capabilities: Optional[list[str]] = None,
    ) -> ClusterNode:
        with self._lock:
            node = ClusterNode(
                node_id=node_id,
                node_type=node_type,
                cdp_url=cdp_url,
                concurrency=concurrency,
                capabilities=capabilities,
            )
            self._nodes[node.node_id] = node
            return node

    def deregister_node(self, node_id: str) -> bool:
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id].status = "offline"
                del self._nodes[node_id]
                return True
            return False

    def list_nodes(self) -> list[dict[str, Any]]:
        with self._lock:
            return [n.to_dict() for n in self._nodes.values()]

    def submit_job(self, procedure_data_or_path: dict | str | Path, name: str = "") -> str:
        """Submit a procedure for cluster execution."""
        proc_data: dict = {}
        proc_name = name
        if isinstance(procedure_data_or_path, (str, Path)):
            p = Path(procedure_data_or_path)
            if p.exists() and p.is_file():
                proc_data = json.loads(p.read_text(encoding="utf-8"))
                if not proc_name:
                    proc_name = proc_data.get("goal") or p.stem
            else:
                try:
                    proc_data = json.loads(str(procedure_data_or_path))
                except Exception:
                    raise ValueError(f"Invalid procedure path or JSON: {procedure_data_or_path}")
        elif isinstance(procedure_data_or_path, dict):
            proc_data = procedure_data_or_path
        else:
            raise TypeError("Expected dict, str or Path")

        if not proc_name:
            proc_name = proc_data.get("goal") or f"job-{uuid.uuid4().hex[:6]}"

        job_id = f"job-{uuid.uuid4().hex[:8]}"
        job = ClusterJob(
            job_id=job_id,
            procedure_data=proc_data,
            procedure_name=proc_name,
            status="queued"
        )
        with self._lock:
            self._jobs[job_id] = job
            self._job_queue.put(job_id)
        return job_id

    def submit_batch(self, procedures: list[dict | str | Path]) -> list[str]:
        return [self.submit_job(p) for p in procedures]

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            j = self._jobs.get(job_id)
            return j.to_dict() if j else None

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            sorted_jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.to_dict() for j in sorted_jobs[:limit]]

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            total_nodes = len(self._nodes)
            idle_nodes = sum(1 for n in self._nodes.values() if n.status == "idle")
            busy_nodes = sum(1 for n in self._nodes.values() if n.status == "busy")

            total_jobs = len(self._jobs)
            queued_jobs = sum(1 for j in self._jobs.values() if j.status == "queued")
            running_jobs = sum(1 for j in self._jobs.values() if j.status == "running")
            completed_jobs = sum(1 for j in self._jobs.values() if j.status == "completed")
            failed_jobs = sum(1 for j in self._jobs.values() if j.status == "failed")

            return {
                "nodes": {
                    "total": total_nodes,
                    "idle": idle_nodes,
                    "busy": busy_nodes,
                },
                "jobs": {
                    "total": total_jobs,
                    "queued": queued_jobs,
                    "running": running_jobs,
                    "completed": completed_jobs,
                    "failed": failed_jobs,
                },
                "queue_depth": self._job_queue.qsize(),
            }

    def _get_idle_node(self) -> Optional[ClusterNode]:
        with self._lock:
            for node in self._nodes.values():
                if node.status == "idle":
                    return node
            return None

    def _dispatch_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id = self._job_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            # Wait for an idle node
            node = None
            while not self._stop_event.is_set():
                node = self._get_idle_node()
                if node:
                    break
                time.sleep(0.1)

            if not node:
                break

            with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    continue
                job.status = "running"
                job.started_at = time.time()
                job.assigned_node_id = node.node_id
                node.status = "busy"
                node.current_job_id = job_id

            # Launch execution thread for this node/job
            t = threading.Thread(target=self._run_job_on_node, args=(job, node), daemon=True)
            t.start()

    def _run_job_on_node(self, job: ClusterJob, node: ClusterNode) -> None:
        try:
            res = node.execute_procedure(job.procedure_data)
            with self._lock:
                job.completed_at = time.time()
                job.result = res
                job.status = "completed" if res.get("ok") else "failed"
                if not res.get("ok"):
                    job.error = res.get("error") or res.get("verdict", "FAIL")
        except Exception as e:
            with self._lock:
                job.completed_at = time.time()
                job.status = "failed"
                job.error = str(e)
                job.result = {"ok": False, "verdict": "INFRA_ERROR", "error": str(e)}
        finally:
            with self._lock:
                node.status = "idle"
                node.current_job_id = None

    def generate_aggregate_report(self, job_ids: Optional[list[str]] = None, format: str = "junit", suite_name: str = "StepProof Cluster Suite") -> str:
        """Aggregate completed cluster jobs into standard enterprise JUnit XML or HTML report."""
        with self._lock:
            target_jobs = [self._jobs[jid] for jid in (job_ids or list(self._jobs.keys())) if jid in self._jobs]

        # Convert to test report format expected by generate_junit_xml and generate_html_report
        test_runs = []
        for j in target_jobs:
            passed = j.status == "completed" and bool((j.result or {}).get("ok", False))
            dur = (j.completed_at - j.started_at) if (j.completed_at and j.started_at) else 0.0
            test_runs.append({
                "name": j.procedure_name,
                "success": passed,
                "wall_s": round(dur, 3),
                "error": (j.error or (j.result or {}).get("error", "")),
                "drifted": False,
                "checks_passed": 1 if passed else 0,
                "checks_total": 1,
            })

        if format.lower() == "html":
            return generate_html_report(suite_name, test_runs)
        return generate_junit_xml(suite_name, test_runs)


# Global singleton
_cluster_manager: Optional[ClusterManager] = None
_cm_lock = threading.Lock()


def get_cluster_manager() -> ClusterManager:
    global _cluster_manager
    with _cm_lock:
        if _cluster_manager is None:
            _cluster_manager = ClusterManager()
        return _cluster_manager
