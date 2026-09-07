"""Per-assessment scoring within a PROVABLY decomposable category.

A category is decomposable only when the model itself establishes how its
assessments compose (see weighting._decomposition_children):

  1. it has >= 1 Assessment naming it in `.category`;
  2. every such Assessment has a non-null `.weight`;
  3. those weights sum to the category weight within 0.01;
  4. a stated `.count` equals the number of such Assessments;

plus a structural guard against normalized-name collisions. When any of
these fails, behavior is exactly as before: the parent category is the
only component and its assessments stay informational.
"""

import pytest

from GradusIQ_career.syllabus.calculator import (
    AssessmentScoreInput,
    CategoryScoreInput,
    GradeInputValidationError,
    ScoreStatus,
    StudentGradeState,
    calculate_grade_projection,
    solve_required_score,
)
from GradusIQ_career.syllabus.models import (
    Assessment,
    GradeCategory,
    GradeModel,
    GradeThreshold,
    GradingMethod,
    GradingRule,
    GradingRuleType,
    SourceEvidence,
)
from GradusIQ_career.syllabus.reconciliation import (
    GradeModelReconciliationResult,
    ReconciliationStatus,
    reconcile_grade_model,
)
from GradusIQ_career.syllabus.relevance import RelevantPage, RelevantSyllabusContent
from GradusIQ_career.syllabus.validation import ValidationSeverity, validate_category_weights
from GradusIQ_career.syllabus.weighting import get_effective_course_weights


def evidence(text: str) -> SourceEvidence:
    return SourceEvidence(page=1, text=text, confidence=1.0)


def content_for(*texts: str) -> RelevantSyllabusContent:
    pages = [RelevantPage(page_number=i + 1, markdown=text, relevance_score=5.0) for i, text in enumerate(texts)]
    combined = "\n\n".join(f"<!-- page: {p.page_number} -->\n\n{p.markdown}" for p in pages)
    return RelevantSyllabusContent(
        selected_pages=pages,
        selected_sections=[],
        markdown=combined,
        source_page_count=len(pages),
        selected_page_count=len(pages),
    )


def accepted(
    grade_model: GradeModel,
    content: RelevantSyllabusContent,
    *,
    confirmed_category_value_claims: set[str] | None = None,
) -> GradeModelReconciliationResult:
    result = reconcile_grade_model(
        grade_model, content, confirmed_category_value_claims=confirmed_category_value_claims
    )
    assert result.status == ReconciliationStatus.ACCEPTED, result.findings
    return result


# --- CSCE 222's real stored shape ------------------------------------------------


CSCE_222_CONTENT = content_for(
    "Homework assignment (35%) 2 midterms midterm I (Sept. 24) midterm II (Oct. 29) final exam (35%) "
    "A = 90-100% B = 80-89% C = 70-79% D = 60-69% F = 0-59%"
)


def csce_222_model() -> GradeModel:
    """Shape of the real confirmed_grade_model row: 'midterm exam' weight 30 /
    count 2 with children 'midterm I' + 'midterm II' at 15 each, and a
    single-child 'final exam' whose one assessment shares its name. Threshold
    evidence texts are cleaned to parse (the real row reached ACCEPTED for F
    via a confirm_threshold_value correction instead).
    """
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework assignment", weight=35, evidence=evidence("Homework assignment (35%)")),
            GradeCategory(name="midterm exam", weight=30, count=2, evidence=evidence("2 midterms")),
            GradeCategory(name="final exam", weight=35, count=1, evidence=evidence("final exam (35%)")),
        ],
        assessments=[
            Assessment(
                name="midterm I",
                category="midterm exam",
                weight=15,
                date="Sept. 24",
                evidence=evidence("midterm I (Sept. 24)"),
            ),
            Assessment(
                name="midterm II",
                category="midterm exam",
                weight=15,
                date="Oct. 29",
                evidence=evidence("midterm II (Oct. 29)"),
            ),
            Assessment(name="final exam", category="final exam", weight=35, evidence=evidence("final exam (35%)")),
        ],
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90, maximum=100, evidence=evidence("A = 90-100%")),
            GradeThreshold(letter="B", minimum=80, maximum=89, evidence=evidence("B = 80-89%")),
            GradeThreshold(letter="C", minimum=70, maximum=79, evidence=evidence("C = 70-79%")),
            GradeThreshold(letter="D", minimum=60, maximum=69, evidence=evidence("D = 60-69%")),
            GradeThreshold(letter="F", minimum=0, maximum=59, evidence=evidence("F = 0-59%")),
        ],
    )


