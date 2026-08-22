"""Tests for the hand-edited config under data/job_postings/.

These files are edited by people, not generated, so the failure mode is a
typo or a drift from the fourteen target roles rather than a logic bug. That
is what these pin.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

yaml = pytest.importorskip(
    "yaml", reason="pyyaml is not a declared dependency yet -- see data/job_postings/README.md"
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "data" / "job_postings"
ROLE_FAMILIES = CONFIG / "role_families.yaml"
SKILL_ALIASES = CONFIG / "skill_aliases.yaml"
ROLE_REQUIREMENTS = REPO_ROOT / "data" / "role_requirements.json"


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def target_roles() -> list[str]:
    with ROLE_REQUIREMENTS.open(encoding="utf-8") as f:
        return [k for k in json.load(f) if k != "_notes"]


# ---------------------------------------------------------------------------
# role_families.yaml
# ---------------------------------------------------------------------------

def test_families_are_exactly_the_target_roles():
    """The whole point of the 2026-08-19 rewrite.

    A family string that is not a key in role_requirements.json produces
    postings that FIT and GAP can never retrieve, because they key off that
    file. The previous version used a mid-career taxonomy and overlapped by
    roughly five.
    """
    families = [f["family"] for f in load(ROLE_FAMILIES)["families"]]
    assert sorted(families) == sorted(target_roles())


def test_no_phrase_is_claimed_by_two_families():
    """Longest-phrase-first cannot arbitrate a literal tie, so a duplicate
    silently hands the posting to whichever family is iterated first."""
    seen: dict[str, str] = {}
    for fam in load(ROLE_FAMILIES)["families"]:
        for phrase in fam["match_phrases"]:
            assert phrase not in seen, (
                f"{phrase!r} claimed by both {seen.get(phrase)} and {fam['family']}"
            )
            seen[phrase] = fam["family"]


def test_every_family_has_at_least_one_phrase():
    for fam in load(ROLE_FAMILIES)["families"]:
        assert fam.get("match_phrases"), f"{fam['family']} has no match_phrases"


def test_phrases_are_lowercase():
    """normalize_title() casefolds before matching, so an uppercase phrase is
    dead config that can never fire."""
    for fam in load(ROLE_FAMILIES)["families"]:
        for phrase in fam["match_phrases"] + list(fam.get("exclude_phrases") or []):
            assert phrase == phrase.lower(), f"{fam['family']}: {phrase!r} is not lowercase"


def test_no_phrase_carries_a_seniority_word():
    """Spec §6 keeps level out of the family, and normalize_title() collapses
    Sr./Senior/II/III before matching -- so a phrase containing one is dead
    config that looks alive."""
    seniority = {"senior", "sr", "sr.", "junior", "jr", "jr.", "lead",
                 "principal", "staff", " ii", " iii", " iv"}
    for fam in load(ROLE_FAMILIES)["families"]:
        for phrase in fam["match_phrases"]:
            low = f" {phrase} "
            for word in seniority:
                assert f" {word} " not in low, f"{fam['family']}: {phrase!r} contains {word!r}"


def test_exclude_phrases_do_not_collide_with_own_match_phrases():
    """A family excluding something it also matches can never fire that rule."""
    for fam in load(ROLE_FAMILIES)["families"]:
        overlap = set(fam.get("exclude_phrases") or []) & set(fam["match_phrases"])
        assert not overlap, f"{fam['family']} both matches and excludes {overlap}"


# ---------------------------------------------------------------------------
# skill_aliases.yaml
# ---------------------------------------------------------------------------

def test_canonical_names_are_unique():
    names = [s["canonical"] for s in load(SKILL_ALIASES)["skills"]]
    assert len(names) == len(set(names))


def test_every_skill_has_aliases():
    for skill in load(SKILL_ALIASES)["skills"]:
        assert skill.get("aliases"), f"{skill['canonical']} has no aliases"


def test_canonical_appears_among_its_own_aliases_or_is_deliberately_absent():
    """Epic and Node.js deliberately exclude their bare canonical form, because
    'epic collaboration' and 'Node' are too collision-prone. Every other skill
    should be findable by its own name."""
    deliberate = {"Epic", "Node.js", "Social Media Marketing"}
    for skill in load(SKILL_ALIASES)["skills"]:
        name = skill["canonical"]
        if name in deliberate:
            continue
        lowered = {a.lower() for a in skill["aliases"]}
        assert name.lower() in lowered, f"{name} is not among its own aliases"


def test_no_alias_is_claimed_by_two_skills():
    """A shared alias makes matching order decide the answer."""
    seen: dict[str, str] = {}
    for skill in load(SKILL_ALIASES)["skills"]:
        for alias in skill["aliases"]:
            key = alias.lower()
            assert key not in seen, (
                f"{alias!r} claimed by both {seen.get(key)} and {skill['canonical']}"
            )
            seen[key] = skill["canonical"]


def test_the_harvested_skills_are_present():
    """Seven skills came from the corpus evidence; the other 114 fired terms
    were collisions. Pinned so a later edit does not quietly drop them."""
    names = {s["canonical"] for s in load(SKILL_ALIASES)["skills"]}
    assert {"Google Analytics", "Adobe Analytics", "Google Ads",
            "Social Media Marketing", "Epic", "Figma", "Node.js"} <= names


def test_no_alias_is_a_bare_collision_prone_token():
    """The generated vocabulary failed because terms like 'Vision', 'Shape'
    and 'MAGIC' match ordinary prose. Nothing that short and generic should
    reach this file."""
    banned = {"epic", "node", "vision", "shape", "magic", "impact", "client",
              "training", "testing", "sales", "legal", "dental"}
    for skill in load(SKILL_ALIASES)["skills"]:
        for alias in skill["aliases"]:
            assert alias.lower() not in banned, (
                f"{skill['canonical']} carries collision-prone alias {alias!r}"
            )
