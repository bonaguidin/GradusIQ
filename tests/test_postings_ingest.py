"""Tests for the postings ingest -- normalization, identity wiring, retention.

No network and no database anywhere in here. The vendor payloads below are
fixtures shaped like each vendor's documented response, which is the same
basis the field maps in normalize.py were written from -- so these tests prove
the maps are internally consistent and fail loudly when a field is absent.
They do NOT prove the maps match what the vendors really send. Only a live
call can do that; see normalize.py's header.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "job_postings"))

from ingest import (  # noqa: E402
    DryRunStore,
    RunReport,
    load_target_roles,
    resolve_and_attach_identity,
)
from normalize import (  # noqa: E402
    ADZUNA,
    JSEARCH,
    NormalizationError,
    describe_shape,
    normalize_listing,
    normalize_response,
)
from retention import cutoff_for  # noqa: E402


ADZUNA_LISTING = {
    "id": "4812345678",
    "title": "Finance Intern",
    "company": {"display_name": "Toyota Motor North America"},
    "location": {"display_name": "Plano, Texas"},
    "redirect_url": "https://www.adzuna.com/land/ad/4812345678",
    "created": "2026-08-11T09:14:00Z",
    "description": "Support the FP&A team with reporting and reconciliation.",
    "salary_min": 42000,
    "salary_max": 55000,
}

JSEARCH_LISTING = {
    "job_id": "abc123XYZ",
    "job_title": "Software Engineering Intern",
    "employer_name": "Match Group",
    "job_city": "Dallas",
    "job_state": "TX",
    "job_country": "US",
    "job_apply_link": "https://jobs.lever.co/matchgroup/3414ba28-35f7-45d3-8e13-35c883959635",
    "job_posted_at_datetime_utc": "2026-08-09T00:00:00.000Z",
    "job_description": "Build and ship features with the platform team.",
    "job_min_salary": None,
    "job_max_salary": None,
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_adzuna_listing_normalizes():
    row = normalize_listing(ADZUNA_LISTING, ADZUNA, target_role="Finance Intern")
    assert row["source"] == "adzuna"
    assert row["source_job_id"] == "4812345678"
    assert row["company"] == "Toyota Motor North America"
    assert row["location"] == "Plano, Texas"
    assert row["posted_date"] == date(2026, 8, 11)
    assert row["is_dfw"] is True
    assert row["location_kind"] == "dfw_metro"
    assert row["raw_payload"] is ADZUNA_LISTING


def test_jsearch_listing_normalizes_and_joins_location():
    row = normalize_listing(JSEARCH_LISTING, JSEARCH, target_role="Software Engineering Intern")
    assert row["source"] == "jsearch"
    assert row["location"] == "Dallas, TX, US"
    assert row["is_dfw"] is True
    assert row["salary_min"] is None


def test_source_job_id_is_stringified():
    """Adzuna hands back a number, JSearch a string. The column is text, and a
    type mismatch here would fork the upsert key."""
    row = normalize_listing({**ADZUNA_LISTING, "id": 4812345678}, ADZUNA, target_role="X")
    assert row["source_job_id"] == "4812345678"


def test_missing_url_is_fatal_not_silent():
    """A row with no URL cannot be exact-matched or spot-checked, and nothing
    downstream would look wrong. So it must fail here."""
    listing = {**ADZUNA_LISTING}
    del listing["redirect_url"]
    with pytest.raises(NormalizationError, match="url"):
        normalize_listing(listing, ADZUNA, target_role="Finance Intern")


@pytest.mark.parametrize("missing", ["id", "title"])
def test_other_required_fields_are_fatal(missing):
    listing = {k: v for k, v in ADZUNA_LISTING.items() if k != missing}
    with pytest.raises(NormalizationError):
        normalize_listing(listing, ADZUNA, target_role="Finance Intern")


def test_error_message_names_the_unverified_field_map():
    """The message has to point at the likely cause, since a wrong map is far
    more probable than a genuinely malformed listing."""
    listing = {k: v for k, v in ADZUNA_LISTING.items() if k != "title"}
    with pytest.raises(NormalizationError, match="unverified"):
        normalize_listing(listing, ADZUNA, target_role="Finance Intern")


def test_inverted_salary_is_swapped_not_rejected():
    row = normalize_listing(
        {**ADZUNA_LISTING, "salary_min": 90000, "salary_max": 50000},
        ADZUNA,
        target_role="Finance Intern",
    )
    assert (row["salary_min"], row["salary_max"]) == (50000.0, 90000.0)


def test_unparseable_date_becomes_none_rather_than_raising():
    row = normalize_listing({**ADZUNA_LISTING, "created": "sometime last week"},
                            ADZUNA, target_role="X")
    assert row["posted_date"] is None


def test_normalize_response_isolates_one_bad_listing():
    """One malformed listing must not discard a page that cost a call."""
    payload = {"results": [ADZUNA_LISTING, {"id": "no-title-here"}]}
    rows, errors = normalize_response(payload, "adzuna", target_role="Finance Intern")
    assert len(rows) == 1
    assert len(errors) == 1


def test_normalize_response_rejects_an_unexpected_envelope():
    with pytest.raises(NormalizationError, match="no 'results' key|has no"):
        normalize_response({"jobs": []}, "adzuna", target_role="X")


def test_describe_shape_flags_missing_fields():
    out = describe_shape({"results": [{"id": "1"}]}, "adzuna")
    assert "MISSING" in out and "title" in out


# ---------------------------------------------------------------------------
# Identity wiring
# ---------------------------------------------------------------------------

def test_same_job_from_two_sources_lands_in_one_cluster():
    """The whole point. A JSearch listing whose apply link is a Lever URL must
    join the row already ingested from Lever directly, not start its own."""
    from_ats = {
        "source": "lever",
        "url": "https://jobs.lever.co/matchgroup/3414ba28-35f7-45d3-8e13-35c883959635",
        "company": "Match Group",
        "title": "Software Engineering Intern",
        "location": "Dallas, TX",
    }
    from_vendor = {
        "source": "jsearch",
        # Same posting, wrapped in a syndicator's tracking params.
        "url": "https://jobs.lever.co/matchgroup/3414ba28-35f7-45d3-8e13-35c883959635?utm_source=jsearch",
        "company": "Match Group",
        "title": "Software Engineering Intern",
        "location": "Dallas, TX",
    }
    store = DryRunStore()
    report = RunReport(started_at=datetime.now(timezone.utc), dry_run=True)

    resolve_and_attach_identity([from_ats], store, report)
    resolve_and_attach_identity([from_vendor], store, report)

    assert from_ats["posting_identity"] == from_vendor["posting_identity"]
    assert report.clusters_created == 1
    assert report.clusters_matched_exact == 1


def test_genuinely_different_jobs_get_separate_clusters():
    rows = [
        {"source": "adzuna", "url": "https://www.adzuna.com/land/ad/1",
         "company": "Acme", "title": "Finance Intern", "location": "Dallas, TX"},
        {"source": "adzuna", "url": "https://www.adzuna.com/land/ad/2",
         "company": "Acme", "title": "Senior Finance Analyst", "location": "Dallas, TX"},
    ]
    store, report = DryRunStore(), RunReport(started_at=datetime.now(timezone.utc), dry_run=True)
    resolve_and_attach_identity(rows, store, report)
    assert rows[0]["posting_identity"] != rows[1]["posting_identity"]
    assert report.clusters_created == 2


def test_fuzzy_path_actually_clusters():
    """Two vendor-native listings for one job, neither carrying an ATS link.

    Worth its own test because the first cut of SupabaseStore returned None for
    every fuzzy key, so this path created a new cluster every time while the
    dict-backed test double happily passed.
    """
    a = {"source": "adzuna", "url": "https://www.adzuna.com/land/ad/111",
         "company": "Toyota Motor North America, Inc.", "title": "Finance Intern (R4412)",
         "location": "Plano, TX"}
    b = {"source": "jsearch", "url": "https://www.linkedin.com/jobs/view/999",
         "company": "Toyota Motor North America", "title": "Finance Intern",
         "location": "Plano, Texas"}
    store, report = DryRunStore(), RunReport(started_at=datetime.now(timezone.utc), dry_run=True)
    resolve_and_attach_identity([a], store, report)
    resolve_and_attach_identity([b], store, report)

    assert a["posting_identity"] == b["posting_identity"]
    assert report.clusters_matched_fuzzy == 1
    assert report.clusters_created == 1


def test_late_ats_row_merges_two_clusters():
    """DEDUP.md §5. A vendor delivers first and lands in a fuzzy cluster; the
    employer's own feed surfaces the job later, and that row's recovered ATS id
    is the evidence the two clusters are one."""
    vendor_first = {
        "source": "adzuna", "url": "https://www.adzuna.com/land/ad/222",
        "company": "PMG", "title": "Affiliate Marketing Lead", "location": "Dallas, TX",
    }
    store, report = DryRunStore(), RunReport(started_at=datetime.now(timezone.utc), dry_run=True)
    resolve_and_attach_identity([vendor_first], store, report)

    # A different vendor listing that DOES carry the Greenhouse link, seeding
    # an exact-keyed cluster separate from the fuzzy one above.
    syndicated = {
        "source": "jsearch",
        "url": "https://job-boards.greenhouse.io/pmg/jobs/8496729002",
        "company": "Someone Else", "title": "Different Title", "location": "Dallas, TX",
    }
    resolve_and_attach_identity([syndicated], store, report)
    assert syndicated["posting_identity"] != vendor_first["posting_identity"]

    # Now the ATS row itself: exact key hits the syndicated cluster, fuzzy key
    # hits the vendor one. Two clusters, one job.
    ats_row = {
        "source": "greenhouse",
        "url": "https://job-boards.greenhouse.io/pmg/jobs/8496729002",
        "company": "PMG", "title": "Affiliate Marketing Lead", "location": "Dallas, TX",
    }
    resolve_and_attach_identity([ats_row], store, report)

    assert report.clusters_merged == 1
    assert store.merges[0]["match_rule"] == "ats_url_id"
    assert store.find_cluster("ats:greenhouse:8496729002") == ats_row["posting_identity"]
    # The absorbed cluster's keys now point at the survivor.
    assert store.clusters[
        [k for k in store.clusters if k.startswith("fuzzy:pmg")][0]
    ] == ats_row["posting_identity"]


def test_ats_row_becomes_canonical_over_a_vendor_row():
    """The ATS row is the employer's own feed -- unrewritten title, real date."""
    store, report = DryRunStore(), RunReport(started_at=datetime.now(timezone.utc), dry_run=True)
    vendor = {"source": "adzuna", "source_job_id": "v1",
              "url": "https://job-boards.greenhouse.io/pmg/jobs/8496729002?src=adzuna",
              "company": "PMG", "title": "Affiliate Marketing Lead", "location": "Dallas, TX"}
    resolve_and_attach_identity([vendor], store, report)
    cluster = vendor["posting_identity"]
    assert store.canonical[cluster][0] == "adzuna"

    ats = {"source": "greenhouse", "source_job_id": "8496729002",
           "url": "https://job-boards.greenhouse.io/pmg/jobs/8496729002",
           "company": "PMG", "title": "Affiliate Marketing Lead", "location": "Dallas, TX"}
    resolve_and_attach_identity([ats], store, report)
    assert store.canonical[cluster] == ("greenhouse", "8496729002")


