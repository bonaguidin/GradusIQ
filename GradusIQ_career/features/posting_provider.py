"""Read-only job-posting provider for FIT market grounding.

This module intentionally lives outside ``market_data.py``. O*NET market
requirements are static, role-to-SOC reference data; postings are live,
role-scoped rows with vendor identity and freshness caveats. Keeping the
provider separate makes that different cardinality and failure mode explicit.

Eligibility is property-based: a posting is retrievable only when
``target_role`` matches the requested role, which means the row came from a
role-scoped query. Whole-board Workday rows are excluded even if a malformed
row ever carries ``target_role``; Workday is not role-labeled evidence.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Mapping, Sequence

POSTINGS_TABLE = "job_postings"
DEFAULT_LIMIT_PER_ROLE = 10
DESCRIPTION_SNIPPET_CHARS = 500

PROVIDER_LIMITATIONS = [
    {
        "code": "clusters_not_opening_counts",
        "message": (
            "Clusters are not opening counts. Vendor rows use fuzzy identity; "
            "syndicated duplicates may collapse, and distinct requisitions at "
            "one employer may also collapse."
        ),
    },
    {
        "code": "cross_source_double_count_possible",
        "message": (
            "The same job may be counted twice across sources because vendor "
            "rows expose no employer ATS id and never join Workday requisitions."
        ),
    },
    {
        "code": "tracked_corpus_denominator",
        "message": (
            'Any denominator is "within postings we track", never "in DFW".'
        ),
    },
]

SELECT_COLUMNS = (
    "id,posting_identity,company,title,location,url,posted_date,fetched_at,"
    "source,target_role,is_dfw,raw_payload"
)


def get_role_posting_grounding(
    client: Any,
    target_roles: Sequence[str],
    *,
    limit_per_role: int = DEFAULT_LIMIT_PER_ROLE,
) -> dict[str, Any]:
    """Fetch role-labeled DFW postings from Supabase and classify coverage.

    The path is read-only: it only calls ``select`` and filters on already
    stored fields. Ordering is deterministic after fetch: ``posted_date``
    descending, then ``fetched_at`` descending, then posting id ascending.
    """

    rows: list[dict[str, Any]] = []
    for role in _clean_roles(target_roles):
        response = (
            client.table(POSTINGS_TABLE)
            .select(SELECT_COLUMNS)
            .eq("target_role", role)
            .eq("is_dfw", True)
            .neq("source", "workday")
            .execute()
        )
        rows.extend(response.data or [])
    return build_role_posting_grounding(
        rows,
        target_roles,
        limit_per_role=limit_per_role,
    )


def build_role_posting_grounding(
    rows: Sequence[Mapping[str, Any]],
    target_roles: Sequence[str],
    *,
    limit_per_role: int = DEFAULT_LIMIT_PER_ROLE,
) -> dict[str, Any]:
    """Build FIT-ready posting grounding from already-fetched rows.

    ``freshness`` is deliberately ``unknown`` for every row. Role-labeled rows
    are vendor/query scoped today, and absence from a query result is not
    evidence that a posting closed. ``posted_date`` is the only age signal.
    """

    if limit_per_role < 0:
        raise ValueError("limit_per_role must be non-negative")

    by_role: dict[str, Any] = {}
    for role in _clean_roles(target_roles):
        eligible = [
            row
            for row in rows
            if row.get("target_role") == role
            and row.get("is_dfw") is True
            and row.get("source") != "workday"
        ]
        ordered = sorted(eligible, key=_posting_sort_key)[:limit_per_role]
        postings = [_posting_record(row) for row in ordered]
        clusters = {
            _string_or_none(row.get("posting_identity"))
            for row in eligible
            if row.get("posting_identity") is not None
        }
        employers = {
            str(row.get("company")).strip()
            for row in eligible
            if isinstance(row.get("company"), str) and str(row.get("company")).strip()
        }
        by_role[role] = {
            "target_role": role,
            "coverage": "available" if eligible else "no_market_data",
            "no_market_data": not eligible,
            "available_postings": len(eligible),
            "returned_postings": len(postings),
            "postings": postings,
            "distinct_clusters": len(clusters),
            "distinct_employers": len(employers),
            "constraints": PROVIDER_LIMITATIONS,
        }
        if not eligible:
            by_role[role]["reason"] = "no role-labeled DFW postings found"

    return {
        "source": "job_postings",
        "role_labeled_by": "query",
        "ordering": ["posted_date desc", "fetched_at desc", "posting id asc"],
        "limit_per_role": limit_per_role,
        "constraints": PROVIDER_LIMITATIONS,
        "by_role": by_role,
    }


def _clean_roles(target_roles: Sequence[str]) -> list[str]:
    roles: list[str] = []
    seen: set[str] = set()
    for role in target_roles:
        if not isinstance(role, str):
            continue
        cleaned = role.strip()
        if cleaned and cleaned not in seen:
            roles.append(cleaned)
            seen.add(cleaned)
    return roles


def _posting_record(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "posting_id": _string_or_none(row.get("id")),
        "cluster_id": _string_or_none(row.get("posting_identity")),
        "employer": _string_or_none(row.get("company")),
        "title": _string_or_none(row.get("title")),
        "location": _string_or_none(row.get("location")),
        "url": _string_or_none(row.get("url")),
        "posted_date": _iso_or_none(row.get("posted_date")),
        "fetched_at": _iso_or_none(row.get("fetched_at")),
        "source": _string_or_none(row.get("source")),
        "description_snippet": _description_snippet(row.get("raw_payload")),
        "role_labeled_by": "query",
        "identity_basis": "vendor_id",
        "freshness": "unknown",
        "description_completeness": "truncated",
    }


def _description_snippet(raw_payload: Any) -> str | None:
    if not isinstance(raw_payload, Mapping):
        return None
    for key in ("description", "job_description", "snippet"):
        value = raw_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:DESCRIPTION_SNIPPET_CHARS]
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _iso_or_none(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _posting_sort_key(row: Mapping[str, Any]) -> tuple[int, int, str]:
    posted = _epoch_seconds(row.get("posted_date"), date_only=True)
    fetched = _epoch_seconds(row.get("fetched_at"), date_only=False)
    return (-posted, -fetched, str(row.get("id") or ""))


def _epoch_seconds(value: Any, *, date_only: bool) -> int:
    parsed = _parse_temporal(value, date_only=date_only)
    if parsed is None:
        return 0
    return int(parsed.timestamp())


def _parse_temporal(value: Any, *, date_only: bool) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if date_only:
            return datetime.combine(date.fromisoformat(text[:10]), time.min, tzinfo=timezone.utc)
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
