"""Deterministic single-unknown target-score solving.

    solve_required_score(reconciliation, grade_state, target_component=..., target_grade=... | target_letter=...)
        -> TargetScoreResult

Solves for exactly ONE named component's required score. Every OTHER
component must already have a known score (actual, or an explicit
projected assumption the caller supplied in `grade_state`) -- if any other
component is unknown, this returns an explicit insufficient-information
result rather than guessing how to distribute unknowns (section 16 of the
Phase 6 task). No symbolic algebra library: the rule set is small enough
that a closed-form per-branch solve (see _solve_with_replacement_as_source)
is exact and simple.

REPLACEMENT-AWARE SOLVING
--------------------------
A naive "solve the plain weighted equation, then separately apply the
replacement rule" is wrong whenever the target component is itself the
rule's source: the replacement changes which weights apply to it exactly
at the threshold the student is trying to solve for (see PHYS 207's Final
Exam, which is 50% on its own AND additionally absorbs the 35% Mid-term
weight once it exceeds the Mid-term score). This module instead solves
both possible branches (rule inactive / rule active) and keeps whichever
branch's own solution is internally consistent with the branch's trigger
condition -- the approach the Phase 6 task itself suggests, no more
sophisticated than that.

Only the case where the SOLVED-FOR component is the replacement's SOURCE
is supported (the common "what do I need on X" question, and the only one
tested). Solving for a component that is a replacement's TARGET is
detected and explicitly rejected: the triggered branch makes that
component's own value irrelevant to the total (it gets overridden by the
other side), which is a fundamentally different, non-linear question this
module does not attempt to answer -- see _target_is_replaced_side.
"""

from typing import NoReturn

from GradusIQ_career.syllabus.calculator.engine import build_components
from GradusIQ_career.syllabus.calculator.models import (
    CalculationComponent,
    GradeInputValidationError,
    GradeModelStructureError,
    StudentGradeState,
    TargetScoreResult,
    UnsupportedRuleConditionError,
    require_accepted,
)
from GradusIQ_career.syllabus.calculator.rules import apply_deterministic_rules, looks_like_simple_greater_than
from GradusIQ_career.syllabus.models import GradeModel, GradingRule, GradingRuleType
from GradusIQ_career.syllabus.reconciliation import GradeModelReconciliationResult
from GradusIQ_career.syllabus.weighting import get_effective_course_weights

_ROUND_DIGITS = 2


def _round(value: float) -> float:
    return round(value, _ROUND_DIGITS)


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


def _find_component(components: list[CalculationComponent], name: str) -> CalculationComponent | None:
    normalized = _normalize_name(name)
    for component in components:
        if _normalize_name(component.name) == normalized:
            return component
    return None


def _find_threshold(grade_model: GradeModel, letter: str):
    normalized = letter.strip().lower()
    for threshold in grade_model.grade_thresholds:
        if threshold.letter.strip().lower() == normalized:
            return threshold
    return None


def _relevant_replacement_rules(grade_model: GradeModel, target_name: str) -> list[GradingRule]:
    normalized_target = _normalize_name(target_name)
    matches = []
    for rule in grade_model.rules:
        if rule.rule_type != GradingRuleType.REPLACEMENT or rule.source is None or rule.target is None:
            continue
        if _normalize_name(rule.source) == normalized_target or _normalize_name(rule.target) == normalized_target:
            matches.append(rule)
    return matches


def _fixed_contribution(components: list[CalculationComponent]) -> float:
    return sum(
        (c.effective_score * c.weight_percent / 100)
        for c in components
        if c.effective_score is not None and c.weight_percent is not None
    )


def _solve_linear(target_grade: float, target: CalculationComponent, fixed: list[CalculationComponent]) -> float:
    return (target_grade - _fixed_contribution(fixed)) * 100 / target.weight_percent


