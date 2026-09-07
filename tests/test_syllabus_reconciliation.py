import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from GradusIQ_career.syllabus.models import (
    Assessment,
    CourseMetadata,
    ExtractionWarning,
    ExtractionWarningType,
    GradeCategory,
    GradeModel,
    GradeThreshold,
    GradingMethod,
    GradingRule,
    GradingRuleType,
    SourceEvidence,
)
from GradusIQ_career.syllabus.reconciliation import (
    EvidenceCoverage,
    GradeModelReconciliationResult,
    ReconciliationStatus,
    reconcile_grade_model,
)
from GradusIQ_career.syllabus.relevance import RelevantPage, RelevantSyllabusContent
from GradusIQ_career.syllabus.validation import ValidationSeverity

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "phys_207_grade_model.json"


def page(page_number: int, markdown: str) -> RelevantPage:
    return RelevantPage(page_number=page_number, markdown=markdown, relevance_score=5.0)


def content_from_pages(pages: list[RelevantPage]) -> RelevantSyllabusContent:
    combined = "\n\n".join(f"<!-- page: {p.page_number} -->\n\n{p.markdown}" for p in pages)
    return RelevantSyllabusContent(
        selected_pages=pages,
        selected_sections=[],
        markdown=combined,
        source_page_count=len(pages),
        selected_page_count=len(pages),
    )


def evidence(page_number: int, text: str, confidence: float | None = 1.0) -> SourceEvidence:
    return SourceEvidence(page=page_number, text=text, confidence=confidence)


# --- PHYS 207 fixtures ---------------------------------------------------------

PHYS_207_PAGES = [
    page(2, "Mid-term Exam: 35%\nFinal Exam: 50%\nLecture Quizzes: 5%\nRecitation Quizzes: 10%"),
    page(3, "A: 90-100\nB: 80-89\nC: 60-79\nD: 45-59\nF: below 45"),
    page(
        4,
        "If the Final Exam grade is higher than the Mid-term Exam grade, the "
        "Final Exam replaces the Mid-term Exam grade.\n\n"
        "Grades may be curved upward.",
    ),
]
PHYS_207_CONTENT = content_from_pages(PHYS_207_PAGES)


def phys_207_grade_model(*, include_curve: bool) -> GradeModel:
    rules = [
        GradingRule(
            rule_type=GradingRuleType.REPLACEMENT,
            description=(
                "If the Final Exam grade is higher than the Mid-term Exam grade, "
                "the Final Exam replaces the Mid-term Exam grade."
            ),
            source="Final Exam",
            target="Mid-term Exam",
            condition="final_score > midterm_score",
            evidence=evidence(
                4,
                "If the Final Exam grade is higher than the Mid-term Exam grade, "
                "the Final Exam replaces the Mid-term Exam grade.",
            ),
        )
    ]
    warnings = [
        ExtractionWarning(
            type=ExtractionWarningType.UNKNOWN_ASSESSMENT_COUNT,
            description="The exact number of Lecture Quizzes is unknown.",
            related_field="Lecture Quizzes",
        ),
        ExtractionWarning(
            type=ExtractionWarningType.UNKNOWN_ASSESSMENT_COUNT,
            description="The exact number of Recitation Quizzes is unknown.",
            related_field="Recitation Quizzes",
        ),
    ]
    if include_curve:
        rules.append(
            GradingRule(
                rule_type=GradingRuleType.CURVE,
                description="Grades may be curved upward.",
                evidence=evidence(4, "Grades may be curved upward."),
            )
        )
        warnings.append(
            ExtractionWarning(
                type=ExtractionWarningType.POSSIBLE_CURVE,
                description="Grades may be curved upward, but no deterministic curve formula is given.",
            )
        )

    return GradeModel(
        course=CourseMetadata(course_code="PHYS 207", section="529", term="Fall 2026"),
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Mid-term Exam", weight=35, evidence=evidence(2, "Mid-term Exam: 35%")),
            GradeCategory(name="Final Exam", weight=50, evidence=evidence(2, "Final Exam: 50%")),
            GradeCategory(name="Lecture Quizzes", weight=5, evidence=evidence(2, "Lecture Quizzes: 5%")),
            GradeCategory(name="Recitation Quizzes", weight=10, evidence=evidence(2, "Recitation Quizzes: 10%")),
        ],
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90, maximum=100, evidence=evidence(3, "A: 90-100")),
            GradeThreshold(letter="B", minimum=80, maximum=89, evidence=evidence(3, "B: 80-89")),
            GradeThreshold(letter="C", minimum=60, maximum=79, evidence=evidence(3, "C: 60-79")),
            GradeThreshold(letter="D", minimum=45, maximum=59, evidence=evidence(3, "D: 45-59")),
            GradeThreshold(letter="F", maximum=44, evidence=evidence(3, "F: below 45")),
        ],
        rules=rules,
        warnings=warnings,
    )


