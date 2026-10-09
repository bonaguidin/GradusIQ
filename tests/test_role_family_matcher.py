"""Tests for scripts/job_postings/role_family_matcher.py.

The matching algorithm (longest phrase first, exclude_phrases scoped to the
family that declares them, no match -> None) was previously only documented
in role_families.yaml's header and pinned structurally by
tests/test_job_postings_config.py -- nothing ever executed it. These pin
the actual behavior against real titles, including the exact boundary
cases this feature's scoping measurement surfaced.
"""

from __future__ import annotations

from scripts.job_postings.role_family_matcher import (
    classify_title,
    expand_families,
    load_all_families,
    load_feed_families,
)

FAMILIES = load_all_families()


def test_classifies_an_exact_role_families_phrase():
    assert classify_title("Software Engineering Intern", FAMILIES) == "Software Engineering Intern"


def test_classifies_a_feed_only_family():
    assert classify_title("AI Engineering Intern (Python & Agentic AI)", FAMILIES) == "AI/ML Intern"
    assert classify_title("Data Engineer Intern", FAMILIES) == "Data Engineering Intern"
    assert classify_title("Site Reliability Engineer Intern", FAMILIES) == "QA/SDET/SRE Intern"


def test_longest_phrase_wins_across_both_files():
    """CE's own 'digital design intern' (role_families.yaml) is shorter than
    the feed-only 'digital design engineering intern' -- a title containing
    both strings must resolve to the longer, more specific one."""
    title = "Digital Design Engineering Intern"
    assert classify_title(title, FAMILIES) == "Design Engineering Intern"


def test_exclude_phrase_suppresses_only_its_own_family():
    """'Sales Engineer Intern' is Software Engineering Intern's own exclude.
    It must not match that family, and must not match anything else either,
    since no other family's match_phrases claim it."""
    assert classify_title("Sales Engineer Intern", FAMILIES) is None


def test_design_engineering_excludes_catch_a_compound_title():
    """'Site Design Engineering Intern' contains the Design Engineering
    match phrase 'design engineering intern' AND the short exclude fragment
    'site design' -- confirmed against a real Adzuna sample title. The
    exclude must win even though it is shorter than the match."""
    assert classify_title("Site Design Engineering Intern", FAMILIES) is None


def test_design_engineering_exclude_fragments_do_not_block_real_matches():
    assert classify_title("IC Design Engineering Intern", FAMILIES) == "Design Engineering Intern"
    assert classify_title("Digital IC Design Engineering Intern - Bachelors", FAMILIES) == (
        "Design Engineering Intern"
    )


def test_bare_qa_without_engineering_is_excluded():
    assert classify_title("Quality Assurance Intern", FAMILIES) is None
    assert classify_title("Quality Control Intern", FAMILIES) is None


def test_qa_engineering_intern_still_matches_despite_the_bare_qa_exclude():
    """The QA exclude requires 'assurance'/'control' directly followed by
    'intern' with no 'engineering' between -- it must not also suppress the
    engineering-qualified match_phrases."""
    assert classify_title("Quality Assurance Engineering Intern", FAMILIES) == "QA/SDET/SRE Intern"


def test_no_match_returns_none():
    assert classify_title("Senior Accountant", FAMILIES) is None
    assert classify_title(None, FAMILIES) is None
    assert classify_title("", FAMILIES) is None


def test_seniority_and_punctuation_do_not_block_a_match():
    assert classify_title("Sr. Software Engineering Intern", FAMILIES) == "Software Engineering Intern"


def test_expand_families_adds_related_families_without_duplicates():
    _, related = load_feed_families()
    expanded = expand_families(["Software Engineering Intern"], related)
    assert expanded == [
        "Software Engineering Intern",
        "AI/ML Intern",
        "Data Engineering Intern",
        "QA/SDET/SRE Intern",
    ]


def test_expand_families_for_computer_engineering():
    _, related = load_feed_families()
    expanded = expand_families(["Computer Engineering Intern"], related)
    assert expanded == [
        "Computer Engineering Intern",
        "Embedded Systems Intern",
        "Design Engineering Intern",
    ]


def test_expand_families_is_not_transitive():
    """Embedded Systems Intern is a related family of Computer Engineering
    Intern, but has no entry of its own in related_families -- expanding it
    directly must not pull in anything Computer Engineering Intern maps to."""
    _, related = load_feed_families()
    assert expand_families(["Embedded Systems Intern"], related) == ["Embedded Systems Intern"]


def test_expand_families_preserves_order_and_dedupes_across_multiple_roles():
    _, related = load_feed_families()
    expanded = expand_families(
        ["Software Engineering Intern", "Computer Engineering Intern"], related
    )
    assert expanded == [
        "Software Engineering Intern",
        "AI/ML Intern",
        "Data Engineering Intern",
        "QA/SDET/SRE Intern",
        "Computer Engineering Intern",
        "Embedded Systems Intern",
        "Design Engineering Intern",
    ]


def test_a_role_with_no_related_families_expands_to_just_itself():
    _, related = load_feed_families()
    assert expand_families(["Lab Assistant"], related) == ["Lab Assistant"]
