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

import workday  # noqa: E402
from ingest import (  # noqa: E402
    CLUSTERS_TABLE,
    KEYS_TABLE,
    POSTINGS_TABLE,
    UPSERT_CONFLICT,
    DryRunStore,
    FetchOutcome,
    RunReport,
    SupabaseStore,
    dedupe_by_conflict_key,
    gc_empty_clusters,
    load_target_roles,
    resolve_and_attach_identity,
    run_workday,
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


def test_adzuna_empty_company_normalizes_to_none_not_empty_string():
    """Regression: Adzuna returns company.display_name = "" (not an absent
    key) when it has no employer to report -- confirmed live on the Computer
    Engineering Intern pull that produced distinct_employers=0. An empty
    string is not None to anything downstream that checks identity/falsiness
    against None specifically (fuzzy_key's `if not employer_key` catches it,
    but employer-counting code that checks `is None` would not)."""
    listing = {**ADZUNA_LISTING, "company": {"display_name": ""}}
    row = normalize_listing(listing, ADZUNA, target_role="Finance Intern")
    assert row["company"] is None


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


def _workday_identity_row(employer: str, requisition: str) -> dict:
    return {
        "source": "workday",
        "source_job_id": requisition,
        "url": f"https://example.wd1.myworkdayjobs.com/job/x/Engineer_{requisition}",
        "company": employer,
        "title": "Software Engineering Intern",
        "location": "Dallas, TX",
    }


def test_workday_different_requisitions_do_not_fuzzy_merge():
    rows = [
        _workday_identity_row("Copart", "JR109672"),
        _workday_identity_row("Copart", "JR111173"),
    ]
    store, report = DryRunStore(), RunReport(started_at=datetime.now(timezone.utc), dry_run=True)

    resolve_and_attach_identity(rows, store, report)

    assert rows[0]["posting_identity"] != rows[1]["posting_identity"]
    assert report.clusters_created == 2
    assert report.clusters_matched_fuzzy == 0


def test_workday_same_requisition_converges():
    rows = [
        _workday_identity_row("Copart", "JR109672"),
        _workday_identity_row("Copart", "JR109672"),
    ]
    store, report = DryRunStore(), RunReport(started_at=datetime.now(timezone.utc), dry_run=True)

    resolve_and_attach_identity(rows, store, report)

    assert rows[0]["posting_identity"] == rows[1]["posting_identity"]
    assert report.clusters_created == 1
    assert report.clusters_matched_exact == 1


def test_workday_requisition_id_is_employer_scoped():
    rows = [
        _workday_identity_row("Copart", "JR109672"),
        _workday_identity_row("Parkland Health", "JR109672"),
    ]
    store, report = DryRunStore(), RunReport(started_at=datetime.now(timezone.utc), dry_run=True)

    resolve_and_attach_identity(rows, store, report)

    assert rows[0]["posting_identity"] != rows[1]["posting_identity"]
    assert report.clusters_created == 2


def test_rekeyed_row_with_sole_membership_adopts_its_old_cluster():
    """Regression for the cluster-departure leak (planning-docs context, and
    see resolve_and_attach_identity's docstring): a row's exact-key algorithm
    changes (e.g. Workday's commit 2c76894, which moved it off fuzzy keying),
    so a row ingested nightly under an old fuzzy key suddenly computes a
    brand-new exact key nobody has seen. Before the adoption fix this
    abandoned the row's old cluster -- its sole member -- which is exactly how
    the orphaned posting_clusters rows check_integrity.py flags were produced.

    Simulated directly against DryRunStore's internals (store.clusters,
    store.remember_identity) rather than by monkeypatching identity_keys,
    since the scenario is "this row's computed key changed since last night",
    not anything identity_keys() would compute differently within one call.
    """
    store = DryRunStore()
    report = RunReport(started_at=datetime.now(timezone.utc), dry_run=True)

    # Night 1 (pre-fix): the row landed under a fuzzy key only, as an old
    # cluster's sole member.
    old_cluster_id = "dry-cluster-old"
    store.clusters["fuzzy:acme:software engineering intern:dfw"] = old_cluster_id
    store.remember_identity("workday", "R123", old_cluster_id)

    # Night 2 (post-fix): the same row now computes an exact key that has
    # never been seen, and Workday rows never emit a fuzzy key at all -- both
    # exact_hit and fuzzy_hit miss.
    row = _workday_identity_row("Acme", "R123")

    resolve_and_attach_identity([row], store, report)

    assert row["posting_identity"] == old_cluster_id
    assert row["_match_rule"] == "adopted"
    assert report.clusters_created == 0
    assert report.clusters_adopted == 1
    # The new exact key now also resolves to the adopted cluster, so the next
    # ingest finds it by exact match rather than repeating the adoption.
    assert store.find_cluster("ats:workday:acme:R123") == old_cluster_id
    # The old fuzzy key is gone -- left live, it would let an unrelated
    # posting that merely shares this employer/title text fuzzy-merge into a
    # cluster an exact id now anchors to one specific requisition.
    assert "fuzzy:acme:software engineering intern:dfw" not in store.clusters
    keys_for_cluster = [k for k, v in store.clusters.items() if v == old_cluster_id]
    assert keys_for_cluster == ["ats:workday:acme:R123"]


def test_adopted_cluster_no_longer_fuzzy_matches_a_later_adzuna_row():
    """The cross-source merge exposure Step 1 flagged: without dropping the
    old fuzzy key, a later Adzuna row for the same employer/title/dfw bucket
    would fuzzy-hit the adopted cluster on weak evidence, even though an
    exact Workday requisition id now anchors it to one specific job."""
    store = DryRunStore()
    report = RunReport(started_at=datetime.now(timezone.utc), dry_run=True)

    old_cluster_id = "dry-cluster-old"
    store.clusters["fuzzy:acme:software engineering intern:dfw"] = old_cluster_id
    store.remember_identity("workday", "R123", old_cluster_id)

    row = _workday_identity_row("Acme", "R123")
    resolve_and_attach_identity([row], store, report)
    assert row["posting_identity"] == old_cluster_id  # adopted, per the test above

    later_adzuna = {
        "source": "adzuna", "source_job_id": "a1",
        "url": "https://www.adzuna.com/land/ad/555",
        "company": "Acme", "title": "Software Engineering Intern",
        "location": "Dallas, TX",
    }
    resolve_and_attach_identity([later_adzuna], store, report)

    assert later_adzuna["posting_identity"] != old_cluster_id
    assert later_adzuna["_match_rule"] == "seed"
    assert report.clusters_matched_fuzzy == 0


def test_rekeyed_row_with_siblings_still_mints_a_new_cluster():
    """Same re-keying scenario as above, but the row's old cluster has
    ANOTHER member that is not this row. Adopting would wrongly absorb a
    still-valid sibling posting with no evidence they are the same job, so
    the old (safe) create_cluster behavior must be preserved here."""
    store = DryRunStore()
    report = RunReport(started_at=datetime.now(timezone.utc), dry_run=True)

    old_cluster_id = "dry-cluster-old"
    store.clusters["fuzzy:acme:software engineering intern:dfw"] = old_cluster_id
    store.remember_identity("workday", "R123", old_cluster_id)
    store.remember_identity("workday", "R999", old_cluster_id)  # a real sibling

    row = _workday_identity_row("Acme", "R123")

    resolve_and_attach_identity([row], store, report)

    assert row["posting_identity"] != old_cluster_id
    assert row["_match_rule"] == "seed"
    assert report.clusters_created == 1
    assert report.clusters_adopted == 0


def test_keyless_posting_gets_per_posting_fallback_key():
    row = {
        "source": "adzuna",
        "source_job_id": "5858325305",
        "url": "https://www.adzuna.com/details/5858325305",
        "company": None,
        "title": "Field Engineer Intern",
        "location": "Dallas, TX",
    }
    store, report = DryRunStore(), RunReport(started_at=datetime.now(timezone.utc), dry_run=True)

    resolve_and_attach_identity([row], store, report)

    assert store.find_cluster("posting:adzuna:5858325305") == row["posting_identity"]


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


# ---------------------------------------------------------------------------
# run_workday -- the (source x employer) driver
# ---------------------------------------------------------------------------

def _wd_row(job_id: str, location: str, company: str = "Atmos Energy") -> dict:
    """A row shaped like workday.normalize_listing() output."""
    return {
        "source": "workday",
        "source_job_id": job_id,
        "title": f"Analyst {job_id}",
        "company": company,
        "location": location,
        "url": f"https://atmosenergy.wd108.myworkdayjobs.com/job/x/Analyst_{job_id}",
        "posted_date": "2026-08-19",
        "salary_min": None,
        "salary_max": None,
        "raw_payload": {"externalPath": f"/job/x/Analyst_{job_id}"},
    }


@pytest.fixture
def one_atmos_board(monkeypatch):
    board = workday.WorkdayBoard(
        "atmosenergy.wd108.myworkdayjobs.com", "atmosenergy", "External_Career_Site"
    )
    monkeypatch.setattr(
        workday, "usable_workday_boards", lambda: [("Atmos Energy", board, False)]
    )
    return board


def test_run_workday_keeps_dfw_rows_and_drops_the_rest(monkeypatch, one_atmos_board):
    fetched = [
        _wd_row("JR1", "Texas - Dallas"),      # keep
        _wd_row("JR2", "Plano, TX"),           # keep
        _wd_row("JR3", "Atlanta, GA"),         # drop -- non-DFW
        _wd_row("JR4", "2 Locations"),         # drop -- no locality to match
        _wd_row("JR5", "Remote - US"),         # drop -- remote, no DFW anchor
    ]
    monkeypatch.setattr(workday, "fetch_board", lambda *a, **k: (fetched, []))

    store = DryRunStore()
    report = run_workday(live=True, write=False, store=store)

    kept = {r["source_job_id"] for r in store.rows}
    assert kept == {"JR1", "JR2"}
    assert all(r["is_dfw"] is True for r in store.rows)
    assert {r["location_kind"] for r in store.rows} == {"dfw_metro"}
    assert report.rows_upserted == 2


def test_run_workday_always_dfw_keeps_facility_string_rows(monkeypatch):
    """Parkland's locationsText is a building name with no city token, so
    classify_location returns non-DFW. always_dfw=True keeps it anyway and
    labels it dfw_metro."""
    board = workday.WorkdayBoard("wd12.myworkdaysite.com", "parklandhospital",
                                 "Parkland_Careers")
    monkeypatch.setattr(
        workday, "usable_workday_boards",
        lambda: [("Parkland Health", board, True)],
    )
    fetched = [
        _wd_row("JR1", "Main Hospital Bldg - 1st Flr"),   # no city token
        _wd_row("JR2", "Moody Outpatient Center"),        # no city token
        _wd_row("JR3", "Southeast Dallas Health Ctr"),    # has "dallas"
    ]
    monkeypatch.setattr(workday, "fetch_board", lambda *a, **k: (fetched, []))

    store = DryRunStore()
    run_workday(live=True, write=False, store=store)

    assert {r["source_job_id"] for r in store.rows} == {"JR1", "JR2", "JR3"}
    assert all(r["is_dfw"] is True for r in store.rows)
    assert {r["location_kind"] for r in store.rows} == {"dfw_metro"}


def test_run_workday_without_always_dfw_drops_the_same_facility_rows(monkeypatch):
    """Same rows, always_dfw=False -> the two city-less strings are dropped,
    only the one naming a DFW suburb survives."""
    board = workday.WorkdayBoard("wd12.myworkdaysite.com", "parklandhospital",
                                 "Parkland_Careers")
    monkeypatch.setattr(
        workday, "usable_workday_boards",
        lambda: [("Parkland Health", board, False)],
    )
    fetched = [
        _wd_row("JR1", "Main Hospital Bldg - 1st Flr"),
        _wd_row("JR2", "Moody Outpatient Center"),
        _wd_row("JR3", "Southeast Dallas Health Ctr"),
    ]
    monkeypatch.setattr(workday, "fetch_board", lambda *a, **k: (fetched, []))

    store = DryRunStore()
    run_workday(live=True, write=False, store=store)

    assert {r["source_job_id"] for r in store.rows} == {"JR3"}


def test_run_workday_stamps_target_role_null(monkeypatch, one_atmos_board):
    monkeypatch.setattr(
        workday, "fetch_board", lambda *a, **k: ([_wd_row("JR1", "Dallas, TX")], [])
    )
    store = DryRunStore()
    run_workday(live=True, write=False, store=store)
    assert store.rows[0]["target_role"] is None


def test_run_workday_fetch_log_is_employer_keyed_and_satisfies_has_subject(
    monkeypatch, one_atmos_board
):
    # 45 listings seen -> ceil(45/20) = 3 pages -> quota_used proxy = 3.
    rows = [_wd_row(f"JR{i}", "Dallas, TX") for i in range(45)]
    monkeypatch.setattr(workday, "fetch_board", lambda *a, **k: (rows, []))

    store = DryRunStore()
    run_workday(live=True, write=False, store=store)

    assert len(store.log_rows) == 1
    log = store.log_rows[0]
    assert log["source"] == "workday"
    assert log["employer"] == "Atmos Energy"
    assert log["target_role"] is None
    # job_posting_fetch_log_has_subject: target_role IS NOT NULL OR employer IS NOT NULL
    assert (log["target_role"] is not None) or (log["employer"] is not None)
    assert log["status"] == "success"
    assert log["quota_used"] == 3


def test_run_workday_one_employer_store_failure_does_not_abort_the_sweep(monkeypatch):
    """A DB write error for one employer must be caught, logged, and the
    remaining employers still processed -- same catch-log-continue posture as
    a fetch_board failure. Regression for the 2026-08-30 crash, where an
    upsert error propagated and killed the whole sweep partway through."""
    boards = [
        ("Alpha", workday.WorkdayBoard("a.wd1.myworkdayjobs.com", "a", "S"), False),
        ("Bravo", workday.WorkdayBoard("b.wd1.myworkdayjobs.com", "b", "S"), False),
        ("Charlie", workday.WorkdayBoard("c.wd1.myworkdayjobs.com", "c", "S"), False),
    ]
    monkeypatch.setattr(workday, "usable_workday_boards", lambda: boards)
    monkeypatch.setattr(
        workday, "fetch_board",
        lambda board, employer, *, live: ([_wd_row(f"{employer}-1", "Dallas, TX",
                                                   company=employer)], []),
    )

    class FlakyStore(DryRunStore):
        def upsert_postings(self, rows):
            if rows and rows[0]["company"] == "Bravo":
                raise RuntimeError("simulated DB write failure")
            return super().upsert_postings(rows)

    store = FlakyStore()
    report = run_workday(live=True, write=False, store=store)

    assert {(o.employer, o.status) for o in report.outcomes} == {
        ("Alpha", "success"), ("Bravo", "error"), ("Charlie", "success"),
    }
    assert {r["source_job_id"] for r in store.rows} == {"Alpha-1", "Charlie-1"}
    assert len(store.log_rows) == 3   # every employer logged, Bravo included
    bravo = next(l for l in store.log_rows if l["employer"] == "Bravo")
    assert bravo["status"] == "error"
    assert "simulated DB write failure" in bravo["error_detail"]


def test_run_workday_records_a_failed_board_without_aborting_the_sweep(monkeypatch):
    good = workday.WorkdayBoard("a.wd1.myworkdayjobs.com", "a", "S")
    bad = workday.WorkdayBoard("b.wd1.myworkdayjobs.com", "b", "S")
    monkeypatch.setattr(
        workday, "usable_workday_boards",
        lambda: [("Bad Co", bad, False), ("Good Co", good, False)],
    )

    def fake_fetch_board(board, employer, *, live):
        if employer == "Bad Co":
            from errors import JobPostingRequestError

            raise JobPostingRequestError("Workday HTTP 503", transient=True)
        return ([_wd_row("JR9", "Irving, TX")], [])

    monkeypatch.setattr(workday, "fetch_board", fake_fetch_board)

    store = DryRunStore()
    report = run_workday(live=True, write=False, store=store)

    statuses = {(o.employer, o.status) for o in report.outcomes}
    assert statuses == {("Bad Co", "error"), ("Good Co", "success")}
    assert {r["source_job_id"] for r in store.rows} == {"JR9"}
    assert len(store.log_rows) == 2  # both boards logged


def test_run_workday_dry_run_writes_nothing(monkeypatch, one_atmos_board):
    # live=False: workday.fetch_board returns ([], []) and prints the request.
    monkeypatch.setattr(workday, "fetch_board", lambda *a, **k: ([], []))
    store = DryRunStore()
    report = run_workday(live=False, write=False, store=store)
    assert store.rows == []
    assert store.log_rows == []
    assert report.rows_upserted == 0


def test_run_workday_does_not_touch_the_vendor_fetch_log_payload():
    """Adzuna/JSearch log rows must stay byte-identical -- no employer key."""
    vendor = FetchOutcome(source="adzuna", target_role="Finance Intern",
                          results_count=3, quota_used=1)
    assert "employer" not in vendor.log_row()
    wd = FetchOutcome(source="workday", employer="Atmos Energy", results_count=3)
    assert wd.log_row()["employer"] == "Atmos Energy"
    assert wd.log_row()["target_role"] is None


# ---------------------------------------------------------------------------
# Batch de-dupe -- one requisition posted at N locations must not 21000
# ---------------------------------------------------------------------------

def test_dedupe_by_conflict_key_keeps_first_seen():
    rows = [
        {"source": "workday", "source_job_id": "R1", "location": "Frisco"},
        {"source": "workday", "source_job_id": "R1", "location": "Plano"},   # dup
        {"source": "workday", "source_job_id": "R2", "location": "Dallas"},
        {"source": "workday", "source_job_id": "R1", "location": "Irving"},  # dup
    ]
    out = dedupe_by_conflict_key(rows)
    assert [(r["source_job_id"], r["location"]) for r in out] == [
        ("R1", "Frisco"), ("R2", "Dallas"),
    ]


def test_dedupe_is_scoped_by_source_not_just_job_id():
    rows = [
        {"source": "workday", "source_job_id": "R1"},
        {"source": "adzuna", "source_job_id": "R1"},  # same id, different source -> kept
    ]
    assert len(dedupe_by_conflict_key(rows)) == 2


class _FakeUpsertClient:
    """Captures the payload handed to .upsert(on_conflict=...).execute()."""
    def __init__(self):
        self.upsert_payload = None
        self.upsert_on_conflict = None

    def table(self, _name):
        return self

    def upsert(self, payload, on_conflict=None):
        self.upsert_payload = payload
        self.upsert_on_conflict = on_conflict
        return self

    def execute(self):
        return type("R", (), {"data": self.upsert_payload})()


def test_supabase_upsert_never_sends_a_duplicate_conflict_key():
    """Regression for the 2026-08-30 crash: a batch where one requisition
    repeats (open at several store locations) must reach PostgREST with no
    (source, source_job_id) appearing twice -- otherwise Postgres raises
    21000 'ON CONFLICT DO UPDATE cannot affect row a second time' and the
    whole sweep aborts."""
    store = SupabaseStore.__new__(SupabaseStore)   # skip __init__ / real client
    store.client = _FakeUpsertClient()
    store._cluster_cache = {}

    batch = [
        {"source": "workday", "source_job_id": "R00323100-1", "title": "PT Merch Mgr",
         "location": loc, "_match_rule": "seed"}
        for loc in ("Frisco", "Plano", "Irving", "Denton", "Arlington")
    ] + [
        {"source": "workday", "source_job_id": "R00319440-1", "title": "Stocker",
         "location": "Southlake"},
    ]

    written = store.upsert_postings(batch)

    payload = store.client.upsert_payload
    assert store.client.upsert_on_conflict == UPSERT_CONFLICT
    keys = [(r["source"], r["source_job_id"]) for r in payload]
    assert len(keys) == len(set(keys)) == 2      # 5 Michaels dups collapsed to 1
    assert written == 2
    assert all("_match_rule" not in r for r in payload)   # private keys still stripped
    assert all("fetched_at" in r for r in payload)


def test_supabase_upsert_serializes_date_values_for_postgrest():
    """A normalized Python date must not survive to the JSON request body."""
    store = SupabaseStore.__new__(SupabaseStore)
    store.client = _FakeUpsertClient()
    store._cluster_cache = {}

    store.upsert_postings([
        {
            "source": "adzuna",
            "source_job_id": "5874456703",
            "title": "Software Engineer Intern",
            "posted_date": date(2026, 9, 7),
            "raw_payload": {"created": "2026-09-07T16:16:21Z"},
        }
    ])

    assert store.client.upsert_payload[0]["posted_date"] == "2026-09-07"


# ---------------------------------------------------------------------------
# gc_empty_clusters -- the orphaned-cluster backstop
# ---------------------------------------------------------------------------

class _FakeGcTable:
    """One table handle. Supports the chains gc_empty_clusters actually
    issues: select().order().range() (paginated read, page 1 only since these
    tests never exceed 1000 rows), select().in_() (filtered read), and
    delete().in_() (filtered delete, applied to the backing list)."""

    def __init__(self, client: "_FakeGcClient", name: str):
        self.client = client
        self.name = name
        self._in_col: str | None = None
        self._in_values: set | None = None
        self._deleting = False

    def select(self, _cols):
        return self

    def order(self, _col):
        return self

    def range(self, _start, _end):
        return self

    def in_(self, col, values):
        self._in_col = col
        self._in_values = set(values)
        return self

    def delete(self):
        self._deleting = True
        return self

    def _rows(self) -> list[dict]:
        return {
            CLUSTERS_TABLE: self.client.clusters,
            POSTINGS_TABLE: self.client.postings,
            KEYS_TABLE: self.client.keys,
        }[self.name]

    def execute(self):
        rows = self._rows()
        if self._in_values is not None:
            matched = [r for r in rows if r.get(self._in_col) in self._in_values]
        else:
            matched = list(rows)

        if self._deleting:
            self.client.deletes.append((self.name, self._in_col, set(self._in_values or [])))
            kept = [r for r in rows if r.get(self._in_col) not in (self._in_values or set())]
            if self.name == CLUSTERS_TABLE:
                self.client.clusters = kept
            elif self.name == KEYS_TABLE:
                self.client.keys = kept
            return type("R", (), {"data": None})()

        return type("R", (), {"data": matched})()


class _FakeGcClient:
    def __init__(self, *, clusters: list[dict], postings: list[dict], keys: list[dict]):
        self.clusters = list(clusters)
        self.postings = list(postings)
        self.keys = list(keys)
        self.deletes: list[tuple[str, str, set]] = []

    def table(self, name):
        return _FakeGcTable(self, name)


def test_gc_empty_clusters_dry_run_reports_but_touches_nothing():
    clusters = [{"id": "c-empty-1"}, {"id": "c-empty-2"}, {"id": "c-has-member"}]
    postings = [{"id": "p1", "posting_identity": "c-has-member"}]
    keys = [
        {"key": "fuzzy:x", "cluster_id": "c-empty-1"},
        {"key": "ats:workday:x:1", "cluster_id": "c-empty-2"},
        {"key": "ats:workday:y:2", "cluster_id": "c-has-member"},
    ]
    client = _FakeGcClient(clusters=clusters, postings=postings, keys=keys)

    report = gc_empty_clusters(dry_run=True, client=client)

    assert sorted(report.empty_cluster_ids) == ["c-empty-1", "c-empty-2"]
    assert sorted(report.orphaned_key_ids) == ["ats:workday:x:1", "fuzzy:x"]
    assert client.deletes == []
    assert len(client.clusters) == 3
    assert len(client.keys) == 3


def test_gc_empty_clusters_never_selects_a_cluster_with_a_member():
    """The HALT condition this task's diagnostics called out: selecting
    anything with a member row would mean the zero-member query is wrong."""
    clusters = [{"id": "c-has-member"}]
    postings = [{"id": "p1", "posting_identity": "c-has-member"}]
    keys = [{"key": "ats:workday:y:2", "cluster_id": "c-has-member"}]
    client = _FakeGcClient(clusters=clusters, postings=postings, keys=keys)

    report = gc_empty_clusters(dry_run=True, client=client)

    assert report.empty_cluster_ids == []
    assert report.orphaned_key_ids == []


def test_gc_empty_clusters_live_deletes_keys_before_clusters_and_spares_members():
    clusters = [{"id": "c-empty-1"}, {"id": "c-has-member"}]
    postings = [{"id": "p1", "posting_identity": "c-has-member"}]
    keys = [
        {"key": "fuzzy:x", "cluster_id": "c-empty-1"},
        {"key": "ats:workday:y:2", "cluster_id": "c-has-member"},
    ]
    client = _FakeGcClient(clusters=clusters, postings=postings, keys=keys)

    report = gc_empty_clusters(dry_run=False, client=client)

    assert report.empty_cluster_ids == ["c-empty-1"]
    assert report.orphaned_key_ids == ["fuzzy:x"]
    # Keys deleted before clusters -- a crash mid-run leaves an unreachable
    # but intact cluster, never a key pointing at nothing.
    assert [d[0] for d in client.deletes] == [KEYS_TABLE, CLUSTERS_TABLE]
    assert client.clusters == [{"id": "c-has-member"}]
    assert client.keys == [{"key": "ats:workday:y:2", "cluster_id": "c-has-member"}]
