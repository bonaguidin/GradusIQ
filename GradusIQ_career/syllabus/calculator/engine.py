"""Deterministic current/projected grade calculation.

    ACCEPTED GradeModelReconciliationResult + StudentGradeState
        -> build_components() [weighted | points | hybrid]
        -> apply_deterministic_rules() [rules.py]
        -> breakdown arithmetic
        -> GradeCalculationResult

WHY CATEGORIES AND STANDALONE ASSESSMENTS, NEVER AGGREGATED
-------------------------------------------------------------
A GradeCategory (e.g. "Lecture Quizzes: 5%, count: null") is the primary,
always-safe way to score a weighted bucket whose internal composition is
unknown -- the student enters one category average directly. An Assessment
whose `.category` field names that same category is never used to
reconstruct the category's score: the schema does not establish how
multiple assessments combine within a category (equal weight? point
weighted? is this even the complete set?), and guessing at that is exactly
what Phase 1/5's "do not infer a count" and this phase's "do not guess
equal weighting" requirements forbid. An Assessment only participates
directly in a weighted calculation when it stands alone (no `.category`,
its own `.weight`) -- otherwise the syllabus's own category weight is the
only safe percentage to use, and the assessment is informational only in
Phase 6.

The single exception is a category the model PROVES decomposable (see
weighting._decomposition_children: every child weighted, child weights sum
to the parent's, stated count matches, no name collisions) FOR WHICH the
student supplied a score on at least one child assessment this request.
Only then does the calculator emit one ASSESSMENT component per child at
the child's own weight and drop the parent category component -- the
children's weights already sum to the parent's, so the course total and
_compute_breakdown's flat sum are unchanged. The decision is per
calculation, from grade_state alone: the same model scored by
CategoryScoreInput keeps its single parent component, exactly as before
(no migration). If both a category score and a child score name the same
category, the child scores win and a warning records that the category
score was ignored. A child of a category that is not decomposable (or not
decomposed this request) still cannot be scored directly.

WHY THE SAME MATH WORKS FOR WEIGHTED AND POINTS
--------------------------------------------------
Both engines reduce every component to (name, weight_percent, score 0-100).
For a points assessment, weight_percent = possible_points / total_possible
* 100 and score = earned_points / possible_points * 100. Substituting into
the shared weighted formula reproduces exactly the points formulas the
Phase 6 task specifies (current = earned / possible_completed * 100; final
= total_earned / total_possible * 100) -- so _compute_breakdown is written
once and reused by every grading method.
"""

from GradusIQ_career.syllabus.calculator.models import (
    AssessmentScoreInput,
    CalculationComponent,
    CategoryScoreInput,
    ComponentSourceType,
    GradeCalculationResult,
    GradeInputValidationError,
    GradeModelStructureError,
    ScoreStatus,
    StudentGradeState,
    UnsupportedGradingMethodError,
    UnsupportedGradingStructureError,
    require_accepted,
)
from GradusIQ_career.syllabus.calculator.rules import apply_deterministic_rules
from GradusIQ_career.syllabus.models import GradeModel, GradingMethod
from GradusIQ_career.syllabus.reconciliation import GradeModelReconciliationResult
from GradusIQ_career.syllabus.weighting import get_effective_course_weights

_ROUND_DIGITS = 2


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, _ROUND_DIGITS)


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


def classify_grade(grade_model: GradeModel, score: float | None) -> str | None:
    """Deterministic letter classification from GradeModel.grade_thresholds.

    Phase 5 already blocks overlapping thresholds from reaching ACCEPTED;
    a gap in the scale (no threshold covers `score`) is not an error, it
    just yields no letter.
    """
    if score is None:
        return None
    for threshold in grade_model.grade_thresholds:
        lo = threshold.minimum if threshold.minimum is not None else float("-inf")
        hi = threshold.maximum if threshold.maximum is not None else float("inf")
        if lo <= score <= hi:
            return threshold.letter
    return None


# ---------------------------------------------------------------------------
# Student-input validation and indexing (shared by every engine)
# ---------------------------------------------------------------------------