def test_csce_222_children_scorable_parent_not_emitted_total_still_100():
    model = csce_222_model()

    effective = get_effective_course_weights(model)
    assert {c.name for c in effective.decomposable_categories} == {"midterm exam", "final exam"}
    assert [a.name for a in effective.decomposed_assessments] == ["midterm I", "midterm II", "final exam"]
    # total_weight still counts the parent weight -- condition 3 makes that
    # identical to summing the children.
    assert effective.total_weight == 100.0
    assert validate_category_weights(model)[0].severity == ValidationSeverity.VALID

    reconciliation = accepted(
        model, CSCE_222_CONTENT, confirmed_category_value_claims={"midterm exam"}
    )
    state = StudentGradeState(
        category_scores=[CategoryScoreInput(category_name="Homework assignment", actual_score=95)],
        assessment_scores=[
            AssessmentScoreInput(assessment_name="midterm I", actual_score=90),
            AssessmentScoreInput(assessment_name="midterm II", actual_score=80),
            AssessmentScoreInput(assessment_name="final exam", actual_score=100),
        ],
    )
    result = calculate_grade_projection(reconciliation, state)

    by_name = {c.name: c for c in result.components}
    assert set(by_name) == {"Homework assignment", "midterm I", "midterm II", "final exam"}
    assert "midterm exam" not in by_name  # parent suppressed
    assert by_name["midterm I"].source_type.value == "assessment"
    assert by_name["midterm I"].weight_percent == 15.0
    assert by_name["midterm II"].weight_percent == 15.0
    assert by_name["final exam"].weight_percent == 35.0
    assert sum(c.weight_percent for c in result.components) == 100.0

    # no "has both a category and its own weight ... excluded" warning for the children
    assert not any("has both a category" in w for w in result.warnings)

    expected = 95 * 0.35 + 90 * 0.15 + 80 * 0.15 + 100 * 0.35
    assert result.projected_grade == round(expected, 2) == 93.75
    assert result.current_grade == round(expected, 2)


def test_csce_222_real_saved_state_scored_by_category_is_unchanged():
    """The actual saved grade_state for the live CSCE 222 row: a category
    score for every category, assessment_scores empty. Decomposition is
    per-request and keyed off child assessment scores, of which there are
    none -- so nothing decomposes, the three parent CATEGORY components are
    emitted exactly as before, and the result is identical to pre-change
    (current_grade 94.0, letter 'A'). No raise, no data loss.
    """
    reconciliation = accepted(
        csce_222_model(), CSCE_222_CONTENT, confirmed_category_value_claims={"midterm exam"}
    )
    state = StudentGradeState(
        category_scores=[
            CategoryScoreInput(category_name="Homework assignment", actual_score=100),
            CategoryScoreInput(category_name="midterm exam", actual_score=80),
            CategoryScoreInput(category_name="final exam", actual_score=100),
        ],
        assessment_scores=[],
    )
    result = calculate_grade_projection(reconciliation, state)

    assert [(c.name, c.source_type.value, c.weight_percent) for c in result.components] == [
        ("Homework assignment", "category", 35.0),
        ("midterm exam", "category", 30.0),
        ("final exam", "category", 35.0),
    ]
    assert result.current_grade == 94.0
    assert result.current_letter_grade == "A"
    assert result.projected_grade == 94.0
    assert not any("ignored" in w for w in result.warnings)


