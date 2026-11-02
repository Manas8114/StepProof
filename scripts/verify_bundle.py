"""CLI to verify an evidence bundle offline on any machine without network access.
Usage: python -m scripts.verify_bundle <bundle.zip|bundle.tar.gz> [--live]
"""
from __future__ import annotations
import sys
from stepproof.verify_bundle import main

if __name__ == "__main__":
    main()

