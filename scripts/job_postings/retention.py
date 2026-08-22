#!/usr/bin/env python3
"""Age out raw_payload after 90 days. Keeps the row, drops the blob.

Postgres has no row expiry and Supabase adds none, so this is a statement
something has to run on a schedule -- the same schedule as the ingest.

WHY 90 DAYS, AND WHY NULL RATHER THAN DELETE

raw_payload exists so a changed extraction pass can be re-run without spending
vendor quota to refetch. That is the whole justification, and it sets the
window: long enough to survive one iteration loop on the skill vocabulary,
which is near-certain to need one (only 121 of 8,725 candidate terms have ever
fired against a real posting).

An earlier proposal said 7 days. That was sized for debugging -- diffing
extracted output against source prose during verification -- which is a much
shorter horizon than reprocessing, and it was defending against a storage
ceiling that measurement did not support: real descriptions average 5.0 KB,
and O*NET occupies none of the 500 MB tier because it is a flat file rather
than a table.

Nulling rather than deleting keeps the posting. The extracted fields are the
durable product; the payload is scaffolding. A deleted row would also break
any cluster pointing at it, and clusters are the thing counting reads.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from errors import JobPostingConfigError  # noqa: E402

POSTINGS_TABLE = "job_postings"
DEFAULT_RETENTION_DAYS = 90


def cutoff_for(days: int, *, now: datetime | None = None) -> datetime:
    """The timestamp before which payloads age out.

    Split out so the boundary is testable without a database -- an off-by-one
    here silently destroys data that quota cannot replace.
    """
    if days < 1:
        raise ValueError("retention window must be at least one day")
    reference = now or datetime.now(timezone.utc)
    return reference - timedelta(days=days)


def expire_payloads(client, *, days: int = DEFAULT_RETENTION_DAYS, dry_run: bool = True) -> int:
    """Null raw_payload on rows fetched before the cutoff. Returns the count.

    Counts first and reports even in dry run, because "how much would this
    remove" is the question worth answering before the first real run.
    """
    cutoff = cutoff_for(days).isoformat()

    pending = (
        client.table(POSTINGS_TABLE)
        .select("id", count="exact")
        .lt("fetched_at", cutoff)
        .not_.is_("raw_payload", "null")
        .execute()
    )
    count = pending.count if pending.count is not None else len(pending.data or [])

    if dry_run or count == 0:
        return count

    (
        client.table(POSTINGS_TABLE)
        .update({"raw_payload": None})
        .lt("fetched_at", cutoff)
        .not_.is_("raw_payload", "null")
        .execute()
    )
    return count


def build_client():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "").strip()
    secret = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    if not url or not secret:
        raise JobPostingConfigError(
            "SUPABASE_URL and SUPABASE_SECRET_KEY are both required."
        )
    return create_client(url, secret)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually null the payloads. Without this, only reports how many would age out.",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")

    try:
        client = build_client()
    except JobPostingConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    count = expire_payloads(client, days=args.days, dry_run=not args.apply)
    verb = "aged out" if args.apply else "would age out"
    print(f"{count} payload(s) {verb} (older than {args.days} days). Rows are kept.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
