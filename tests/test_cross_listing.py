"""Tests for course_discovery/cross_listing.py.

courses_are_cross_listed() is built on the real, on-disk TAMU catalog data
(LocalCatalogRepository, data/catalog/**/*.json) rather than synthetic
CourseCatalogRecord fixtures, because the whole point of this utility is to
answer correctly against the actual catalog's cross_listings field -- a
mocked record could pass while the real data shape (two separate rows, one
per department, each carrying the other in its own cross_listings list)
still breaks the resolver.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from GradusIQ_career.course_discovery.catalog import LocalCatalogRepository
from GradusIQ_career.course_discovery.cross_listing import (
    courses_are_cross_listed,
    cross_listing_map,
)
from GradusIQ_career.course_discovery.models import CatalogInstitution

CATALOG_ROOT = Path(__file__).resolve().parents[1] / "data" / "catalog"


@pytest.fixture(scope="module")
def repo():
    return LocalCatalogRepository()


def _all_tamu_cross_listed_pairs():
    """Every (code, partner) pair across the real TAMU catalog JSON, read
    directly from disk -- independent of LocalCatalogRepository's own
    parsing, so a sample drawn from here is a check against the source data,
    not a tautological check against the same loader under test.

    Paired as (this row's own code, a listed partner), not as arbitrary
    combinations across a row's whole cross_listings list: some rows list
    partner department codes (e.g. HIST 377's cross_listings names AFST 377
    and WGST 377) that have no catalog row of their own in this snapshot --
    real, but not independently resolvable, and not what
    courses_are_cross_listed is meant to answer. Anchoring on the row's own
    code guarantees each pair is genuinely checkable: that code's row is the
    one we just read the partner out of.
    """
    pairs: set[tuple[str, str]] = set()
    for path in CATALOG_ROOT.rglob("*.json"):
        if "requirements_" in path.name or "tamu" == path.parent.name:
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            code = row.get("code")
            if not code:
                continue
            for partner in row.get("cross_listings") or []:
                if partner and partner != code:
                    pairs.add((code, partner))
    return sorted(pairs)


def test_cross_listed_pair_detected_regardless_of_lookup_order(repo):
    assert courses_are_cross_listed(repo, CatalogInstitution.TAMU, "CSCE 222", "ECEN 222") is True
    assert courses_are_cross_listed(repo, CatalogInstitution.TAMU, "ECEN 222", "CSCE 222") is True


def test_non_cross_listed_pair_is_not_flagged(repo):
    # CSCE 121 and MATH 251 are both real TAMU courses, unrelated departments,
    # no cross-listing between them.
    assert courses_are_cross_listed(repo, CatalogInstitution.TAMU, "CSCE 121", "MATH 251") is False


def test_identical_code_is_not_flagged_as_cross_listed_with_itself(repo):
    # This function answers "is B an alias of A", not "is B the same string
    # as A" -- callers already have a cheaper exact-match check for that.
    assert courses_are_cross_listed(repo, CatalogInstitution.TAMU, "CSCE 222", "CSCE 222") is False


def test_unknown_code_on_either_side_is_not_flagged(repo):
    assert courses_are_cross_listed(repo, CatalogInstitution.TAMU, "CSCE 222", "ZZZZ 9999") is False
    assert courses_are_cross_listed(repo, CatalogInstitution.TAMU, "ZZZZ 9999", "CSCE 222") is False


def test_case_and_whitespace_variation_still_resolves(repo):
    assert courses_are_cross_listed(repo, CatalogInstitution.TAMU, "csce222", "ecen 222") is True


@pytest.mark.parametrize(
    "code_a,code_b",
    [
        ("ENGR 216", "PHYS 216"),
        ("CVEN 301", "EVEN 301"),
        ("CSCE 350", "ECEN 350"),
        ("BICH 101", "GENE 101"),
        ("HIST 212", "RELS 212"),
        ("COMM 302", "JOUR 302"),
        ("ASTR 109", "PHYS 109"),
        ("MATH 424", "STAT 424"),
        ("CYBR 466", "ECEN 466"),
        ("SOCI 207", "WGST 207"),
    ],
)
def test_a_sample_of_real_tamu_pairs_beyond_csce_222_ecen_222(repo, code_a, code_b):
    assert courses_are_cross_listed(repo, CatalogInstitution.TAMU, code_a, code_b) is True


def test_every_real_tamu_cross_listed_pair_resolves(repo):
    """Confirms the utility against the full real sample (300 pairs as of
    this session), not just the ten spot-checked above -- catches a resolver
    bug that happens to dodge the hand-picked sample."""
    pairs = _all_tamu_cross_listed_pairs()
    assert len(pairs) >= 250, "sanity check: the real catalog sample shrank unexpectedly"
    failures = [
        pair for pair in pairs
        if not courses_are_cross_listed(repo, CatalogInstitution.TAMU, pair[0], pair[1])
    ]
    assert failures == []


def test_cross_listing_map_matches_the_pairwise_check(repo):
    mapping = cross_listing_map(repo, CatalogInstitution.TAMU)
    assert mapping["CSCE 222"] == ["ECEN 222"]
    assert mapping["ECEN 222"] == ["CSCE 222"]
    assert "CSCE 121" not in mapping

    # No code lists itself as its own partner.
    for code, partners in mapping.items():
        assert code not in partners
