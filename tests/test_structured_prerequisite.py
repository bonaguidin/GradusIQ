"""Tests for course_discovery/prerequisites.py's structured_prerequisite() --
the richer parser built for the degree-planner scheduler
(planning-docs/degree-planner-spec.md §4), added alongside the existing
conservative prerequisite_requirement()/evaluate_prerequisites() rather than
replacing them (see that function's module-level comment for why).

Every case here is a real prerequisites string pulled live this session from
data/catalog/engineering/computer_science_engineering.json,
data/catalog/engineering/general_engineering.json, and data/catalog/smu/
lyle.json -- not invented examples. Course codes passed as prerequisite_courses
are exactly what fetch_smu_catalog.py's codes_in() / normalize_catalog.py's
extract_prerequisite_courses() would have already extracted from the same
text, since structured_prerequisite() trusts that extraction rather than
re-deriving it.
"""

from __future__ import annotations

import pytest

from GradusIQ_career.course_discovery.models import CatalogInstitution, CourseCatalogRecord
from GradusIQ_career.course_discovery.prerequisites import structured_prerequisite


def _course(prerequisite_text, prerequisite_courses, cross_listings=None):
    return CourseCatalogRecord(
        institution=CatalogInstitution.TAMU,
        course_code="TEST 1",
        title="Test Course",
        description="A test course.",
        department="Test Department",
        credit_min=3,
        credit_max=3,
        prerequisite_text=prerequisite_text,
        prerequisite_courses=prerequisite_courses,
        restrictions=[],
        cross_listings=cross_listings or [],
        catalog_year="2026-2027",
        source_url="https://example.edu",
        source_last_checked="2026-08-18",
    )


def _clauses(result):
    """(course_codes, grade_min) per requires_all entry, for compact asserts."""
    return [(clause.course_codes, clause.grade_min) for clause in result.requires_all]


# ── No prerequisite text at all ─────────────────────────────────────────────


def test_none_prerequisite_text_yields_empty_structure():
    result = structured_prerequisite(_course(None, []))
    assert result.requires_all == []
    assert result.coreq_allowed == []
    assert result.restrictions == []
    assert result.needs_review == []
    assert result.raw_text is None


# ── Plain AND of two courses, with a restriction clause riding along ───────
# CSCE 350/ECEN 350 cross-listed course, TAMU CSCE catalog, live.


def test_and_of_two_courses_with_restriction_clause():
    text = (
        "Prerequisites: Grade of C or better in ECEN 248 and CSCE 120 ; "
        "junior or senior classification. Cross Listing: ECEN 350/CSCE 350 ."
    )
    codes = ["ECEN 248", "CSCE 120"]
    result = structured_prerequisite(_course(text, codes))
    assert _clauses(result) == [(["ECEN 248"], "C"), (["CSCE 120"], "C")]
    assert result.restrictions == ["junior or senior classification"]
    assert result.needs_review == []


# ── AND of two OR-groups, grade-min restated per group ──────────────────────
# CSCE elective, TAMU, live. Also confirms the trailing "Cross Listing:"
# sentence is stripped rather than parsed as a bogus third AND clause.


def test_and_of_two_or_groups_grade_min_per_group():
    text = (
        "Prerequisites: Grade of C or better in ENGR 102 , CSCE 110 , CSCE 111 , "
        "or CSCE 206 ; grade of C or better in MATH 251 , MATH 253 , or STAT 211 ; "
        "junior or senior classification. Cross Listing: ECEN 360 and STAT 315 ."
    )
    codes = [
        "ENGR 102", "CSCE 110", "CSCE 111", "CSCE 206",
        "MATH 251", "MATH 253", "STAT 211", "ECEN 360", "STAT 315",
    ]
    result = structured_prerequisite(_course(text, codes, cross_listings=["ECEN 360", "STAT 315"]))
    assert _clauses(result) == [
        (["ENGR 102", "CSCE 110", "CSCE 111", "CSCE 206"], "C"),
        (["MATH 251", "MATH 253", "STAT 211"], "C"),
    ]
    assert result.restrictions == ["junior or senior classification"]
    assert result.needs_review == []
    # Cross-listed codes must not leak into requires_all from anywhere.
    all_codes = [code for clause in result.requires_all for code in clause.course_codes]
    assert "ECEN 360" not in all_codes
    assert "STAT 315" not in all_codes


