#!/usr/bin/env python3
"""Read-only integrity check for job posting identity clusters."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

POSTINGS_TABLE = "job_postings"
CLUSTERS_TABLE = "posting_clusters"
KEYS_TABLE = "posting_identity_keys"
SAMPLE_LIMIT = 10
PAGE_SIZE = 1000


class IntegrityConfigError(RuntimeError):
    """The check cannot connect loudly enough to be trustworthy."""


@dataclass(frozen=True)
class Snapshot:
    postings: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    keys: list[dict[str, Any]]
    source: str = "fixture"


@dataclass(frozen=True)
class CheckFailure:
    name: str
    actual: Any
    expected: Any
    sample: list[Any]


@dataclass(frozen=True)
class IntegrityReport:
    counts: dict[str, int]
    failures: list[CheckFailure]

    @property
    def ok(self) -> bool:
        return not self.failures


def _sample(values: Iterable[Any], limit: int = SAMPLE_LIMIT) -> list[Any]:
    return list(values)[:limit]


def evaluate(snapshot: Snapshot) -> IntegrityReport:
    postings = snapshot.postings
    clusters = snapshot.clusters
    keys = snapshot.keys

    cluster_ids = {str(c["id"]) for c in clusters}
    postings_by_cluster: dict[str, list[dict[str, Any]]] = {}
    for row in postings:
        cluster_id = row.get("posting_identity")
        if cluster_id is not None:
            postings_by_cluster.setdefault(str(cluster_id), []).append(row)

    keys_by_cluster: dict[str, list[dict[str, Any]]] = {}
    for key in keys:
        cluster_id = key.get("cluster_id")
        if cluster_id is not None:
            keys_by_cluster.setdefault(str(cluster_id), []).append(key)

    empty_clusters = sorted(cluster_ids - set(postings_by_cluster))
    null_canonical = sorted(str(c["id"]) for c in clusters if not c.get("canonical_posting_id"))
    canonical_not_member = []
    for cluster in clusters:
        canonical = cluster.get("canonical_posting_id")
        if not canonical:
            continue
        members = postings_by_cluster.get(str(cluster["id"]), [])
        if str(canonical) not in {str(p["id"]) for p in members}:
            canonical_not_member.append(str(cluster["id"]))
    canonical_not_member.sort()

    bad_keys = []
    for key in keys:
        cluster_id = str(key.get("cluster_id"))
        if cluster_id not in cluster_ids or cluster_id not in postings_by_cluster:
            bad_keys.append(key.get("key"))
    bad_keys = sorted(str(k) for k in bad_keys)

    null_posting_identity = sorted(str(p["id"]) for p in postings if not p.get("posting_identity"))

    bad_workday_clusters: list[dict[str, Any]] = []
    for cluster_id, members in postings_by_cluster.items():
        workday_req_ids = sorted(
            {
                str(p["source_job_id"])
                for p in members
                if p.get("source") == "workday" and p.get("source_job_id")
            }
        )
        if len(workday_req_ids) >= 2:
            bad_workday_clusters.append({"cluster_id": cluster_id, "workday_req_ids": workday_req_ids})
    bad_workday_clusters.sort(key=lambda item: item["cluster_id"])

    keyless_clusters = sorted(cluster_ids - set(keys_by_cluster))
    cluster_key_delta = len(clusters) - len(keys)
    expected_delta = len(keyless_clusters)

    checks = [
        ("empty_clusters", len(empty_clusters), 0, empty_clusters),
        ("canonical_not_member", len(canonical_not_member), 0, canonical_not_member),
        ("null_canonical", len(null_canonical), 0, null_canonical),
        ("keys_to_missing_or_empty_clusters", len(bad_keys), 0, bad_keys),
        ("null_posting_identity", len(null_posting_identity), 0, null_posting_identity),
        (
            "clusters_with_multiple_workday_requisition_ids",
            len(bad_workday_clusters),
            0,
            bad_workday_clusters,
        ),
        ("cluster_key_count_delta", cluster_key_delta, expected_delta, keyless_clusters),
    ]
    failures = [
        CheckFailure(name=name, actual=actual, expected=expected, sample=_sample(sample))
        for name, actual, expected, sample in checks
        if actual != expected
    ]

    return IntegrityReport(
        counts={
            "postings": len(postings),
            "clusters": len(clusters),
            "identity_keys": len(keys),
            "empty_clusters": len(empty_clusters),
            "canonical_not_member": len(canonical_not_member),
            "null_canonical": len(null_canonical),
            "keys_to_missing_or_empty_clusters": len(bad_keys),
            "null_posting_identity": len(null_posting_identity),
            "clusters_with_multiple_workday_requisition_ids": len(bad_workday_clusters),
            "keyless_clusters": len(keyless_clusters),
            "cluster_key_delta": cluster_key_delta,
        },
        failures=failures,
    )


def _load_with_psql(db_url: str) -> Snapshot:
    psql = shutil.which("psql")
    if not psql:
        raise IntegrityConfigError("SUPABASE_DB_URL is set, but psql is not available on PATH.")

    query = """
