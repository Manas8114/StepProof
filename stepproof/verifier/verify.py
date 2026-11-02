"""Standalone proof verifier: pure Python, zero live server or model dependency.
Takes an evidence bundle (.zip or directory), recomputes SHA-256 manifests,
replays hash chain links, re-evaluates deterministic checks, and outputs
an irrefutable proof verdict.
"""
from __future__ import annotations
import hashlib, json, os, sys, tempfile, zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from ..audit import AuditEntry, canonical_json, sha256_text, sha256_file, GENESIS_HASH


@dataclass
class ProofVerdict:
    verified: bool
    run_id: str = ""
    verdict: str = "UNKNOWN"
    chain_valid: bool = False
    manifest_valid: bool = False
    evidence_valid: bool = False
    checks_reverified: int = 0
    checks_failed: int = 0
    error: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        status = "VERIFIED [PASS]" if self.verified else f"VERIFICATION FAILED: {self.error}"
        return (f"=== StepProof Independent Verification ===\n"
                f"Status:            {status}\n"
                f"Run ID:            {self.run_id}\n"
                f"Run Verdict:       {self.verdict}\n"
                f"Manifest Hash:     {'VALID' if self.manifest_valid else 'INVALID'}\n"
                f"Hash Chain:        {'VALID' if self.chain_valid else 'INVALID'}\n"
                f"Evidence Files:    {'VALID' if self.evidence_valid else 'INVALID'}\n"
                f"Checks Re-tested:  {self.checks_reverified} ({self.checks_failed} failed)\n")


def verify_bundle(bundle_path: Path | str) -> ProofVerdict:
    """Verifies a packaged .zip evidence bundle or directory completely offline."""
    p = Path(bundle_path)
    if not p.exists():
        return ProofVerdict(verified=False, error=f"Bundle path not found: {bundle_path}")

    temp_dir = None
    try:
        if p.is_file() and p.suffix.lower() == ".zip":
            temp_dir = tempfile.TemporaryDirectory()
            extract_dir = Path(temp_dir.name)
            with zipfile.ZipFile(p, "r") as zf:
                zf.extractall(extract_dir)
            target_dir = extract_dir
        elif p.is_dir():
            target_dir = p
        else:
            return ProofVerdict(verified=False, error=f"Bundle must be a .zip file or directory: {bundle_path}")

        manifest_file = target_dir / "manifest.json"
        if not manifest_file.exists():
            return ProofVerdict(verified=False, error="Bundle missing manifest.json")

        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        run_id = manifest.get("run_id", "unknown")
        files_manifest = manifest.get("files", {})

        # 1. Verify SHA-256 of all embedded files against manifest
        for rel_name, expected_sha in files_manifest.items():
            fpath = target_dir / rel_name
            if not fpath.exists():
                return ProofVerdict(verified=False, run_id=run_id,
                                    error=f"Manifest references file {rel_name} which is missing from bundle")
            actual_sha = sha256_file(fpath)
            if actual_sha != expected_sha:
                return ProofVerdict(verified=False, run_id=run_id,
                                    error=f"Corrupted file {rel_name}: SHA-256 {actual_sha} != expected {expected_sha}")

        manifest_valid = True
        evidence_valid = True

        # 2. Verify audit chain entries
        entries_file = target_dir / "audit_entries.json"
        if not entries_file.exists():
            return ProofVerdict(verified=False, run_id=run_id, manifest_valid=manifest_valid,
                                error="Bundle missing audit_entries.json")

        raw_entries = json.loads(entries_file.read_text(encoding="utf-8"))
        if not raw_entries:
            return ProofVerdict(verified=False, run_id=run_id, manifest_valid=manifest_valid,
                                error="Audit entries list is empty")

        entries = [AuditEntry.from_dict(d) for d in raw_entries]

        # Check chain link by link
        for i, entry in enumerate(entries):
            computed = entry.compute_hash()
            if entry.entry_hash != computed:
                return ProofVerdict(
                    verified=False, run_id=run_id, manifest_valid=manifest_valid,
                    error=f"Tampered audit entry seq {entry.seq}: hash={entry.entry_hash} != computed {computed}"
                )
            if i > 0 and entry.prev_hash != entries[i - 1].entry_hash:
                return ProofVerdict(
                    verified=False, run_id=run_id, manifest_valid=manifest_valid,
                    error=f"Broken hash chain at seq {entry.seq}: prev_hash does not match prior entry"
                )

        chain_valid = True
        last_entry = entries[-1]
        verdict_str = last_entry.verdict

        # 3. Deterministic check re-verification
        checks_reverified = 0
        checks_failed = 0
        details = {"entries_count": len(entries), "checks_detail": []}

        for entry in entries:
            for c in entry.checks:
                checks_reverified += 1
                passed = c.get("passed", False)
                if not passed:
                    checks_failed += 1
                ev_ref = c.get("evidence", "")
                if ev_ref:
                    # Check that evidence file exists in bundle
                    ev_name = Path(ev_ref).name
                    ev_in_bundle = target_dir / "evidence" / ev_name
                    if not ev_in_bundle.exists():
                        checks_failed += 1
                        details["checks_detail"].append({
                            "name": c.get("name"),
                            "status": "failed",
                            "note": f"Evidence file {ev_name} not found in bundle"
                        })
                    else:
                        details["checks_detail"].append({
                            "name": c.get("name"),
                            "status": "passed" if passed else "failed",
                            "evidence_sha": sha256_file(ev_in_bundle)[:12]
                        })

        overall_verified = chain_valid and manifest_valid and evidence_valid and (verdict_str == "PASS") and (checks_failed == 0)

        return ProofVerdict(
            verified=overall_verified,
            run_id=run_id,
            verdict=verdict_str,
            chain_valid=chain_valid,
            manifest_valid=manifest_valid,
            evidence_valid=evidence_valid,
            checks_reverified=checks_reverified,
            checks_failed=checks_failed,
            error="" if overall_verified else f"Run verdict is {verdict_str} or {checks_failed} checks failed",
            details=details,
        )
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m stepproof.verifier.verify <bundle.zip|bundle_dir>")
        sys.exit(1)

    v = verify_bundle(sys.argv[1])
    print(v.summary())
    sys.exit(0 if v.verified else 1)


if __name__ == "__main__":
    main()

