"""CLI helper to sign, verify, and inspect portable Procedure artifacts.
Usage:
    python -m scripts.sign_procedure <path/to/proc.json> [--key <secret>] [--verify] [--out <out.json>]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

from stepproof.proc import Procedure
from stepproof.signing import sign_procedure, verify_procedure, get_signing_key


def main():
    parser = argparse.ArgumentParser(description="Sign or verify a StepProof Procedure artifact")
    parser.add_argument("path", help="Path to procedure JSON file")
    parser.add_argument("--key", default=None, help="HMAC signing key (defaults to STEPPROOF_SIGNING_KEY or dev key)")
    parser.add_argument("--verify", action="store_true", help="Only verify existing signature, do not re-sign")
    parser.add_argument("--out", default=None, help="Output path (defaults to overwrite input)")

    args = parser.parse_args()
    p = Path(args.path)
    if not p.exists():
        print(f"Error: file not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    raw_data = json.loads(p.read_text(encoding="utf-8"))

    if args.verify:
        try:
            # Load without auto-verifying first, then verify with specified key
            proc = Procedure.from_dict(raw_data, verify_signature=False)
            valid, err = verify_procedure(proc, key=args.key)
            if valid:
                print(f"VERIFIED: {args.path}")
                print(f"  Procedure SHA-256: {proc.manifest.get('procedure_hash')}")
                print(f"  Signature:        {proc.signature[:16]}...")
                print(f"  Compiler:         {proc.provenance.get('compiler_version')}")
                sys.exit(0)
            else:
                print(f"VERIFICATION FAILED: {err}", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"VERIFICATION ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    # Sign procedure
    proc = Procedure.from_dict(raw_data, verify_signature=False)
    sign_procedure(proc, key=args.key)
    out_dict = proc.to_dict()
    out_path = Path(args.out) if args.out else p
    out_path.write_text(json.dumps(out_dict, indent=2), encoding="utf-8")
    print(f"SIGNED: {out_path}")
    print(f"  Procedure SHA-256: {proc.manifest.get('procedure_hash')}")
    print(f"  Signature:        {proc.signature[:16]}...")


if __name__ == "__main__":
    main()