select json_build_object(
  'postings', coalesce((
    select json_agg(json_build_object(
      'id', id,
      'source', source,
      'source_job_id', source_job_id,
      'posting_identity', posting_identity
    ) order by id)
    from job_postings
  ), '[]'::json),
  'clusters', coalesce((
    select json_agg(json_build_object(
      'id', id,
      'canonical_posting_id', canonical_posting_id
    ) order by id)
    from posting_clusters
  ), '[]'::json),
  'keys', coalesce((
    select json_agg(json_build_object(
      'key', key,
      'cluster_id', cluster_id
    ) order by key)
    from posting_identity_keys
  ), '[]'::json)
)::text
"""
    env = os.environ.copy()
    env["PGOPTIONS"] = " ".join(
        part for part in [env.get("PGOPTIONS", ""), "-c default_transaction_read_only=on"] if part
    )
    result = subprocess.run(
        [psql, db_url, "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", query],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if result.returncode != 0:
        raise IntegrityConfigError(f"psql read failed: {result.stderr.strip() or 'exit ' + str(result.returncode)}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise IntegrityConfigError("psql returned no snapshot payload.")
    payload = json.loads(lines[-1])
    return Snapshot(
        postings=payload["postings"],
        clusters=payload["clusters"],
        keys=payload["keys"],
        source="direct Postgres via SUPABASE_DB_URL",
    )


def _fetch_all(client: Any, table: str, columns: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        page = (
            client.table(table)
            .select(columns)
            .order("id" if table != KEYS_TABLE else "key")
            .range(start, start + PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def _load_with_postgrest() -> Snapshot:
    url = os.environ.get("SUPABASE_URL", "").strip()
    secret = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    if not url or not secret:
        raise IntegrityConfigError(
            "Set SUPABASE_DB_URL for direct Postgres, or SUPABASE_URL and SUPABASE_SECRET_KEY for PostgREST."
        )

    from supabase import create_client

    client = create_client(url, secret)
    return Snapshot(
        postings=_fetch_all(client, POSTINGS_TABLE, "id,source,source_job_id,posting_identity"),
        clusters=_fetch_all(client, CLUSTERS_TABLE, "id,canonical_posting_id"),
        keys=_fetch_all(client, KEYS_TABLE, "key,cluster_id"),
        source="PostgREST via SUPABASE_URL/SUPABASE_SECRET_KEY",
    )


def load_snapshot() -> Snapshot:
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if db_url:
        return _load_with_psql(db_url)
    return _load_with_postgrest()


def print_report(snapshot: Snapshot, report: IntegrityReport) -> None:
    print(f"connection: {snapshot.source}")
    if report.ok:
        print("PASS job posting cluster integrity")
    else:
        print("FAIL job posting cluster integrity")
    for name, value in report.counts.items():
        print(f"{name}: {value}")
    for failure in report.failures:
        print(
            "assertion_failed "
            f"{failure.name}: actual={failure.actual} expected={failure.expected} "
            f"sample={json.dumps(failure.sample, sort_keys=True)}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    try:
        snapshot = load_snapshot()
        report = evaluate(snapshot)
    except Exception as exc:
        print(f"ERROR: job posting integrity check could not run: {exc}", file=sys.stderr)
        return 2

    print_report(snapshot, report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
