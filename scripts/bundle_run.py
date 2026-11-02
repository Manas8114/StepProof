"""CLI to bundle a run into a portable evidence package.
Usage: python -m scripts.bundle_run <run_id> [--out path/to/bundle.zip]
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from stepproof.audit import get_spine


def main() -> None:
    parser = argparse.ArgumentParser(description="Package run evidence and audit chain into a portable bundle")
    parser.add_argument("run_id", help="The run_id to package")
    parser.add_argument("--out", type=str, default="", help="Destination archive path (.zip)")
    args = parser.parse_args()

    spine = get_spine()
    out_p = Path(args.out) if args.out else None
    try:
        bundled = spine.package_run(args.run_id, out_path=out_p)
        print(f"Successfully packaged run '{args.run_id}' -> {bundled}")
    except Exception as e:
        print(f"Error packaging run: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