# ── Cross-listed pair inside one OR-group (same course, two department
#    codes), distinct from the "Cross Listing:" trailing-sentence shape ────


def test_cross_listed_pair_inside_or_group_is_one_clause():
    text = (
        "Prerequisites: Grade of C or better in CSCE 221 and CSCE 222/ECEN 222 ; "
        "grade of C or better in STAT 211 or ECEN 303 ; also taught at Galveston campus."
    )
    codes = ["CSCE 221", "CSCE 222", "ECEN 222", "STAT 211", "ECEN 303"]
    result = structured_prerequisite(_course(text, codes))
    assert _clauses(result) == [
        (["CSCE 221"], "C"),
        (["CSCE 222", "ECEN 222"], "C"),
        (["STAT 211", "ECEN 303"], "C"),
    ]
    assert result.restrictions == ["also taught at Galveston campus"]
    assert result.needs_review == []


# ── Trailing "or concurrent enrollment": completion OR concurrent
#    enrollment both satisfy it -- appears in BOTH requires_all and
#    coreq_allowed ─────────────────────────────────────────────────────────


def test_trailing_or_concurrent_enrollment():
    text = (
        "Prerequisites: Grade C or better in CSCE 120 or CSCE 121 ; grade of C "
        "or better in CSCE 222/ECEN 222 or ECEN 222/CSCE 222 , or concurrent enrollment."
    )
    codes = ["CSCE 120", "CSCE 121", "CSCE 222", "ECEN 222"]
    result = structured_prerequisite(_course(text, codes))
    assert _clauses(result) == [
        (["CSCE 120", "CSCE 121"], "C"),
        (["CSCE 222", "ECEN 222"], "C"),
    ]
    # Only the clause that actually said "or concurrent enrollment" -- not
    # the CSCE 120/121 clause, which had no such phrase.
    assert result.coreq_allowed == ["CSCE 222", "ECEN 222"]
    assert result.needs_review == []


def test_simple_trailing_coreq_single_course():
    text = "Prerequisite: Grade of C or better in CSCE 221 , or concurrent enrollment."
    result = structured_prerequisite(_course(text, ["CSCE 221"]))
    assert _clauses(result) == [(["CSCE 221"], "C")]
    assert result.coreq_allowed == ["CSCE 221"]


# ── Explicit named corequisite, its own clause, no prior completion at all ─


def test_explicit_named_corequisite_own_clause():
    text = (
        "Prerequisite: CSCE 312 and CSCE 314 , or CSCE 350/ECEN 350 or "
        "ECEN 350/CSCE 350 ; concurrent enrollment in CSCE 313 ."
    )
    codes = ["CSCE 312", "CSCE 314", "CSCE 350", "ECEN 350", "CSCE 313"]
    result = structured_prerequisite(_course(text, codes))
    assert _clauses(result) == [
        (["CSCE 312"], None),
        (["CSCE 314", "CSCE 350", "ECEN 350"], None),
    ]
    # CSCE 313 is a pure corequisite here -- concurrent enrollment only,
    # never named in requires_all, no prior-completion requirement at all.
    assert result.coreq_allowed == ["CSCE 313"]
    assert not any("CSCE 313" in clause.course_codes for clause in result.requires_all)


def test_explicit_corequisite_label_is_pure_corequisite():
    result = structured_prerequisite(_course("Corequisite: BIOL 1301.", ["BIOL 1301"]))
    assert result.requires_all == []
    assert result.coreq_allowed == ["BIOL 1301"]
    assert result.needs_review == []