# --- PHYS 207: with curve -> ACCEPTED, curve findings surfaced not blocking -----


def test_phys_207_with_curve_is_accepted_curve_findings_non_blocking():
    # A correctly-extracted curve is informational, not an ambiguity to
    # resolve (syllabus-review redesign, planning-docs/
    # syllabus-review-redesign-spec.md §2C / §5). The findings are still
    # produced -- the UI shows the rule as a Professor's Rule -- they just
    # no longer force NEEDS_STUDENT_REVIEW.
    result = reconcile_grade_model(phys_207_grade_model(include_curve=True), PHYS_207_CONTENT)
    assert result.status == ReconciliationStatus.ACCEPTED
    codes = {f.code for f in result.findings}
    assert "possible_curve" in codes
    assert "non_deterministic_grading_rule" in codes


def test_phys_207_with_curve_weights_and_references_still_pass():
    result = reconcile_grade_model(phys_207_grade_model(include_curve=True), PHYS_207_CONTENT)
    weight_findings = [f for f in result.findings if f.code == "category_weight_validation"]
    assert len(weight_findings) == 1
    assert weight_findings[0].severity.value == "valid"
    assert not any(f.code == "unresolved_rule_reference" for f in result.findings)
    assert not any(f.code == "duplicate_category" for f in result.findings)


def test_phys_207_unknown_quiz_counts_are_warnings_not_errors():
    result = reconcile_grade_model(phys_207_grade_model(include_curve=True), PHYS_207_CONTENT)
    quiz_findings = [f for f in result.findings if f.code == "unknown_assessment_count"]
    assert len(quiz_findings) == 2
    assert all(f.severity.value == "warning" for f in quiz_findings)


# --- PHYS 207: without curve -> ACCEPTED reachable --------------------------------


def test_phys_207_without_curve_is_accepted():
    result = reconcile_grade_model(phys_207_grade_model(include_curve=False), PHYS_207_CONTENT)
    assert result.status == ReconciliationStatus.ACCEPTED


# --- clean accepted fixture (section 30) ------------------------------------------


def clean_grade_model() -> GradeModel:
    return GradeModel(
        course=CourseMetadata(course_code="TEST 100"),
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Midterm", weight=30, evidence=evidence(1, "Midterm: 30%")),
            GradeCategory(name="Final", weight=40, evidence=evidence(1, "Final: 40%")),
            GradeCategory(name="Homework", weight=30, evidence=evidence(1, "Homework: 30%")),
        ],
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90, maximum=100, evidence=evidence(1, "A: 90-100")),
            GradeThreshold(letter="B", minimum=80, maximum=89, evidence=evidence(1, "B: 80-89")),
            GradeThreshold(letter="C", minimum=70, maximum=79, evidence=evidence(1, "C: 70-79")),
            GradeThreshold(letter="D", minimum=60, maximum=69, evidence=evidence(1, "D: 60-69")),
            GradeThreshold(letter="F", maximum=59, evidence=evidence(1, "F: below 60")),
        ],
        rules=[],
        warnings=[],
    )


CLEAN_CONTENT = content_from_pages(
    [
        page(
            1,
            "Midterm: 30%\nFinal: 40%\nHomework: 30%\n"
            "A: 90-100\nB: 80-89\nC: 70-79\nD: 60-69\nF: below 60",
        )
    ]
)


def test_clean_fixture_is_accepted():
    result = reconcile_grade_model(clean_grade_model(), CLEAN_CONTENT)
    assert result.status == ReconciliationStatus.ACCEPTED
    assert result.findings == [] or all(f.severity.value == "valid" for f in result.findings)


def test_acceptance_is_reachable_not_impossible():
    """Proves Phase 5 doesn't force every realistic syllabus into review."""
    result = reconcile_grade_model(clean_grade_model(), CLEAN_CONTENT)
    assert result.status == ReconciliationStatus.ACCEPTED


# --- evidence inconsistency (section 25) ------------------------------------------


def test_category_weight_mismatch_with_real_evidence_needs_review():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Mid-term Exam", weight=50, evidence=evidence(1, "Mid-term Exam: 35%")),
        ],
    )
    content = content_from_pages([page(1, "Mid-term Exam: 35%")])
    result = reconcile_grade_model(model, content)
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    mismatch = [f for f in result.findings if f.code == "claim_evidence_value_mismatch"]
    assert len(mismatch) == 1
    assert "50" in mismatch[0].message and "35.0" in mismatch[0].message