def _solve_with_replacement_as_source(
    target_grade: float,
    target: CalculationComponent,
    other: CalculationComponent,
    rest: list[CalculationComponent],
) -> tuple[float | None, bool]:
    """`target` is the replacement rule's SOURCE; `other` is the TARGET side
    (a known component whose effective score may be overridden by
    `target`'s score once it is higher). Returns (required_score,
    replacement_triggered_by_that_score) or (None, False) if neither
    branch's own solution satisfies its own trigger condition.
    """
    # Branch 1: replacement does not trigger (x <= other's score) -- `other`
    # keeps its own score, contributing at its own weight.
    x_no_trigger = _solve_linear(target_grade, target, rest + [other])
    if x_no_trigger <= other.effective_score:
        return x_no_trigger, False

    # Branch 2: replacement triggers (x > other's score) -- `other`'s weight
    # folds into `target`'s, since both now carry the same effective score.
    combined_weight = target.weight_percent + other.weight_percent
    x_trigger = (target_grade - _fixed_contribution(rest)) * 100 / combined_weight
    if x_trigger > other.effective_score:
        return x_trigger, True

    return None, False


def _target_is_replaced_side(grade_model: GradeModel, target_name: str, rule: GradingRule) -> bool:
    return _normalize_name(rule.target) == _normalize_name(target_name)


def _raise_for_missing_target(grade_model: GradeModel, target_component: str) -> NoReturn:
    """`target_component` did not match any built component. If it names a
    decomposable category, its own component was intentionally suppressed in
    favor of one per child assessment (see weighting._decomposition_children /
    engine._build_weighted_components) -- say so and name the children,
    matching the category-input rejection's wording. Otherwise it is simply
    unknown.
    """
    normalized = _normalize_name(target_component)
    effective = get_effective_course_weights(grade_model)
    for category in effective.decomposable_categories:
        if _normalize_name(category.name) == normalized:
            children = [
                a.name
                for a in effective.decomposed_assessments
                if a.category is not None and _normalize_name(a.category) == normalized
            ]
            raise GradeInputValidationError(
                f"category '{target_component}' is scored through its individual assessments in this "
                f"GradeModel; solve for one of its components instead: {', '.join(children)}"
            )
    raise GradeInputValidationError(f"unknown target_component: '{target_component}'")