def test_plural_explicit_corequisites_label():
    result = structured_prerequisite(
        _course("Corequisites: BIOL 1301 and CHEM 1303.", ["BIOL 1301", "CHEM 1303"])
    )
    assert result.requires_all == []
    assert result.coreq_allowed == ["BIOL 1301", "CHEM 1303"]


def test_prerequisite_or_corequisite_allows_concurrent_enrollment():
    result = structured_prerequisite(
        _course("Prerequisite or corequisite: BIOL 1101.", ["BIOL 1101"])
    )
    assert _clauses(result) == [(["BIOL 1101"], None)]
    assert result.coreq_allowed == ["BIOL 1101"]
    assert result.needs_review == []


def test_plural_prerequisites_or_corequisites_allows_concurrent_enrollment():
    result = structured_prerequisite(
        _course(
            "Prerequisites or corequisites: BIOL 1101 and CHEM 1113.",
            ["BIOL 1101", "CHEM 1113"],
        )
    )
    assert _clauses(result) == [(["BIOL 1101"], None), (["CHEM 1113"], None)]
    assert result.coreq_allowed == ["BIOL 1101", "CHEM 1113"]


@pytest.mark.parametrize(
    ("text", "codes", "expected_clauses"),
    [
        (
            "Prerequisite/Corequisite: STAT 4340 or STAT 4341.",
            ["STAT 4340", "STAT 4341"],
            [(["STAT 4340", "STAT 4341"], None)],
        ),
        (
            "or prerequisite or corequisite: APSM 2310.",
            ["APSM 2310"],
            [(["APSM 2310"], None)],
        ),
        (
            "or prerequisite or corequisite APSM 2310.",
            ["APSM 2310"],
            [(["APSM 2310"], None)],
        ),
    ],
)
def test_real_explicit_corequisite_label_variants(text, codes, expected_clauses):
    result = structured_prerequisite(_course(text, codes))

    assert _clauses(result) == expected_clauses
    assert result.coreq_allowed == codes


def test_mixed_explicit_prerequisite_and_corequisite_labels():
    result = structured_prerequisite(
        _course(
            "Prerequisite: CS 3341. Corequisite: CS 5330.",
            ["CS 3341", "CS 5330"],
        )
    )
    assert _clauses(result) == [(["CS 3341"], None)]
    assert result.coreq_allowed == ["CS 5330"]
    assert result.needs_review == []


# ── Real course mixed with an unverifiable non-course alternative path:
#    must NOT enter requires_all, or a student who satisfied it via the
#    other path would be wrongly blocked ────────────────────────────────────


def test_course_with_ap_exam_and_consent_alternatives_is_not_required():
    text = (
        "Prerequisites: C- or better in CS 1341, a grade of at least 4 on the "
        "AP Computer Science A Exam, or departmental consent."
    )
    result = structured_prerequisite(_course(text, ["CS 1341"]))
    assert result.requires_all == []
    assert len(result.needs_review) == 1
    assert "CS 1341" in result.needs_review[0]


def test_course_list_with_consent_of_instructor_alternative_is_not_required():
    text = (
        "Prerequisites: Any one of the following with grade of C or better: "
        "CS 4381, CS 5385, ECE 5381, ECE 5383, ECE 5385, or consent of instructor."
    )
    codes = ["CS 4381", "CS 5385", "ECE 5381", "ECE 5383", "ECE 5385"]
    result = structured_prerequisite(_course(text, codes))
    assert result.requires_all == []
    assert len(result.needs_review) == 1


# ── Trailing "or equivalent" / "or permission of instructor": parsed
#    normally into requires_all, with the footnote preserved on
#    PrerequisiteClause.alternate_paths rather than dropped or forced into
#    needs_review. All 5 cases here are real prerequisites strings pulled
#    live this session from data/catalog/smu/*.json (CS 3377, CS 2341,
#    CS 5325, OREM 3340, CHEM 1303) -- the exact set spec §10 flagged as
#    the needs-review bucket sharing this one boilerplate pattern, with
#    CS 2341 being the one gating half of CS Core's remaining chain. ──────