def test_threshold_value_mismatch_needs_review():
    model = GradeModel(
        grade_thresholds=[GradeThreshold(letter="A", minimum=90, maximum=100, evidence=evidence(1, "A: 80-90"))],
    )
    content = content_from_pages([page(1, "A: 80-90")])
    result = reconcile_grade_model(model, content)
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    assert any(f.code == "claim_evidence_value_mismatch" for f in result.findings)


def test_consistent_evidence_produces_no_mismatch_finding():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Midterm", weight=35, evidence=evidence(1, "Midterm: 35%"))],
    )
    content = content_from_pages([page(1, "Midterm: 35%")])
    result = reconcile_grade_model(model, content)
    assert not any(f.code == "claim_evidence_value_mismatch" for f in result.findings)


def test_unverifiable_evidence_text_produces_warning_not_mismatch():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Midterm", weight=35, evidence=evidence(1, "Midterm counts significantly"))],
    )
    content = content_from_pages([page(1, "Midterm counts significantly")])
    result = reconcile_grade_model(model, content)
    unverifiable = [f for f in result.findings if f.code == "claim_evidence_consistency_unverifiable"]
    assert len(unverifiable) == 1
    assert not any(f.code == "claim_evidence_value_mismatch" for f in result.findings)


# --- missing evidence (section 26) -------------------------------------------------


def test_missing_evidence_on_critical_claim_needs_review():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Final Exam", weight=50, evidence=None)],
    )
    content = content_from_pages([page(1, "Final Exam: 50%")])
    result = reconcile_grade_model(model, content)
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    missing = [f for f in result.findings if f.code == "missing_claim_evidence"]
    assert len(missing) == 1
    assert result.evidence_coverage.supported_claims == 0
    assert result.evidence_coverage.total_claims == 1


def test_null_count_does_not_require_evidence():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Lecture Quizzes", weight=5, count=None, evidence=evidence(1, "Lecture Quizzes: 5%"))
        ],
    )
    content = content_from_pages([page(1, "Lecture Quizzes: 5%")])
    result = reconcile_grade_model(model, content)
    assert not any(f.code == "missing_claim_evidence" and "count" in f.field for f in result.findings)
    assert result.evidence_coverage.total_claims == 1  # only the weight claim


# --- duplicate category (section 27) -----------------------------------------------


def test_duplicate_category_needs_review():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Midterm", weight=35, evidence=evidence(1, "Midterm: 35%")),
            GradeCategory(name="midterm", weight=35, evidence=evidence(1, "midterm: 35%")),
        ],
    )
    content = content_from_pages([page(1, "Midterm: 35%\nmidterm: 35%")])
    result = reconcile_grade_model(model, content)
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    duplicates = [f for f in result.findings if f.code == "duplicate_category"]
    assert len(duplicates) == 1


def test_categories_are_not_merged():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Midterm", weight=35),
            GradeCategory(name="midterm", weight=35),
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert len(result.grade_model.categories) == 2


def test_whitespace_variant_duplicate_is_detected():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Mid-term Exam", weight=35),
            GradeCategory(name="Mid-term   Exam", weight=35),
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert any(f.code == "duplicate_category" for f in result.findings)


def test_different_categories_are_not_flagged_as_duplicates():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Tests", weight=50), GradeCategory(name="Exams", weight=50)],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert not any(f.code == "duplicate_category" for f in result.findings)