def _validate_and_index_category_inputs(
    grade_state: StudentGradeState, grade_model: GradeModel
) -> dict[str, CategoryScoreInput]:
    known = {_normalize_name(c.name) for c in grade_model.categories}
    result: dict[str, CategoryScoreInput] = {}
    for input_ in grade_state.category_scores:
        key = _normalize_name(input_.category_name)
        if key not in known:
            raise GradeInputValidationError(f"unknown category: '{input_.category_name}'")
        if key in result:
            raise GradeInputValidationError(f"duplicate category input: '{input_.category_name}'")
        result[key] = input_
    return result


def _validate_and_index_assessment_inputs(
    grade_state: StudentGradeState, grade_model: GradeModel
) -> dict[str, AssessmentScoreInput]:
    known = {_normalize_name(a.name) for a in grade_model.assessments}
    result: dict[str, AssessmentScoreInput] = {}
    for input_ in grade_state.assessment_scores:
        key = _normalize_name(input_.assessment_name)
        if key not in known:
            raise GradeInputValidationError(f"unknown assessment: '{input_.assessment_name}'")
        if key in result:
            raise GradeInputValidationError(f"duplicate assessment input: '{input_.assessment_name}'")
        result[key] = input_
    return result


# ---------------------------------------------------------------------------
# Component builders
# ---------------------------------------------------------------------------


def _build_weighted_components(
    grade_model: GradeModel, grade_state: StudentGradeState
) -> tuple[list[CalculationComponent], list[str]]:
    warnings: list[str] = []
    effective = get_effective_course_weights(grade_model)

    category_inputs = _validate_and_index_category_inputs(grade_state, grade_model)
    assessment_inputs = _validate_and_index_assessment_inputs(grade_state, grade_model)

    # Decomposition is decided per calculation, from what the student actually
    # supplied -- not baked into the model. A structurally decomposable
    # category (weighting._decomposition_children) only decomposes for THIS
    # request when the student supplied a score for at least one of its child
    # assessments. Otherwise it stays a single CATEGORY component, scored by a
    # CategoryScoreInput exactly as before -- so a course scored by category
    # keeps working untouched, with no migration.
    structural_children_by_key: dict[str, tuple] = {}
    for category in effective.decomposable_categories:
        key = _normalize_name(category.name)
        structural_children_by_key[key] = tuple(
            a
            for a in effective.decomposed_assessments
            if a.category is not None and _normalize_name(a.category) == key
        )

    decomposed_keys: set[str] = set()
    for key, children in structural_children_by_key.items():
        child_keys = {_normalize_name(c.name) for c in children}
        if assessment_inputs.keys() & child_keys:
            decomposed_keys.add(key)
            if key in category_inputs:
                # Precedence: children win, the category score is ignored.
                warnings.append(
                    f"category '{category_inputs[key].category_name}' has both a category score and "
                    "individual assessment scores; the assessment scores are used and the category "
                    "score is ignored"
                )

    decomposed_children = tuple(
        child for key in decomposed_keys for child in structural_children_by_key[key]
    )
    decomposed_names = {_normalize_name(a.name) for a in decomposed_children}

    for category in effective.categories_without_weight:
        warnings.append(f"category '{category.name}' has no known weight and is excluded from the calculation")
    for assessment in effective.category_scoped_weighted_assessments:
        if _normalize_name(assessment.name) in decomposed_names:
            continue  # this child is emitted as its own component this request
        warnings.append(
            f"assessment '{assessment.name}' has both a category ('{assessment.category}') and its own weight; "
            "Phase 6 does not know whether the category weight already includes it, so it is excluded -- enter "
            f"a category score for '{assessment.category}' directly instead"
        )

    standalone_names = {_normalize_name(a.name) for a in effective.standalone_weighted_assessments}
    directly_scoreable_assessment_names = standalone_names | decomposed_names
    non_standalone_names = {
        _normalize_name(a.name)
        for a in grade_model.assessments
        if _normalize_name(a.name) not in directly_scoreable_assessment_names
    }

    category_by_key = {_normalize_name(c.name): c for c in effective.weighted_categories}
    assessment_by_key = {_normalize_name(a.name): a for a in effective.standalone_weighted_assessments}
    for child in decomposed_children:
        # A decomposed category's children score exactly like standalone
        # weighted assessments: own weight, percentage input only.
        assessment_by_key[_normalize_name(child.name)] = child

    for key, input_ in assessment_inputs.items():
        if key in non_standalone_names:
            raise GradeInputValidationError(
                f"assessment '{input_.assessment_name}' cannot be scored directly in this weighted "
                "calculation (it belongs to a category, or has no known weight)"
            )
        if key in assessment_by_key and input_.is_points_based:
            raise GradeInputValidationError(
                f"assessment '{input_.assessment_name}' is weighted (percentage-based) in this "
                "GradeModel; earned_points input is not applicable"
            )

    components: list[CalculationComponent] = []
    for key, category in category_by_key.items():
        if key in decomposed_keys:
            continue  # emitted below as one component per child assessment
        input_ = category_inputs.get(key)
        score = input_.score if input_ is not None else None
        status = input_.status if input_ is not None else None
        components.append(
            CalculationComponent(
                name=category.name,
                source_type=ComponentSourceType.CATEGORY,
                status=status,
                original_score=score,
                effective_score=score,
                weight_percent=category.weight,
            )
        )
    for key, assessment in assessment_by_key.items():
        input_ = assessment_inputs.get(key)
        score = None
        status = None
        if input_ is not None:
            if input_.actual_score is not None:
                score, status = input_.actual_score, ScoreStatus.COMPLETED
            else:
                score, status = input_.projected_score, ScoreStatus.PROJECTED
        components.append(
            CalculationComponent(
                name=assessment.name,
                source_type=ComponentSourceType.ASSESSMENT,
                status=status,
                original_score=score,
                effective_score=score,
                weight_percent=assessment.weight,
            )
        )
    return components, warnings