def test_vendor_row_never_displaces_an_ats_canonical():
    store, report = DryRunStore(), RunReport(started_at=datetime.now(timezone.utc), dry_run=True)
    ats = {"source": "lever", "source_job_id": "3414ba28-35f7-45d3-8e13-35c883959635",
           "url": "https://jobs.lever.co/matchgroup/3414ba28-35f7-45d3-8e13-35c883959635",
           "company": "Match Group", "title": "SWE Intern", "location": "Dallas, TX"}
    resolve_and_attach_identity([ats], store, report)
    cluster = ats["posting_identity"]

    later_vendor = {"source": "jsearch", "source_job_id": "j9",
                    "url": "https://jobs.lever.co/matchgroup/3414ba28-35f7-45d3-8e13-35c883959635?utm=x",
                    "company": "Match Group", "title": "SWE Intern", "location": "Dallas, TX"}
    resolve_and_attach_identity([later_vendor], store, report)
    assert store.canonical[cluster][0] == "lever"


def test_exact_match_is_preferred_over_fuzzy():
    """Evidence must beat inference: a recovered ATS id decides the cluster
    even when a fuzzy key would have matched something else."""
    ats_row = {
        "source": "greenhouse",
        "url": "https://job-boards.greenhouse.io/pmg/jobs/8496729002",
        "company": "PMG", "title": "Affiliate Marketing Lead", "location": "Dallas, TX",
    }
    store, report = DryRunStore(), RunReport(started_at=datetime.now(timezone.utc), dry_run=True)
    resolve_and_attach_identity([ats_row], store, report)

    syndicated = {
        "source": "adzuna",
        "url": "https://job-boards.greenhouse.io/pmg/jobs/8496729002?src=adzuna",
        "company": "PMG Inc.",              # different rendering
        "title": "Affiliate Marketing Lead (Dallas, TX)",  # different rendering
        "location": "Dallas-Fort Worth",    # different rendering
    }
    resolve_and_attach_identity([syndicated], store, report)

    assert syndicated["posting_identity"] == ats_row["posting_identity"]
    assert syndicated["_match_rule"] == "ats_url_id"


# ---------------------------------------------------------------------------
# Roles and retention
# ---------------------------------------------------------------------------

def test_target_roles_come_from_the_existing_file():
    """A second role list would produce postings nothing can retrieve."""
    roles = load_target_roles()
    assert len(roles) == 14
    assert "_notes" not in roles
    assert "Software Engineering Intern" in roles


def test_retention_cutoff_is_the_requested_window():
    now = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    assert cutoff_for(90, now=now) == now - timedelta(days=90)


def test_retention_window_must_be_positive():
    """A zero or negative window would null every payload in the table."""
    for bad in (0, -1):
        with pytest.raises(ValueError):
            cutoff_for(bad)
