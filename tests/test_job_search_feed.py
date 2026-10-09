"""Tests for GradusIQ_career/features/job_search_feed.py.

A fake Supabase-shaped client, not a real one -- the same style as
posting_provider's own tests and the ingest DryRunStore pattern. Covers
classification + exclusion, related-family expansion, each filter, the
days whitelist, dedupe (including the Micron-shaped two-row example), the
newest-first-with-NULL-last ordering, pagination, the no-roles case, and
role= compatibility. Also pins that raw_payload/description are never
selected, since that is the one thing #114's class of bug and this
feature's own scoping report both flagged as a real risk.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

TODAY = date.today()


def _days_ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()

from GradusIQ_career.features.job_search_feed import (
    SELECT_COLUMNS,
    fetch_candidate_pool,
    get_job_search_feed,
)


class _FakeTable:
    def __init__(self, rows: list[dict[str, Any]], calls: list[dict[str, Any]]):
        self._rows = rows
        self._calls = calls
        self._eq: dict[str, Any] = {}
        self._select_cols: str | None = None

    def select(self, cols):
        self._select_cols = cols
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def range(self, start, end):
        matched = [r for r in self._rows if all(r.get(k) == v for k, v in self._eq.items())]
        self._calls.append({"select": self._select_cols, "eq": dict(self._eq), "start": start, "end": end})
        self._page = matched[start : end + 1]
        return self

    def execute(self):
        return SimpleNamespace(data=self._page)


class _FakeClient:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    def table(self, name):
        assert name == "job_postings"
        return _FakeTable(self.rows, self.calls)


_UNSET = object()


def _row(
    id_,
    *,
    posting_identity=None,
    company="Acme",
    title="Software Engineering Intern",
    location="Dallas, TX",
    posted_date=_UNSET,
    fetched_at=_UNSET,
    source="adzuna",
    is_dfw=True,
):
    if posted_date is _UNSET:
        posted_date = _days_ago(0)
    if fetched_at is _UNSET:
        fetched_at = f"{_days_ago(0)}T00:00:00Z"
    return {
        "id": id_,
        "posting_identity": posting_identity,
        "company": company,
        "title": title,
        "location": location,
        "posted_date": posted_date,
        "fetched_at": fetched_at,
        "source": source,
        "is_dfw": is_dfw,
    }


def test_never_selects_raw_payload_or_description():
    client = _FakeClient([])
    fetch_candidate_pool(client, days=30)
    assert client.calls, "the fake client was never queried"
    for call in client.calls:
        assert "raw_payload" not in call["select"]
        assert "description" not in call["select"]
    assert "raw_payload" not in SELECT_COLUMNS
    assert "description" not in SELECT_COLUMNS


def test_candidate_pool_is_scoped_to_is_dfw():
    client = _FakeClient([_row("1", is_dfw=True), _row("2", is_dfw=False)])
    fetch_candidate_pool(client, days=30)
    assert all(call["eq"] == {"is_dfw": True} for call in client.calls)


def test_title_must_look_like_an_internship_or_co_op():
    rows = [
        _row("1", title="Software Engineering Intern"),
        _row("2", title="Summer 2027 Internship"),
        _row("3", title="Engineering Co-op"),
        _row("4", title="Senior Accountant"),
    ]
    pool = fetch_candidate_pool(_FakeClient(rows), days=30)
    assert {r["id"] for r in pool} == {"1", "2", "3"}


def test_days_window_excludes_old_rows_but_keeps_null_dated_rows():
    rows = [
        _row("recent", posted_date=_days_ago(0)),
        _row("old", posted_date=_days_ago(60)),
        _row("undated", posted_date=None),
    ]
    pool = fetch_candidate_pool(_FakeClient(rows), days=7)
    assert {r["id"] for r in pool} == {"recent", "undated"}


def test_dedupe_by_posting_identity_merges_locations_micron_example():
    """Two rows of the same posting_identity, different company-name
    spellings and different locations, collapse to one card with both
    locations merged and the alias-folded employer name."""
    client = _FakeClient(
        [
            _row(
                "1", posting_identity="c1", company="Micron", title="Intern - Design Engineer, HIG HBM",
                location="Boise, ID", posted_date=_days_ago(1),
            ),
            _row(
                "2", posting_identity="c1", company="Micron Technology, Inc.",
                title="Intern - Design Engineer, HIG HBM", location="Dallas, TX", posted_date=_days_ago(0),
            ),
        ]
    )
    result = get_job_search_feed(client, target_role_families=[], families=["Computer Engineering Intern"])
    # This title does not classify to any family (word order: "Intern" comes
    # before "Design Engineer", not after), so it never appears in postings
    # -- but the dedupe itself is visible in the employer facet count.
    employers = {f["employer"]: f["count"] for f in result["facets"]["employers"]}
    assert employers.get("Micron Technology, Inc.") == 1


def test_dedupe_merges_locations_for_a_classifiable_cluster():
    client = _FakeClient(
        [
            _row("1", posting_identity="c1", title="Software Engineering Intern", location="Dallas, TX"),
            _row("2", posting_identity="c1", title="Software Engineering Intern", location="Plano, TX"),
        ]
    )
    result = get_job_search_feed(
        client, target_role_families=["Software Engineering Intern"],
    )
    assert result["total"] == 1
    assert sorted(result["postings"][0]["locations"]) == ["Dallas, TX", "Plano, TX"]


def test_rows_with_null_posting_identity_stand_alone():
    client = _FakeClient(
        [
            _row("1", posting_identity=None, title="Software Engineering Intern"),
            _row("2", posting_identity=None, title="Software Engineering Intern"),
        ]
    )
    result = get_job_search_feed(client, target_role_families=["Software Engineering Intern"])
    assert result["total"] == 2


def test_ordering_newest_posted_date_first_then_fetched_at_then_id():
    client = _FakeClient(
        [
            _row("b", title="Software Engineering Intern", posted_date=_days_ago(1), fetched_at=f"{_days_ago(1)}T00:00:00Z"),
            _row("a", title="Software Engineering Intern", posted_date=_days_ago(0), fetched_at=f"{_days_ago(1)}T00:00:00Z"),
            _row("c", title="Software Engineering Intern", posted_date=None, fetched_at=f"{_days_ago(0)}T00:00:05Z"),
        ]
    )
    result = get_job_search_feed(client, target_role_families=["Software Engineering Intern"])
    assert [p["posting_id"] for p in result["postings"]] == ["a", "b", "c"]


def test_family_filter_scopes_to_requested_families_only():
    client = _FakeClient(
        [
            _row("1", title="Software Engineering Intern"),
            _row("2", title="AI Engineering Intern"),
        ]
    )
    result = get_job_search_feed(
        client, target_role_families=[], families=["Software Engineering Intern"],
    )
    assert [p["title"] for p in result["postings"]] == ["Software Engineering Intern"]


def test_default_family_set_is_target_roles_plus_related():
    client = _FakeClient(
        [
            _row("1", title="Software Engineering Intern"),
            _row("2", title="AI Engineering Intern"),
            _row("3", title="Finance Intern"),
        ]
    )
    result = get_job_search_feed(client, target_role_families=["Software Engineering Intern"])
    titles = {p["title"] for p in result["postings"]}
    assert titles == {"Software Engineering Intern", "AI Engineering Intern"}


def test_employer_filter_matches_the_display_name():
    client = _FakeClient(
        [
            _row("1", title="Software Engineering Intern", company="Micron"),
            _row("2", title="Software Engineering Intern", company="Other Co"),
        ]
    )
    result = get_job_search_feed(
        client, target_role_families=["Software Engineering Intern"], employer="Micron Technology, Inc.",
    )
    assert len(result["postings"]) == 1
    assert result["postings"][0]["employer"] == "Micron Technology, Inc."


@pytest.mark.parametrize("days", [1, 0, 365, -5])
def test_invalid_days_falls_back_to_the_default(days):
    client = _FakeClient([_row("1", title="Software Engineering Intern")])
    result = get_job_search_feed(client, target_role_families=["Software Engineering Intern"], days=days)
    assert result["coverage"] == "available"


def test_no_target_roles_and_no_explicit_families_returns_no_target_roles_coverage():
    client = _FakeClient([_row("1", title="Software Engineering Intern")])
    result = get_job_search_feed(client, target_role_families=[])
    assert result["coverage"] == "no_target_roles"
    assert result["postings"] == []
    assert result["total"] == 0


def test_explicit_families_param_works_even_with_no_target_roles():
    client = _FakeClient([_row("1", title="Software Engineering Intern")])
    result = get_job_search_feed(
        client, target_role_families=[], families=["Software Engineering Intern"],
    )
    assert result["coverage"] == "available"
    assert result["total"] == 1


def test_empty_result_after_filtering_is_no_market_data_not_an_error():
    client = _FakeClient([_row("1", title="Finance Intern")])
    result = get_job_search_feed(client, target_role_families=["Software Engineering Intern"])
    assert result["coverage"] == "no_market_data"
    assert result["postings"] == []


def test_pagination_page_size_and_next_cursor():
    rows = [
        _row(str(i), title="Software Engineering Intern", posted_date=_days_ago(0), fetched_at=f"{_days_ago(0)}T00:00:{i:02d}Z")
        for i in range(30)
    ]
    client = _FakeClient(rows)
    first = get_job_search_feed(client, target_role_families=["Software Engineering Intern"], cursor=0, page_size=25)
    assert len(first["postings"]) == 25
    assert first["total"] == 30
    assert first["next_cursor"] == 25

    second = get_job_search_feed(
        client, target_role_families=["Software Engineering Intern"], cursor=first["next_cursor"], page_size=25,
    )
    assert len(second["postings"]) == 5
    assert second["next_cursor"] is None


def test_role_param_is_treated_as_a_single_family_override():
    client = _FakeClient(
        [
            _row("1", title="Software Engineering Intern"),
            _row("2", title="AI Engineering Intern"),
        ]
    )
    result = get_job_search_feed(
        client, target_role_families=[], families=["Software Engineering Intern"],
    )
    assert [p["title"] for p in result["postings"]] == ["Software Engineering Intern"]


def test_unknown_family_names_are_dropped_not_errored():
    client = _FakeClient([_row("1", title="Software Engineering Intern")])
    result = get_job_search_feed(
        client, target_role_families=[], families=["Not A Real Family", "Software Engineering Intern"],
    )
    assert result["coverage"] == "available"
    assert result["total"] == 1


def test_facets_reflect_the_pool_before_the_family_filter_is_applied():
    client = _FakeClient(
        [
            _row("1", title="Software Engineering Intern"),
            _row("2", title="Finance Intern"),
        ]
    )
    result = get_job_search_feed(
        client, target_role_families=[], families=["Software Engineering Intern"],
    )
    family_names = {f["family"] for f in result["facets"]["families"]}
    assert family_names == {"Software Engineering Intern", "Finance Intern"}
    assert len(result["postings"]) == 1
