"""CAPTCHA challenge detection across Cloudflare Turnstile, hCaptcha, reCAPTCHA, and Cloudflare interstitials."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ChallengeInfo:
    """Structured metadata about an observed anti-bot challenge."""
    detected: bool
    kind: str  # "turnstile" | "hcaptcha" | "recaptcha" | "interstitial" | "aws_waf" | "none"
    sitekey: Optional[str] = None
    action: Optional[str] = None
    cdata: Optional[str] = None
    page_url: str = ""
    frame_selector: Optional[str] = None
    checkbox_selector: Optional[str] = None
    is_interactive: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "kind": self.kind,
            "sitekey": self.sitekey,
            "action": self.action,
            "cdata": self.cdata,
            "page_url": self.page_url,
            "frame_selector": self.frame_selector,
            "checkbox_selector": self.checkbox_selector,
            "is_interactive": self.is_interactive,
            "details": self.details,
        }


_DETECTION_SCRIPT = """() => {
    const res = {
        detected: false,
        kind: 'none',
        sitekey: null,
        action: null,
        cdata: null,
        frame_selector: null,
        checkbox_selector: null,
        is_interactive: true,
        details: {}
    };

    // 1. Cloudflare Turnstile Check
    const tsIframe = document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]');
    const tsElem = document.querySelector('.cf-turnstile, [data-turnstile], [data-sitekey]');
    const tsInput = document.querySelector('input[name="cf-turnstile-response"]');

    if (tsIframe || (tsElem && tsElem.classList.contains('cf-turnstile')) || tsInput) {
        res.detected = true;
        res.kind = 'turnstile';
        res.frame_selector = tsIframe ? 'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]' : null;
        res.checkbox_selector = 'input[type="checkbox"], .cb-lb, #challenge-stage';

        if (tsElem && tsElem.getAttribute('data-sitekey')) {
            res.sitekey = tsElem.getAttribute('data-sitekey');
        } else if (tsIframe && tsIframe.src) {
            try {
                const url = new URL(tsIframe.src);
                res.sitekey = url.searchParams.get('sitekey') || url.searchParams.get('key');
                res.action = url.searchParams.get('action');
                res.cdata = url.searchParams.get('cdata');
            } catch (e) {}
        }
        res.details.has_response_field = !!tsInput;
        return res;
    }

    // 2. Cloudflare Interstitial / Under-Attack Mode
    const title = (document.title || '').trim().toLowerCase();
    const bodyText = (document.body ? document.body.innerText || '' : '').toLowerCase();
    if (
        title.includes('just a moment...') ||
        title.includes('attention required! | cloudflare') ||
        (bodyText.includes('checking your browser before accessing') && bodyText.includes('cloudflare')) ||
        (bodyText.includes('verifying you are human') && bodyText.includes('cloudflare'))
    ) {
        res.detected = true;
        res.kind = 'interstitial';
        res.is_interactive = true;
        res.details.title = document.title;
        return res;
    }

    // 3. hCaptcha Check
    const hIframe = document.querySelector('iframe[src*="hcaptcha.com"]');
    const hElem = document.querySelector('.h-captcha, [data-hcaptcha]');
    const hInput = document.querySelector('textarea[name="h-captcha-response"], input[name="h-captcha-response"]');

    if (hIframe || hElem || hInput) {
        res.detected = true;
        res.kind = 'hcaptcha';
        res.frame_selector = 'iframe[src*="hcaptcha.com"]';
        res.checkbox_selector = '#checkbox';
        if (hElem && hElem.getAttribute('data-sitekey')) {
            res.sitekey = hElem.getAttribute('data-sitekey');
        } else if (hIframe && hIframe.src) {
            try {
                const url = new URL(hIframe.src);
                res.sitekey = url.searchParams.get('sitekey');
            } catch (e) {}
        }
        return res;
    }

    // 4. Google reCAPTCHA Check (v2 / v3 / Enterprise)
    const rcIframe = document.querySelector('iframe[src*="google.com/recaptcha"], iframe[src*="recaptcha/api2"]');
    const rcElem = document.querySelector('.g-recaptcha, [data-recaptcha]');
    const rcInput = document.querySelector('textarea[name="g-recaptcha-response"], input[name="g-recaptcha-response"]');

    if (rcIframe || rcElem || rcInput) {
        res.detected = true;
        res.kind = 'recaptcha';
        res.frame_selector = 'iframe[src*="google.com/recaptcha"], iframe[src*="recaptcha/api2"]';
        res.checkbox_selector = '.recaptcha-checkbox';
        if (rcElem && rcElem.getAttribute('data-sitekey')) {
            res.sitekey = rcElem.getAttribute('data-sitekey');
        } else if (rcIframe && rcIframe.src) {
            try {
                const url = new URL(rcIframe.src);
                res.sitekey = url.searchParams.get('k');
            } catch (e) {}
        }
        return res;
    }

    // 5. AWS WAF Captcha Check
    const awsElem = document.querySelector('#aws-waf-captcha, iframe[src*="awswaf.com"]');
    if (awsElem) {
        res.detected = true;
        res.kind = 'aws_waf';
        res.frame_selector = 'iframe[src*="awswaf.com"]';
        return res;
    }

    return res;
}"""


def detect_challenge(page: Any) -> ChallengeInfo:
    """Detect anti-bot challenge on a Playwright page or mock page."""
    current_url = ""
    try:
        current_url = getattr(page, "url", "")
    except Exception:
        pass

    try:
        raw = page.evaluate(_DETECTION_SCRIPT)
        if isinstance(raw, dict):
            return ChallengeInfo(
                detected=bool(raw.get("detected", False)),
                kind=str(raw.get("kind", "none")),
                sitekey=raw.get("sitekey"),
                action=raw.get("action"),
                cdata=raw.get("cdata"),
                page_url=current_url,
                frame_selector=raw.get("frame_selector"),
                checkbox_selector=raw.get("checkbox_selector"),
                is_interactive=bool(raw.get("is_interactive", True)),
                details=raw.get("details", {}),
            )
    except Exception as e:
        # Fallback regex check on page content if evaluate fails
        try:
            content = page.content().lower()
            if "challenges.cloudflare.com" in content or "cf-turnstile" in content:
                sitekey_match = re.search(r'data-sitekey=["\']([^"\']+)["\']', content)
                return ChallengeInfo(
                    detected=True,
                    kind="turnstile",
                    sitekey=sitekey_match.group(1) if sitekey_match else None,
                    page_url=current_url,
                )
            if "just a moment..." in content and "cloudflare" in content:
                return ChallengeInfo(
                    detected=True,
                    kind="interstitial",
                    page_url=current_url,
                )
        except Exception:
            pass

    return ChallengeInfo(
        detected=False,
        kind="none",
        page_url=current_url,
    )