def test_assessments_with_different_dates_are_not_duplicates():
    model = GradeModel(
        assessments=[
            Assessment(name="Quiz", date="Sep 2"),
            Assessment(name="Quiz", date="Sep 9"),
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert not any(f.code == "duplicate_assessment" for f in result.findings)


def test_assessments_with_same_name_and_date_are_duplicates():
    model = GradeModel(
        assessments=[
            Assessment(name="Quiz", date="Sep 2"),
            Assessment(name="quiz", date="Sep 2"),
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert any(f.code == "duplicate_assessment" for f in result.findings)


def test_duplicate_assessment_field_is_unique_across_groups_with_the_same_name():
    """Two separate duplicate-groups can share a name and differ only by
    date (each "Quiz" duplicated on its own date) -- field must include the
    date, or both findings collapse onto the same field value even though
    they're about two different pairs of assessments.
    """
    model = GradeModel(
        assessments=[
            Assessment(name="Quiz", date="Sep 2"),
            Assessment(name="quiz", date="Sep 2"),
            Assessment(name="Quiz", date="Sep 9"),
            Assessment(name="quiz", date="Sep 9"),
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    findings = [f for f in result.findings if f.code == "duplicate_assessment"]
    assert len(findings) == 2
    fields = {f.field for f in findings}
    assert len(fields) == 2


# --- conflicting threshold (section 28) --------------------------------------------


def test_overlapping_thresholds_need_review():
    model = GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90, maximum=100),
            GradeThreshold(letter="B", minimum=85, maximum=95),
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    assert any(f.code == "overlapping_grade_thresholds" for f in result.findings)


def test_non_overlapping_thresholds_pass():
    model = GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90, maximum=100),
            GradeThreshold(letter="B", minimum=80, maximum=89),
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert not any(f.code == "overlapping_grade_thresholds" for f in result.findings)


# --- confirmed_cutoff_pairs suppression ----------------------------------------------


def _bc_boundary_overlap_model() -> GradeModel:
    # Isolated, cleanly-resolvable B/C overlap at 80 (A kept clear of B).
    return GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=91, maximum=100),
            GradeThreshold(letter="B", minimum=80, maximum=90),
            GradeThreshold(letter="C", minimum=70, maximum=80),
        ],
    )


def test_confirmed_resolvable_pair_suppresses_the_overlap_error():
    model = _bc_boundary_overlap_model()
    result = reconcile_grade_model(
        model, content_from_pages([page(1, "x")]), confirmed_cutoff_pairs={frozenset(("B", "C"))}
    )
    assert not any(f.code == "overlapping_grade_thresholds" for f in result.findings)
    # thresholds are returned exactly as given -- nothing was narrowed
    assert [(t.letter, t.minimum, t.maximum) for t in result.grade_model.grade_thresholds] == [
        ("A", 91, 100),
        ("B", 80, 90),
        ("C", 70, 80),
    ]


def test_unconfirmed_overlap_still_errors():
    result = reconcile_grade_model(_bc_boundary_overlap_model(), content_from_pages([page(1, "x")]))
    assert any(f.code == "overlapping_grade_thresholds" for f in result.findings)
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW


def test_confirming_a_non_adjacent_pair_does_not_suppress_the_error():
    # A vs C overlap, not rank-adjacent -> resolve_cutoff_overlaps leaves it
    # unresolved, so the confirmed set is ignored and the ERROR stands.
    model = GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=80, maximum=100),
            GradeThreshold(letter="C", minimum=70, maximum=85),
        ],
    )
    result = reconcile_grade_model(
        model, content_from_pages([page(1, "x")]), confirmed_cutoff_pairs={frozenset(("A", "C"))}
    )
    assert any(f.code == "overlapping_grade_thresholds" for f in result.findings)
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW


def test_confirming_a_multi_way_component_does_not_suppress_the_error():
    # A/B share 90, B/C share 80 -> 3-threshold connected component -> the
    # resolver refuses it; confirming (B,C) must not sneak past.
    model = GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90, maximum=100),
            GradeThreshold(letter="B", minimum=80, maximum=90),
            GradeThreshold(letter="C", minimum=70, maximum=80),
        ],
    )
    result = reconcile_grade_model(
        model, content_from_pages([page(1, "x")]), confirmed_cutoff_pairs={frozenset(("B", "C"))}
    )
    assert any(f.code == "overlapping_grade_thresholds" for f in result.findings)


# --- confirmed_value_claims suppression --------------------------------------------


def _unverifiable_bc_model() -> GradeModel:
    """Otherwise-clean weighted model. B and C carry fully-bounded ranges
    whose evidence text uses ">= / <" comparison phrasing _RANGE_RE cannot
    parse -> each yields a claim_evidence_consistency_unverifiable WARNING,
    which is the model's only blocker. A is single-bound so it is skipped by
    the range check entirely (kept clear of the overlap scan).
    """
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Overall", weight=100, evidence=evidence(1, "Overall: 100%"))],
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90, evidence=evidence(1, "A: >= 90%")),
            GradeThreshold(letter="B", minimum=80, maximum=89, evidence=evidence(1, "B: >= 80% and < 90%")),
            GradeThreshold(letter="C", minimum=70, maximum=79, evidence=evidence(1, "C: >= 70% and < 80%")),
        ],
    )


def test_confirmed_value_claim_suppresses_unverifiable_finding():
    model = _unverifiable_bc_model()
    result = reconcile_grade_model(
        model, content_from_pages([page(1, "x")]), confirmed_value_claims={"b", "c"}
    )
    assert not any(f.code == "claim_evidence_consistency_unverifiable" for f in result.findings)
    assert result.status == ReconciliationStatus.ACCEPTED
    # thresholds and their verbatim evidence are returned exactly as given
    assert [(t.letter, t.minimum, t.maximum, t.evidence.text) for t in result.grade_model.grade_thresholds] == [
        ("A", 90, None, "A: >= 90%"),
        ("B", 80, 89, "B: >= 80% and < 90%"),
        ("C", 70, 79, "C: >= 70% and < 80%"),
    ]


