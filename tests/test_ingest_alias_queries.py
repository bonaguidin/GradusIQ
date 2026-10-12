"""Tests for the alias-query addition to scripts/job_postings/ingest.py
(design (v), PR 3): alias rows never carry a target_role key, stay in
their own upsert_postings() call, and the hard per-run Adzuna quota cap.

Mirrors tests/test_job_postings_clients.py's style -- scripts/job_postings
added to sys.path, no real network or database calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "job_postings"))

import ingest  # noqa: E402
from normalize import normalize_listing, normalize_response  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


class _FakeFieldMap:
    """Minimal FieldMap stand-in -- just enough for normalize_listing."""

    source = "adzuna"

    def source_job_id(self, listing):
        return listing["id"]

    def title(self, listing):
        return listing["title"]

    def company(self, listing):
        return listing.get("company", "Acme")

    def location(self, listing):
        return listing.get("location", "Dallas, TX")

    def url(self, listing):
        return listing.get("url", "https://example.com")

    def posted_date(self, listing):
        return listing.get("posted_date")

    def salary_min(self, listing):
        return None

    def salary_max(self, listing):
        return None


def _listing(job_id: str, title: str = "Software Engineering Intern") -> dict:
    """A FAKE field map shape (for direct normalize_listing calls)."""
    return {"id": job_id, "title": title, "url": f"https://example.com/{job_id}"}


def _adzuna_listing(job_id: str, title: str = "Software Engineering Intern") -> dict:
    """The REAL Adzuna field map's shape -- for normalize_response, which
    always looks up FIELD_MAPS["adzuna"] itself regardless of any fake
    passed elsewhere in this file."""
    return {
        "id": job_id,
        "title": title,
        "redirect_url": f"https://example.com/{job_id}",
        "company": {"display_name": "Acme"},
        "location": {"display_name": "Dallas, TX"},
        "created": "2026-10-01T00:00:00Z",
    }


# ---------------------------------------------------------- (1) no key at all


def test_alias_normalize_listing_omits_target_role_key_entirely():
    row = normalize_listing(_listing("job-1"), _FakeFieldMap(), target_role=None)
    assert "target_role" not in row


def test_role_normalize_listing_still_carries_target_role():
    row = normalize_listing(_listing("job-1"), _FakeFieldMap(), target_role="Software Engineering Intern")
    assert row["target_role"] == "Software Engineering Intern"


def test_alias_normalize_response_rows_all_omit_target_role():
    payload = {"results": [_adzuna_listing("job-1"), _adzuna_listing("job-2")]}
    rows, errors = normalize_response(payload, "adzuna", target_role=None)
    assert errors == []
    assert all("target_role" not in r for r in rows)


# --------------------------------------------- (2) simulated merge-upsert


def _simulate_pg_merge_upsert(table: dict, payload: list[dict]) -> None:
    """Mirrors Postgres' real `INSERT ... ON CONFLICT (source,
    source_job_id) DO UPDATE SET <declared columns> = EXCLUDED.<column>`,
    where "declared columns" is the UNION of keys across the whole
    payload list (postgrest-py's `columns=` param, confirmed by reading
    postgrest/base_request_builder.py's `_unique_columns` and
    `pre_upsert`). A column entirely absent from every row in this call
    is never declared, so an existing row's value for it survives
    untouched -- this is the mechanism the ALIAS INVARIANT relies on.
    """
    declared_columns = {k for row in payload for k in row}
    for row in payload:
        key = (row["source"], row["source_job_id"])
        existing = table.get(key, {})
        merged = dict(existing)
        for col in declared_columns:
            merged[col] = row.get(col)  # NULL if this row omitted a declared column
        table[key] = merged


def test_role_then_alias_leaves_target_role_unchanged():
    table: dict = {}
    role_row = {"source": "adzuna", "source_job_id": "job-1", "target_role": "Software Engineering Intern", "title": "x"}
    alias_row = {"source": "adzuna", "source_job_id": "job-1", "title": "x"}  # no target_role key

    _simulate_pg_merge_upsert(table, [role_row])
    _simulate_pg_merge_upsert(table, [alias_row])

    assert table[("adzuna", "job-1")]["target_role"] == "Software Engineering Intern"


def test_alias_then_role_also_leaves_target_role_as_the_role_label():
    table: dict = {}
    role_row = {"source": "adzuna", "source_job_id": "job-1", "target_role": "Software Engineering Intern", "title": "x"}
    alias_row = {"source": "adzuna", "source_job_id": "job-1", "title": "x"}

    _simulate_pg_merge_upsert(table, [alias_row])
    _simulate_pg_merge_upsert(table, [role_row])

    assert table[("adzuna", "job-1")]["target_role"] == "Software Engineering Intern"


def test_mixed_batch_in_one_call_WOULD_null_the_column_this_is_why_calls_stay_separate():
    """Negative control: proves the risk is real when rows are combined
    into ONE call, which is exactly what _assert_homogeneous_target_role
    (tested below) now refuses to let happen."""
    table: dict = {("adzuna", "job-1"): {"target_role": "Software Engineering Intern"}}
    mixed_payload = [
        {"source": "adzuna", "source_job_id": "job-1", "title": "x"},  # no target_role
        {"source": "adzuna", "source_job_id": "job-2", "target_role": "Finance Intern", "title": "y"},
    ]
    _simulate_pg_merge_upsert(table, mixed_payload)
    assert table[("adzuna", "job-1")]["target_role"] is None  # nulled -- the bug this PR avoids


# -------------------------------------------------------- (3) homogeneity guard


def test_homogeneity_guard_allows_all_role_rows():
    store = ingest.DryRunStore()
    rows = [
        {"source": "adzuna", "source_job_id": "1", "target_role": "Finance Intern"},
        {"source": "adzuna", "source_job_id": "2", "target_role": "Finance Intern"},
    ]
    store.upsert_postings(rows)  # must not raise
    assert len(store.rows) == 2


def test_homogeneity_guard_allows_all_alias_rows():
    store = ingest.DryRunStore()
    rows = [
        {"source": "adzuna", "source_job_id": "1"},
        {"source": "adzuna", "source_job_id": "2"},
    ]
    store.upsert_postings(rows)  # must not raise
    assert len(store.rows) == 2


def test_homogeneity_guard_rejects_a_mixed_batch():
    store = ingest.DryRunStore()
    rows = [
        {"source": "adzuna", "source_job_id": "1", "target_role": "Finance Intern"},
        {"source": "adzuna", "source_job_id": "2"},
    ]
    with pytest.raises(ingest.MixedTargetRoleBatchError):
        store.upsert_postings(rows)


def test_run_never_combines_alias_and_role_rows_into_one_upsert_call(monkeypatch):
    """End-to-end: run() with both roles and aliases configured must never
    trip the homogeneity guard, because each query's rows go through
    their own upsert_postings() call."""
    monkeypatch.setattr(ingest, "fetch_one", lambda *a, **k: ingest.FetchOutcome(
        source="adzuna", target_role=a[1],
        rows=[{"source": "adzuna", "source_job_id": f"role-{a[1]}", "target_role": a[1], "title": "x"}],
        results_count=1,
    ))
    monkeypatch.setattr(ingest, "fetch_alias", lambda *a, **k: ingest.FetchOutcome(
        source="adzuna", target_role=f"alias:{a[1]}",
        rows=[{"source": "adzuna", "source_job_id": f"alias-{a[1]}", "title": "x"}],
        results_count=1,
    ))
    report = ingest.run(
        sources=("adzuna",), roles=["Finance Intern", "Operations Intern"],
        live=False, write=False, page_size=5, where="Dallas", dump_shape=False,
        aliases=["AI intern"],
    )
    assert report.rows_upserted == 3  # 2 role + 1 alias, each call counted


# --------------------------------------------------------------- (4) the cap


def test_cap_refuses_before_any_call_when_planned_exceeds_it():
    with pytest.raises(ingest.AdzunaQuotaExceededError, match=r"18 planned.*cap of 5"):
        ingest.run(
            sources=("adzuna",), roles=ingest.load_target_roles(),
            live=False, write=False, page_size=5, where="Dallas", dump_shape=False,
            aliases=ingest.load_adzuna_query_aliases(), max_adzuna_calls=5,
        )


def test_cap_allows_a_run_within_the_default():
    report = ingest.run(
        sources=("adzuna",), roles=ingest.load_target_roles(),
        live=False, write=False, page_size=5, where="Dallas", dump_shape=False,
        aliases=ingest.load_adzuna_query_aliases(),
    )
    assert report is not None  # did not raise; default cap is 24, planned is 18


def test_cap_is_scoped_to_adzuna_not_workday_or_jsearch_only_runs():
    # workday has no Adzuna quota at all; a jsearch-only run (no "adzuna" in
    # sources) must not be gated by the Adzuna-specific cap either.
    report = ingest.run(
        sources=("jsearch",), roles=["Finance Intern"] * 50,
        live=False, write=False, page_size=5, where="Dallas", dump_shape=False,
        aliases=ingest.load_adzuna_query_aliases(), max_adzuna_calls=1,
    )
    assert report is not None


# ------------------------------------------------- (5) role payloads unchanged


def test_fetch_one_role_payload_is_byte_identical_to_before(monkeypatch):
    """Golden test: fetch_one itself was not touched by this PR (only a new
    sibling fetch_alias was added) -- a role query's row still carries
    target_role exactly as it always has."""
    fake_payload = {"results": [_adzuna_listing("job-99", "Software Engineering Intern")]}

    class _FakeClient:
        def search(self, **kwargs):
            assert kwargs["what"] == "Software Engineering Intern"
            return fake_payload

    monkeypatch.setattr(ingest, "build_client", lambda source: _FakeClient())
    outcome = ingest.fetch_one("adzuna", "Software Engineering Intern", live=True)
    assert outcome.status == "success"
    assert len(outcome.rows) == 1
    assert outcome.rows[0]["target_role"] == "Software Engineering Intern"
    assert outcome.rows[0]["source_job_id"] == "job-99"


# ------------------------------------------------- (6) FIT grounding unchanged


def test_fit_posting_grounding_ignores_alias_rows_entirely():
    sys.path.insert(0, str(REPO_ROOT))
    from GradusIQ_career.features.posting_provider import build_role_posting_grounding

    role_row = {
        "id": "1", "posting_identity": "c1", "company": "Acme",
        "target_role": "Software Engineering Intern", "is_dfw": True, "source": "adzuna",
        "posted_date": "2026-10-01", "fetched_at": "2026-10-01T00:00:00Z",
    }
    # An alias row for the SAME role conceptually, but with no target_role
    # at all -- exactly what fetch_alias produces.
    alias_row = {
        "id": "2", "posting_identity": "c2", "company": "Other Co",
        "is_dfw": True, "source": "adzuna",
        "posted_date": "2026-10-01", "fetched_at": "2026-10-01T00:00:00Z",
    }

    with_alias = build_role_posting_grounding(
        [role_row, alias_row], ["Software Engineering Intern"],
    )
    without_alias = build_role_posting_grounding(
        [role_row], ["Software Engineering Intern"],
    )

    assert (
        with_alias["by_role"]["Software Engineering Intern"]["available_postings"]
        == without_alias["by_role"]["Software Engineering Intern"]["available_postings"]
        == 1
    )
