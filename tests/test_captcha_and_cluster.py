"""Comprehensive test suite for Cloudflare Turnstile/CAPTCHA architecture and Distributed Cloud Cluster execution."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from stepproof.api_v2 import app
from stepproof.captcha.detector import ChallengeInfo, detect_challenge
from stepproof.captcha.solver import (
    CaptchaHandler,
    LocalTurnstileSolver,
    RemoteProviderSolver,
    SolveResult,
)
from stepproof.cluster.manager import ClusterManager, get_cluster_manager
from stepproof.cluster.node import ClusterNode


# ==============================================================================
# Mock Page Helper for Deterministic DOM Tests
# ==============================================================================

class MockPage:
    def __init__(self, url: str = "http://localhost:8011/site/protected", evaluate_results: dict | None = None) -> None:
        self.url = url
        self.evaluate_results = evaluate_results or {}
        self.evaluations: list[str] = []
        self.frames = []
        self.mouse = MagicMock()

    def evaluate(self, expr: str, *args) -> any:
        self.evaluations.append(expr)
        for key, val in self.evaluate_results.items():
            if key in expr:
                return val
        return None

    def locator(self, sel: str) -> MagicMock:
        mock_el = MagicMock()
        mock_el.first = mock_el
        mock_el.is_visible.return_value = True
        mock_el.bounding_box.return_value = {"x": 100, "y": 200, "width": 300, "height": 65}
        return mock_el


# ==============================================================================
# 1. CAPTCHA Detector Tests
# ==============================================================================

def test_detect_turnstile_challenge():
    mock_eval = {
        "Cloudflare Turnstile Check": {
            "detected": True,
            "kind": "turnstile",
            "sitekey": "0x4AAAAAAAE-test-sitekey",
            "action": "login",
            "cdata": "cdata123",
            "frame_selector": "iframe[src*='challenges.cloudflare.com']",
            "checkbox_selector": "input[type='checkbox']",
            "is_interactive": True,
            "details": {"has_response_field": True},
        }
    }
    page = MockPage(evaluate_results=mock_eval)
    ch = detect_challenge(page)
    assert ch.detected is True
    assert ch.kind == "turnstile"
    assert ch.sitekey == "0x4AAAAAAAE-test-sitekey"
    assert ch.action == "login"
    assert ch.cdata == "cdata123"


def test_detect_cloudflare_interstitial():
    mock_eval = {
        "Cloudflare Interstitial": {
            "detected": True,
            "kind": "interstitial",
            "sitekey": None,
            "frame_selector": None,
            "checkbox_selector": None,
            "is_interactive": True,
            "details": {"title": "Just a moment..."},
        }
    }
    page = MockPage(url="https://cf-protected.example.com", evaluate_results=mock_eval)
    ch = detect_challenge(page)
    assert ch.detected is True
    assert ch.kind == "interstitial"


def test_detect_no_challenge_on_clean_page():
    mock_eval = {
        "Cloudflare Turnstile Check": {
            "detected": False,
            "kind": "none",
            "sitekey": None,
            "details": {},
        }
    }
    page = MockPage(evaluate_results=mock_eval)
    ch = detect_challenge(page)
    assert ch.detected is False
    assert ch.kind == "none"


# ==============================================================================
# 2. CAPTCHA Solvers Tests
# ==============================================================================

def test_local_turnstile_solver_success():
    page = MockPage(evaluate_results={
        "cf-turnstile-response": "mock_cf_token_success_abcdef12345"
    })
    ch = ChallengeInfo(detected=True, kind="turnstile", sitekey="test-key")
    solver = LocalTurnstileSolver(timeout_sec=1.0)
    res = solver.solve(ch, page)
    assert res.ok is True
    assert res.method == "local_actuation"
    assert "mock_cf_token_success" in res.token


def test_remote_provider_solver_mock():
    page = MockPage()
    ch = ChallengeInfo(detected=True, kind="turnstile", sitekey="test-key", page_url="http://site.com")
    solver = RemoteProviderSolver(provider="mock")
    res = solver.solve(ch, page)
    assert res.ok is True
    assert res.method == "mock"
    assert res.token.startswith("tok_mock_turnstile_")
    # Verify injection script was evaluated on page
    assert any("cf-turnstile-response" in ev for ev in page.evaluations)


def test_captcha_handler_orchestration_and_fallback():
    # Page with challenge where local solver succeeds
    page_turnstile = MockPage(evaluate_results={
        "Cloudflare Turnstile Check": {"detected": True, "kind": "turnstile", "sitekey": "k1"},
        "cf-turnstile-response": "valid_token_1234567890"
    })
    handler = CaptchaHandler(auto_solve_turnstile=True)
    ch, res = handler.handle(page_turnstile)
    assert ch.detected is True
    assert res.ok is True

    # Page with unresolved interstitial requesting operator takeover
    page_interstitial = MockPage(evaluate_results={
        "Cloudflare Turnstile Check": {"detected": True, "kind": "interstitial", "sitekey": None}
    })
    handler_no_remote = CaptchaHandler(auto_solve_turnstile=True)
    ch2, res2 = handler_no_remote.handle(page_interstitial)
    assert ch2.detected is True
    assert res2.ok is False
    assert res2.method == "human_takeover"


# ==============================================================================
# 3. Distributed Cluster Node & Execution Tests
# ==============================================================================

def test_cluster_node_lifecycle_and_metrics():
    node = ClusterNode(node_id="test-worker-1", node_type="local", concurrency=1)
    assert node.status == "idle"
    assert node.node_id == "test-worker-1"
    assert "chromium" in node.capabilities

    d = node.to_dict()
    assert d["node_id"] == "test-worker-1"
    assert d["status"] == "idle"
    assert d["metrics"]["total_runs"] == 0

    # Test execution with mock procedure
    sample_proc = {
        "goal": "Test Cluster Job",
        "steps": [],
        "checks": []
    }
    with patch("stepproof.agent.executor.execute_procedure") as mock_exec, \
         patch("stepproof.browser.session.TinyBrowser") as mock_tb_cls:
        mock_exec.return_value = MagicMock(success=True, steps_run=0, healed_steps=[], error="")
        outcome = node.execute_procedure(sample_proc)
        assert outcome["ok"] is True
        assert outcome["verdict"] == "PASS"
        assert node.metrics.total_runs == 1
        assert node.metrics.passed_runs == 1


def test_cluster_cdp_node_configuration():
    cdp_url = "wss://browserbase.grid.internal:9222/devtools"
    node = ClusterNode(node_id="cdp-worker-1", node_type="cdp", cdp_url=cdp_url)
    assert node.node_type == "cdp"
    assert node.cdp_url == cdp_url
    d = node.to_dict()
    assert d["cdp_url"] == cdp_url


# ==============================================================================
# 4. ClusterManager Orchestration & Aggregate Reporting Tests
# ==============================================================================

def test_cluster_manager_queue_and_batch_execution():
    cm = ClusterManager(auto_start_worker=False)
    # Register 2 workers
    w1 = cm.register_node("worker-alpha", node_type="local")
    w2 = cm.register_node("worker-beta", node_type="local")
    assert len(cm.list_nodes()) == 2

    # Mock node execution to run immediately and pass
    def mock_run(proc_data):
        return {"node_id": "test", "ok": True, "verdict": "PASS", "steps_run": 2, "healed_steps": [], "error": ""}

    w1.execute_procedure = mock_run
    w2.execute_procedure = mock_run

    procs = [
        {"goal": "Cluster Job 1", "steps": []},
        {"goal": "Cluster Job 2", "steps": []},
        {"goal": "Cluster Job 3", "steps": []},
    ]
    job_ids = cm.submit_batch(procs)
    assert len(job_ids) == 3

    # Wait briefly for dispatcher loop to run
    deadline = time.time() + 5.0
    while time.time() < deadline:
        st = cm.get_status()
        if st["jobs"]["completed"] == 3:
            break
        time.sleep(0.1)

    status = cm.get_status()
    assert status["jobs"]["completed"] == 3
    assert status["jobs"]["failed"] == 0

    # Aggregate JUnit XML report
    junit_xml = cm.generate_aggregate_report(job_ids=job_ids, format="junit")
    assert "<testsuite" in junit_xml
    assert "Cluster Job 1" in junit_xml
    assert 'failures="0"' in junit_xml

    # Aggregate HTML report
    html_rep = cm.generate_aggregate_report(job_ids=job_ids, format="html")
    assert "<!doctype html>" in html_rep.lower()
    assert "Cluster Job 2" in html_rep


# ==============================================================================
# 5. REST API v2 Integration Tests
# ==============================================================================

def test_api_v2_captcha_and_cluster_endpoints():
    client = TestClient(app)

    # 1. Test CAPTCHA detect
    resp = client.get("/api/v2/browser/captcha/detect")
    assert resp.status_code == 200
    data = resp.json()
    assert "detected" in data
    assert "kind" in data

    # 2. Test CAPTCHA solve
    resp_solve = client.post("/api/v2/browser/captcha/solve", json={"provider": "mock"})
    assert resp_solve.status_code == 200
    solve_data = resp_solve.json()
    assert "challenge" in solve_data
    assert "result" in solve_data

    # 3. Test Cluster Status
    resp_cstatus = client.get("/api/v2/cluster/status")
    assert resp_cstatus.status_code == 200
    cst = resp_cstatus.json()
    assert "nodes" in cst
    assert "jobs" in cst

    # 4. Test Cluster Register Node
    node_payload = {
        "node_id": "test-remote-cdp-node",
        "node_type": "cdp",
        "cdp_url": "wss://remote-grid:9222",
        "base_url": "https://remote.grid.corp",
        "concurrency": 2,
        "capabilities": ["chromium", "turnstile"]
    }
    resp_reg = client.post("/api/v2/cluster/nodes", json=node_payload)
    assert resp_reg.status_code == 200
    assert resp_reg.json()["node_id"] == "test-remote-cdp-node"
    assert resp_reg.json()["base_url"] == "https://remote.grid.corp"

    # 5. Test Cluster List Nodes
    resp_nodes = client.get("/api/v2/cluster/nodes")
    assert resp_nodes.status_code == 200
    node_ids = [n["node_id"] for n in resp_nodes.json()]
    assert "test-remote-cdp-node" in node_ids

    # 6. Test Cluster Submit Job
    job_payload = {
        "procedure": {"goal": "API Cluster Test Job", "steps": []},
        "name": "API Cluster Test Job"
    }
    resp_job = client.post("/api/v2/cluster/jobs", json=job_payload)
    assert resp_job.status_code == 200
    job_id = resp_job.json()["job_id"]
    assert resp_job.json()["status"] == "queued"

    # 7. Test Cluster Get Job
    resp_get_job = client.get(f"/api/v2/cluster/jobs/{job_id}")
    assert resp_get_job.status_code == 200
    assert resp_get_job.json()["job_id"] == job_id

    # 8. Test Cluster Report (JUnit)
    resp_rep = client.get("/api/v2/cluster/report?format=junit")
    assert resp_rep.status_code == 200
    assert resp_rep.headers["content-type"].startswith("application/xml")
    assert "<testsuite" in resp_rep.text

    # 9. Test Cluster Deregister Node
    resp_dereg = client.delete("/api/v2/cluster/nodes/test-remote-cdp-node")
    assert resp_dereg.status_code == 200
    assert resp_dereg.json()["ok"] is True


def test_cluster_node_base_url_resolution():
    """Verify that remote CDP nodes do not inject local host base unless configured."""
    # 1. Local node without base_url defaults to http://localhost:8011
    local_node = ClusterNode(node_id="test-local-1", node_type="local")
    assert local_node.base_url is None
    d_local = local_node.to_dict()
    assert d_local["node_type"] == "local"
    assert d_local["base_url"] is None

    # 2. CDP node without base_url remains None (does not inject local base)
    cdp_node = ClusterNode(node_id="test-cdp-1", node_type="cdp", cdp_url="wss://worker.corp:9222")
    assert cdp_node.base_url is None
    assert cdp_node.to_dict()["base_url"] is None

    # 3. CDP node with custom base_url preserves it
    cdp_custom = ClusterNode(
        node_id="test-cdp-2",
        node_type="cdp",
        cdp_url="wss://worker.corp:9222",
        base_url="https://staging.internal.corp",
    )
    assert cdp_custom.base_url == "https://staging.internal.corp"
    assert cdp_custom.to_dict()["base_url"] == "https://staging.internal.corp"

    # 4. Verify base resolution in execute_procedure invocation logic
    mock_proc = {
        "site": "/site/expense",
        "steps": [],
    }
    with patch("stepproof.cluster.node.execute_procedure") as mock_exec, \
         patch("stepproof.browser.session.TinyBrowser") as mock_tb_cls:
        mock_tb = MagicMock()
        mock_tb.start_site.return_value = {"ok": True, "url": "https://example.com"}
        mock_tb_cls.return_value = mock_tb
        mock_exec.return_value = MagicMock(success=True, steps_run=1, healed_steps=[], error="")

        # Test local node execution -> injects http://localhost:8011
        local_node.execute_procedure(mock_proc)
        mock_tb.start_site.assert_called_with("/site/expense", base="http://localhost:8011")

        # Test remote cdp node execution -> injects None (no local base)
        mock_tb.reset_mock()
        mock_tb.start_site.return_value = {"ok": True, "url": "https://example.com"}
        cdp_node.execute_procedure(mock_proc)
        mock_tb.start_site.assert_called_with("/site/expense", base=None)

        # Test remote cdp node with explicit base_url -> injects custom base
        mock_tb.reset_mock()
        mock_tb.start_site.return_value = {"ok": True, "url": "https://example.com"}
        cdp_custom.execute_procedure(mock_proc)
        mock_tb.start_site.assert_called_with("/site/expense", base="https://staging.internal.corp")


def test_cluster_node_navigation_refusal_short_circuit():
    """Verify that when start_site navigation is refused by allowlist, node immediately returns INFRA_ERROR."""
    node = ClusterNode(node_id="test-infra-1", node_type="cdp", cdp_url="wss://worker.corp:9222")
    mock_proc = {
        "site": "https://untrusted.host.corp/login",
        "steps": [{"id": "s1", "description": "click submit", "action": "click", "arg": {"name": "Submit"}}],
    }
    with patch("stepproof.cluster.node.execute_procedure") as mock_exec, \
         patch("stepproof.browser.session.TinyBrowser") as mock_tb_cls:
        mock_tb = MagicMock()
        mock_tb_cls.return_value = mock_tb
        mock_tb.start_site.return_value = {
            "ok": False,
            "error": "refused: host 'untrusted.host.corp' not on the allowlist"
        }

        res = node.execute_procedure(mock_proc)
        assert res["ok"] is False
        assert res["verdict"] == "INFRA_ERROR"
        assert "refused" in res["error"]
        assert res["steps_run"] == 0
        # execute_procedure MUST NOT have been called on blank page
        mock_exec.assert_not_called()


