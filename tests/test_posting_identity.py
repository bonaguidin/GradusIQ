"""Tests for scripts/job_postings/identity.py -- cross-source posting identity.

The corpus regression at the bottom is the one that matters most: it asserts
the exact-match premise the whole dedup design rests on, against real pulled
data rather than invented URLs. It skips when that corpus is not on disk,
because postings.csv is gitignored output and will not exist in CI.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "job_postings"))

from identity import (  # noqa: E402
    LocationKind,
    classify_location,
    exact_key,
    fuzzy_key,
    identity_keys,
    is_dfw,
    normalize_employer,
    normalize_title,
    normalize_url,
    recover_ats_id,
)

CORPUS = REPO_ROOT / "data" / "ats_fetcher" / "postings.csv"


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://Job-Boards.Greenhouse.IO/pmg/jobs/8496729002",
         "https://job-boards.greenhouse.io/pmg/jobs/8496729002"),
        ("https://job-boards.greenhouse.io/pmg/jobs/8496729002/",
         "https://job-boards.greenhouse.io/pmg/jobs/8496729002"),
        ("https://www.jobs.lever.co/matchgroup/abc",
         "https://jobs.lever.co/matchgroup/abc"),
        ("", None),
        ("   ", None),
        (None, None),
        ("not-a-url", None),
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


def test_normalize_url_drops_tracking_query():
    """Syndicator referral params are exactly what makes two links to the same
    posting look different, so they have to go."""
    a = normalize_url("https://job-boards.greenhouse.io/pmg/jobs/8496729002?utm_source=jsearch&ref=xyz")
    b = normalize_url("https://job-boards.greenhouse.io/pmg/jobs/8496729002")
    assert a == b


def test_normalize_url_drops_fragment():
    assert normalize_url("https://jobs.lever.co/matchgroup/abc#apply") == \
        "https://jobs.lever.co/matchgroup/abc"


# ---------------------------------------------------------------------------
# ATS id recovery -- the exact path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url, expected",
    [
        # Confirmed against real pulled data.
        ("https://job-boards.greenhouse.io/pmg/jobs/8496729002", ("greenhouse", "8496729002")),
        ("https://boards.greenhouse.io/acme/jobs/1234567", ("greenhouse", "1234567")),
        ("https://jobs.lever.co/matchgroup/3414ba28-35f7-45d3-8e13-35c883959635",
         ("lever", "3414ba28-35f7-45d3-8e13-35c883959635")),
        # Unconfirmed shapes -- adapters exist but have never run.
        ("https://jobs.ashbyhq.com/ramp/3414ba28-35f7-45d3-8e13-35c883959635",
         ("ashby", "3414ba28-35f7-45d3-8e13-35c883959635")),
        ("https://jobs.smartrecruiters.com/Visa/744000012345678", ("smartrecruiters", "744000012345678")),
        ("https://acme.recruitee.com/o/senior-data-analyst", ("recruitee", "senior-data-analyst")),
        # Nothing recoverable.
        ("https://www.indeed.com/viewjob?jk=abc123", None),
        ("https://job-boards.greenhouse.io/pmg", None),
        ("https://jobs.lever.co/matchgroup/not-a-uuid", None),
        (None, None),
        ("", None),
    ],
)
def test_recover_ats_id(url, expected):
    assert recover_ats_id(url) == expected


def test_recover_ats_id_survives_tracking_params():
    """A vendor link wrapped in referral params still yields the board's id --
    this is the whole mechanism by which a syndicated listing matches the row
    already fetched from the ATS directly."""
    direct = recover_ats_id("https://job-boards.greenhouse.io/pmg/jobs/8496729002")
    syndicated = recover_ats_id(
        "https://job-boards.greenhouse.io/pmg/jobs/8496729002?utm_campaign=adzuna&src=feed"
    )
    assert direct == syndicated == ("greenhouse", "8496729002")


def test_exact_key_is_none_without_recoverable_id():
    assert exact_key("https://www.indeed.com/viewjob?jk=abc") is None
    assert exact_key("https://job-boards.greenhouse.io/pmg/jobs/8496729002") == \
        "ats:greenhouse:8496729002"


# ---------------------------------------------------------------------------
# Employer normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Match Group", "match group"),
        ("Match Group, Inc.", "match group"),
        ("Match Group LLC", "match group"),
        ("PMG", "pmg"),
        ("Toyota Motor North America, Inc.", "toyota motor north america"),
        ("Peña Systems", "pena systems"),
        ("  Acme   Corp  ", "acme"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_employer(raw, expected):
    assert normalize_employer(raw) == expected


# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------

def test_normalize_title_unifies_seniority_spellings():
    """One job spelled two ways must collapse."""
    assert normalize_title("Sr. Data Analyst") == normalize_title("Senior Data Analyst")
    assert normalize_title("Jr Developer") == normalize_title("Junior Developer")


def test_normalize_title_keeps_seniority_levels_distinct():
    """Two different openings must NOT collapse.

    This is the correction to DEDUP.md §3.2, which originally said to strip
    seniority markers outright. At one employer "Data Analyst" and "Senior Data
    Analyst" are plausibly two real jobs, and merging them undercounts.
    """
    assert normalize_title("Data Analyst") != normalize_title("Senior Data Analyst")
    assert normalize_title("Engineer II") != normalize_title("Engineer III")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Data Analyst (R12345)", "data analyst"),
        ("Data Analyst #98765", "data analyst"),
        ("Data Analyst req 44412", "data analyst"),
        ("Data Analyst (Dallas, TX)", "data analyst"),
        ("Data Analyst (Dallas, TX) (Remote)", "data analyst"),
        ("Data Analyst [Hybrid]", "data analyst"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_title_strips_noise(raw, expected):
    assert normalize_title(raw) == expected


def test_normalize_title_preserves_meaningful_parentheticals_mid_string():
    """Only a TRAILING aside is dropped. One in the middle may be load-bearing."""
    assert "python" in normalize_title("Engineer (Python) - Platform")


# ---------------------------------------------------------------------------
# DFW bucketing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "location, expected",
    [
        ("Dallas, TX", True),
        ("Fort Worth, Texas", True),
        ("Plano, TX", True),
        ("Dallas, TX; New York, NY", True),      # real shape from the corpus
        ("New York, New York", False),
        ("Seoul, South Korea", False),
        ("Remote", False),
        ("Remote - US", False),
        ("Work from home", False),
        ("", False),
        (None, False),
    ],
)
def test_is_dfw(location, expected):
    assert is_dfw(location) is expected


def test_is_dfw_named_locality_beats_remote():
    """'Remote (Dallas, TX)' is a DFW posting."""
    assert is_dfw("Remote (Dallas, TX)") is True


@pytest.mark.parametrize(
    "location, verdict, kind",
    [
        ("Dallas, TX", True, LocationKind.DFW_METRO),
        ("Plano, TX", True, LocationKind.DFW_METRO),
        ("Dallas, TX; New York, NY", True, LocationKind.MULTI_INCLUDES_DFW),
        ("Hybrid - Dallas, TX", True, LocationKind.HYBRID_DFW),
        ("Austin, TX", False, LocationKind.TEXAS_NON_DFW),
        ("Houston, Texas", False, LocationKind.TEXAS_NON_DFW),
        ("Remote - US", False, LocationKind.REMOTE_US),
        ("Remote (Nationwide)", False, LocationKind.REMOTE_US),
        ("Remote", False, LocationKind.REMOTE_ANYWHERE),
        ("Work from home", False, LocationKind.REMOTE_ANYWHERE),
        ("Seoul, South Korea", False, LocationKind.NON_DFW),
        ("", False, LocationKind.UNKNOWN),
        (None, False, LocationKind.UNKNOWN),
    ],
)
def test_classify_location(location, verdict, kind):
    assert classify_location(location) == (verdict, kind)


def test_classify_location_verdict_agrees_with_is_dfw():
    """is_dfw is a thin wrapper; the two must never disagree."""
    for location in ["Dallas, TX", "Austin, TX", "Remote", "", None, "Hybrid - Plano"]:
        assert classify_location(location)[0] is is_dfw(location)


def test_remote_is_false_but_recoverable():
    """The whole reason location_kind exists: the remote call is reversible.

    Remote roles are excluded today, and if that decision flips, the kind is
    what makes it a query instead of a re-pull.
    """
    remote_kinds = {LocationKind.REMOTE_US, LocationKind.REMOTE_ANYWHERE}
    for location in ["Remote", "Remote - US", "Fully remote, USA"]:
        verdict, kind = classify_location(location)
        assert verdict is False
        assert kind in remote_kinds


def test_is_dfw_does_not_match_substrings_of_other_words():
    """Token matching, not naive substring search -- 'Allentown' is not 'Allen'."""
    assert is_dfw("Allentown, PA") is False


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

def test_fuzzy_key_is_none_when_underspecified():
    """A key built from nothing would collide with every other empty row."""
    assert fuzzy_key(None, "Data Analyst", True) is None
    assert fuzzy_key("Match Group", None, True) is None
    assert fuzzy_key("", "", True) is None


def test_fuzzy_key_separates_dfw_buckets():
    assert fuzzy_key("Acme", "Data Analyst", True) != fuzzy_key("Acme", "Data Analyst", False)
    assert fuzzy_key("Acme", "Data Analyst", None) != fuzzy_key("Acme", "Data Analyst", True)


def test_identity_keys_returns_exact_first():
    posting = {
        "url": "https://job-boards.greenhouse.io/pmg/jobs/8496729002",
        "company": "PMG",
        "title": "Affiliate Marketing Lead",
        "location": "Dallas, TX",
    }
    exact, fuzzy = identity_keys(posting)
    assert exact == "ats:greenhouse:8496729002"
    assert fuzzy is not None


def test_identity_keys_derives_is_dfw_when_absent():
    posting = {"url": None, "company": "Acme", "title": "Analyst", "location": "Plano, TX"}
    _, fuzzy = identity_keys(posting)
    assert fuzzy is not None and fuzzy.endswith(":dfw")


# ---------------------------------------------------------------------------
# Regression against the real corpus
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CORPUS.exists(), reason="postings.csv is gitignored output")
def test_every_real_posting_url_recovers_its_stored_external_id():
    """The premise the exact-match dedup path depends on, checked end to end.

    If this ever fails, DEDUP.md §3.1 has stopped being true for some board and
    those postings are silently falling back to fuzzy matching.
    """
    with CORPUS.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert rows, "corpus present but empty"
    mismatches = [
        (r["ats"], r["external_id"], r["url"], recover_ats_id(r["url"]))
        for r in rows
        if recover_ats_id(r["url"]) != (r["ats"], r["external_id"])
    ]
    assert not mismatches, f"{len(mismatches)} of {len(rows)} failed: {mismatches[:5]}"


@pytest.mark.skipif(not CORPUS.exists(), reason="postings.csv is gitignored output")
def test_real_corpus_locations_all_classify():
    """Every real posting carries a usable location, so none should land in
    UNKNOWN. One that does means the string shape is unhandled, not that the
    posting is genuinely locationless."""
    with CORPUS.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    unknown = {
        r["location"] for r in rows
        if classify_location(r["location"])[1] is LocationKind.UNKNOWN
    }
    assert not unknown, f"unclassified locations: {sorted(unknown)[:10]}"