def test_or_equivalent_smu_cs_3377():
    text = "Prerequisites: C- or better in CS 2341 or equivalent."
    result = structured_prerequisite(_course(text, ["CS 2341"]))
    assert _clauses(result) == [(["CS 2341"], "C-")]
    assert result.requires_all[0].alternate_paths == ["or equivalent"]
    assert result.needs_review == []


def test_or_equivalent_smu_cs_2341_gates_cs_core_chain():
    """CS 2341 is the prerequisite gating half of CS Core's remaining
    no-choice chain (spec §10) -- this is the concrete case the fix exists
    for, so it gets its own named test rather than riding along generically.
    """
    text = "Prerequisite: C- or better in CS 1342 or equivalent."
    result = structured_prerequisite(_course(text, ["CS 1342"]))
    assert _clauses(result) == [(["CS 1342"], "C-")]
    assert result.requires_all[0].alternate_paths == ["or equivalent"]
    assert result.needs_review == []


def test_or_permission_of_instructor_smu_cs_5325():
    text = "Prerequisite: CS 5324 or permission of instructor."
    result = structured_prerequisite(_course(text, ["CS 5324"]))
    assert _clauses(result) == [(["CS 5324"], None)]
    assert result.requires_all[0].alternate_paths == ["or permission of instructor"]
    assert result.needs_review == []


def test_or_equivalent_smu_orem_3340():
    text = "Prerequisite: C- or better in MATH 1338 or equivalent."
    result = structured_prerequisite(_course(text, ["MATH 1338"]))
    assert _clauses(result) == [(["MATH 1338"], "C-")]
    assert result.requires_all[0].alternate_paths == ["or equivalent"]
    assert result.needs_review == []


def test_chem_1303_mid_clause_equivalent_with_third_alternative_still_needs_review():
    """NOT the same shape as the 4 cases above: "equivalent" appears
    mid-clause, followed by a third, distinct alternative (an exam) -- no
    clean "course, plus one trailing footnote" shape to parse, so this must
    remain conservative rather than being force-fit into the new pattern.
    """
    text = (
        "Prerequisite to all advanced courses in the department. Prerequisites: "
        "C- or higher in CHEM 1302, appropriate equivalent credit for CHEM 1303, "
        "or a passing grade on the Chemistry Placement Exam."
    )
    result = structured_prerequisite(_course(text, ["CHEM 1302", "CHEM 1303"]))
    assert result.requires_all == []
    assert len(result.needs_review) == 1
    assert "CHEM 1302" in result.needs_review[0]


def test_or_equivalent_does_not_swallow_a_genuine_second_alternative():
    """A course code followed by "or equivalent" mid-clause, with unrelated
    content still trailing after it, must not match the trailing-only
    regex -- guards against over-matching beyond the exact anchored shape.
    """
    text = "Prerequisite: CS 9999 or equivalent, and departmental approval."
    result = structured_prerequisite(_course(text, ["CS 9999"]))
    assert result.requires_all == []
    assert len(result.needs_review) == 1


# ── Bare comma-separated course list, no "and"/"or" connector: AND, not
#    OR (spec §10.1's follow-up finding, scoped in this session's
#    investigation to 230 real courses -- CS 3353 was the one that
#    surfaced it). Splits into one clause per course. All 6 real cases
#    here are live text pulled from data/catalog/smu/*.json this session.
#    Confirmed both collection points needed the fix: CS 3353 hits the
#    top-level fallback (no "and" anywhere); CS 5320/5330/5343 hit the
#    _AND_SPLIT sub-clause loop (a literal "and" appears before the LAST
#    item only, leaving the earlier bare-comma pair merged before this
#    fix) ─────────────────────────────────────────────────────────────────


def test_bare_comma_two_courses_no_connector_splits_into_and():
    text = "Prerequisites: C- or better in CS 2341, CS 2353."
    result = structured_prerequisite(_course(text, ["CS 2341", "CS 2353"]))
    assert _clauses(result) == [(["CS 2341"], "C-"), (["CS 2353"], "C-")]
    assert result.needs_review == []


