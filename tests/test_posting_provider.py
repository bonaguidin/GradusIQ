from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from GradusIQ_career.features.posting_provider import (
    build_role_posting_grounding,
    get_role_posting_grounding,
)


def _row(
    posting_id: str,
    role: str,
    *,
    source: str = "adzuna",
    cluster: str | None = None,
    company: str = "Acme",
    title: str = "Software Engineering Intern",
    is_dfw: bool = True,
    posted_date: object = "2026-09-10",
    fetched_at: object = "2026-09-12T10:00:00+00:00",
    description: str = "Build production software with mentors.",
) -> dict[str, object]:
    return {
        "id": posting_id,
        "posting_identity": cluster or f"cluster-{posting_id}",
        "company": company,
        "title": title,
        "location": "Dallas, TX",
        "url": f"https://example.test/{posting_id}",
        "posted_date": posted_date,
        "fetched_at": fetched_at,
        "source": source,
        "target_role": role,
        "is_dfw": is_dfw,
        "raw_payload": {"description": description},
    }


def _role_block(result: dict[str, object], role: str) -> dict[str, object]:
    return result["by_role"][role]  # type: ignore[index]


def test_role_with_postings_returns_records_and_metadata():
    result = build_role_posting_grounding(
        [_row("p1", "Software Engineering Intern")],
        ["Software Engineering Intern"],
    )

    role = _role_block(result, "Software Engineering Intern")
    posting = role["postings"][0]  # type: ignore[index]
    assert role["coverage"] == "available"
    assert role["no_market_data"] is False
    assert role["available_postings"] == 1
    assert role["returned_postings"] == 1
    assert role["distinct_clusters"] == 1
    assert role["distinct_employers"] == 1
    assert role["unknown_employer_postings"] == 0
    assert posting == {
        "posting_id": "p1",
        "cluster_id": "cluster-p1",
        "employer": "Acme",
        "title": "Software Engineering Intern",
        "location": "Dallas, TX",
        "url": "https://example.test/p1",
        "posted_date": "2026-09-10",
        "fetched_at": "2026-09-12T10:00:00+00:00",
        "source": "adzuna",
        "role_labeled_by": "query",
        "identity_basis": "vendor_id",
        "freshness": "unknown",
        "description_completeness": "truncated",
    }
    assert result["constraints"] == role["constraints"]


def test_role_with_zero_postings_gets_explicit_no_coverage_marker():
    result = build_role_posting_grounding([], ["Flight Systems Intern"])

    role = _role_block(result, "Flight Systems Intern")
    assert role["coverage"] == "no_market_data"
    assert role["no_market_data"] is True
    assert role["available_postings"] == 0
    assert role["returned_postings"] == 0
    assert role["postings"] == []
    assert role["distinct_clusters"] == 0
    assert role["distinct_employers"] == 0
    assert role["unknown_employer_postings"] == 0
    assert role["reason"] == "no role-labeled DFW postings found"


def test_non_dfw_postings_are_excluded():
    result = build_role_posting_grounding(
        [_row("p1", "Software Engineering Intern", is_dfw=False)],
        ["Software Engineering Intern"],
    )

    assert _role_block(result, "Software Engineering Intern")["postings"] == []


def test_workday_rows_are_never_returned_even_if_target_role_is_set():
    result = build_role_posting_grounding(
        [_row("p1", "Software Engineering Intern", source="workday")],
        ["Software Engineering Intern"],
    )

    assert _role_block(result, "Software Engineering Intern")["postings"] == []


def test_ordering_is_deterministic_across_repeated_calls():
    rows = [
        _row("b", "Software Engineering Intern", posted_date="2026-09-10", fetched_at="2026-09-11T00:00:00Z"),
        _row("a", "Software Engineering Intern", posted_date="2026-09-10", fetched_at="2026-09-11T00:00:00Z"),
        _row("c", "Software Engineering Intern", posted_date=date(2026, 9, 12), fetched_at=datetime(2026, 9, 12, tzinfo=timezone.utc)),
    ]

    first = build_role_posting_grounding(rows, ["Software Engineering Intern"])
    second = build_role_posting_grounding(list(reversed(rows)), ["Software Engineering Intern"])

    first_ids = [p["posting_id"] for p in _role_block(first, "Software Engineering Intern")["postings"]]
    second_ids = [p["posting_id"] for p in _role_block(second, "Software Engineering Intern")["postings"]]
    assert first_ids == ["c", "a", "b"]
    assert second_ids == ["c", "a", "b"]


