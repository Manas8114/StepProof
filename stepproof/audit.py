"""Append-only, hash-chained audit log and portable evidence bundle packager.
Models perceive, code decides: every execution verdict, check result, evidence link,
model fallback disclosure, and cost record is deterministically hashed and chained.
Tamper-evident by construction: modifying any entry invalidates all subsequent links.
"""
from __future__ import annotations
import hashlib, json, os, time, uuid, zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Any

from . import config as cfg
from .events import BUS

GENESIS_HASH = "0" * 64


def canonical_json(data: Any) -> str:
    """Byte-deterministic, canonical JSON serialization: pinned separators and sorted keys."""
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    p = Path(path)
    if not p.is_file():
        return ""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class AuditEntry:
    seq: int
    run_id: str
    ts: float
    verdict: str                        # PASS | FAIL | BLOCKED | ERROR | REPLAY
    checks: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    model_disclosure: dict = field(default_factory=dict)
    cost: dict = field(default_factory=dict)
    prev_hash: str = GENESIS_HASH
    entry_hash: str = ""

    def payload_dict(self) -> dict:
        return {
            "seq": self.seq,
            "run_id": self.run_id,
            "ts": round(self.ts, 3),
            "verdict": self.verdict,
            "checks": self.checks,
            "steps": self.steps,
            "evidence_paths": self.evidence_paths,
            "model_disclosure": self.model_disclosure,
            "cost": self.cost,
            "prev_hash": self.prev_hash,
        }

    def compute_hash(self) -> str:
        return sha256_text(canonical_json(self.payload_dict()))

    def to_dict(self) -> dict:
        d = self.payload_dict()
        d["entry_hash"] = self.entry_hash
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AuditEntry":
        d = dict(d)
        entry_hash = d.pop("entry_hash", "")
        entry = cls(**d)
        entry.entry_hash = entry_hash or entry.compute_hash()
        return entry


class AuditSpine:
    """Append-only, hash-chained log stored in SQLite and JSONL."""

    def __init__(self, sink_dir: Optional[Path] = None, use_global_db: bool = True) -> None:
        self.sink_dir = sink_dir or (cfg.DATA_DIR / "audit")
        self.sink_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_file = self.sink_dir / "audit_chain.jsonl"
        self.use_global_db = use_global_db and (sink_dir is None or sink_dir == (cfg.DATA_DIR / "audit"))
        self._entries: list[AuditEntry] = []
        self._load_existing()

    def _load_existing(self) -> None:
        if self.use_global_db:
            from . import store
            store.init()
            db_entries = store.get_audit_entries()
            if db_entries:
                self._entries = [AuditEntry.from_dict(e) for e in db_entries]
                return
        if self.jsonl_file.exists():
            for line in self.jsonl_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._entries.append(AuditEntry.from_dict(json.loads(line)))

    @property
    def last_entry(self) -> Optional[AuditEntry]:
        return self._entries[-1] if self._entries else None

    @property
    def last_hash(self) -> str:
        return self.last_entry.entry_hash if self.last_entry else GENESIS_HASH

    def append(self, run_id: str, verdict: str, checks: list[dict] | None = None,
               steps: list[dict] | None = None, evidence_paths: list[str] | None = None,
               model_disclosure: dict | None = None, cost: dict | None = None) -> AuditEntry:
        """Append a new verified entry to the hash chain."""
        seq = len(self._entries)
        prev_h = self.last_hash
        entry = AuditEntry(
            seq=seq,
            run_id=run_id,
            ts=time.time(),
            verdict=verdict,
            checks=checks or [],
            steps=steps or [],
            evidence_paths=evidence_paths or [],
            model_disclosure=model_disclosure or {},
            cost=cost or {},
            prev_hash=prev_h,
        )
        entry.entry_hash = entry.compute_hash()
        self._entries.append(entry)

        # Write to JSONL sink
        with open(self.jsonl_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")

        # Write to SQLite store if using global DB
        if self.use_global_db:
            from . import store
            store.append_audit_entry(entry.to_dict())

        BUS.publish("audit_entry", {"seq": entry.seq, "run_id": entry.run_id,
                                    "verdict": entry.verdict, "entry_hash": entry.entry_hash[:12]})
        return entry

    def get_entries(self, run_id: Optional[str] = None) -> list[AuditEntry]:
        if run_id:
            return [e for e in self._entries if e.run_id == run_id]
        return list(self._entries)

    def verify(self, entries: Optional[list[AuditEntry]] = None) -> tuple[bool, Optional[str]]:
        """Verify the integrity of the whole chain or a slice."""
        chain = self._entries if entries is None else entries
        if not chain:
            return True, None

        expected_prev = GENESIS_HASH if chain[0].seq == 0 else chain[0].prev_hash
        for i, entry in enumerate(chain):
            if entry.prev_hash != expected_prev:
                return False, f"Broken link at seq {entry.seq}: prev_hash={entry.prev_hash} != expected {expected_prev}"
            computed = entry.compute_hash()
            if entry.entry_hash != computed:
                return False, f"Tampered entry at seq {entry.seq}: hash={entry.entry_hash} != computed {computed}"
            expected_prev = entry.entry_hash

        return True, None

    def package_run(self, run_id: str, out_path: Optional[Path] = None) -> Path:
        """Emit a self-contained, portable .zip bundle for a run."""
        entries = self.get_entries(run_id)
        if not entries:
            raise ValueError(f"No audit entries found for run_id: {run_id}")

        valid, err = self.verify(entries)
        if not valid:
            raise ValueError(f"Audit chain verification failed for run {run_id}: {err}")

        out_zip = out_path or (self.sink_dir / f"bundle_{run_id}.zip")
        out_zip.parent.mkdir(parents=True, exist_ok=True)

        manifest_files = {}
        entries_dicts = [e.to_dict() for e in entries]

        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Embed audit entries JSON
            entries_json = canonical_json(entries_dicts)
            zf.writestr("audit_entries.json", entries_json)
            manifest_files["audit_entries.json"] = sha256_text(entries_json)

            # 2. Embed all referenced evidence files
            for entry in entries:
                for rel_path in entry.evidence_paths:
                    p = Path(rel_path)
                    # Resolve if relative
                    if not p.is_absolute():
                        candidates = [
                            cfg.DATA_DIR / rel_path,
                            cfg.BASE / rel_path,
                            Path(rel_path)
                        ]
                        for c in candidates:
                            if c.exists() and c.is_file():
                                p = c
                                break
                    if p.exists() and p.is_file():
                        arcname = f"evidence/{p.name}"
                        zf.write(p, arcname=arcname)
                        manifest_files[arcname] = sha256_file(p)

            # 3. Create canonical bundle manifest
            manifest = {
                "format": "stepproof-evidence-bundle-v1",
                "run_id": run_id,
                "created": round(time.time(), 3),
                "entries_count": len(entries),
                "last_entry_hash": entries[-1].entry_hash,
                "files": manifest_files,
            }
            manifest_json = canonical_json(manifest)
            zf.writestr("manifest.json", manifest_json)

        return out_zip


_SPINE: Optional[AuditSpine] = None


def get_spine() -> AuditSpine:
    global _SPINE
    if _SPINE is None:
        _SPINE = AuditSpine()
    return _SPINE

