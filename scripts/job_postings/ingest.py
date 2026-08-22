#!/usr/bin/env python3
"""Nightly postings ingest -- fetch, normalize, dedup, store.

Loops the target roles, asks each vendor for that role in the DFW metro,
normalizes every response into one row shape, resolves cross-source identity,
and upserts. Every call writes a job_posting_fetch_log row whether it worked
or not.

DRY RUN IS THE DEFAULT, same as the vendor clients this builds on. Without
--live nothing is fetched and nothing is written; the planned calls are
printed instead. Both free tiers are small -- Adzuna ~1,000/mo and JSearch
~200/mo across 14 roles -- so an accidental run is a real cost, not a
nuisance.

CADENCE IS PER VENDOR, NOT GLOBAL. Adzuna's ~70 calls/role/month affords a
nightly fetch. JSearch's ~14 cannot: nightly would burn the month's quota in
two weeks. The integration spec narrows JSearch further still, to
LinkedIn-source confirmation only, after a live 2026-08-17 test returned zero
results on both vendors for the role it was meant to gap-fill. So JSearch is
opt-in per run rather than part of the nightly sweep.

WHAT THIS CANNOT DO YET
-----------------------
The tables do not exist. supabase/migrations/20260817210000 is staged and
says not to apply it until Deepak has reviewed. So --live --write will fail
against a real project until that lands; --live on its own fetches and
normalizes without writing, which is the useful shape for confirming the
field maps in normalize.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from errors import JobPostingConfigError, JobPostingRequestError  # noqa: E402
from identity import identity_keys  # noqa: E402
from normalize import (  # noqa: E402
    NormalizationError,
    describe_shape,
    normalize_response,
)

ROLE_REQUIREMENTS = REPO_ROOT / "data" / "role_requirements.json"

POSTINGS_TABLE = "job_postings"
FETCH_LOG_TABLE = "job_posting_fetch_log"
CLUSTERS_TABLE = "posting_clusters"
MERGES_TABLE = "posting_cluster_merges"
KEYS_TABLE = "posting_identity_keys"

# Syndicators. An ATS row outranks these when choosing a cluster's canonical
# posting, because it is the employer's own feed rather than a rewrite of it.
VENDOR_SOURCES = frozenset({"adzuna", "jsearch"})

UPSERT_CONFLICT = "source,source_job_id"

# Rows per vendor call. Small on purpose -- one call returns one page, and a
# bigger page does not cost more quota but does cost more to normalize wrongly
# while the field maps are unconfirmed.
DEFAULT_PAGE_SIZE = 20

DEFAULT_WHERE = "Dallas"
DEFAULT_DISTANCE_MILES = 30

# See the module docstring. Adzuna alone is the nightly sweep.
NIGHTLY_SOURCES = ("adzuna",)


def load_target_roles() -> list[str]:
    """The 14 roles, from the file that already defines them.

    Deliberately not a second list. role_requirements.json is what GAP and FIT
    already key off, and a role string that exists here but not there would
    produce postings nothing can ever retrieve.
    """
    with ROLE_REQUIREMENTS.open(encoding="utf-8") as f:
        data = json.load(f)
    return [k for k in data if k != "_notes"]


@dataclass
class FetchOutcome:
    """One vendor call. Becomes exactly one job_posting_fetch_log row."""

    source: str
    target_role: str
    results_count: int = 0
    quota_used: int = 0
    status: str = "success"
    error_detail: str | None = None
    rows: list[dict] = field(default_factory=list)
    normalization_errors: list[str] = field(default_factory=list)

    def log_row(self) -> dict:
        return {
            "source": self.source,
            "target_role": self.target_role,
            "results_count": self.results_count,
            "quota_used": self.quota_used,
            "status": self.status,
            "error_detail": self.error_detail,
        }


@dataclass
class RunReport:
    started_at: datetime
    dry_run: bool
    outcomes: list[FetchOutcome] = field(default_factory=list)
    rows_upserted: int = 0
    clusters_created: int = 0
    clusters_matched_exact: int = 0
    clusters_matched_fuzzy: int = 0
    clusters_merged: int = 0

    @property
    def quota_spent(self) -> int:
        return sum(o.quota_used for o in self.outcomes)

    @property
    def failed(self) -> list[FetchOutcome]:
        return [o for o in self.outcomes if o.status == "error"]

    def render(self) -> str:
        lines = [
            "",
            "=" * 68,
            f"  postings ingest -- {'DRY RUN' if self.dry_run else 'LIVE'}",
            f"  started {self.started_at.isoformat(timespec='seconds')}",
            "=" * 68,
            f"  vendor calls      {len(self.outcomes)}",
            f"  quota spent       {self.quota_spent}",
            f"  listings returned {sum(o.results_count for o in self.outcomes)}",
            f"  rows upserted     {self.rows_upserted}",
            "",
            "  cross-source identity:",
            f"    exact  (ATS id from URL)  {self.clusters_matched_exact}",
            f"    fuzzy  (employer/title)   {self.clusters_matched_fuzzy}",
            f"    new clusters              {self.clusters_created}",
            f"    clusters merged           {self.clusters_merged}",
        ]
        errors = sum(len(o.normalization_errors) for o in self.outcomes)
        if errors:
            lines += [
                "",
                f"  !! {errors} listing(s) failed to normalize.",
                "     The field maps in normalize.py are unverified against live",
                "     responses -- a high count here means a wrong map, not bad data.",
            ]
            for o in self.outcomes:
                for e in o.normalization_errors[:2]:
                    lines.append(f"     - {e[:150]}")
        if self.failed:
            lines += ["", f"  !! {len(self.failed)} call(s) failed:"]
            for o in self.failed:
                lines.append(f"     - {o.source}/{o.target_role}: {o.error_detail}")
        lines.append("=" * 68)
        return "\n".join(lines)


def build_client(source: str):
    """Vendor client, constructed lazily so a missing credential for one vendor
    does not stop the other from running."""
    if source == "adzuna":
        from adzuna_client import AdzunaClient

        return AdzunaClient()
    if source == "jsearch":
        from jsearch_client import JSearchClient

        return JSearchClient()
    raise JobPostingConfigError(f"unknown source {source!r}")


def fetch_one(
    source: str,
    target_role: str,
    *,
    live: bool,
    page_size: int = DEFAULT_PAGE_SIZE,
    where: str = DEFAULT_WHERE,
    dump_shape: bool = False,
) -> FetchOutcome:
    """One vendor, one role, one call."""
    outcome = FetchOutcome(source=source, target_role=target_role)

    try:
        client = build_client(source)
    except JobPostingConfigError as exc:
        outcome.status = "error"
        outcome.error_detail = f"config: {exc}"
        return outcome

    try:
        if source == "adzuna":
            payload = client.search(
                what=target_role,
                where=where,
                distance=DEFAULT_DISTANCE_MILES,
                results_per_page=page_size,
                live=live,
            )
        else:
            payload = client.search(
                query=target_role,
                location=where,
                num_results=page_size,
                live=live,
            )
    except JobPostingRequestError as exc:
        outcome.status = "error"
        outcome.error_detail = f"request (transient={exc.transient}): {exc}"
        outcome.quota_used = 1  # a failed call still spends the call
        return outcome
    except TypeError as exc:
        # A client signature that does not match what this caller assumes is a
        # wiring bug, and it should be loud rather than logged as a vendor error.
        raise RuntimeError(f"{source} client signature mismatch: {exc}") from exc

    if payload is None:  # dry run -- the client printed the request
        return outcome

    outcome.quota_used = 1

    if dump_shape:
        print(describe_shape(payload, source))

    try:
        rows, errors = normalize_response(payload, source, target_role=target_role)
    except NormalizationError as exc:
        outcome.status = "error"
        outcome.error_detail = f"normalize: {exc}"
        return outcome

    outcome.rows = rows
    outcome.normalization_errors = errors
    outcome.results_count = len(rows)
    return outcome


def resolve_and_attach_identity(rows: list[dict], store: Any, report: RunReport) -> None:
    """Assign every row a posting_identity, per data/ats_fetcher/DEDUP.md.

    Exact before fuzzy, and never the other way round: an ATS id recovered
    from an apply URL is evidence, while an employer/title match is an
    inference, and an inference must not override evidence.
    """
    for row in rows:
        exact, fuzzy = identity_keys(row)
        exact_hit = store.find_cluster(exact) if exact else None
        fuzzy_hit = store.find_cluster(fuzzy) if fuzzy else None

        if exact_hit is not None:
            cluster_id, rule = exact_hit, "ats_url_id"
            report.clusters_matched_exact += 1

            # DEDUP.md §5. A vendor can deliver a posting before the employer's
            # own feed surfaces it, so the earlier row may already sit in a
            # fuzzy cluster. This row -- carrying a recovered ATS id that
            # resolves elsewhere -- is the evidence those two are one job.
            if fuzzy_hit is not None and fuzzy_hit != exact_hit:
                store.merge_clusters(
                    absorbed=fuzzy_hit,
                    surviving=exact_hit,
                    match_rule="ats_url_id",
                )
                report.clusters_merged += 1

        elif fuzzy_hit is not None:
            cluster_id, rule = fuzzy_hit, "fuzzy"
            report.clusters_matched_fuzzy += 1

        else:
            cluster_id = store.create_cluster(
                keys=[k for k in (exact, fuzzy) if k],
                match_rule="seed",
            )
            report.clusters_created += 1
            rule = "seed"

        # Register whichever key this row contributed that the cluster did not
        # already know. This is how a cluster first seen by fuzzy match becomes
        # findable by exact id once an ATS row arrives.
        store.attach_keys(cluster_id, [k for k in (exact, fuzzy) if k])

        # normalize.py guarantees source_job_id on anything it produced, but
        # canonical selection is an enhancement rather than a correctness
        # requirement -- a row without one still gets clustered, it just cannot
        # be pointed to as the representative.
        source_job_id = row.get("source_job_id")
        if source_job_id is not None:
            store.set_canonical(cluster_id, row["source"], str(source_job_id))

        row["posting_identity"] = cluster_id
        row["_match_rule"] = rule


class DryRunStore:
    """Records what would happen. No network, no database.

    Mirrors SupabaseStore's interface exactly, including merges and canonical
    selection. Earlier this class was a bare dict and the tests passed against
    it while the real store's fuzzy path did nothing at all -- a fake simpler
    than the thing it stands in for produces confidence rather than coverage.
    """

    def __init__(self) -> None:
        self.clusters: dict[str, str] = {}          # key -> cluster id
        self.canonical: dict[str, tuple[str, str]] = {}
        self.rows: list[dict] = []
        self.log_rows: list[dict] = []
        self.merges: list[dict] = []
        self._next = 0

    def find_cluster(self, key: str) -> str | None:
        return self.clusters.get(key)

    def create_cluster(self, keys: list[str], match_rule: str) -> str:
        self._next += 1
        cluster_id = f"dry-cluster-{self._next:05d}"
        self.attach_keys(cluster_id, keys)
        return cluster_id

    def attach_keys(self, cluster_id: str, keys: list[str]) -> None:
        for k in keys:
            self.clusters[k] = cluster_id

    def merge_clusters(self, absorbed: str, surviving: str, *, match_rule: str,
                       triggered_by: str | None = None) -> None:
        for k, v in list(self.clusters.items()):
            if v == absorbed:
                self.clusters[k] = surviving
        for row in self.rows:
            if row.get("posting_identity") == absorbed:
                row["posting_identity"] = surviving
        if absorbed in self.canonical:
            self.canonical.pop(absorbed)
        self.merges.append({
            "absorbed_cluster_id": absorbed,
            "surviving_cluster_id": surviving,
            "match_rule": match_rule,
            "triggered_by_posting_id": triggered_by,
        })

    def set_canonical(self, cluster_id: str, source: str, source_job_id: str) -> None:
        current = self.canonical.get(cluster_id)
        if current is not None and source in VENDOR_SOURCES:
            return
        self.canonical[cluster_id] = (source, source_job_id)

    def upsert_postings(self, rows: list[dict]) -> int:
        self.rows.extend(rows)
        return len(rows)

    def write_log(self, log_row: dict) -> None:
        self.log_rows.append(log_row)


class SupabaseStore:
    """Service-role writer.

    Uses SUPABASE_SECRET_KEY, matching scripts/import_students.py and
    scripts/fetch_smu_term_dates.py. That key bypasses RLS, which is the
    intended posture: job_postings is public-read and service-role-write, and
    posting_clusters denies everyone but the service role outright.
    """

    def __init__(self) -> None:
        from supabase import create_client

        url = os.environ.get("SUPABASE_URL", "").strip()
        secret = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
        if not url or not secret:
            raise JobPostingConfigError(
                "SUPABASE_URL and SUPABASE_SECRET_KEY are both required to write."
            )
        self.client = create_client(url, secret)
        self._cluster_cache: dict[str, str] = {}

    def find_cluster(self, key: str) -> str | None:
        """Exact lookup against posting_identity_keys.

        Not a substring search over job_postings.url, which was the first cut
        and was wrong twice: an ATS job id can sit inside a longer id or a
        query parameter and match the wrong row, and a fuzzy key corresponds
        to no URL at all -- so the whole fallback path would have quietly
        created a fresh cluster every time and deduped nothing.
        """
        if key in self._cluster_cache:
            return self._cluster_cache[key]
        found = (
            self.client.table(KEYS_TABLE)
            .select("cluster_id")
            .eq("key", key)
            .limit(1)
            .execute()
            .data
        )
        if found:
            cluster_id = found[0]["cluster_id"]
            self._cluster_cache[key] = cluster_id
            return cluster_id
        return None

    def create_cluster(self, keys: list[str], match_rule: str) -> str:
        created = (
            self.client.table(CLUSTERS_TABLE)
            .insert({"match_rule": match_rule})
            .execute()
            .data
        )
        cluster_id = created[0]["id"]
        self.attach_keys(cluster_id, keys)
        return cluster_id

    def attach_keys(self, cluster_id: str, keys: list[str]) -> None:
        """Point keys at a cluster. Idempotent -- a key already pointing here
        is the normal case on a re-fetch, not a conflict."""
        if not keys:
            return
        (
            self.client.table(KEYS_TABLE)
            .upsert(
                [{"key": k, "cluster_id": cluster_id} for k in keys],
                on_conflict="key",
            )
            .execute()
        )
        for k in keys:
            self._cluster_cache[k] = cluster_id

    def merge_clusters(self, absorbed: str, surviving: str, *, match_rule: str,
                       triggered_by: str | None = None) -> None:
        """Fold `absorbed` into `surviving` and record why.

        Repointing happens before the delete so no row is ever orphaned
        mid-merge, and the log row is written last so it describes something
        that actually completed.
        """
        self.client.table(KEYS_TABLE).update(
            {"cluster_id": surviving}
        ).eq("cluster_id", absorbed).execute()

        self.client.table(POSTINGS_TABLE).update(
            {"posting_identity": surviving}
        ).eq("posting_identity", absorbed).execute()

        self.client.table(MERGES_TABLE).insert({
            "absorbed_cluster_id": absorbed,
            "surviving_cluster_id": surviving,
            "match_rule": match_rule,
            "triggered_by_posting_id": triggered_by,
        }).execute()

        self.client.table(CLUSTERS_TABLE).delete().eq("id", absorbed).execute()

        for k, v in list(self._cluster_cache.items()):
            if v == absorbed:
                self._cluster_cache[k] = surviving

    def set_canonical(self, cluster_id: str, source: str, source_job_id: str) -> None:
        """Point a cluster at its representative row, ATS over vendor.

        The ATS row is the employer's own feed: unrewritten title, real posting
        date. Only promotes -- a vendor row never displaces an ATS one.
        """
        existing = (
            self.client.table(CLUSTERS_TABLE)
            .select("canonical_posting_id")
            .eq("id", cluster_id)
            .limit(1)
            .execute()
            .data
        )
        if existing and existing[0].get("canonical_posting_id") and source in VENDOR_SOURCES:
            return
        row = (
            self.client.table(POSTINGS_TABLE)
            .select("id")
            .eq("source", source)
            .eq("source_job_id", source_job_id)
            .limit(1)
            .execute()
            .data
        )
        if row:
            self.client.table(CLUSTERS_TABLE).update(
                {"canonical_posting_id": row[0]["id"]}
            ).eq("id", cluster_id).execute()

    def upsert_postings(self, rows: list[dict]) -> int:
        payload = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
        for r in payload:
            r["fetched_at"] = datetime.now(timezone.utc).isoformat()
        result = (
            self.client.table(POSTINGS_TABLE)
            .upsert(payload, on_conflict=UPSERT_CONFLICT)
            .execute()
        )
        return len(result.data or [])

    def write_log(self, log_row: dict) -> None:
        self.client.table(FETCH_LOG_TABLE).insert(log_row).execute()


def run(
    *,
    sources: tuple[str, ...],
    roles: list[str],
    live: bool,
    write: bool,
    page_size: int,
    where: str,
    dump_shape: bool,
) -> RunReport:
    report = RunReport(started_at=datetime.now(timezone.utc), dry_run=not live)
    store: Any = SupabaseStore() if write else DryRunStore()

    for source in sources:
        for role in roles:
            outcome = fetch_one(
                source,
                role,
                live=live,
                page_size=page_size,
                where=where,
                dump_shape=dump_shape,
            )
            report.outcomes.append(outcome)

            if outcome.rows:
                resolve_and_attach_identity(outcome.rows, store, report)
                report.rows_upserted += store.upsert_postings(outcome.rows)

            if live:
                store.write_log(outcome.log_row())

    return report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--source",
        action="append",
        choices=sorted({"adzuna", "jsearch"}),
        help=f"Vendor to fetch. Repeatable. Defaults to {list(NIGHTLY_SOURCES)} "
             f"-- JSearch is excluded from the nightly sweep on quota grounds.",
    )
    p.add_argument("--role", action="append", help="Target role. Repeatable. Defaults to all 14.")
    p.add_argument("--where", default=DEFAULT_WHERE)
    p.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    p.add_argument(
        "--live",
        action="store_true",
        help="Actually call the vendors. Without this, prints the planned requests and exits.",
    )
    p.add_argument(
        "--write",
        action="store_true",
        help="Write to Supabase. Requires --live. The tables do not exist until the "
             "staged migration is applied, so this will fail until then.",
    )
    p.add_argument(
        "--dump-shape",
        action="store_true",
        help="Print what the vendor actually returned against what normalize.py expects. "
             "Use this to confirm the field maps with one deliberately-spent call.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")

    if args.write and not args.live:
        print("--write requires --live: refusing to write rows nothing fetched.", file=sys.stderr)
        return 2

    sources = tuple(args.source) if args.source else NIGHTLY_SOURCES
    roles = args.role if args.role else load_target_roles()

    if "jsearch" in sources and len(roles) > 3 and args.live:
        print(
            f"Refusing: {len(roles)} roles x jsearch would spend {len(roles)} of a "
            f"~200/month quota in one run, and the integration spec narrows JSearch "
            f"to LinkedIn-source confirmation. Pass --role explicitly to target it.",
            file=sys.stderr,
        )
        return 2

    report = run(
        sources=sources,
        roles=roles,
        live=args.live,
        write=args.write,
        page_size=args.page_size,
        where=args.where,
        dump_shape=args.dump_shape,
    )
    print(report.render())
    return 1 if report.failed and len(report.failed) == len(report.outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
