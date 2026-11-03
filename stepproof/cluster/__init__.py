"""Distributed Cloud Cluster Execution layer for StepProof.

Coordinates multi-worker execution pools across local instances and remote CDP nodes
(Browserbase, Playwright Grid, Browserless, Docker Swarm), with an asynchronous job
queue and aggregated enterprise test reporting (JUnit XML & HTML).
"""
from __future__ import annotations

from .node import ClusterNode
from .manager import ClusterManager, ClusterJob, get_cluster_manager

__all__ = [
    "ClusterNode",
    "ClusterManager",
    "ClusterJob",
    "get_cluster_manager",
]

