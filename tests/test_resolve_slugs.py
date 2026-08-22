"""Tests for slug candidate generation and the worksheet.

No network. The live probe is deliberately untested here -- it exists to talk
to five third-party services, and a test that did so would be a slow, flaky
way to assert someone else's uptime.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "job_postings"))

from resolve_slugs import ATS_PROBES, candidate_slugs, render_worksheet  # noqa: E402


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "employer, domain, expected",
    [
        # The only two slugs anyone has actually confirmed. If generation stops
        # producing these, it has regressed against real evidence.
        ("Match Group", "mtch.com", "matchgroup"),
        ("PMG", None, "pmg"),
    ],
)
def test_known_slugs_are_generated(employer, domain, expected):
    assert expected in candidate_slugs(employer, domain)


def test_full_name_is_tried_before_the_suffix_stripped_one():
    """Match Group's real slug keeps the word 'Group'.

    Treating Group/Holdings as legal suffixes and dropping them is the same
    mistake identity.py's employer normalizer had -- there it merged two
    companies, here it would silently miss a live board.
    """
    cands = candidate_slugs("Match Group", "mtch.com")
    assert cands.index("matchgroup") < cands.index("match")


def test_domain_root_comes_first():
    """An employer picks one identifier and reuses it, so the domain beats
    anything derived from the display name."""
    assert candidate_slugs("Charles Schwab", "schwab.com")[0] == "schwab"


def test_www_is_stripped_from_the_domain():
    assert candidate_slugs("Acme", "www.acme.com")[0] == "acme"


def test_punctuation_is_removed():
    assert "mrcoopergroup" in candidate_slugs("Mr. Cooper Group", None)


def test_candidates_are_deduplicated_and_ordered():
    cands = candidate_slugs("Acme", "acme.com")
    assert len(cands) == len(set(cands))


def test_no_domain_still_produces_candidates():
    assert candidate_slugs("Texas Instruments", None)


def test_empty_employer_does_not_crash():
    assert candidate_slugs("", None) == []


def test_short_first_word_is_not_offered_alone():
    """A three-letter fragment matches too many unrelated boards to be worth a
    request, and a wrong board is worse than an unfetched one."""
    assert "ibm" not in candidate_slugs("IBM Global Services", None)[1:]


# ---------------------------------------------------------------------------
# Probe definitions
# ---------------------------------------------------------------------------

def test_every_ats_builds_both_urls():
    for probe in ATS_PROBES:
        assert probe.careers_url("acme").startswith("https://")
        assert probe.api_url("acme").startswith("https://")


def test_recruitee_puts_the_slug_in_the_hostname():
    """Which is why a wrong Recruitee slug is a DNS failure, not a 404."""
    recruitee = next(p for p in ATS_PROBES if p.name == "recruitee")
    assert recruitee.api_url("acme").startswith("https://acme.recruitee.com")


def test_recruitee_is_probed_last():
    assert ATS_PROBES[-1].name == "recruitee"


@pytest.mark.parametrize(
    "name, payload, expected",
    [
        ("greenhouse", {"jobs": [{"title": "A"}, {"title": "B"}]}, 2),
        ("lever", [{"text": "A"}], 1),
        ("ashby", {"jobs": [{"title": "A"}]}, 1),
        ("smartrecruiters", {"totalFound": 7, "content": []}, 7),
        ("recruitee", {"offers": [{"title": "A"}, {"title": "B"}]}, 2),
    ],
)
def test_counts_read_each_vendors_envelope(name, payload, expected):
    probe = next(p for p in ATS_PROBES if p.name == name)
    assert probe.count(payload) == expected


@pytest.mark.parametrize("probe", ATS_PROBES, ids=lambda p: p.name)
def test_counts_survive_an_unexpected_shape(probe):
    """A miss returns whatever the host felt like sending. It must read as
    zero rather than raising and aborting the sweep."""
    for junk in ({}, [], {"error": "not found"}, None):
        assert probe.count(junk) == 0


# ---------------------------------------------------------------------------
# Worksheet
# ---------------------------------------------------------------------------

def _row(**kw):
    base = {"name": "Acme", "domain": "acme.com", "priority": 1,
            "ats_platform": None, "slug": None, "notes": None}
    base.update(kw)
    return base


def test_worksheet_lists_every_employer():
    out = render_worksheet([_row(name="Acme"), _row(name="Beta", priority=2)])
    assert "### Acme" in out and "### Beta" in out


def test_worksheet_groups_by_priority():
    out = render_worksheet([_row(priority=2, name="Two"), _row(priority=1, name="One")])
    assert out.index("Priority 1") < out.index("Priority 2")


def test_worksheet_handles_unset_priority():
    out = render_worksheet([_row(priority=None)])
    assert "(unset)" in out


def test_worksheet_surfaces_an_already_known_ats():
    out = render_worksheet([_row(name="Match Group", ats_platform="lever")])
    assert "already recorded" in out and "lever" in out


def test_worksheet_carries_the_notes_through():
    out = render_worksheet([_row(notes="Enterprise HCM likely")])
    assert "Enterprise HCM likely" in out


def test_worksheet_warns_that_a_wrong_slug_beats_a_blank_one():
    out = render_worksheet([_row()])
    assert "wrong slug is worse" in out.lower()


def test_worksheet_tells_the_reader_to_record_none():
    """Otherwise an employer on Workday gets researched repeatedly."""
    out = render_worksheet([_row()])
    assert "`none`" in out
