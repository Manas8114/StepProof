"""Automated and pluggable CAPTCHA solving architecture.

Supports:
1. Local Cloudflare Turnstile Solver: DOM checkbox locating, realistic jittered mouse actuation, and token resolution.
2. Remote Provider Solver: Standard pluggable adapter for 2Captcha, CapSolver, AntiCaptcha, and offline Mock.
3. CaptchaHandler: Orchestrator that detects, attempts automated resolution, and gracefully triggers operator takeover (PAUSED_HUMAN) if needed.
"""
from __future__ import annotations

import json
import os
import random
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

from .detector import ChallengeInfo, detect_challenge
from .. import events


@dataclass
class SolveResult:
    ok: bool
    token: Optional[str] = None
    method: str = "none"  # "local_actuation" | "remote_provider" | "mock" | "human_takeover" | "failed" | "none"
    error: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "token": self.token,
            "method": self.method,
            "error": self.error,
            "details": self.details,
        }


class BaseCaptchaSolver:
    """Abstract solver base."""
    def solve(self, challenge: ChallengeInfo, page: Any) -> SolveResult:
        raise NotImplementedError


class LocalTurnstileSolver(BaseCaptchaSolver):
    """Local solver for Cloudflare Turnstile challenges.
    
    Interacts with the embedded Turnstile iframe or container, applies human-like
    jittered coordinates to actuate the checkbox, and awaits response token.
    """

    def __init__(self, timeout_sec: float = 8.0) -> None:
        self.timeout_sec = timeout_sec

    def solve(self, challenge: ChallengeInfo, page: Any) -> SolveResult:
        if challenge.kind != "turnstile":
            return SolveResult(ok=False, method="local_actuation", error=f"Unsupported kind: {challenge.kind}")

        t0 = time.time()

        # Step 1: Check if already solved
        try:
            existing_tok = page.evaluate("() => document.querySelector('input[name=\"cf-turnstile-response\"]')?.value || null")
            if existing_tok and len(existing_tok.strip()) > 10:
                return SolveResult(ok=True, token=existing_tok, method="local_actuation", details={"status": "already_present"})
        except Exception:
            pass

        # Step 2: Locate Turnstile frame or element
        actuated = False
        try:
            # Try frame locator first
            frames = getattr(page, "frames", [])
            ts_frame = None
            for f in frames:
                f_url = getattr(f, "url", "")
                if "challenges.cloudflare.com" in f_url or "turnstile" in f_url:
                    ts_frame = f
                    break

            if ts_frame:
                # Click checkbox inside frame
                for sel in ["input[type='checkbox']", ".cb-lb", "#challenge-stage", "label.ctp-checkbox-label"]:
                    try:
                        box = ts_frame.locator(sel).first
                        if box.is_visible(timeout=1000):
                            box.click()
                            actuated = True
                            break
                    except Exception:
                        continue

            # Fallback: click within parent page iframe bounding box with human-like jitter
            if not actuated:
                for iframe_sel in ['iframe[src*="challenges.cloudflare.com"]', 'iframe[src*="turnstile"]', '.cf-turnstile']:
                    try:
                        el = page.locator(iframe_sel).first
                        if el.is_visible(timeout=1000):
                            bb = el.bounding_box()
                            if bb:
                                # Turnstile checkbox is at ~30px from left edge, vertically centered
                                jitter_x = bb["x"] + 28 + random.uniform(-4, 4)
                                jitter_y = bb["y"] + (bb["height"] / 2) + random.uniform(-4, 4)
                                page.mouse.move(jitter_x, jitter_y)
                                time.sleep(0.08)
                                page.mouse.down()
                                time.sleep(random.uniform(0.04, 0.12))
                                page.mouse.up()
                                actuated = True
                                break
                    except Exception:
                        continue
        except Exception as e:
            # If actuation throws, continue to poll in case it auto-solves
            pass

        # Step 3: Poll for token resolution
        deadline = t0 + self.timeout_sec
        while time.time() < deadline:
            try:
                tok = page.evaluate("() => document.querySelector('input[name=\"cf-turnstile-response\"]')?.value || null")
                if tok and len(tok.strip()) > 10:
                    return SolveResult(ok=True, token=tok, method="local_actuation", details={"elapsed_sec": round(time.time() - t0, 3)})
            except Exception:
                pass
            time.sleep(0.3)

        return SolveResult(
            ok=False,
            method="local_actuation",
            error=f"Turnstile local actuation timed out after {self.timeout_sec}s",
            details={"actuated": actuated}
        )