def test_bare_comma_two_courses_no_connector_splits_into_and_second_example():
    text = "Prerequisites: C- or better in MATH 1337, MATH 1338."
    result = structured_prerequisite(_course(text, ["MATH 1337", "MATH 1338"]))
    assert _clauses(result) == [(["MATH 1337"], "C-"), (["MATH 1338"], "C-")]


def test_and_split_sub_clause_with_bare_comma_pair_also_splits():
    """CS 5320: the literal "and" only appears before the THIRD item, so
    the AND-split sub-clause loop -- not the top-level fallback -- is what
    has to apply the fix to the earlier "CS 3353, CS 4340" pair. This is
    the case proving both collection points needed the change, not just
    one."""
    text = "Prerequisites: C- or better in CS 3353, CS 4340, and MATH 3304."
    result = structured_prerequisite(_course(text, ["CS 3353", "CS 4340", "MATH 3304"]))
    assert _clauses(result) == [
        (["CS 3353"], "C-"), (["CS 4340"], "C-"), (["MATH 3304"], "C-"),
    ]


def test_and_split_sub_clause_bare_comma_pair_cs_5330():
    text = "Prerequisites: C- or better in CS 2341, CS 2353, and CS 3341."
    result = structured_prerequisite(_course(text, ["CS 2341", "CS 2353", "CS 3341"]))
    assert _clauses(result) == [
        (["CS 2341"], "C-"), (["CS 2353"], "C-"), (["CS 3341"], "C-"),
    ]


def test_and_split_sub_clause_bare_comma_pair_cs_5343():
    text = "Prerequisites: C- or better in CS 2340, CS 3353, and CS 3341."
    result = structured_prerequisite(_course(text, ["CS 2340", "CS 3353", "CS 3341"]))
    assert _clauses(result) == [
        (["CS 2340"], "C-"), (["CS 3353"], "C-"), (["CS 3341"], "C-"),
    ]


def test_ambiguous_bucket_list_ending_in_or_permission_stays_merged():
    """Out of scope for this fix, deliberately unchanged: a comma list
    whose ONLY connector is a trailing "or permission of instructor"
    governs the WHOLE list (a genuine multi-way OR: any one of the 5
    courses, or permission), not an AND-list with a footnote. Real text,
    SMU ASCE department."""
    text = "Prerequisite: ASCE 1300, ASCE 1310, ASCE 3300, ASCE 3320, ASCE 3330, or permission of instructor."
    codes = ["ASCE 1300", "ASCE 1310", "ASCE 3300", "ASCE 3320", "ASCE 3330"]
    result = structured_prerequisite(_course(text, codes))
    assert _clauses(result) == [(codes, None)]
    assert result.requires_all[0].alternate_paths == ["or permission of instructor"]
    assert result.needs_review == []


def test_ambiguous_bucket_two_course_list_ending_in_or_permission_stays_merged():
    """The genuinely-ambiguous case named in this session's investigation:
    "(CHEM 1303 AND CHEM 1304) OR permission" vs. "CHEM 1303 OR CHEM 1304
    OR permission" cannot be told apart from the text alone. Left exactly
    as today produces it -- one merged clause -- rather than guessed at
    either direction. Real text, SMU CHEM department (CHEM 4306/4317/
    4321/4322 all share this exact string)."""
    text = "Prerequisites: CHEM 1303, CHEM 1304 or permission of instructor."
    result = structured_prerequisite(_course(text, ["CHEM 1303", "CHEM 1304"]))
    assert _clauses(result) == [(["CHEM 1303", "CHEM 1304"], None)]
    assert result.requires_all[0].alternate_paths == ["or permission of instructor"]
    assert result.needs_review == []