def test_unconfirmed_value_claim_still_blocks():
    result = reconcile_grade_model(_unverifiable_bc_model(), content_from_pages([page(1, "x")]))
    assert [f.field for f in result.findings if f.code == "claim_evidence_consistency_unverifiable"] == [
        "threshold:B",
        "threshold:C",
    ]
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW


def test_confirmed_value_claim_is_letter_scoped():
    result = reconcile_grade_model(
        _unverifiable_bc_model(), content_from_pages([page(1, "x")]), confirmed_value_claims={"b"}
    )
    assert [f.field for f in result.findings if f.code == "claim_evidence_consistency_unverifiable"] == [
        "threshold:C",
    ]
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW


def test_confirmed_value_claim_suppresses_value_mismatch_error():
    # Evidence says 80-90 but the student narrowed B to 80-89 (e.g. to break
    # a cutoff overlap) -> _RANGE_RE parses "80-90", the deterministic check
    # reads it as a claim_evidence_value_mismatch ERROR. Affirming the value
    # suppresses it; the threshold stays 80-89 with its verbatim evidence.
    model = GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="B", minimum=80, maximum=89, evidence=evidence(1, "B: 80-90")),
        ],
    )
    unconfirmed = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert any(f.code == "claim_evidence_value_mismatch" for f in unconfirmed.findings)

    confirmed = reconcile_grade_model(
        model, content_from_pages([page(1, "x")]), confirmed_value_claims={"b"}
    )
    assert not any(f.code == "claim_evidence_value_mismatch" for f in confirmed.findings)
    assert confirmed.grade_model.grade_thresholds[0].maximum == 89
    assert confirmed.grade_model.grade_thresholds[0].evidence.text == "B: 80-90"


def test_confirmed_value_claim_only_skips_a_finding_it_would_have_emitted():
    # B verifies clean against its evidence; "confirming" it changes nothing
    # and does not suppress C's genuine unverifiable finding.
    model = GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="B", minimum=80, maximum=90, evidence=evidence(1, "B: 80-90")),
            GradeThreshold(letter="C", minimum=70, maximum=79, evidence=evidence(1, "C: >= 70% and < 80%")),
        ],
    )
    result = reconcile_grade_model(
        model, content_from_pages([page(1, "x")]), confirmed_value_claims={"b", "c"}
    )
    # C was confirmed too, so it is suppressed; B never had a finding.
    assert not any(f.code.startswith("claim_evidence") for f in result.findings)
    result_b_only = reconcile_grade_model(
        model, content_from_pages([page(1, "x")]), confirmed_value_claims={"b"}
    )
    assert [f.field for f in result_b_only.findings if f.code == "claim_evidence_consistency_unverifiable"] == [
        "threshold:C",
    ]


def test_confirmed_category_value_claim_suppresses_unverifiable_finding():
    # weight=100 keeps category_weight_validation itself VALID, isolating
    # the claim_evidence check under test. "2 midterms" (a count fact) has
    # no percent for _PERCENT_RE to find -- exactly the shape a category
    # whose weight was just filled in via SET_WEIGHT produces, since
    # GradeCategory has one shared evidence field, not one per fact.
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Midterm Exam", weight=100, evidence=evidence(1, "2 midterms"))],
    )
    unconfirmed = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert any(f.code == "claim_evidence_consistency_unverifiable" for f in unconfirmed.findings)

    confirmed = reconcile_grade_model(
        model, content_from_pages([page(1, "x")]), confirmed_category_value_claims={"midterm exam"}
    )
    assert not any(f.code == "claim_evidence_consistency_unverifiable" for f in confirmed.findings)
    assert confirmed.status == ReconciliationStatus.ACCEPTED
    # the category and its verbatim evidence are returned exactly as given
    assert confirmed.grade_model.categories[0].weight == 100
    assert confirmed.grade_model.categories[0].evidence.text == "2 midterms"


def test_confirmed_category_value_claim_does_not_suppress_value_mismatch_error():
    # Deliberately narrower than the threshold path (see
    # _check_category_weight_consistency): weight=100 (so category_weight_
    # validation itself stays VALID) but evidence explicitly cites 25% -- a
    # positive, cited contradiction, not something the checker merely
    # failed to parse. Affirming it must NOT clear this.
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Midterm Exam", weight=100, evidence=evidence(1, "Midterm Exam (25%)"))],
    )
    unconfirmed = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert any(f.code == "claim_evidence_value_mismatch" for f in unconfirmed.findings)
    assert unconfirmed.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW

    confirmed = reconcile_grade_model(
        model, content_from_pages([page(1, "x")]), confirmed_category_value_claims={"midterm exam"}
    )
    assert any(f.code == "claim_evidence_value_mismatch" for f in confirmed.findings)
    assert confirmed.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW


