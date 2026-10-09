"""Combined Job Search feed: internships across a student's target roles
plus related families, newest first, read-only against the cached
job_postings table.

Deliberately separate from posting_provider.py. That module answers "what
has FIT's hiring_signal already cited for this exact target_role", keyed by
the stored target_role column (Adzuna/JSearch only -- Workday rows carry no
target_role and are excluded there on purpose). This feed answers a
different question: every internship-shaped posting across a student's
whole family set, BOTH sources, classified at READ time by title against
role_family_matcher rather than by the stored target_role column. This
module never imports or calls posting_provider.py, and touches no row FIT's
grounding counts depend on.

raw_payload and description are never selected -- cards are built from
title/employer/location/date only.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from scripts.job_postings.identity import employer_display_name
from scripts.job_postings.role_family_matcher import (
    classify_title,
    expand_families,
    load_all_families,
    load_feed_families,
)

POSTINGS_TABLE = "job_postings"
ALLOWED_DAYS = (7, 14, 30)
DEFAULT_DAYS = 30
PAGE_SIZE = 25

SELECT_COLUMNS = (
    "id,posting_identity,company,title,location,url,posted_date,fetched_at,source"
)


_INTERN_PATTERN = re.compile(r"intern(ship)?|co[\s-]?op", re.IGNORECASE)
_PAGE = 1000


def _days_cutoff(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def fetch_candidate_pool(client: Any, days: int) -> list[dict[str, Any]]:
    """Every is_dfw posting, either source, whose title looks like an
    internship or co-op, posted within `days` -- or with no posted_date at
    all, since many Workday rows never carry one and dropping them here
    would silently empty the pool for roles only Workday covers.

    is_dfw is filtered server-side (the one column every row has and the
    one this is always scoped to); the title pattern and the days-or-null
    window are applied in Python. The corpus is a few thousand rows today,
    small enough that two chained PostgREST `or()` filters -- one for the
    title pattern, one for the date window -- are not worth the risk of
    getting their combination wrong against a live API this module has no
    way to test end-to-end.
    """
    cutoff = _days_cutoff(days)
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        response = (
            client.table(POSTINGS_TABLE)
            .select(SELECT_COLUMNS)
            .eq("is_dfw", True)
            .range(start, start + _PAGE - 1)
            .execute()
        )
        page = response.data or []
        rows.extend(page)
        if len(page) < _PAGE:
            break
        start += _PAGE

    pool = []
    for row in rows:
        title = row.get("title") or ""
        if not _INTERN_PATTERN.search(title):
            continue
        posted = row.get("posted_date")
        if posted is not None and str(posted) < cutoff:
            continue
        pool.append(row)
    return pool


def _sort_key(row: Mapping[str, Any]) -> tuple[int, int, str]:
    posted = _epoch_or_zero(row.get("posted_date"), date_only=True)
    fetched = _epoch_or_zero(row.get("fetched_at"), date_only=False)
    return (-posted, -fetched, str(row.get("id") or ""))


def _epoch_or_zero(value: Any, *, date_only: bool) -> int:
    if value is None:
        return 0
    try:
        if date_only:
            parsed = datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return 0
    return int(parsed.timestamp())


class Card:
    """One deduped card: the newest row in a posting_identity cluster, with
    every distinct location in the cluster merged in."""

    __slots__ = ("row", "locations", "family", "size")

    def __init__(self, row: Mapping[str, Any], locations: list[str], family: str | None, size: int):
        self.row = row
        self.locations = locations
        self.family = family
        self.size = size

    def to_dict(self) -> dict[str, Any]:
        row = self.row
        return {
            "posting_id": _string_or_none(row.get("id")),
            "title": _string_or_none(row.get("title")),
            "employer": employer_display_name(_string_or_none(row.get("company"))),
            "locations": self.locations,
            "posted_date": _string_or_none(row.get("posted_date")),
            "url": _string_or_none(row.get("url")),
            "family": self.family,
            "source": _string_or_none(row.get("source")),
        }


def _string_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def build_cards(rows: Sequence[Mapping[str, Any]], families: list[dict[str, Any]]) -> list[Card]:
    """Dedupe the candidate pool by posting_identity. A row with no
    posting_identity stands alone, keyed by its own id. The cluster's
    family is the classification of its newest row's title; locations
    across every row in the cluster are merged and de-duplicated.
    """
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        key = row.get("posting_identity") or f"single:{row.get('id')}"
        groups.setdefault(key, []).append(row)

    cards: list[Card] = []
    for members in groups.values():
        members_sorted = sorted(members, key=_sort_key)
        newest = members_sorted[0]
        locations = sorted(
            {loc for loc in (m.get("location") for m in members) if loc},
        )
        family = classify_title(newest.get("title"), families)
        cards.append(Card(newest, locations, family, len(members)))
    return cards


def build_facets(cards: Sequence[Card]) -> dict[str, list[dict[str, Any]]]:
    """Family and employer counts over the deduped, days-filtered card set
    -- before the request's own families/employer filters are applied, so
    toggling a filter does not change what the facets themselves show."""
    family_counts: dict[str, int] = {}
    employer_counts: dict[str, int] = {}
    for card in cards:
        if card.family:
            family_counts[card.family] = family_counts.get(card.family, 0) + 1
        employer = card.to_dict()["employer"]
        if employer:
            employer_counts[employer] = employer_counts.get(employer, 0) + 1
    return {
        "families": [
            {"family": name, "count": count}
            for name, count in sorted(family_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "employers": [
            {"employer": name, "count": count}
            for name, count in sorted(employer_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }


def resolve_family_set(
    requested_families: list[str] | None,
    target_role_families: list[str],
    all_family_names: set[str],
) -> list[str]:
    """The families a request actually scopes to. An explicit `families`
    param overrides the student's own set entirely (validated against the
    full vocabulary, unknown names dropped) -- it does not narrow it, since
    the facets expose every family in the pool for exploration, not just the
    student's own. With no param, the default is the student's own
    target-role families plus job_search_feed_families.yaml's related
    families for each.
    """
    if requested_families is not None:
        return [f for f in requested_families if f in all_family_names]
    _, related = load_feed_families()
    return expand_families(target_role_families, related)


def get_job_search_feed(
    client: Any,
    *,
    target_role_families: list[str],
    families: list[str] | None = None,
    days: int = DEFAULT_DAYS,
    employer: str | None = None,
    cursor: int = 0,
    page_size: int = PAGE_SIZE,
) -> dict[str, Any]:
    """The full feed response: coverage marker, one page of cards, facets
    over the full (pre-family-filter) days-windowed pool, total, and the
    next cursor."""
    if days not in ALLOWED_DAYS:
        days = DEFAULT_DAYS

    all_families = load_all_families()
    all_family_names = {f["family"] for f in all_families}
    scoped_families = resolve_family_set(families, target_role_families, all_family_names)

    if not target_role_families and families is None:
        return {
            "coverage": "no_target_roles",
            "postings": [],
            "facets": {"families": [], "employers": []},
            "total": 0,
            "next_cursor": None,
            "scoped_families": [],
        }

    rows = fetch_candidate_pool(client, days)
    cards = build_cards(rows, all_families)
    facets = build_facets(cards)

    filtered = [card for card in cards if card.family and card.family in scoped_families]
    if employer:
        filtered = [card for card in filtered if card.to_dict()["employer"] == employer]
    filtered.sort(key=lambda card: _sort_key(card.row))

    total = len(filtered)
    page = filtered[cursor : cursor + page_size]
    next_cursor = cursor + page_size if cursor + page_size < total else None

    return {
        "coverage": "available" if page else "no_market_data",
        "postings": [card.to_dict() for card in page],
        "facets": facets,
        "total": total,
        "next_cursor": next_cursor,
        # The family set actually applied -- the student's own default
        # (target roles + related) when no explicit `families`/`role` was
        # given, or exactly the validated override otherwise. The frontend
        # needs this to know which chips start "on"; the response alone
        # would not otherwise reveal the server-computed default.
        "scoped_families": scoped_families,
    }