def solve_required_score(
    reconciliation: GradeModelReconciliationResult,
    grade_state: StudentGradeState,
    *,
    target_component: str,
    target_grade: float | None = None,
    target_letter: str | None = None,
) -> TargetScoreResult:
    """Solve for the score `target_component` needs, given every other
    component's score is already known (actual or a supplied projection).
    Requires an ACCEPTED reconciliation result -- see models.require_accepted.
    """
    require_accepted(reconciliation)
    grade_model = reconciliation.grade_model

    if (target_grade is None) == (target_letter is None):
        raise GradeInputValidationError("solve_required_score requires exactly one of target_grade or target_letter")

    target_label: str | None = None
    if target_letter is not None:
        threshold = _find_threshold(grade_model, target_letter)
        if threshold is None:
            raise GradeInputValidationError(f"unknown grade threshold letter: '{target_letter}'")
        if threshold.minimum is None:
            raise GradeInputValidationError(
                f"threshold '{target_letter}' has no usable minimum; cannot solve a numeric target from it"
            )
        target_grade = threshold.minimum
        target_label = threshold.letter

    components, build_warnings = build_components(grade_model, grade_state)
    if not components:
        raise GradeModelStructureError(
            "the accepted GradeModel has no usable weighted/points components to calculate from"
        )
    components, applied_rules, rule_warnings = apply_deterministic_rules(grade_model, components)
    warnings = list(build_warnings) + list(rule_warnings)

    target = _find_component(components, target_component)
    if target is None:
        _raise_for_missing_target(grade_model, target_component)
    if target.weight_percent is None or target.weight_percent <= 0:
        raise GradeModelStructureError(f"'{target_component}' has no known positive weight; cannot solve for it")

    others = [c for c in components if c is not target]
    unknown_others = [c for c in others if c.effective_score is None]
    if unknown_others:
        warnings.append(
            "cannot solve: the following components have no actual or projected score and no "
            "assumption was supplied: " + ", ".join(c.name for c in unknown_others)
        )
        return TargetScoreResult(
            target_component=target.name,
            target_grade=target_grade,
            target_label=target_label,
            required_score=None,
            feasible=False,
            already_achieved=False,
            applied_rules=applied_rules,
            warnings=warnings,
        )

    relevant_rules = _relevant_replacement_rules(grade_model, target.name)
    triggered = False

    if not relevant_rules:
        required = _solve_linear(target_grade, target, others)
    elif len(relevant_rules) > 1:
        warnings.append(
            f"'{target.name}' is referenced by more than one replacement rule; solving with combined "
            "rule effects is not supported"
        )
        return TargetScoreResult(
            target_component=target.name,
            target_grade=target_grade,
            target_label=target_label,
            required_score=None,
            feasible=False,
            already_achieved=False,
            applied_rules=applied_rules,
            warnings=warnings,
        )
    else:
        rule = relevant_rules[0]
        if not looks_like_simple_greater_than(rule.condition):
            raise UnsupportedRuleConditionError(
                f"replacement rule condition '{rule.condition}' is not a recognized simple comparison; "
                "refusing to guess its meaning"
            )
        if _target_is_replaced_side(grade_model, target.name, rule):
            warnings.append(
                f"'{target.name}' is the TARGET of a replacement rule (its own score can be overridden "
                "by another component); solving for the replaced side is not supported -- solve for the "
                f"rule's source component ('{rule.source}') instead"
            )
            return TargetScoreResult(
                target_component=target.name,
                target_grade=target_grade,
                target_label=target_label,
                required_score=None,
                feasible=False,
                already_achieved=False,
                applied_rules=applied_rules,
                warnings=warnings,
            )
        other = _find_component(others, rule.target)
        if other is None:
            # Defensive: Phase 5 should already have blocked an unresolved
            # rule reference from reaching ACCEPTED (see reconciliation.py's
            # unresolved_rule_reference finding), but a hand-built or
            # bypassed reconciliation result could still reach here.
            warnings.append(
                f"replacement rule references '{rule.target}', which does not match a known component"
            )
            return TargetScoreResult(
                target_component=target.name,
                target_grade=target_grade,
                target_label=target_label,
                required_score=None,
                feasible=False,
                already_achieved=False,
                applied_rules=applied_rules,
                warnings=warnings,
            )
        rest = [c for c in others if c is not other]
        required, triggered = _solve_with_replacement_as_source(target_grade, target, other, rest)
        if triggered:
            warnings.append(
                f"solution assumes the replacement rule is active: '{target.name}' also replaces "
                f"'{other.name}' at this score"
            )
        if required is None:
            warnings.append(
                f"could not find a mathematically consistent branch for '{target.name}' under its "
                "replacement rule"
            )
            return TargetScoreResult(
                target_component=target.name,
                target_grade=target_grade,
                target_label=target_label,
                required_score=None,
                feasible=False,
                already_achieved=False,
                applied_rules=applied_rules,
                warnings=warnings,
            )

    already_achieved = required <= 0
    feasible = required <= 100

    if already_achieved:
        warnings.append(f"'{target.name}' target is already achieved under the supplied assumptions")
    elif not feasible:
        warnings.append(
            f"target is not achievable: a score of {_round(required)} on '{target.name}' would be required, "
            "which exceeds 100"
        )

    return TargetScoreResult(
        target_component=target.name,
        target_grade=target_grade,
        target_label=target_label,
        required_score=_round(required),
        feasible=feasible,
        already_achieved=already_achieved,
        applied_rules=applied_rules,
        warnings=warnings,
    )
