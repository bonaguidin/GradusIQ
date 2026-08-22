"""Tests for the Workday adapter.

The fixture below is a real captured response from Atmos Energy's board on
2026-08-19, trimmed to one posting. That matters: unlike the Adzuna and
JSearch maps in normalize.py, this shape is observed rather than assumed, and
these tests are pinning what the endpoint actually sends.

No network. --probe is how the live shape gets re-checked.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "job_postings"))

from workday import (  # noqa: E402
    WorkdayBoard,
    describe_shape,
    listings_from,
    normalize_listing,
    parse_posted_on,
    parse_workday_slug,
    total_from,
)

# Captured live, 2026-08-19.
LIVE_LISTING = {
    "title": "Sr Applications Developer",
    "externalPath": "/job/Texas---Dallas/Sr-Applications-Developer_JR13846",
    "locationsText": "Texas - Dallas",
    "postedOn": "Posted Today",
    "bulletFields": ["JR13846"],
}
LIVE_RESPONSE = {
    "facets": [],
    "jobPostings": [LIVE_LISTING],
    "total": 44,
    "userAuthenticated": False,
}
ATMOS = WorkdayBoard("atmosenergy.wd108.myworkdayjobs.com", "atmosenergy", "External_Career_Site")


# ---------------------------------------------------------------------------
# Slug parsing -- both host layouts in the real employer list
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "slug, host, tenant, site",
    [
        ("att.wd1.myworkdayjobs.com/ATTGeneral",
         "att.wd1.myworkdayjobs.com", "att", "ATTGeneral"),
        ("atmosenergy.wd108.myworkdayjobs.com/External_Career_Site",
         "atmosenergy.wd108.myworkdayjobs.com", "atmosenergy", "External_Career_Site"),
        # The myworkdaysite layout puts the tenant in the path, not the host.
        ("wd12.myworkdaysite.com/recruiting/parklandhospital/Parkland_Careers",
         "wd12.myworkdaysite.com", "parklandhospital", "Parkland_Careers"),
        ("wd1.myworkdaysite.com/recruiting/fmr/FidelityCareers",
         "wd1.myworkdaysite.com", "fmr", "FidelityCareers"),
        # Tolerated noise.
        ("https://copart.wd12.myworkdayjobs.com/Copart/",
         "copart.wd12.myworkdayjobs.com", "copart", "Copart"),
        ("swa.wd1.myworkdayjobs.com/external?foo=bar",
         "swa.wd1.myworkdayjobs.com", "swa", "external"),
    ],
)
def test_parse_workday_slug(slug, host, tenant, site):
    board = parse_workday_slug(slug)
    assert board == WorkdayBoard(host, tenant, site)


@pytest.mark.parametrize(
    "slug",
    [
        # Every one of these is a real row in the employer CSV: a host with no
        # site segment. Seven employers are in this state.
        "ghr.wd1.myworkdayjobs.com",
        "usaa.wd1.myworkdayjobs.com",
        "capitalone.wd12.myworkdayjobs.com",
        "accenture.wd103.myworkdayjobs.com",
        "careers.example.com",
        "",
        None,
    ],
)
def test_unbuildable_slugs_return_none(slug):
    """None rather than a guessed site. Defaulting to something like 'careers'
    would 404, or succeed against a different site on the same tenant and file
    real postings under the wrong board."""
    assert parse_workday_slug(slug) is None


def test_jobs_url_is_the_cxs_endpoint():
    assert ATMOS.jobs_url == (
        "https://atmosenergy.wd108.myworkdayjobs.com"
        "/wday/cxs/atmosenergy/External_Career_Site/jobs"
    )


# ---------------------------------------------------------------------------
# Response reading
# ---------------------------------------------------------------------------

def test_reads_the_live_envelope():
    assert total_from(LIVE_RESPONSE) == 44
    assert len(listings_from(LIVE_RESPONSE)) == 1


@pytest.mark.parametrize("junk", [{}, [], None, {"error": "nope"}, "text"])
def test_envelope_readers_survive_junk(junk):
    assert total_from(junk) == 0
    assert listings_from(junk) == []


def test_normalize_the_live_listing():
    row = normalize_listing(LIVE_LISTING, ATMOS, "Atmos Energy")
    assert row["source"] == "workday"
    assert row["title"] == "Sr Applications Developer"
    assert row["company"] == "Atmos Energy"
    assert row["location"] == "Texas - Dallas"
    assert row["url"] == (
        "https://atmosenergy.wd108.myworkdayjobs.com"
        "/job/Texas---Dallas/Sr-Applications-Developer_JR13846"
    )


def test_job_id_prefers_the_requisition_number():
    """externalPath embeds the title, so it forks when a title is edited and
    one posting becomes two rows. The requisition number does not move."""
    row = normalize_listing(LIVE_LISTING, ATMOS, "Atmos Energy")
    assert row["source_job_id"] == "JR13846"


def test_job_id_falls_back_to_the_path_tail():
    listing = {k: v for k, v in LIVE_LISTING.items() if k != "bulletFields"}
    row = normalize_listing(listing, ATMOS, "Atmos Energy")
    assert row["source_job_id"] == "Sr-Applications-Developer_JR13846"


def test_empty_bulletfields_falls_back_rather_than_producing_a_blank_id():
    listing = {**LIVE_LISTING, "bulletFields": [""]}
    row = normalize_listing(listing, ATMOS, "Atmos Energy")
    assert row["source_job_id"] == "Sr-Applications-Developer_JR13846"


@pytest.mark.parametrize("missing", ["externalPath", "title"])
def test_missing_required_field_is_fatal(missing):
    listing = {k: v for k, v in LIVE_LISTING.items() if k != missing}
    with pytest.raises(ValueError, match=missing):
        normalize_listing(listing, ATMOS, "Atmos Energy")


# ---------------------------------------------------------------------------
# postedOn -- relative prose, never a timestamp
# ---------------------------------------------------------------------------

def test_posted_today():
    assert parse_posted_on("Posted Today") == date.today().isoformat()


def test_posted_yesterday():
    assert parse_posted_on("Posted Yesterday") == (date.today() - timedelta(days=1)).isoformat()


def test_posted_n_days_ago():
    assert parse_posted_on("Posted 3 Days Ago") == (date.today() - timedelta(days=3)).isoformat()


def test_posted_thirty_plus_days_is_not_a_date():
    """'30+ Days Ago' is a floor, not a date. Treating it as exact would make
    a stale posting look precisely dated."""
    assert parse_posted_on("Posted 30+ Days Ago") is None


@pytest.mark.parametrize("value", [None, "", "Posted Recently", 12345, "next tuesday"])
def test_unparseable_posted_on_is_none(value):
    assert parse_posted_on(value) is None


# ---------------------------------------------------------------------------
# Shape reporting
# ---------------------------------------------------------------------------

def test_describe_shape_reports_the_live_response():
    out = describe_shape(LIVE_RESPONSE, ATMOS)
    assert "total: 44" in out
    assert "externalPath" in out


def test_describe_shape_flags_a_missing_field():
    payload = {"jobPostings": [{"title": "A"}], "total": 1}
    assert "MISSING" in describe_shape(payload, ATMOS)