def test_csce_222_child_scores_only_decomposes():
    reconciliation = accepted(
        csce_222_model(), CSCE_222_CONTENT, confirmed_category_value_claims={"midterm exam"}
    )
    state = StudentGradeState(
        category_scores=[CategoryScoreInput(category_name="Homework assignment", actual_score=100)],
        assessment_scores=[
            AssessmentScoreInput(assessment_name="midterm I", actual_score=80),
            AssessmentScoreInput(assessment_name="midterm II", actual_score=80),
            AssessmentScoreInput(assessment_name="final exam", actual_score=100),
        ],
    )
    result = calculate_grade_projection(reconciliation, state)

    by_name = {c.name: c.source_type.value for c in result.components}
    assert by_name == {
        "Homework assignment": "category",
        "midterm I": "assessment",
        "midterm II": "assessment",
        "final exam": "assessment",
    }
    assert "midterm exam" not in by_name
    assert result.current_grade == 94.0  # 100*.35 + 80*.15 + 80*.15 + 100*.35


def test_csce_222_both_category_and_child_scores_children_win_with_warning():
    reconciliation = accepted(
        csce_222_model(), CSCE_222_CONTENT, confirmed_category_value_claims={"midterm exam"}
    )
    state = StudentGradeState(
        category_scores=[
            CategoryScoreInput(category_name="Homework assignment", actual_score=100),
            CategoryScoreInput(category_name="midterm exam", actual_score=50),  # should be ignored
            CategoryScoreInput(category_name="final exam", actual_score=100),
        ],
        assessment_scores=[
            AssessmentScoreInput(assessment_name="midterm I", actual_score=80),
            AssessmentScoreInput(assessment_name="midterm II", actual_score=80),
        ],
    )
    result = calculate_grade_projection(reconciliation, state)

    by_name = {c.name: c for c in result.components}
    # 'midterm exam' decomposed (child scores present); 'final exam' did NOT
    # (no child score for it) and keeps its category score.
    assert by_name["midterm I"].source_type.value == "assessment"
    assert by_name["midterm II"].effective_score == 80.0
    assert "midterm exam" not in by_name
    assert by_name["final exam"].source_type.value == "category"
    assert by_name["final exam"].effective_score == 100.0

    assert any(
        "midterm exam" in w and "category score is ignored" in w for w in result.warnings
    )
    # the ignored 50 never reached the math: 100*.35 + 80*.15 + 80*.15 + 100*.35
    assert result.current_grade == 94.0


def test_same_model_switches_decomposition_between_two_calculations():
    reconciliation = accepted(
        csce_222_model(), CSCE_222_CONTENT, confirmed_category_value_claims={"midterm exam"}
    )

    by_category = calculate_grade_projection(
        reconciliation,
        StudentGradeState(
            category_scores=[
                CategoryScoreInput(category_name="Homework assignment", actual_score=100),
                CategoryScoreInput(category_name="midterm exam", actual_score=80),
                CategoryScoreInput(category_name="final exam", actual_score=100),
            ]
        ),
    )
    assert {c.name for c in by_category.components} == {"Homework assignment", "midterm exam", "final exam"}
    assert by_category.current_grade == 94.0

    by_children = calculate_grade_projection(
        reconciliation,
        StudentGradeState(
            category_scores=[CategoryScoreInput(category_name="Homework assignment", actual_score=100)],
            assessment_scores=[
                AssessmentScoreInput(assessment_name="midterm I", actual_score=70),
                AssessmentScoreInput(assessment_name="midterm II", actual_score=90),
                AssessmentScoreInput(assessment_name="final exam", actual_score=100),
            ],
        ),
    )
    assert {c.name for c in by_children.components} == {
        "Homework assignment",
        "midterm I",
        "midterm II",
        "final exam",
    }
    assert by_children.current_grade == 94.0  # 100*.35 + 70*.15 + 90*.15 + 100*.35

    # and back to category scoring on the very same reconciliation object
    again = calculate_grade_projection(
        reconciliation,
        StudentGradeState(
            category_scores=[
                CategoryScoreInput(category_name="Homework assignment", actual_score=100),
                CategoryScoreInput(category_name="midterm exam", actual_score=80),
                CategoryScoreInput(category_name="final exam", actual_score=100),
            ]
        ),
    )
    assert [(c.name, c.source_type.value) for c in again.components] == [
        ("Homework assignment", "category"),
        ("midterm exam", "category"),
        ("final exam", "category"),
    ]
    assert again.current_grade == 94.0


