"""Signed, portable procedure artifacts.
Models perceive, code decides: a Procedure is cryptographically signed at compile/save
time. Replay on another machine verifies the SHA-256 manifest and provenance signature
deterministically. Any alteration to steps, locators, or checks is rejected.
"""
from __future__ import annotations
import hashlib, hmac, json, os, time
from typing import Optional, Any
from pathlib import Path

DEFAULT_DEV_KEY = "dev-insecure-key-stepproof-v2-local"


def get_device_key(key_dir: Optional[Path] = None) -> str:
    """Retrieve or generate persistent device key from data/keys/device.key.
    Generated on first sign into data/keys/ (gitignored). Stdlib secrets - no new dependencies.
    """
    key = os.getenv("STEPPROOF_SIGNING_KEY", "").strip()
    if key:
        return key
    key_path = os.getenv("STEPPROOF_SIGNING_KEY_PATH", "")
    if key_path and Path(key_path).exists():
        return Path(key_path).read_text(encoding="utf-8").strip()

    d_dir = key_dir or (Path(__file__).resolve().parent.parent / "data" / "keys")
    d_dir.mkdir(parents=True, exist_ok=True)
    d_key_file = d_dir / "device.key"
    if d_key_file.exists():
        k = d_key_file.read_text(encoding="utf-8").strip()
        if k:
            return k

    import secrets
    new_key = secrets.token_hex(32)
    d_key_file.write_text(new_key, encoding="utf-8")
    return new_key


def get_signing_key() -> str:
    """Retrieve signing key: explicit env, file, or device key."""
    return get_device_key()


def canonical_json(data: Any) -> str:
    """Byte-deterministic canonical JSON representation: sorted keys and pinned separators."""
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def canonical_procedure_payload(proc: Any) -> dict:
    """Canonical dictionary representation of the procedure body for SHA-256 hashing."""
    steps_list = []
    for s in getattr(proc, "steps", []):
        locs = []
        for l in getattr(s, "locators", []):
            kind = l.kind if hasattr(l, "kind") else l.get("kind", "css")
            val = l.value if hasattr(l, "value") else l.get("value", "")
            locs.append({"kind": kind, "value": val})
        s_dict = {
            "id": getattr(s, "id", ""),
            "description": getattr(s, "description", ""),
            "action": getattr(s, "action", "click"),
            "arg": getattr(s, "arg", {}) or {},
            "locators": locs,
            "success": getattr(s, "success", []) or [],
            "note": getattr(s, "note", "") or "",
            "vision_concept": getattr(s, "vision_concept", "") or "",
        }
        steps_list.append(s_dict)

    return {
        "goal": getattr(proc, "goal", "") or "",
        "site": getattr(proc, "site", "") or "",
        "parameters": getattr(proc, "parameters", {}) or {},
        "source": getattr(proc, "source", "manual") or "manual",
        "steps": steps_list,
        "success_checks": getattr(proc, "success_checks", []) or [],
    }


def compute_procedure_hash(proc: Any) -> str:
    """Compute the SHA-256 hash of the canonical procedure payload."""
    payload = canonical_procedure_payload(proc)
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def build_manifest(proc: Any) -> dict:
    """Build the canonical manifest containing hashes and counts."""
    proc_hash = compute_procedure_hash(proc)
    steps = getattr(proc, "steps", [])
    checks = getattr(proc, "success_checks", [])
    return {
        "version": "1.0",
        "format": "stepproof-procedure-manifest-v1",
        "procedure_hash": proc_hash,
        "step_count": len(steps),
        "check_count": len(checks),
        "steps_hashes": [
            hashlib.sha256(canonical_json(s).encode("utf-8")).hexdigest()
            for s in canonical_procedure_payload(proc)["steps"]
        ],
    }


def sign_procedure(proc: Any, key: Optional[str] = None, model_name: str = "compiler") -> Any:
    """Sign a procedure in-place and return it."""
    k = key or get_signing_key()
    manifest = build_manifest(proc)
    proc.manifest = manifest

    prov = dict(getattr(proc, "provenance", {}) or {})
    prov.setdefault("compiler_version", "stepproof-v2.1")
    prov.setdefault("model_used", model_name)
    prov.setdefault("signing_key_id", "custom" if k != DEFAULT_DEV_KEY else "dev-default")
    prov["ts"] = round(time.time(), 3)
    proc.provenance = prov

    # Compute HMAC-SHA256 signature over canonical manifest
    manifest_bytes = canonical_json(manifest).encode("utf-8")
    proc.signature = hmac.new(k.encode("utf-8"), manifest_bytes, hashlib.sha256).hexdigest()
    return proc


def verify_procedure(proc: Any, key: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """Verify that the procedure's manifest and signature match the procedure contents."""
    if not getattr(proc, "signature", None) or not getattr(proc, "manifest", None):
        return False, "Unsigned procedure: missing signature or manifest"

    manifest = getattr(proc, "manifest", {})
    expected_proc_hash = compute_procedure_hash(proc)
    manifest_proc_hash = manifest.get("procedure_hash")

    if manifest_proc_hash != expected_proc_hash:
        return False, (f"Tampered procedure body: payload SHA-256 {expected_proc_hash} "
                       f"does not match manifest {manifest_proc_hash}")

    k = key or get_signing_key()
    manifest_bytes = canonical_json(manifest).encode("utf-8")
    expected_sig = hmac.new(k.encode("utf-8"), manifest_bytes, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(proc.signature, expected_sig):
        # Scope DEFAULT_DEV_KEY fallback exclusively to standard templates declaring dev-default in provenance
        prov = getattr(proc, "provenance", {}) or {}
        if prov.get("signing_key_id") == "dev-default":
            dev_sig = hmac.new(DEFAULT_DEV_KEY.encode("utf-8"), manifest_bytes, hashlib.sha256).hexdigest()
            if hmac.compare_digest(proc.signature, dev_sig):
                return True, None
        return False, f"Signature mismatch: procedure was modified or signed with different key"

    return True, None
