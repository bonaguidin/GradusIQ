"""Vendor payload -> one job_postings row shape.

Six response shapes reach this module and one shape leaves it. The ATS README
makes the point that the work is normalization rather than fetching, and that
holds harder now that two syndicating vendors are in the mix.

UNVERIFIED AGAINST LIVE RESPONSES -- READ THIS BEFORE TRUSTING THE OUTPUT
--------------------------------------------------------------------------
The Adzuna and JSearch field maps below are written from each vendor's
documented response shape, NOT from a captured live response. Nobody has spent
a call to confirm them: the integration spec pins down `source_job_id`
(Adzuna "id", JSearch "job_id") and nothing else, and both free tiers are
small and already partly spent.

So the maps are declared as data in ONE place, and every one of them fails
loudly rather than quietly writing NULL. A silently-null column is the failure
mode that matters here -- a posting with no URL cannot participate in exact
dedup at all, and nothing about the row would look wrong.

To confirm or correct a map, spend one call:

    python -m ingest --source adzuna --role "Finance Intern" --live --dump-shape

That prints the keys the vendor actually returned alongside what the map
expects, which is enough to fix this file without guessing twice.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from identity import classify_location  # noqa: E402


class NormalizationError(ValueError):
    """A payload did not carry a field the row shape requires.

    Deliberately fatal rather than a warning. The alternative is a row that
    looks fine and is missing the thing dedup depends on.
    """


@dataclass(frozen=True)
class FieldMap:
    """How one vendor's listing maps onto the row shape.

    Each entry is a callable rather than a key name because the vendors nest
    differently -- Adzuna puts the employer at company.display_name, JSearch
    keeps it flat at employer_name -- and a dotted-path mini-language would be
    a worse version of a lambda.
    """

    source: str
    listings_key: str
    source_job_id: Callable[[dict], Any]
    title: Callable[[dict], Any]
    company: Callable[[dict], Any]
    location: Callable[[dict], Any]
    url: Callable[[dict], Any]
    posted_date: Callable[[dict], Any]
    description: Callable[[dict], Any]
    salary_min: Callable[[dict], Any]
    salary_max: Callable[[dict], Any]


def _get(d: dict, *path: str) -> Any:
    """Walk a nested path, returning None rather than raising on a gap."""
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


# Adzuna: results[] -- https://developer.adzuna.com
ADZUNA = FieldMap(
    source="adzuna",
    listings_key="results",
    source_job_id=lambda r: r.get("id"),
    title=lambda r: r.get("title"),
    company=lambda r: _get(r, "company", "display_name"),
    location=lambda r: _get(r, "location", "display_name"),
    url=lambda r: r.get("redirect_url"),
    posted_date=lambda r: r.get("created"),
    description=lambda r: r.get("description"),
    salary_min=lambda r: r.get("salary_min"),
    salary_max=lambda r: r.get("salary_max"),
)

# JSearch: data[] -- flat, and note the job_ prefix on nearly everything.
JSEARCH = FieldMap(
    source="jsearch",
    listings_key="data",
    source_job_id=lambda r: r.get("job_id"),
    title=lambda r: r.get("job_title"),
    company=lambda r: r.get("employer_name"),
    location=lambda r: _jsearch_location(r),
    url=lambda r: r.get("job_apply_link"),
    posted_date=lambda r: r.get("job_posted_at_datetime_utc"),
    description=lambda r: r.get("job_description"),
    salary_min=lambda r: r.get("job_min_salary"),
    salary_max=lambda r: r.get("job_max_salary"),
)

FIELD_MAPS = {"adzuna": ADZUNA, "jsearch": JSEARCH}

# Fields without which a row is not worth storing. url is on the list on
# purpose: a listing with no link cannot be exact-matched against an ATS row,
# cannot be spot-checked by a human, and is the one field whose absence is
# invisible downstream.
REQUIRED = ("source_job_id", "title", "url")


def _jsearch_location(listing: dict) -> str | None:
    """JSearch splits the location across city/state/country."""
    parts = [listing.get("job_city"), listing.get("job_state"), listing.get("job_country")]
    joined = ", ".join(p for p in parts if p)
    return joined or None


def _coerce_date(value: Any) -> date | None:
    """Both vendors hand back ISO-ish strings; neither is guaranteed."""
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _coerce_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_listing(listing: dict, field_map: FieldMap, *, target_role: str) -> dict:
    """One vendor listing -> one job_postings row. Raises on a missing required field."""
    row: dict[str, Any] = {
        "source": field_map.source,
        "source_job_id": field_map.source_job_id(listing),
        "title": field_map.title(listing),
        "company": field_map.company(listing),
        "location": field_map.location(listing),
        "url": field_map.url(listing),
        "target_role": target_role,
        "posted_date": _coerce_date(field_map.posted_date(listing)),
        "salary_min": _coerce_number(field_map.salary_min(listing)),
        "salary_max": _coerce_number(field_map.salary_max(listing)),
        "raw_payload": listing,
    }

    missing = [f for f in REQUIRED if row.get(f) in (None, "")]
    if missing:
        raise NormalizationError(
            f"{field_map.source} listing missing required {missing}. "
            f"Keys present: {sorted(listing)[:20]}. "
            f"The field map in normalize.py is unverified against live responses -- "
            f"this is what that looks like when it is wrong."
        )

    row["source_job_id"] = str(row["source_job_id"])
    is_dfw, kind = classify_location(row["location"])
    row["is_dfw"] = is_dfw
    row["location_kind"] = kind.value

    # Salary can arrive inverted. Cheaper to swap than to fail a whole run, and
    # the DB check constraint would reject it anyway.
    lo, hi = row["salary_min"], row["salary_max"]
    if lo is not None and hi is not None and lo > hi:
        row["salary_min"], row["salary_max"] = hi, lo

    return row


def normalize_response(
    payload: dict,
    source: str,
    *,
    target_role: str,
) -> tuple[list[dict], list[str]]:
    """Whole vendor response -> (rows, errors).

    Returns errors instead of raising so one malformed listing cannot discard a
    page that cost a call to fetch. The caller decides what a tolerable error
    rate is; a run where most listings fail is a wrong field map, not bad luck.
    """
    field_map = FIELD_MAPS.get(source)
    if field_map is None:
        raise NormalizationError(f"no field map for source {source!r}")

    listings = payload.get(field_map.listings_key)
    if listings is None:
        raise NormalizationError(
            f"{source} response has no {field_map.listings_key!r} key. "
            f"Top-level keys: {sorted(payload)}"
        )

    rows, errors = [], []
    for listing in listings:
        try:
            rows.append(normalize_listing(listing, field_map, target_role=target_role))
        except NormalizationError as exc:
            errors.append(str(exc))
    return rows, errors


def describe_shape(payload: dict, source: str) -> str:
    """What the vendor actually sent vs what the map expects.

    The output of one deliberately-spent call. Prints rather than guesses.
    """
    field_map = FIELD_MAPS.get(source)
    if field_map is None:
        return f"no field map for source {source!r}"

    lines = [f"{source}: top-level keys = {sorted(payload)}"]
    listings = payload.get(field_map.listings_key)
    if not listings:
        lines.append(f"  !! expected listings under {field_map.listings_key!r}, found none")
        return "\n".join(lines)

    first = listings[0]
    lines.append(f"  {len(listings)} listing(s); first listing keys = {sorted(first)}")
    lines.append("  field map resolution against the first listing:")
    for name in ("source_job_id", "title", "company", "location", "url",
                 "posted_date", "description", "salary_min", "salary_max"):
        value = getattr(field_map, name)(first)
        shown = repr(value)[:70] if value is not None else "None  <-- MISSING"
        lines.append(f"    {name:<16} {shown}")
    return "\n".join(lines)