def test_result_count_respects_bound():
    rows = [_row(f"p{i}", "Software Engineering Intern") for i in range(3)]

    result = build_role_posting_grounding(
        rows,
        ["Software Engineering Intern"],
        limit_per_role=2,
    )

    assert len(_role_block(result, "Software Engineering Intern")["postings"]) == 2


def test_employer_spelling_variants_collapse_to_one_via_shared_normalizer():
    rows = [
        _row("p1", "Software Engineering Intern", cluster="c1", company="Texas Instruments"),
        _row("p2", "Software Engineering Intern", cluster="c2", company="Texas Instruments Incorporated"),
    ]

    result = build_role_posting_grounding(rows, ["Software Engineering Intern"])

    role = _role_block(result, "Software Engineering Intern")
    assert role["distinct_employers"] == 1
    postings = role["postings"]
    assert {p["employer"] for p in postings} == {
        "Texas Instruments",
        "Texas Instruments Incorporated",
    }


def test_null_company_is_excluded_from_distinct_employers_and_counted_separately():
    rows = [
        _row("p1", "Software Engineering Intern", cluster="c1", company="Acme"),
        _row("p2", "Software Engineering Intern", cluster="c2"),
    ]
    rows[1]["company"] = None

    result = build_role_posting_grounding(rows, ["Software Engineering Intern"])

    role = _role_block(result, "Software Engineering Intern")
    assert role["distinct_employers"] == 1
    assert role["unknown_employer_postings"] == 1
    assert role["postings"][1]["employer"] is None


def test_cluster_and_employer_counts_are_distinct_counts_not_row_counts():
    rows = [
        _row("p1", "Software Engineering Intern", cluster="c1", company="Acme"),
        _row("p2", "Software Engineering Intern", cluster="c1", company="Acme"),
        _row("p3", "Software Engineering Intern", cluster="c2", company="Beta"),
    ]

    result = build_role_posting_grounding(rows, ["Software Engineering Intern"])

    role = _role_block(result, "Software Engineering Intern")
    assert len(role["postings"]) == 3
    assert role["distinct_clusters"] == 2
    assert role["distinct_employers"] == 2


def test_coverage_counts_use_all_available_rows_not_only_returned_bound():
    rows = [
        _row("p1", "Software Engineering Intern", cluster="c1", company="Acme"),
        _row("p2", "Software Engineering Intern", cluster="c2", company="Beta"),
    ]

    result = build_role_posting_grounding(
        rows,
        ["Software Engineering Intern"],
        limit_per_role=1,
    )

    role = _role_block(result, "Software Engineering Intern")
    assert role["available_postings"] == 2
    assert role["returned_postings"] == 1
    assert role["distinct_clusters"] == 2
    assert role["distinct_employers"] == 2


def test_negative_limit_is_rejected():
    with pytest.raises(ValueError, match="limit_per_role"):
        build_role_posting_grounding([], ["Software Engineering Intern"], limit_per_role=-1)


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def neq(self, column, value):
        self.filters.append(("neq", column, value))
        return self

    def execute(self):
        data = []
        for row in self.rows:
            if all(
                (row.get(column) == value if op == "eq" else row.get(column) != value)
                for op, column, value in self.filters
            ):
                data.append(dict(row))
        return FakeResponse(data)


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        return FakeQuery(self.rows)


def test_fetch_helper_uses_read_only_filters():
    client = FakeClient(
        [
            _row("p1", "Software Engineering Intern"),
            _row("p2", "Software Engineering Intern", source="workday"),
            _row("p3", "Finance Intern"),
        ]
    )

    result = get_role_posting_grounding(client, ["Software Engineering Intern"])

    assert client.tables == ["job_postings"]
    postings = _role_block(result, "Software Engineering Intern")["postings"]
    assert [p["posting_id"] for p in postings] == ["p1"]