def test_bare_comma_split_does_not_break_slash_joined_cross_listing():
    """CEE 5363: a genuine cross-listed pair (CEE 2310/ME 2310) alongside
    a separately bare-comma'd course (CEE 2320) -- must split into 2
    clauses (AND), but the cross-listed pair must stay merged as ONE of
    them, not shatter into 3 independently-required courses. This is the
    regression risk the fix has to get right from the start."""
    text = "Prerequisites: CEE 2310/ME 2310, CEE 2320."
    result = structured_prerequisite(_course(text, ["CEE 2310", "ME 2310", "CEE 2320"]))
    assert _clauses(result) == [
        (["CEE 2310", "ME 2310"], None),
        (["CEE 2320"], None),
    ]


# ── Genuinely ambiguous nested AND/OR: best-effort parse recorded, flagged
#    for review -- not silently trusted, not silently discarded ───────────


def test_ambiguous_nested_and_or_is_flagged_but_still_parsed_best_effort():
    text = (
        "Prerequisite: Grade of C or better in MATH 304 , MATH 311 , or MATH 323 ; "
        "Grade of C or better in STAT 211 , and STAT 404 or CSCE 221 , or ECEN 303 , "
        "and CSCE 121 or CSCE 120 . Cross Listing: ECEN 427 and STAT 421 ."
    )
    codes = [
        "MATH 304", "MATH 311", "MATH 323", "STAT 211", "STAT 404", "CSCE 221",
        "ECEN 303", "CSCE 121", "CSCE 120", "ECEN 427", "STAT 421",
    ]
    result = structured_prerequisite(
        _course(text, codes, cross_listings=["ECEN 427", "STAT 421"])
    )
    # The clean, unambiguous first clause parses normally.
    assert (["MATH 304", "MATH 311", "MATH 323"], "C") in _clauses(result)
    # The genuinely ambiguous second clause still produces a best-effort
    # mechanical AND-of-ORs split (useful to the scheduler)...
    assert (["STAT 211"], "C") in _clauses(result)
    assert (["STAT 404", "CSCE 221", "ECEN 303"], "C") in _clauses(result)
    assert (["CSCE 121", "CSCE 120"], "C") in _clauses(result)
    # ...but is flagged rather than silently trusted.
    assert len(result.needs_review) == 1
    assert "STAT 211" in result.needs_review[0]
    assert "MATH 304" not in result.needs_review[0]


# ── Restriction-only text: no course logic, recognized and routed to
#    restrictions rather than needs_review ──────────────────────────────────


def test_restriction_only_smu_text():
    result = structured_prerequisite(_course("Restricted to Lyle seniors.", []))
    assert result.requires_all == []
    assert result.restrictions == ["Restricted to Lyle seniors"]
    assert result.needs_review == []


def test_restriction_only_second_smu_example():
    result = structured_prerequisite(_course("Restricted to NexPoint Tower Scholars.", []))
    assert result.restrictions == ["Restricted to NexPoint Tower Scholars"]
    assert result.needs_review == []


def test_classification_and_instructor_approval_restriction():
    result = structured_prerequisite(
        _course("Freshman or sophomore classification and approval of instructor.", [])
    )
    assert result.requires_all == []
    assert len(result.restrictions) == 1
    assert result.needs_review == []


# ── Genuinely unrecognized non-course phrasing: flagged, not silently
#    dropped, not miscategorized as a known restriction ────────────────────


def test_unrecognized_non_course_clause_is_flagged_not_dropped():
    result = structured_prerequisite(_course("Some brand-new phrasing never seen before.", []))
    assert result.requires_all == []
    assert result.restrictions == []
    assert result.needs_review == ["Some brand-new phrasing never seen before"]


# ── raw_text is always preserved verbatim, whitespace-normalized ──────────


def test_raw_text_preserved_and_whitespace_normalized():
    text = "Prerequisite:   Grade of C or better   in CSCE 221 ."
    result = structured_prerequisite(_course(text, ["CSCE 221"]))
    assert result.raw_text == "Prerequisite: Grade of C or better in CSCE 221 ."