# --- each gate condition failing independently -> unchanged behavior ------------


def _two_midterm_model(
    *,
    child_weights: tuple[float | None, float | None] = (15.0, 15.0),
    category_weight: float | None = 30.0,
    count: int | None = 2,
    child_names: tuple[str, str] = ("Midterm 1", "Midterm 2"),
) -> GradeModel:
    w1, w2 = child_weights
    n1, n2 = child_names
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework", weight=70, evidence=evidence("Homework: 70%")),
            GradeCategory(
                name="Midterms",
                weight=category_weight,
                count=count,
                evidence=evidence(f"Midterms: {category_weight}%" if category_weight is not None else "2 midterms"),
            ),
        ],
        assessments=[
            Assessment(name=n1, category="Midterms", weight=w1, evidence=evidence(f"{n1}")),
            Assessment(name=n2, category="Midterms", weight=w2, evidence=evidence(f"{n2}")),
        ],
    )


def _assert_not_decomposable_and_unchanged(model: GradeModel) -> None:
    effective = get_effective_course_weights(model)
    assert effective.decomposable_categories == ()
    assert effective.decomposed_assessments == ()

    # A category-scoped child still cannot be scored directly.
    content = content_for("Homework: 70% Midterms Midterm 1 Midterm 2")
    result = reconcile_grade_model(model, content)
    if result.status == ReconciliationStatus.ACCEPTED:
        state = StudentGradeState(
            assessment_scores=[AssessmentScoreInput(assessment_name="Midterm 1", actual_score=80)]
        )
        with pytest.raises(GradeInputValidationError, match="belongs to a category"):
            calculate_grade_projection(result, state)


def test_gate_condition_2_fails_child_missing_weight():
    _assert_not_decomposable_and_unchanged(_two_midterm_model(child_weights=(15.0, None)))


def test_gate_condition_3_fails_children_do_not_sum_to_parent():
    _assert_not_decomposable_and_unchanged(_two_midterm_model(child_weights=(15.0, 10.0)))


def test_gate_condition_4_fails_stated_count_mismatches_children():
    _assert_not_decomposable_and_unchanged(_two_midterm_model(count=3))


def test_gate_condition_1_fails_category_has_no_child_assessments():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework", weight=70, evidence=evidence("Homework: 70%")),
            GradeCategory(name="Midterms", weight=30, count=2, evidence=evidence("2 midterms")),
        ],
    )
    effective = get_effective_course_weights(model)
    assert effective.decomposable_categories == ()


def test_parent_weight_null_is_never_decomposable():
    # Even if children carry weights, a category with no weight of its own
    # has nothing for condition 3 to check against.
    _assert_not_decomposable_and_unchanged(_two_midterm_model(category_weight=None, count=None))


def test_tolerance_boundary_sum_within_0_01_still_decomposes():
    model = _two_midterm_model(child_weights=(15.0, 15.005), category_weight=30.0)
    effective = get_effective_course_weights(model)
    assert {c.name for c in effective.decomposable_categories} == {"Midterms"}


# --- structural collision guard ------------------------------------------------