class RemoteProviderSolver(BaseCaptchaSolver):
    """Pluggable remote solving service adapter.
    
    Supports:
    - 'mock': offline testing and deterministic simulation.
    - '2captcha': standard 2Captcha Turnstile/reCAPTCHA/hCaptcha API.
    - 'capsolver': CapSolver API.
    - 'anticaptcha': Anti-Captcha API.
    """

    def __init__(self, provider: str = "mock", api_key: str = "", solver_url: Optional[str] = None, timeout_sec: float = 45.0) -> None:
        self.provider = provider.lower()
        self.api_key = api_key or os.environ.get("CAPTCHA_API_KEY", "")
        self.solver_url = solver_url or os.environ.get("CAPTCHA_SOLVER_URL", "")
        self.timeout_sec = timeout_sec

    def solve(self, challenge: ChallengeInfo, page: Any) -> SolveResult:
        if self.provider == "mock":
            # Generate deterministic synthetic token and inject into page DOM
            mock_token = f"tok_mock_{challenge.kind}_{int(time.time())}"
            self._inject_token(challenge, page, mock_token)
            return SolveResult(ok=True, token=mock_token, method="mock", details={"provider": "mock"})

        if not self.api_key:
            return SolveResult(ok=False, method="remote_provider", error=f"Missing API key for provider {self.provider}")

        try:
            if self.provider == "2captcha":
                token = self._solve_2captcha(challenge)
            elif self.provider in ("capsolver", "anticaptcha"):
                token = self._solve_capsolver_family(challenge)
            else:
                return SolveResult(ok=False, method="remote_provider", error=f"Unknown provider: {self.provider}")

            if token:
                self._inject_token(challenge, page, token)
                return SolveResult(ok=True, token=token, method="remote_provider", details={"provider": self.provider})
            return SolveResult(ok=False, method="remote_provider", error="No token returned from provider")
        except Exception as e:
            return SolveResult(ok=False, method="remote_provider", error=f"Provider {self.provider} failed: {e}")

    def _solve_2captcha(self, ch: ChallengeInfo) -> str:
        base = self.solver_url or "https://2captcha.com"
        in_params = {
            "key": self.api_key,
            "json": 1,
            "pageurl": ch.page_url,
        }
        if ch.kind == "turnstile":
            in_params.update({"method": "turnstile", "sitekey": ch.sitekey or ""})
            if ch.action: in_params["action"] = ch.action
            if ch.cdata: in_params["data"] = ch.cdata
        elif ch.kind == "hcaptcha":
            in_params.update({"method": "hcaptcha", "sitekey": ch.sitekey or ""})
        elif ch.kind == "recaptcha":
            in_params.update({"method": "userrecaptcha", "googlekey": ch.sitekey or ""})
        else:
            raise ValueError(f"2captcha unsupported kind: {ch.kind}")

        req_data = urllib.parse.urlencode(in_params).encode("utf-8")
        req = urllib.request.Request(f"{base}/in.php", data=req_data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != 1:
            raise RuntimeError(f"2captcha in.php error: {data}")

        task_id = data.get("request")
        deadline = time.time() + self.timeout_sec
        while time.time() < deadline:
            time.sleep(3.0)
            res_url = f"{base}/res.php?key={self.api_key}&action=get&id={task_id}&json=1"
            with urllib.request.urlopen(res_url, timeout=10) as r:
                res_data = json.loads(r.read().decode("utf-8"))
            if res_data.get("status") == 1:
                return res_data.get("request", "")
            if res_data.get("request") != "CAPCHA_NOT_READY":
                raise RuntimeError(f"2captcha res.php failed: {res_data}")

        raise TimeoutError("2captcha polling timed out")

    def _solve_capsolver_family(self, ch: ChallengeInfo) -> str:
        base = self.solver_url or ("https://api.capsolver.com" if self.provider == "capsolver" else "https://api.anti-captcha.com")
        task_type_map = {
            "turnstile": "AntiTurnstileTaskProxyLess",
            "hcaptcha": "HCaptchaTaskProxyLess",
            "recaptcha": "ReCaptchaV2TaskProxyLess",
        }
        task_payload = {
            "type": task_type_map.get(ch.kind, "AntiTurnstileTaskProxyLess"),
            "websiteURL": ch.page_url,
            "websiteKey": ch.sitekey or "",
        }
        create_body = json.dumps({"clientKey": self.api_key, "task": task_payload}).encode("utf-8")
        req = urllib.request.Request(f"{base}/createTask", data=create_body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("errorId", 0) != 0:
            raise RuntimeError(f"CreateTask error: {data}")

        task_id = data.get("taskId")
        deadline = time.time() + self.timeout_sec
        while time.time() < deadline:
            time.sleep(3.0)
            poll_body = json.dumps({"clientKey": self.api_key, "taskId": task_id}).encode("utf-8")
            preq = urllib.request.Request(f"{base}/getTaskResult", data=poll_body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(preq, timeout=10) as presp:
                pdata = json.loads(presp.read().decode("utf-8"))
            status = pdata.get("status")
            if status == "ready":
                sol = pdata.get("solution", {})
                return sol.get("token") or sol.get("gRecaptchaResponse") or ""
            if status == "failed":
                raise RuntimeError(f"Task failed: {pdata}")

        raise TimeoutError(f"{self.provider} polling timed out")

    def _inject_token(self, ch: ChallengeInfo, page: Any, token: str) -> None:
        """Inject solved token into the page DOM input fields and trigger callbacks."""
        script = """(tok) => {
            const setVal = (sel) => {
                const el = document.querySelector(sel);
                if (el) {
                    el.value = tok;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
            };
            setVal('input[name="cf-turnstile-response"]');
            setVal('textarea[name="h-captcha-response"]');
            setVal('input[name="h-captcha-response"]');
            setVal('textarea[name="g-recaptcha-response"]');
            setVal('input[name="g-recaptcha-response"]');

            // Dispatch global event for listeners
            window.dispatchEvent(new CustomEvent('stepproof_captcha_solved', { detail: { token: tok } }));
        }"""
        try:
            page.evaluate(script, token)
        except Exception:
            pass


class CaptchaHandler:
    """Orchestrates detection, automated resolution, and operator takeover."""

    def __init__(self,
                 auto_solve_turnstile: bool = True,
                 remote_provider: Optional[str] = None,
                 provider_api_key: Optional[str] = None) -> None:
        self.auto_solve_turnstile = auto_solve_turnstile
        self.local_turnstile = LocalTurnstileSolver()
        provider = remote_provider or os.environ.get("CAPTCHA_PROVIDER", "")
        self.remote_solver = RemoteProviderSolver(provider=provider, api_key=provider_api_key or "") if provider else None

    def handle(self, page: Any) -> tuple[ChallengeInfo, SolveResult]:
        """Detect challenge, attempt automated solve if configured, or request takeover."""
        ch = detect_challenge(page)
        if not ch.detected:
            return ch, SolveResult(ok=True, method="none")

        events.emit("captcha_detected", ch.to_dict())

        # 1. Try local Turnstile solver if applicable
        if ch.kind == "turnstile" and self.auto_solve_turnstile:
            res = self.local_turnstile.solve(ch, page)
            if res.ok:
                events.emit("captcha_solved", {"kind": "turnstile", "method": res.method, "token": res.token})
                return ch, res

        # 2. Try remote solver if configured
        if self.remote_solver:
            res = self.remote_solver.solve(ch, page)
            if res.ok:
                events.emit("captcha_solved", {"kind": ch.kind, "method": res.method, "token": res.token})
                return ch, res

        # 3. Graceful takeover: emit operator intervention event and return PAUSED_HUMAN state
        takeover_res = SolveResult(
            ok=False,
            method="human_takeover",
            error=f"Unresolved {ch.kind} challenge requires human takeover",
            details=ch.to_dict()
        )
        events.emit("operator_intervene", {
            "reason": f"CAPTCHA challenge detected ({ch.kind}); operator takeover requested.",
            "challenge": ch.to_dict()
        })
        return ch, takeover_res
