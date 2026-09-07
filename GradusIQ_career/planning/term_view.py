"""Assemble a student's terms with their institution's calendar dates.

THE JOIN, AND WHY IT IS DONE HERE RATHER THAN IN POSTGREST
----------------------------------------------------------
academic_terms (per student) and academic_term_dates (per institution) have no
foreign key between them -- they are joined on (institution_id, year, season),
a composite natural key. PostgREST's embedded-resource syntax can only follow
declared foreign keys, so this join cannot be expressed as
`select=*,academic_term_dates(*)`. Two reads and a dict lookup is the whole
implementation, over tens of rows.

Not having that foreign key is deliberate. A student's term row must be
creatable for a term the institution's calendar does not carry -- a transfer
term, a term from before the seeded window, a summer the registrar files
differently -- and an FK would make that a write error at transcript-upload
time.

WHAT "UPCOMING" MEANS
---------------------
The next term that has not started yet: the earliest start_date strictly after
today. This is a PLANNING signal -- during the fall semester a student adding
courses is adding them for spring, and the search box for that belongs on the
term whose registration is still open, not the one already underway.

It is no longer, on its own, where the GPA Calculator's term dropdown opens.
That view now defaults to the term in progress (pickDefaultTermKey in
frontend/src/lib/termPlanning.mjs), because its "Projected GPA" is a projection
from grades being earned right now; `upcoming_term_key` is that dropdown's
second choice, used only when no term contains today. The signal computed here
is unchanged -- what consumes it shifted.

Consequences worth stating, because each is a real case rather than a corner:

  * Mid-term, `upcoming_term_key` still points PAST the term in progress to the
    next one. The GPA dropdown does not follow it there by default anymore, but
    the planning affordance does, and both terms stay in the list either way.
  * A term with no dates row can never be `upcoming` -- it has no start_date to
    compare, so "has it started?" is unanswerable. This is what happens to the
    five seeded 'Current Term' rows (season='current', no calendar row) and to
    Fall 2025 / Spring 2026, which predate the seeded window. All still appear
    in the dropdown.
  * The upcoming term may be one the student has no academic_terms row for --
    a term they have never enrolled in is exactly the one they want to plan.
    Those are returned too, flagged `enrolled: false`, with a null id. Adding a
    planned course to one is what creates its academic_terms row (see
    planned.py), so the id stays null only until the student plans something.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from ..transcript.terms import SEASON_ORDER

# Sorts an unrecognized season after every known one, matching
# terms.chronological_key and repeats._chronological_key. Reached by the seeded
# 'current' rows.
UNKNOWN_SEASON_ORDINAL = 99


@dataclass(frozen=True)
class TermsView:
    terms: list[dict[str, Any]]
    upcoming_term_key: str | None


def _season_ordinal(season: Any) -> int:
    return SEASON_ORDER.get(str(season), UNKNOWN_SEASON_ORDINAL)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def term_key(year: Any, season: Any) -> str:
    """Stable client-side identifier for a term slot.

    NOT academic_terms.id: a term the student has never enrolled in has no such
    row yet, and the dropdown must still be able to name it. "2026-Fall"
    identifies the slot itself, which is what both tables are keyed on.
    """
    return f"{year}-{season}"


def build_terms_view(
    term_rows: Iterable[Mapping[str, Any]],
    date_rows: Iterable[Mapping[str, Any]],
    today: date,
) -> TermsView:
    """Merge a student's academic_terms with their institution's term dates.

    Pure -- no database access, so the ordering and upcoming-term rules are
    testable against a fixed `today` rather than against the clock.
    """
    dates_by_key: dict[tuple[int, str], Mapping[str, Any]] = {}
    for row in date_rows:
        year, season = row.get("year"), row.get("season")
        if year is None or season is None:
            continue
        dates_by_key[(int(year), str(season))] = row

    merged: dict[str, dict[str, Any]] = {}

    for row in term_rows:
        year, season = row.get("year"), row.get("season")
        if year is None or season is None:
            continue
        key = (int(year), str(season))
        dates = dates_by_key.get(key)
        merged[term_key(*key)] = {
            "key": term_key(*key),
            "id": row.get("id"),
            # The student's own label wins over the calendar's: it is what
            # their transcript printed ("Fall 2026 - College Station"), and
            # showing them something else in a dropdown listing their own
            # coursework would read as a different term.
            "label": row.get("label") or (dates or {}).get("label") or term_key(*key),
            "year": int(year),
            "season": str(season),
            "sequence": row.get("sequence"),
            "start_date": (dates or {}).get("start_date"),
            "end_date": (dates or {}).get("end_date"),
            "enrolled": True,
        }

    # Calendar terms the student has no row for. These are the plannable ones.
    for (year, season), row in dates_by_key.items():
        key = term_key(year, season)
        if key in merged:
            continue
        merged[key] = {
            "key": key,
            "id": None,
            "label": row.get("label") or key,
            "year": year,
            "season": season,
            "sequence": None,
            "start_date": row.get("start_date"),
            "end_date": row.get("end_date"),
            "enrolled": False,
        }

    terms = sorted(
        merged.values(),
        key=lambda term: (term["year"], _season_ordinal(term["season"]), term["label"]),
    )

    # Earliest start strictly after today. Ties are impossible in practice (one
    # term per (year, season)) but resolve by the same sort as the list, so the
    # default is never arbitrary.
    upcoming: dict[str, Any] | None = None
    for term in terms:
        start = _parse_date(term["start_date"])
        if start is None or start <= today:
            continue
        if upcoming is None or start < _parse_date(upcoming["start_date"]):
            upcoming = term

    for term in terms:
        term["is_upcoming"] = upcoming is not None and term["key"] == upcoming["key"]

    return TermsView(terms=terms, upcoming_term_key=upcoming["key"] if upcoming else None)


def fetch_terms_view(
    client: Any,
    student_id: str,
    institution_id: str,
    today: date | None = None,
) -> TermsView:
    """Read both tables and merge them. See build_terms_view for the rules."""
    term_rows: Sequence[Mapping[str, Any]] = (
        client.table("academic_terms")
        .select("id,label,year,season,sequence,institution_id")
        .eq("student_id", student_id)
        .execute()
        .data
        or []
    )
    date_rows: Sequence[Mapping[str, Any]] = (
        client.table("academic_term_dates")
        .select("year,season,label,start_date,end_date,source,source_last_checked")
        .eq("institution_id", institution_id)
        .execute()
        .data
        or []
    )
    return build_terms_view(term_rows, date_rows, today or date.today())


def capture_reconstruction_date() -> date:
    """Capture the runtime-local effective date once at a request boundary."""
    return date.today()
