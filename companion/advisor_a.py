"""P2 Advisor A - "is this file important?" (a check-BEFORE-you-delete tool).

Hard rule the whole module enforces: the RISK CLASS and the VERDICT are decided by
DETERMINISTIC CODE from read-only signals. A model may *phrase* the explanation but can
NEVER set the risk class or waive a rule. The OS cannot be reliably intercepted before a
delete, so this is a check tool (a Windows "Send to" shortcut is the stretch, not the core).

Actions are reversible by construction: the only thing this advisor may *do* is move a file
to the Recycle Bin / a managed trash dir (never a permanent delete), and only after a
dry-run + audit log. File names and contents are UNTRUSTED text and cannot change these rules.
"""
from __future__ import annotations
import os, shutil, stat, time
from dataclasses import dataclass, field
from pathlib import Path

_SECRET_PATTERNS = (".env", "id_rsa", "id_ed25519", "wallet", ".key", "credential",
                   "secret", "password", "token", ".pem", "ssh")
_REGENERABLE_PATTERNS = ("node_modules", "pycache", "__pycache__", ".pytest_cache",
                         ".venv", "build", "dist", ".next", "out/", "obj/", ".mypy_cache",
                         "coverage", "target")
_DOC_EXTS = {".pdf", ".docx", ".doc", ".xlsx", ".pptx", ".txt", ".md", ".csv",
             ".pages", ".key", ".zip", ".eml", ".msg"}


@dataclass
class DeleteAdvice:
    verdict: str                 # keep | review | likely_safe | safe
    risk: str                   # low | medium | high
    reasons: list[str] = field(default_factory=list)
    signals: dict = field(default_factory=dict)


def _is_secret(sig: dict) -> bool:
    return bool(sig.get("is_secret")) or any(p in str(sig.get("name", "")).lower() for p in _SECRET_PATTERNS)


def _is_regenerable(sig: dict) -> bool:
    blob = (str(sig.get("path", "")) + " " + str(sig.get("name", ""))).lower()
    return bool(sig.get("is_regenerable")) or any(p in blob for p in _REGENERABLE_PATTERNS)


def risk_class_for(sig: dict) -> str:
    """PURE: the risk class from signals only (no model input). The highest applicable
    risk wins. This is the class the model is FORBIDDEN to change."""
    if _is_secret(sig):
        return "high"
    if sig.get("open_handles"):
        return "medium"
    if sig.get("is_duplicate"):
        return "low"
    if _is_regenerable(sig):
        return "low"
    return "medium"


def assess_delete(sig: dict) -> DeleteAdvice:
    """PURE + DETERMINISTIC: signals -> (verdict, risk, reasons). No I/O, no model.
    'sig' is the signal bundle from gather_signals() (or a test's hand-built dict)."""
    reasons: list[str] = []
    secret = _is_secret(sig)
    regen = _is_regenerable(sig)
    dup = bool(sig.get("is_duplicate"))
    handles = int(sig.get("open_handles") or 0)
    git = str(sig.get("git", "")).lower()

    if secret:
        reasons.append("matches a secrets/credentials pattern (.env, keys, wallets) - high risk")
    if handles:
        reasons.append(f"{handles} open handle(s) on this file")
    if dup:
        reasons.append("a duplicate/synced copy exists")
    if regen:
        reasons.append("regenerable build/artifact or cache")
    if git == "tracked":
        reasons.append("tracked by git (recoverable in history)")

    risk = risk_class_for(sig)
    if secret:
        verdict = "keep"
    elif dup:
        verdict = "safe"
    elif regen and not handles:
        verdict = "likely_safe"
    elif handles:
        verdict = "review"
    elif git == "tracked":
        verdict = "review"
    else:
        # unknown / user document: NEVER 'safe' without duplicate or backup evidence
        verdict = "review" if sig.get("location") in ("documents", "downloads", "home") or \
            sig.get("ext", "").lower() in _DOC_EXTS else "keep"

    return DeleteAdvice(verdict=verdict, risk=risk, reasons=reasons, signals=dict(sig))


def is_reversible_action(action: str) -> bool:
    """Only trash-style actions are ever proposed; permanent delete is refused."""
    s = str(action).lower()
    if s in ("os.remove", "rm", "del", "shutil.rmtree", "permanent") or "rmtree" in s:
        return False
    return "trash" in s


def gather_signals(path: str, roots: list[str] | None = None) -> dict:
    """READ-ONLY signal gather over a user-selected path. Bounded: no unbounded scans, no
    file contents read, psutil/ git used read-only and best-effort. Never touches OS dirs."""
    p = str(path)
    low = p.lower()
    sig: dict = {"path": p, "name": os.path.basename(p), "ext": os.path.splitext(p)[1].lower()}
    sig["is_secret"] = any(t in low for t in _SECRET_PATTERNS)
    sig["is_regenerable"] = any(t in low for t in _REGENERABLE_PATTERNS)
    sig["location"] = _location_class(p)
    sig["is_duplicate"] = False
    sig["open_handles"] = _open_handles(p)
    sig["git"] = _git_state(p)
    return sig


def _location_class(p: str) -> str:
    low = p.lower()
    if any(k in low for k in ("windows", "system32", "\\sysnative", "program files")):
        return "system"
    if any(k in low for k in ("appdata", "node_modules", ".venv", "program")):
        return "app_data"
    if any(k in low for k in ("temp", "cache", "tmp")):
        return "temp"
    if any(k in low for k in ("documents", "downloads", "\\me\\", "users")):
        return "documents" if "documents" in low or "\\me\\" in low else "downloads"
    return "project"


def _open_handles(p: str) -> int:
    try:
        import psutil
        n = 0
        for proc in psutil.process_iter(["num_fds"]):
            try:
                for fh in proc.open_files():
                    if fh.path.lower() == p.lower():
                        n += 1
            except (psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return n
    except Exception:
        return 0


def _git_state(p: str) -> str:
    try:
        import subprocess
        out = subprocess.run(["git", "status", "--porcelain"], cwd=str(Path(p).parent),
                             capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            return "not_git"
        return "tracked" if out.stdout.strip() == "" else "untracked_or_modified"
    except Exception:
        return "unknown"


def suggestion_from_advice(advice: DeleteAdvice) -> dict:
    """The `Suggestion` shape the P2 side panel renders. Risk/verdict come from code; the
    'why' text is what a model MAY rephrase (never the risk class)."""
    return {
        "id": f"adv-a-{abs(hash(advice.signals.get('path', ''))) % 10**6}",
        "title": f"Is '{advice.signals.get('name', 'this file')}' important?",
        "why": "; ".join(advice.reasons) or "no risk signal matched",
        "evidence": {k: advice.signals.get(k) for k in
                      ("location", "git", "open_handles", "ext") if k in advice.signals},
        "risk": advice.risk,
        "verdict": advice.verdict,
        "reversible": True,
        "confidence": round(min(0.99, 0.55 + 0.1 * len(advice.reasons)), 2),
        "action": "trash" if advice.verdict in ("safe", "likely_safe") else "none",
    }
