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

import workday  # noqa: E402
from workday import (  # noqa: E402
    MAX_PAGES,
    WorkdayBoard,
    describe_shape,
    fetch_board,
    listings_from,
    normalize_listing,
    parse_posted_on,
    parse_workday_slug,
    total_from,
    usable_workday_boards,
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


def test_job_id_is_the_post_underscore_segment_of_the_path():
    """externalPath is '<title-slug>_<REQ>'; the REQ is what stays put when a
    title is edited. Unchanged for the Atmos fixture (no '-n' suffix)."""
    row = normalize_listing(LIVE_LISTING, ATMOS, "Atmos Energy")
    assert row["source_job_id"] == "JR13846"


def test_job_id_ignores_bulletfields_even_when_present():
    """bulletFields layout is board-specific and must not be trusted: Michaels
    puts the US state at [0] and the real req at [2]. Regression for the
    source_job_id='Texas' crash -- 70+ rows collapsing onto one upsert key."""
    michaels_listing = {
        "title": "PT Merchandise Manager",
        "externalPath": "/job/Frisco-5255-Eldorado-Pkwy/PT-Merchandise-Manager_R00323100-1",
        "locationsText": "Frisco-5255 Eldorado Pkwy",
        "postedOn": "Posted Today",
        "bulletFields": ["Texas", "United States; Country; Frisco; Texas", "R00323100"],
    }
    board = WorkdayBoard("michaels.wd5.myworkdayjobs.com", "michaels", "External")
    row = normalize_listing(michaels_listing, board, "Michaels")
    assert row["source_job_id"] == "R00323100-1"        # from the URL, not "Texas"


def test_job_id_keeps_the_whole_tail_when_there_is_no_underscore():
    listing = {**LIVE_LISTING, "externalPath": "/job/Somewhere/Plain-Title-Slug"}
    row = normalize_listing(listing, ATMOS, "Atmos Energy")
    assert row["source_job_id"] == "Plain-Title-Slug"


@pytest.mark.parametrize("req", ["R-120761-1", "R-2026-70969", "JR-019450"])
def test_job_id_preserves_hyphenated_requisition_numbers(req):
    """Split is on '_', not '-': reqs contain hyphens."""
    listing = {**LIVE_LISTING, "externalPath": f"/job/Dallas-Texas/Some-Role_{req}"}
    row = normalize_listing(listing, ATMOS, "Atmos Energy")
    assert row["source_job_id"] == req


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


# ---------------------------------------------------------------------------
# Pagination -- fetch_board loops offset until `total`, capped by max_pages
# ---------------------------------------------------------------------------

def _page(n_items: int, total: int) -> dict:
    return {
        "total": total,
        "jobPostings": [
            {
                "title": f"Role {i}",
                "externalPath": f"/job/Texas---Dallas/Role-{i}_JR{i:05d}",
                "locationsText": "Texas - Dallas",
                "postedOn": "Posted Today",
                "bulletFields": [f"JR{i:05d}"],
            }
            for i in range(n_items)
        ],
    }


def test_max_pages_is_generous_enough_for_the_largest_verified_board():
    """Michaels reported 2,000 and AT&T 1,409 postings on 2026-08-19. At
    PAGE_SIZE=20 those need 100 and 71 pages; the cap must clear them with
    headroom so a real board is never silently truncated."""
    assert MAX_PAGES * workday.PAGE_SIZE >= 5000


def test_fetch_board_pages_through_to_total(monkeypatch):
    # 3 full pages then a short one: 65 postings across a 65-total board.
    pages = [_page(20, 65), _page(20, 65), _page(20, 65), _page(5, 65)]
    calls: list[int] = []

    def fake_fetch_page(board, *, offset=0, limit=workday.PAGE_SIZE):
        calls.append(offset)
        return pages[len(calls) - 1]

    monkeypatch.setattr(workday, "fetch_page", fake_fetch_page)
    monkeypatch.setattr(workday.time, "sleep", lambda *_: None)

    rows, errors = fetch_board(ATMOS, "Atmos Energy", live=True)

    assert len(rows) == 65
    assert errors == []
    assert calls == [0, 20, 40, 60]  # stopped once offset >= total, no 5th call


def test_fetch_board_respects_the_max_pages_cap(monkeypatch):
    # A board that never reports a usable `total` would loop forever without
    # the cap. Force it: every page is full and `total` stays huge.
    def fake_fetch_page(board, *, offset=0, limit=workday.PAGE_SIZE):
        return _page(20, 10**9)

    monkeypatch.setattr(workday, "fetch_page", fake_fetch_page)
    monkeypatch.setattr(workday.time, "sleep", lambda *_: None)

    rows, _ = fetch_board(ATMOS, "Atmos Energy", live=True, max_pages=3)

    assert len(rows) == 60  # exactly max_pages * PAGE_SIZE, then it stops


# ---------------------------------------------------------------------------
# usable_workday_boards -- the CSV rows the ingest actually sweeps
# ---------------------------------------------------------------------------

def test_usable_workday_boards_are_the_eighteen_with_a_site_path():
    boards = usable_workday_boards()
    names = {name for name, _, _ in boards}

    # Updated 2026-09-30: 6 of the original 7 host-only rows got a verified
    # site-path segment (Bank of America, Comerica, USAA, Capital One, PwC,
    # Accenture -- see dfw_employers_ats.csv's notes column for each). Globe
    # Life remains unresolved -- no confirmed site, and no confirmed
    # Workday ATS at all -- so it's still excluded.
    assert len(boards) == 18
    assert {
        "Fidelity Investments", "AT&T", "Toyota Motor North America", "Solera",
        "Vistra Energy", "Atmos Energy", "Parkland Health", "McKesson",
        "Southwest Airlines", "Kimberly-Clark", "Michaels", "Copart",
        "Bank of America", "Comerica", "USAA", "Capital One", "PwC", "Accenture",
    } == names
    assert "Globe Life" not in names


def test_usable_workday_boards_returns_real_board_objects():
    boards = usable_workday_boards()
    atmos = next(b for name, b, _ in boards if name == "Atmos Energy")
    assert atmos.jobs_url == (
        "https://atmosenergy.wd108.myworkdayjobs.com"
        "/wday/cxs/atmosenergy/External_Career_Site/jobs"
    )


def test_usable_workday_boards_flags_parkland_always_dfw_and_no_one_else():
    flags = {name: always_dfw for name, _, always_dfw in usable_workday_boards()}
    assert flags["Parkland Health"] is True
    assert all(v is False for k, v in flags.items() if k != "Parkland Health")
