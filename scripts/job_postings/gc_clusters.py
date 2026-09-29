#!/usr/bin/env python3
"""CLI entrypoint for ingest.gc_empty_clusters -- the orphaned-cluster backstop.

DRY RUN IS THE DEFAULT, same posture as ingest.py itself. Without --live this
only reports what it would delete; nothing is written. Run in the nightly
workflow before integrity-check, so the count that check_integrity.py asserts
against reflects a corpus this job has already cleaned up rather than one
still carrying whatever resolve_and_attach_identity's adoption fix could not
retroactively repair (rows ingested before that fix landed).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from ingest import gc_empty_clusters  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--live",
        action="store_true",
        help="Actually delete the orphaned clusters and their identity keys. "
             "Without this, reports what would be deleted and changes nothing.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")

    try:
        report = gc_empty_clusters(dry_run=not args.live)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: cluster gc could not run: {exc}", file=sys.stderr)
        return 2

    print(report.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