def _build_points_components(
    grade_model: GradeModel, grade_state: StudentGradeState
) -> tuple[list[CalculationComponent], list[str]]:
    warnings: list[str] = []

    category_inputs = _validate_and_index_category_inputs(grade_state, grade_model)
    if category_inputs:
        raise GradeInputValidationError(
            "category scores were supplied, but grading_method is 'points'; points-based grading is "
            "calculated from individual assessments, not categories"
        )
    assessment_inputs = _validate_and_index_assessment_inputs(grade_state, grade_model)

    usable: list[tuple] = []
    for a in grade_model.assessments:
        key = _normalize_name(a.name)
        input_ = assessment_inputs.get(key)
        possible = a.points
        if possible is None and input_ is not None and input_.possible_points is not None:
            possible = input_.possible_points
        if possible is None:
            warnings.append(
                f"assessment '{a.name}' has no known possible-points value and is excluded from the "
                "points calculation"
            )
            continue
        usable.append((a, possible, input_))

    total_possible = sum(possible for _, possible, _ in usable)

    components: list[CalculationComponent] = []
    for a, possible, input_ in usable:
        weight_percent = (possible / total_possible * 100) if total_possible else None
        score: float | None = None
        status: ScoreStatus | None = None
        earned_points: float | None = None
        if input_ is not None:
            if input_.is_points_based:
                earned_points = input_.earned_points
                status = input_.points_status
                score = (earned_points / possible * 100) if possible else None
            elif input_.actual_score is not None:
                score, status = input_.actual_score, ScoreStatus.COMPLETED
            elif input_.projected_score is not None:
                score, status = input_.projected_score, ScoreStatus.PROJECTED
        components.append(
            CalculationComponent(
                name=a.name,
                source_type=ComponentSourceType.ASSESSMENT,
                status=status,
                original_score=score,
                effective_score=score,
                weight_percent=weight_percent,
                earned_points=earned_points,
                possible_points=possible,
            )
        )
    return components, warnings


