"""Tests for data/job_postings/job_search_feed_families.yaml.

Mirrors tests/test_job_postings_config.py's checks on role_families.yaml --
same hand-edited-config failure mode (typo, drift), plus the cross-file
checks that matter because role_family_matcher.py classifies over BOTH
files' families together, not role_families.yaml alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml is a declared dependency now; see pyproject.toml")

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "data" / "job_postings"
ROLE_FAMILIES = CONFIG / "role_families.yaml"
FEED_FAMILIES = CONFIG / "job_search_feed_families.yaml"


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def role_families() -> list[dict]:
    return load(ROLE_FAMILIES)["families"]


def feed_families() -> list[dict]:
    return load(FEED_FAMILIES)["families"]


def related_families() -> dict[str, list[str]]:
    return load(FEED_FAMILIES)["related_families"]


# A feed-file block reusing one of the 14 role-family names is not a
# collision in role_family_matcher's combined list -- entries are keyed by
# (phrase, family name), so a repeated name just adds more match_phrases to
# that same family. "Embedded Systems Intern" uses this deliberately to add
# phrases role_families.yaml lacks (see job_search_feed_families.yaml's
# comment) without editing that file. Any other reused name is unintentional
# and should fail the test below.
_INTENTIONAL_NAME_REUSE = {"Embedded Systems Intern"}


def test_feed_families_do_not_reuse_role_families_names_unintentionally():
    role_names = {f["family"] for f in role_families()}
    feed_names = {f["family"] for f in feed_families()}
    overlap = role_names & feed_names
    assert overlap <= _INTENTIONAL_NAME_REUSE, (
        f"unexpected name reuse with role_families.yaml: {overlap - _INTENTIONAL_NAME_REUSE}"
    )


def test_every_feed_family_has_at_least_one_match_phrase():
    for fam in feed_families():
        assert fam.get("match_phrases"), f"{fam['family']} has no match_phrases"


def test_feed_phrases_are_lowercase():
    for fam in feed_families():
        for phrase in fam["match_phrases"] + list(fam.get("exclude_phrases") or []):
            assert phrase == phrase.lower(), f"{fam['family']}: {phrase!r} is not lowercase"


def test_feed_exclude_phrases_do_not_collide_with_own_match_phrases():
    for fam in feed_families():
        overlap = set(fam.get("exclude_phrases") or []) & set(fam["match_phrases"])
        assert not overlap, f"{fam['family']} both matches and excludes {overlap}"


def test_no_match_phrase_is_claimed_by_two_families_across_both_files():
    """Matching runs globally over role_families.yaml + this file together
    (role_family_matcher.load_all_families) -- a duplicate match_phrase
    across the two files is exactly as broken as a duplicate within one."""
    seen: dict[str, str] = {}
    for fam in role_families() + feed_families():
        for phrase in fam["match_phrases"]:
            assert phrase not in seen, (
                f"{phrase!r} claimed by both {seen.get(phrase)} and {fam['family']}"
            )
            seen[phrase] = fam["family"]


def test_related_families_keys_are_real_role_families():
    role_names = {f["family"] for f in role_families()}
    for key in related_families():
        assert key in role_names, f"{key!r} is not one of the 14 target-role families"


def test_related_families_values_are_real_families():
    """A related family must be a real family -- either one of the 14
    role families or one of this file's own feed families -- or the
    expansion silently produces a family nothing can ever classify into."""
    all_names = {f["family"] for f in role_families()} | {f["family"] for f in feed_families()}
    for key, values in related_families().items():
        for value in values:
            assert value in all_names, f"{key!r} maps to unknown family {value!r}"


def test_related_families_do_not_map_a_family_to_itself():
    for key, values in related_families().items():
        assert key not in values, f"{key!r} is related to itself"