def test_name_collision_with_standalone_assessment_blocks_decomposition():
    """A standalone 'Exam' and a category-scoped 'Exam' (distinct only by
    date, so reconciliation does NOT flag them as duplicates) reach the
    calculator together. Decomposing 'Exams' would make the child collide
    with the standalone in `assessment_by_key` and silently drop one, so
    the guard declines: behavior stays exactly as today.
    """
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework", weight=40, evidence=evidence("Homework: 40%")),
            GradeCategory(name="Exams", weight=20, count=1, evidence=evidence("Exams: 20%")),
        ],
        assessments=[
            Assessment(name="Exam", weight=40, evidence=evidence("Exam: 40%")),
            Assessment(
                name="Exam", category="Exams", weight=20, date="May 1", evidence=evidence("Exam (May 1): 20%")
            ),
        ],
    )
    effective = get_effective_course_weights(model)
    assert effective.decomposable_categories == ()
    assert effective.total_weight == 100.0

    content = content_for("Homework: 40% Exams: 20% Exam: 40% Exam (May 1): 20%")
    reconciliation = reconcile_grade_model(model, content)
    assert reconciliation.status == ReconciliationStatus.ACCEPTED, reconciliation.findings

    result = calculate_grade_projection(
        reconciliation,
        StudentGradeState(
            category_scores=[
                CategoryScoreInput(category_name="Homework", actual_score=100),
                CategoryScoreInput(category_name="Exams", actual_score=90),
            ],
            assessment_scores=[AssessmentScoreInput(assessment_name="Exam", actual_score=85)],
        ),
    )
    by_name = {(c.name, c.source_type.value) for c in result.components}
    # parent 'Exams' category component is still emitted; standalone 'Exam' too
    assert ("Exams", "category") in by_name
    assert ("Exam", "assessment") in by_name
    assert sum(c.weight_percent for c in result.components) == 100.0


def test_child_name_equal_to_its_own_parent_still_decomposes():
    # CSCE 222's 'final exam' case in isolation: a single child whose name
    # matches its parent category is NOT a collision -- the parent is
    # suppressed, so only the child component remains.
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework", weight=65, evidence=evidence("Homework: 65%")),
            GradeCategory(name="Final Exam", weight=35, count=1, evidence=evidence("Final Exam: 35%")),
        ],
        assessments=[
            Assessment(name="Final Exam", category="Final Exam", weight=35, evidence=evidence("Final Exam: 35%")),
        ],
    )
    effective = get_effective_course_weights(model)
    assert {c.name for c in effective.decomposable_categories} == {"Final Exam"}


# --- partial entry ------------------------------------------------------------


def test_partial_entry_one_child_scored_one_not():
    reconciliation = accepted(
        csce_222_model(), CSCE_222_CONTENT, confirmed_category_value_claims={"midterm exam"}
    )
    state = StudentGradeState(
        category_scores=[CategoryScoreInput(category_name="Homework assignment", actual_score=100)],
        assessment_scores=[
            AssessmentScoreInput(assessment_name="midterm I", actual_score=80),
            AssessmentScoreInput(assessment_name="final exam", actual_score=100),
            # midterm II deliberately omitted
        ],
    )
    result = calculate_grade_projection(reconciliation, state)

    by_name = {c.name: c for c in result.components}
    assert by_name["midterm II"].effective_score is None
    assert by_name["midterm II"].status is None

    # unscored sibling -> no projected grade, current renormalizes over the
    # completed 85% of the course. No special-casing of the decomposed group.
    assert result.projected_grade is None
    completed_contribution = 100 * 0.35 + 80 * 0.15 + 100 * 0.35
    assert result.current_grade == round(completed_contribution / 0.85, 2)


# --- rules see the nested components -----------------------------------------


def replacement_on_child_model() -> GradeModel:
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework", weight=70, evidence=evidence("Homework: 70%")),
            GradeCategory(name="Midterms", weight=30, count=2, evidence=evidence("Midterms: 30%")),
        ],
        assessments=[
            Assessment(name="Midterm 1", category="Midterms", weight=15, evidence=evidence("Midterm 1: 15%")),
            Assessment(name="Midterm 2", category="Midterms", weight=15, evidence=evidence("Midterm 2: 15%")),
        ],
        rules=[
            GradingRule(
                rule_type=GradingRuleType.REPLACEMENT,
                description="Midterm 2 replaces Midterm 1 when higher",
                source="Midterm 2",
                target="Midterm 1",
                evidence=evidence("Midterm 2 replaces Midterm 1 when higher"),
            )
        ],
    )