def _build_hybrid_components(
    grade_model: GradeModel, grade_state: StudentGradeState
) -> tuple[list[CalculationComponent], list[str]]:
    """The only HYBRID structure Phase 6 supports: every scoreable
    component resolves to a percentage weight (categories and/or standalone
    weighted assessments), with no assessment relying on bare `.points` for
    its course share. That reduces to exactly the WEIGHTED engine. Any
    point-based assessment mixed into a HYBRID model has no established
    course-share weight in this schema, so that combination is rejected
    rather than guessed at.
    """
    if any(a.points is not None for a in grade_model.assessments):
        raise UnsupportedGradingStructureError(
            "hybrid grading with point-based assessments alongside weighted categories has no single "
            "unambiguous interpretation in the current schema; Phase 6 does not support it"
        )
    return _build_weighted_components(grade_model, grade_state)


def build_components(
    grade_model: GradeModel, grade_state: StudentGradeState
) -> tuple[list[CalculationComponent], list[str]]:
    if grade_model.grading_method == GradingMethod.WEIGHTED:
        return _build_weighted_components(grade_model, grade_state)
    if grade_model.grading_method == GradingMethod.POINTS:
        return _build_points_components(grade_model, grade_state)
    if grade_model.grading_method == GradingMethod.HYBRID:
        return _build_hybrid_components(grade_model, grade_state)
    raise UnsupportedGradingMethodError(
        f"grading_method '{grade_model.grading_method.value}' cannot be calculated; never guessed between "
        "weighted and points"
    )


# ---------------------------------------------------------------------------
# Breakdown arithmetic
# ---------------------------------------------------------------------------


def compute_breakdown(
    components: list[CalculationComponent],
) -> tuple[list[CalculationComponent], float, float, float | None, float | None]:
    """Returns (resolved components with contribution filled in,
    completed_weight, earned_course_percentage, current_grade, projected_grade).
    """
    completed_weight = 0.0
    completed_contribution = 0.0
    projected_contribution = 0.0
    all_known = True

    resolved: list[CalculationComponent] = []
    for component in components:
        contribution = None
        if component.effective_score is not None and component.weight_percent is not None:
            contribution = component.effective_score * component.weight_percent / 100
        resolved.append(component.model_copy(update={"contribution": contribution}))

        if component.effective_score is None:
            all_known = False
        else:
            projected_contribution += contribution or 0.0
            if component.status == ScoreStatus.COMPLETED:
                completed_weight += component.weight_percent or 0.0
                completed_contribution += contribution or 0.0

    current_grade = (completed_contribution / (completed_weight / 100)) if completed_weight > 0 else None
    projected_grade = projected_contribution if (all_known and components) else None

    return resolved, completed_weight, completed_contribution, current_grade, projected_grade


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def calculate_grade_projection(
    reconciliation: GradeModelReconciliationResult,
    grade_state: StudentGradeState,
) -> GradeCalculationResult:
    """The Phase 6 public entry point for current/projected grade
    calculation. Requires an ACCEPTED reconciliation result -- see
    models.require_accepted. Reads reconciliation.grade_model, never a
    bare GradeModel the caller might have edited out from under Phase 5.
    """
    require_accepted(reconciliation)
    grade_model = reconciliation.grade_model

    components, build_warnings = build_components(grade_model, grade_state)
    if not components:
        raise GradeModelStructureError(
            "the accepted GradeModel has no usable weighted/points components to calculate from"
        )

    components, applied_rules, rule_warnings = apply_deterministic_rules(grade_model, components)
    resolved, completed_weight, completed_contribution, current_grade, projected_grade = compute_breakdown(
        components
    )

    warnings = build_warnings + rule_warnings
    if projected_grade is None:
        missing = [c.name for c in resolved if c.effective_score is None]
        warnings.append("projected grade unavailable: no actual or projected score supplied for: " + ", ".join(missing))

    return GradeCalculationResult(
        grading_method=grade_model.grading_method,
        components=resolved,
        completed_weight=_round(completed_weight),
        earned_course_percentage=_round(completed_contribution),
        current_grade=_round(current_grade),
        projected_grade=_round(projected_grade),
        current_letter_grade=classify_grade(grade_model, current_grade),
        projected_letter_grade=classify_grade(grade_model, projected_grade),
        applied_rules=applied_rules,
        warnings=warnings,
    )
