"""Signed, portable procedure and skill artifacts.
Models perceive, code decides: artifacts are canonically serialized, hashed with SHA-256,
and signed via HMAC under a persistent local device key.
Replay on another machine verifies the cryptographic manifest deterministically.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional, Any, Union

from .signing import (
    canonical_json,
    canonical_procedure_payload,
    compute_procedure_hash,
    build_manifest,
    get_device_key,
    get_signing_key,
)


def sign_procedure(proc: Any, device_key: Optional[str] = None, model_name: str = "compiler") -> dict:
    """Sign a procedure in-place and return the manifest dictionary.
    Manifest contains procedure SHA-256 and per-step hashes.
    Provenance records timestamp, compiler version, and fallback disclosure.
    HMAC is generated over the canonical manifest JSON.
    """
    k = device_key or get_signing_key()
    manifest = build_manifest(proc)
    proc.manifest = manifest

    prov = dict(getattr(proc, "provenance", {}) or {})
    prov.setdefault("compiler_version", "stepproof-v2.1")
    prov.setdefault("model_used", model_name)
    prov.setdefault("source", getattr(proc, "source", "manual") or "manual")
    prov.setdefault("device_id", hashlib.sha256(k.encode("utf-8")).hexdigest()[:16])
    prov["recorded_ts"] = round(time.time(), 3)
    proc.provenance = prov

    manifest_bytes = canonical_json(manifest).encode("utf-8")
    proc.signature = hmac.new(k.encode("utf-8"), manifest_bytes, hashlib.sha256).hexdigest()
    return manifest


def verify_artifact(payload: Union[dict, Any], device_key: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """Verify cryptographic integrity of an artifact (dict, Procedure, or ProcedureFamily).
    Verifies:
      1. Manifest procedure_hash matches actual payload canonical SHA-256.
      2. If device_key is provided or matches, verifies HMAC signature.
      3. Verifies internal step hashes match steps array.
    """
    if isinstance(payload, dict):
        manifest = payload.get("manifest")
        sig = payload.get("signature")
        raw_proc = payload
    else:
        manifest = getattr(payload, "manifest", None)
        sig = getattr(payload, "signature", None)
        raw_proc = payload

    if not manifest or not sig:
        return False, "Unsigned artifact: missing manifest or signature"

    # Compute actual payload hash
    expected_hash = compute_procedure_hash(raw_proc)
    manifest_hash = manifest.get("procedure_hash")

    if manifest_hash != expected_hash:
        return False, (
            f"Tampered procedure body: actual payload SHA-256 {expected_hash} "
            f"does not match signed manifest {manifest_hash}"
        )

    # Verify per-step hashes
    canonical = canonical_procedure_payload(raw_proc)
    step_hashes = manifest.get("steps_hashes", [])
    actual_steps = canonical.get("steps", [])
    if len(step_hashes) != len(actual_steps):
        return False, f"Step count mismatch: manifest has {len(step_hashes)}, body has {len(actual_steps)}"

    for i, (s_hash, s_body) in enumerate(zip(step_hashes, actual_steps)):
        computed_s_hash = hashlib.sha256(canonical_json(s_body).encode("utf-8")).hexdigest()
        if s_hash != computed_s_hash:
            return False, f"Tampered step {i}: manifest hash {s_hash} does not match computed {computed_s_hash}"

    # HMAC signature check
    k = device_key or get_signing_key()
    manifest_bytes = canonical_json(manifest).encode("utf-8")
    expected_sig = hmac.new(k.encode("utf-8"), manifest_bytes, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(sig, expected_sig):
        return False, "Signature mismatch: artifact was signed with a different key or tampered"

    return True, None


def save_artifact(proc: Any, out_path: Union[str, Path], device_key: Optional[str] = None) -> Path:
    """Sign procedure and save as a portable .artifact JSON file."""
    sign_procedure(proc, device_key=device_key)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(proc, "to_dict"):
        data = proc.to_dict()
    else:
        data = dict(proc)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def load_artifact(in_path: Union[str, Path], device_key: Optional[str] = None) -> Any:
    """Load and cryptographically verify a portable .artifact file."""
    p = Path(in_path)
    if not p.is_file():
        raise FileNotFoundError(f"Artifact not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    from .proc import Procedure
    proc = Procedure.from_dict(data, verify_signature=False)
    valid, err = verify_artifact(proc, device_key=device_key)
    if not valid:
        raise ValueError(f"Invalid artifact verification for {p}: {err}")
    return proc