REPLACEMENT_CONTENT = content_for(
    "Homework: 70% Midterms: 30% Midterm 1: 15% Midterm 2: 15% Midterm 2 replaces Midterm 1 when higher"
)


def test_replacement_rule_targeting_a_decomposed_child_fires():
    reconciliation = accepted(replacement_on_child_model(), REPLACEMENT_CONTENT)
    state = StudentGradeState(
        category_scores=[CategoryScoreInput(category_name="Homework", actual_score=100)],
        assessment_scores=[
            AssessmentScoreInput(assessment_name="Midterm 1", actual_score=60),
            AssessmentScoreInput(assessment_name="Midterm 2", actual_score=90),
        ],
    )
    result = calculate_grade_projection(reconciliation, state)

    assert [(r.rule_type.value, r.source, r.target, r.changed_calculation) for r in result.applied_rules] == [
        ("replacement", "Midterm 2", "Midterm 1", True)
    ]
    by_name = {c.name: c for c in result.components}
    assert by_name["Midterm 1"].original_score == 60.0
    assert by_name["Midterm 1"].effective_score == 90.0  # lifted by the rule
    expected = 100 * 0.70 + 90 * 0.15 + 90 * 0.15
    assert result.projected_grade == round(expected, 2) == 97.0


# --- solver -----------------------------------------------------------------


def test_solver_solves_for_a_decomposed_child():
    reconciliation = accepted(
        csce_222_model(), CSCE_222_CONTENT, confirmed_category_value_claims={"midterm exam"}
    )
    state = StudentGradeState(
        category_scores=[CategoryScoreInput(category_name="Homework assignment", actual_score=95)],
        assessment_scores=[
            AssessmentScoreInput(assessment_name="midterm II", actual_score=80),
            AssessmentScoreInput(assessment_name="final exam", actual_score=100),
        ],
    )
    result = solve_required_score(reconciliation, state, target_component="midterm I", target_grade=90)
    assert result.target_component == "midterm I"
    # 95*.35 + 80*.15 + 100*.35 = 80.25 fixed; (90 - 80.25) / 0.15 = 65.0
    assert result.required_score == 65.0
    assert result.feasible is True


def test_solver_cannot_target_a_suppressed_parent_category():
    reconciliation = accepted(
        csce_222_model(), CSCE_222_CONTENT, confirmed_category_value_claims={"midterm exam"}
    )
    state = StudentGradeState(
        category_scores=[CategoryScoreInput(category_name="Homework assignment", actual_score=95)],
        assessment_scores=[
            AssessmentScoreInput(assessment_name="midterm I", actual_score=90),
            AssessmentScoreInput(assessment_name="midterm II", actual_score=80),
        ],
    )
    # The parent 'midterm exam' is no longer a component; the error says why
    # and names the children, in the category-input rejection's wording --
    # not the misleading "unknown target_component".
    with pytest.raises(GradeInputValidationError) as excinfo:
        solve_required_score(reconciliation, state, target_component="midterm exam", target_grade=90)
    message = str(excinfo.value)
    assert "scored through its individual assessments" in message
    assert "midterm I" in message and "midterm II" in message
    assert "unknown target_component" not in message


def test_solver_unknown_target_still_reports_unknown():
    reconciliation = accepted(
        csce_222_model(), CSCE_222_CONTENT, confirmed_category_value_claims={"midterm exam"}
    )
    with pytest.raises(GradeInputValidationError, match="unknown target_component: 'not a thing'"):
        solve_required_score(
            reconciliation, StudentGradeState(), target_component="not a thing", target_grade=90
        )


# --- determinism -----------------------------------------------------------


def test_decomposition_is_deterministic():
    model = csce_222_model()
    first = get_effective_course_weights(model)
    second = get_effective_course_weights(model)
    assert [c.name for c in first.decomposable_categories] == [c.name for c in second.decomposable_categories]
    assert [a.name for a in first.decomposed_assessments] == [a.name for a in second.decomposed_assessments]