def test_unbounded_thresholds_are_allowed():
    model = GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90),
            GradeThreshold(letter="F", maximum=44),
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert not any(
        f.code in ("overlapping_grade_thresholds", "reversed_grade_threshold") for f in result.findings
    )


def test_threshold_ordering_anomaly_is_flagged():
    model = GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=80),
            GradeThreshold(letter="B", minimum=90),
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert any(f.code == "grade_threshold_ordering_anomaly" for f in result.findings)


def test_non_standard_letters_skip_ordering_check():
    model = GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="Pass", minimum=60),
            GradeThreshold(letter="Fail", maximum=59),
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert not any(f.code == "grade_threshold_ordering_anomaly" for f in result.findings)


# --- broken rule reference (section 29) ---------------------------------------------


def test_unresolved_rule_reference_needs_review():
    model = GradeModel(
        categories=[GradeCategory(name="Final Exam", weight=50)],
        rules=[
            GradingRule(
                rule_type=GradingRuleType.REPLACEMENT,
                description="Final replaces Exam 1",
                source="Final Exam",
                target="Exam 1",
            )
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    unresolved = [f for f in result.findings if f.code == "unresolved_rule_reference"]
    assert len(unresolved) == 1
    assert unresolved[0].field == "Exam 1"


def test_resolved_rule_reference_passes():
    model = GradeModel(
        categories=[
            GradeCategory(name="Final Exam", weight=50),
            GradeCategory(name="Mid-term Exam", weight=35),
        ],
        rules=[
            GradingRule(
                rule_type=GradingRuleType.REPLACEMENT,
                description="Final replaces Midterm",
                source="Final Exam",
                target="Mid-term Exam",
            )
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert not any(f.code == "unresolved_rule_reference" for f in result.findings)


# --- non-deterministic rules --------------------------------------------------------


def test_curve_rule_is_always_non_deterministic():
    model = GradeModel(rules=[GradingRule(rule_type=GradingRuleType.CURVE, description="May be curved.")])
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    finding = next(f for f in result.findings if f.code == "non_deterministic_grading_rule")
    assert finding.severity.value == "warning"
    # non_deterministic_grading_rule no longer forces review on its own; this
    # bare model still needs review, but only because grading_method is
    # UNKNOWN (see test below for the isolated non-blocking case).
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    assert any(f.code == "grading_method_unknown" for f in result.findings)


def test_informational_rules_alone_do_not_force_review():
    """Curve / late-work / makeup rules, correctly extracted, are facts the
    student should see while calculating -- not ambiguities or missing data.
    Reclassified as non-blocking per the syllabus-review redesign
    (planning-docs/syllabus-review-redesign-spec.md §2C / §5). The findings
    are still emitted so the UI can render the Professor's Rules panel.
    """
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Exam", weight=100, evidence=evidence(1, "Exam: 100%"))],
        rules=[
            GradingRule(
                rule_type=GradingRuleType.CURVE,
                description="Grades may be curved.",
                evidence=evidence(1, "Grades may be curved."),
            ),
            GradingRule(
                rule_type=GradingRuleType.LATE_WORK,
                description="No late homework accepted.",
                evidence=evidence(1, "No late homework accepted."),
            ),
            GradingRule(
                rule_type=GradingRuleType.MAKEUP,
                description="Makeup work only for excused absences.",
                evidence=evidence(1, "Makeup work only for excused absences."),
            ),
        ],
        warnings=[
            ExtractionWarning(type=ExtractionWarningType.POSSIBLE_CURVE, description="No curve formula is given."),
            ExtractionWarning(type=ExtractionWarningType.AMBIGUOUS_RULE, description="Late-work policy phrasing is loose."),
        ],
    )
    content = content_from_pages(
        [
            page(
                1,
                "Exam: 100%\nGrades may be curved.\nNo late homework accepted.\n"
                "Makeup work only for excused absences.",
            )
        ]
    )
    result = reconcile_grade_model(model, content)
    assert result.status == ReconciliationStatus.ACCEPTED
    codes = {f.code for f in result.findings}
    assert "non_deterministic_grading_rule" in codes
    assert "possible_curve" in codes
    assert "ambiguous_rule" in codes


def test_replacement_rule_with_source_and_target_is_deterministic():
    model = GradeModel(
        categories=[
            GradeCategory(name="Final Exam", weight=50),
            GradeCategory(name="Mid-term Exam", weight=35),
        ],
        rules=[
            GradingRule(
                rule_type=GradingRuleType.REPLACEMENT,
                description="Final replaces Midterm",
                source="Final Exam",
                target="Mid-term Exam",
            )
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert not any(f.code == "non_deterministic_grading_rule" for f in result.findings)


def test_replacement_rule_without_source_or_target_is_non_deterministic():
    model = GradeModel(
        rules=[GradingRule(rule_type=GradingRuleType.REPLACEMENT, description="The final may replace another test.")]
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert any(f.code == "non_deterministic_grading_rule" for f in result.findings)


def test_extra_credit_rule_is_non_deterministic():
    model = GradeModel(
        rules=[GradingRule(rule_type=GradingRuleType.EXTRA_CREDIT, description="Extra credit may be offered.")]
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert any(f.code == "non_deterministic_grading_rule" for f in result.findings)


def test_non_deterministic_rule_field_is_unique_per_rule_instance():
    """field must be the rule's own index, not its rule_type -- multiple
    rules of the same type used to collapse onto an identical field value
    (e.g. three "other" rules all reporting field="other"), which made them
    indistinguishable to any caller (the frontend) trying to anchor a
    finding back to the one specific rule it's about.
    """
    model = GradeModel(
        rules=[
            GradingRule(rule_type=GradingRuleType.OTHER, description="First unclear rule."),
            GradingRule(rule_type=GradingRuleType.OTHER, description="Second unclear rule."),
            GradingRule(rule_type=GradingRuleType.OTHER, description="Third unclear rule."),
        ]
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    findings = [f for f in result.findings if f.code == "non_deterministic_grading_rule"]
    assert len(findings) == 3
    fields = [f.field for f in findings]
    assert fields == ["rules[0]", "rules[1]", "rules[2]"]
    assert len(set(fields)) == 3


# --- assessment-category reference --------------------------------------------------


def test_valid_assessment_category_reference_passes():
    model = GradeModel(
        categories=[GradeCategory(name="Lecture Quizzes", weight=5)],
        assessments=[Assessment(name="Quiz 1", category="Lecture Quizzes")],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert not any(f.code == "unresolved_assessment_category_reference" for f in result.findings)


def test_unresolved_assessment_category_reference_needs_review():
    model = GradeModel(assessments=[Assessment(name="Quiz 1", category="Nonexistent Category")])
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    assert any(f.code == "unresolved_assessment_category_reference" for f in result.findings)


# --- extraction warning mapping -----------------------------------------------------


def test_unknown_weight_alone_does_not_force_review():
    # unknown_weight is now non-blocking (NON_BLOCKING_WARNING_CODES):
    # category_weight_validation (the deterministic check on the same fact
    # -- do declared category weights sum to ~100) already gates confirm on
    # its own; unknown_weight is an unfalsifiable ExtractionWarning no
    # correction can clear (only DISMISS_WARNING touches GradeModel.warnings,
    # and category/set_weight -- the correction that actually answers the
    # question -- does not), so it stays purely informational. grading_
    # method is set explicitly WEIGHTED with a fully-weighted category so the
    # grading_method_unknown / category_weight_validation checks don't
    # confound this: unknown_weight must be the ONLY thing that could force
    # review here.
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Overall", weight=100, evidence=evidence(1, "Overall: 100%"))],
        warnings=[ExtractionWarning(type=ExtractionWarningType.UNKNOWN_WEIGHT, description="Weight not stated.")],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert any(f.code == "unknown_weight" for f in result.findings)
    assert result.status == ReconciliationStatus.ACCEPTED


def test_category_weight_validation_still_blocks_with_unknown_weight_present():
    # The deterministic check carries the gate on its own: a category whose
    # weight is genuinely unstated (weight=None, with a matching
    # unknown_weight warning) leaves the declared total under 100 --
    # category_weight_validation's own WARNING (not in NON_BLOCKING_
    # WARNING_CODES) still forces review, independent of whether
    # unknown_weight blocks anything.
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework", weight=35, evidence=evidence(1, "Homework: 35%")),
            GradeCategory(name="Midterm Exam", weight=None, count=2, evidence=evidence(1, "2 midterms")),
            GradeCategory(name="Final Exam", weight=35, evidence=evidence(1, "Final Exam: 35%")),
        ],
        warnings=[
            ExtractionWarning(
                type=ExtractionWarningType.UNKNOWN_WEIGHT,
                description="The total weight for the Midterm Exam category is not stated.",
                related_field="Midterm Exam",
            )
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    codes = {f.code for f in result.findings}
    assert "category_weight_validation" in codes
    assert "unknown_weight" in codes
    weight_finding = next(f for f in result.findings if f.code == "category_weight_validation")
    assert weight_finding.severity == ValidationSeverity.WARNING


def test_complete_weights_with_stale_unknown_weight_reaches_accepted():
    # Mirrors the CSCE 222 scenario after a category/set_weight correction:
    # the weight is now supplied and the categories sum to 100, but the
    # unknown_weight ExtractionWarning is stale (SET_WEIGHT never touches
    # GradeModel.warnings) and still present. It must not re-block.
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework", weight=35, evidence=evidence(1, "Homework: 35%")),
            GradeCategory(name="Midterm Exam", weight=30, count=2, evidence=evidence(1, "2 midterms")),
            GradeCategory(name="Final Exam", weight=35, evidence=evidence(1, "Final Exam: 35%")),
        ],
        warnings=[
            ExtractionWarning(
                type=ExtractionWarningType.UNKNOWN_WEIGHT,
                description="The total weight for the Midterm Exam category is not stated.",
                related_field="Midterm Exam",
            )
        ],
    )
    result = reconcile_grade_model(
        model, content_from_pages([page(1, "x")]), confirmed_category_value_claims={"midterm exam"}
    )
    assert any(f.code == "unknown_weight" for f in result.findings)
    weight_finding = next(f for f in result.findings if f.code == "category_weight_validation")
    assert weight_finding.severity == ValidationSeverity.VALID
    assert result.status == ReconciliationStatus.ACCEPTED


def test_missing_grade_scale_warning_alone_does_not_force_review():
    model = GradeModel(
        grading_method=GradingMethod.POINTS,
        warnings=[
            ExtractionWarning(type=ExtractionWarningType.MISSING_GRADE_SCALE, description="No grade scale given.")
        ],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert result.status == ReconciliationStatus.ACCEPTED


# --- grading method coherence --------------------------------------------------------


def test_unknown_grading_method_forces_review():
    model = GradeModel(grading_method=GradingMethod.UNKNOWN)
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    assert any(f.code == "grading_method_unknown" for f in result.findings)


def test_unknown_grading_method_is_never_reinterpreted():
    model = GradeModel(grading_method=GradingMethod.UNKNOWN)
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert result.grade_model.grading_method == GradingMethod.UNKNOWN


def test_weighted_with_all_null_weights_is_error():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Midterm", weight=None), GradeCategory(name="Final", weight=None)],
    )
    result = reconcile_grade_model(model, content_from_pages([page(1, "x")]))
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    weight_findings = [f for f in result.findings if f.code == "category_weight_validation"]
    assert weight_findings[0].severity.value == "error"


# --- missing course metadata does not gate acceptance (section 21) ------------------


def test_missing_course_metadata_does_not_force_review():
    model = clean_grade_model()
    model.course = CourseMetadata()  # everything null
    result = reconcile_grade_model(model, CLEAN_CONTENT)
    assert result.status == ReconciliationStatus.ACCEPTED


# --- contract / strictness -----------------------------------------------------------


def test_result_rejects_extra_fields():
    with pytest.raises(ValidationError):
        GradeModelReconciliationResult(
            status=ReconciliationStatus.ACCEPTED,
            grade_model=GradeModel(),
            evidence_coverage=EvidenceCoverage(total_claims=0, supported_claims=0, coverage_ratio=1.0),
            unexpected="oops",
        )


def test_result_preserves_original_grade_model_content():
    model = clean_grade_model()
    result = reconcile_grade_model(model, CLEAN_CONTENT)
    assert result.grade_model == model


# --- no mutation (section 33) -------------------------------------------------------


def test_reconciliation_does_not_mutate_grade_model():
    model = phys_207_grade_model(include_curve=True)
    before = model.model_dump(mode="json")
    reconcile_grade_model(model, PHYS_207_CONTENT)
    after = model.model_dump(mode="json")
    assert before == after


def test_reconciliation_does_not_mutate_relevant_content():
    content = content_from_pages(copy.deepcopy(PHYS_207_PAGES))
    before = content.model_dump(mode="json")
    reconcile_grade_model(phys_207_grade_model(include_curve=True), content)
    after = content.model_dump(mode="json")
    assert before == after


# --- determinism (section 32) ---------------------------------------------------------


def test_reconciliation_is_deterministic():
    model = phys_207_grade_model(include_curve=True)
    first = reconcile_grade_model(model, PHYS_207_CONTENT)
    second = reconcile_grade_model(model, PHYS_207_CONTENT)
    assert first == second
