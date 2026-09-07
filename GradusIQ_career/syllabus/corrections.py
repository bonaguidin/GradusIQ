"""Deterministic, typed student corrections applied to an extracted GradeModel.

    extracted GradeModel + list[GradeModelCorrection]
        -> apply_grade_model_corrections() -> candidate GradeModel

Pure domain logic: no LLM, no DB, no network. `apply_grade_model_corrections`
never mutates its input -- every step reconstructs through pydantic
validation (never `model_copy(update=...)`, which bypasses field/model
validators in pydantic v2), so an invalid correction (negative weight, bad
enum, an inverted threshold) fails the SAME way constructing that GradeModel
directly would. All corrections in one call apply atomically: any failure
raises before anything is returned, so a caller never receives a
partially-corrected model.

STABLE IDENTIFIERS, NOT LIST INDEXES
--------------------------------------
Categories/assessments are addressed by name (normalized, matching
reconciliation.py's convention), thresholds by letter -- Phase 1 already
requires these to exist and be meaningful. Rules have no such natural key
in the Phase 1 schema (no name, and source/target are often exactly what
needs correcting), so rule corrections are addressed by their position in
GradeModel.rules. This is stable within one extracted revision (rules are
never reordered by anything in this pipeline) but not a persistence-layer
identity across re-extraction -- a known Phase 7 limitation, not solved by
adding an ID field to the Phase 1 schema (see Phase 6.5's precedent of
keeping persistence-layer concerns out of GradeModel).
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from GradusIQ_career.syllabus.cutoff_resolution import resolve_cutoff_overlaps
from GradusIQ_career.syllabus.models import GradeModel, GradingMethod, StrictModel


class CorrectionTargetType(str, Enum):
    CATEGORY = "category"
    ASSESSMENT = "assessment"
    THRESHOLD = "threshold"
    RULE = "rule"
    GRADING_METHOD = "grading_method"
    WARNING = "warning"


class CorrectionOperation(str, Enum):
    RENAME = "rename"
    SET_WEIGHT = "set_weight"
    SET_COUNT = "set_count"
    SET_POINTS = "set_points"
    SET_DATE = "set_date"
    SET_CATEGORY_REFERENCE = "set_category_reference"
    CLEAR_CATEGORY_REFERENCE = "clear_category_reference"
    SET_MINIMUM = "set_minimum"
    SET_MAXIMUM = "set_maximum"
    RESOLVE_CUTOFF_OVERLAP = "resolve_cutoff_overlap"
    CONFIRM_THRESHOLD_VALUE = "confirm_threshold_value"
    CONFIRM_CATEGORY_VALUE = "confirm_category_value"
    SET_SOURCE = "set_source"
    SET_TARGET = "set_target"
    SET_CONDITION = "set_condition"
    REMOVE_RULE = "remove_rule"
    CONFIRM_RULE = "confirm_rule"
    SET_GRADING_METHOD = "set_grading_method"
    DISMISS_WARNING = "dismiss_warning"


# Evidence provenance is never a student-editable field -- see module
# docstring on the extracted-vs-confirmed data-ownership rule. No operation
# above touches `evidence`, and none is added here.


class GradeModelCorrection(StrictModel):
    """One correction operation. Exactly one identifier field is populated,
    matching `target_type` -- validated in apply_grade_model_corrections
    (not here) so the error mentions the specific correction and its index
    in the caller's list.
    """

    target_type: CorrectionTargetType
    operation: CorrectionOperation
    category_name: str | None = None
    assessment_name: str | None = None
    threshold_letter: str | None = None
    rule_index: int | None = Field(default=None, ge=0)
    warning_index: int | None = Field(default=None, ge=0)
    value: Any = None


class CorrectionApplicationError(ValueError):
    """A correction could not be applied: unknown target, wrong operation
    for the target type, an invalid value, or a resulting field that fails
    GradeModel's own validation (negative weight, inverted threshold, an
    unrecognized enum, ...).
    """


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


def _replace_validated(instance: BaseModel, **updates: Any) -> BaseModel:
    """Reconstruct `instance` with `updates` applied, through full pydantic
    validation -- unlike `model_copy(update=...)`, which does not re-run
    validators.
    """
    data = instance.model_dump(mode="json")
    data.update(updates)
    try:
        return type(instance).model_validate(data)
    except Exception as exc:  # pydantic.ValidationError, or a raised ValueError from a model_validator
        raise CorrectionApplicationError(str(exc)) from exc


def _require_str(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorrectionApplicationError(f"{field} requires a non-empty string value, got {value!r}")
    return value


def _require_str_or_none(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field=field)


def _require_number_or_none(value: Any, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CorrectionApplicationError(f"{field} requires a numeric value or null, got {value!r}")
    return float(value)


def _require_int_or_none(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CorrectionApplicationError(f"{field} requires an integer value or null, got {value!r}")
    return value


def _find_by_name(items: list, name: str | None, *, kind: str):
    if name is None:
        raise CorrectionApplicationError(f"{kind} correction requires {kind}_name")
    normalized = _normalize_name(name)
    for index, item in enumerate(items):
        if _normalize_name(item.name) == normalized:
            return index, item
    raise CorrectionApplicationError(f"unknown {kind}: '{name}'")


def _apply_category_correction(model: GradeModel, correction: GradeModelCorrection) -> GradeModel:
    index, category = _find_by_name(model.categories, correction.category_name, kind="category")
    op = correction.operation
    if op == CorrectionOperation.CONFIRM_CATEGORY_VALUE:
        # "Yes, that value is what the syllabus says": the student affirms an
        # extracted category weight reconciliation could not deterministically
        # verify against its cited evidence text. A NO-OP on the GradeModel --
        # same shape as CONFIRM_THRESHOLD_VALUE (corrections.py's threshold
        # equivalent): the category and its verbatim evidence are left
        # exactly as extracted. _find_by_name above already validated the
        # category exists, so there is nothing further to check here -- the
        # affirmation's only effect is downstream, where reconcile_grade_
        # model suppresses claim_evidence_consistency_unverifiable for this
        # category via its confirmed_category_value_claims argument. Unlike
        # CONFIRM_THRESHOLD_VALUE, this does NOT also suppress a
        # claim_evidence_value_mismatch -- see
        # reconciliation._check_category_weight_consistency for why.
        return model
    if op == CorrectionOperation.RENAME:
        updated = _replace_validated(category, name=_require_str(correction.value, field="rename"))
    elif op == CorrectionOperation.SET_WEIGHT:
        updated = _replace_validated(category, weight=_require_number_or_none(correction.value, field="set_weight"))
    elif op == CorrectionOperation.SET_COUNT:
        updated = _replace_validated(category, count=_require_int_or_none(correction.value, field="set_count"))
    else:
        raise CorrectionApplicationError(f"unsupported operation '{op.value}' for target_type 'category'")
    categories = list(model.categories)
    categories[index] = updated
    return _replace_validated(model, categories=[c.model_dump(mode="json") for c in categories])


def _apply_assessment_correction(model: GradeModel, correction: GradeModelCorrection) -> GradeModel:
    index, assessment = _find_by_name(model.assessments, correction.assessment_name, kind="assessment")
    op = correction.operation
    if op == CorrectionOperation.RENAME:
        updated = _replace_validated(assessment, name=_require_str(correction.value, field="rename"))
    elif op == CorrectionOperation.SET_WEIGHT:
        updated = _replace_validated(assessment, weight=_require_number_or_none(correction.value, field="set_weight"))
    elif op == CorrectionOperation.SET_POINTS:
        updated = _replace_validated(assessment, points=_require_number_or_none(correction.value, field="set_points"))
    elif op == CorrectionOperation.SET_DATE:
        updated = _replace_validated(assessment, date=_require_str_or_none(correction.value, field="set_date"))
    elif op == CorrectionOperation.SET_CATEGORY_REFERENCE:
        new_category = _require_str(correction.value, field="set_category_reference")
        if not any(_normalize_name(c.name) == _normalize_name(new_category) for c in model.categories):
            raise CorrectionApplicationError(f"unknown category reference: '{new_category}'")
        updated = _replace_validated(assessment, category=new_category)
    elif op == CorrectionOperation.CLEAR_CATEGORY_REFERENCE:
        updated = _replace_validated(assessment, category=None)
    else:
        raise CorrectionApplicationError(f"unsupported operation '{op.value}' for target_type 'assessment'")
    assessments = list(model.assessments)
    assessments[index] = updated
    return _replace_validated(model, assessments=[a.model_dump(mode="json") for a in assessments])


def _apply_resolve_cutoff_overlap(model: GradeModel, normalized_letter: str, raw_letter: str) -> GradeModel:
    """"Higher grade wins the tie": the student accepts the proposed default
    for one overlapping cutoff pair (spec §2A).

    This is a NO-OP on the GradeModel -- like CONFIRM_RULE. The thresholds
    are left exactly as extracted (so their verbatim evidence text never
    goes stale, i.e. no claim_evidence_value_mismatch is introduced).
    classify_grade already assigns a boundary score to the higher letter
    grade for a canonically-ordered threshold list (first match wins), and
    reconcile_grade_model suppresses the overlapping_grade_thresholds ERROR
    for a pair the student has confirmed (see its confirmed_cutoff_pairs
    argument -- the record of "which pairs" is carried by the correction
    list itself, threaded through by service.apply_student_corrections).

    Still validated here: `threshold_letter` (either letter of the pair)
    must belong to an overlap the resolver classifies as cleanly resolvable
    -- anything it leaves `unresolved` (non-adjacent, multi-way,
    wider-than-a-point, single-bound) is rejected, pointing the student at a
    manual set_minimum / set_maximum instead.
    """
    resolution = resolve_cutoff_overlaps(model.grade_thresholds)
    match = next(
        (r for r in resolution.resolved if normalized_letter in (r.winner.strip().lower(), r.loser.strip().lower())),
        None,
    )
    if match is None:
        raise CorrectionApplicationError(
            f"no cleanly resolvable cutoff overlap involves threshold '{raw_letter}'; "
            "set the boundary manually with a set_minimum / set_maximum correction instead"
        )
    return model


def _apply_confirm_threshold_value(model: GradeModel, normalized_letter: str, raw_letter: str) -> GradeModel:
    """"Yes, that value is what the syllabus says": the student affirms an
    extracted threshold value that reconciliation could not deterministically
    verify against its cited evidence text (claim_evidence_consistency_
    unverifiable), or that the deterministic check read as a mismatch
    (claim_evidence_value_mismatch -- e.g. after the student narrowed the
    bound themselves via SET_MAXIMUM, moving it off the verbatim "< 90%").

    A NO-OP on the GradeModel -- like RESOLVE_CUTOFF_OVERLAP / CONFIRM_RULE.
    The threshold and its verbatim evidence are left exactly as extracted;
    the affirmation's only effect is downstream, where reconcile_grade_model
    suppresses that one finding for this letter (see its
    confirmed_value_claims argument -- the record of "which letters" is
    carried by the correction list itself, threaded through by
    service.apply_student_corrections).

    Validated here: the letter must name an existing threshold. Beyond that
    this is deliberately tolerant -- a letter with no open
    claim_evidence_consistency_unverifiable / claim_evidence_value_mismatch
    finding is a NO-OP, not an error. Two reasons:

    * With no finding, reconcile_grade_model's confirmed_value_claims has
      nothing to suppress for this letter, so recording the affirmation or
      not is downstream-inert -- there is no wrong outcome to guard against.
    * This op is also submitted programmatically. The unified cutoff table
      appends a CONFIRM_THRESHOLD_VALUE for every letter it just edited via
      SET_MINIMUM / SET_MAXIMUM, so a student who types a bound is never
      re-prompted to affirm the value they just entered. That edit may or
      may not leave a residual finding -- a single-bound threshold, one with
      no citable evidence text, or an edit that now matches the cited range
      all leave none -- and the auto-appended confirmation must not fail the
      whole atomic batch when it doesn't.
    """
    threshold = next(
        (t for t in model.grade_thresholds if t.letter.strip().lower() == normalized_letter), None
    )
    if threshold is None:
        raise CorrectionApplicationError(f"unknown threshold letter: '{raw_letter}'")
    # A residual unverified value claim is not a precondition -- see docstring.
    # The affirmation is a validated no-op whether or not one currently exists.
    return model


def _apply_threshold_correction(model: GradeModel, correction: GradeModelCorrection) -> GradeModel:
    if correction.threshold_letter is None:
        raise CorrectionApplicationError("threshold correction requires threshold_letter")
    normalized = correction.threshold_letter.strip().lower()
    op = correction.operation

    if op == CorrectionOperation.RESOLVE_CUTOFF_OVERLAP:
        return _apply_resolve_cutoff_overlap(model, normalized, correction.threshold_letter)

    if op == CorrectionOperation.CONFIRM_THRESHOLD_VALUE:
        return _apply_confirm_threshold_value(model, normalized, correction.threshold_letter)

    index = next(
        (i for i, t in enumerate(model.grade_thresholds) if t.letter.strip().lower() == normalized), None
    )
    if index is None:
        raise CorrectionApplicationError(f"unknown threshold letter: '{correction.threshold_letter}'")
    threshold = model.grade_thresholds[index]
    if op == CorrectionOperation.SET_MINIMUM:
        updated = _replace_validated(threshold, minimum=_require_number_or_none(correction.value, field="set_minimum"))
    elif op == CorrectionOperation.SET_MAXIMUM:
        updated = _replace_validated(threshold, maximum=_require_number_or_none(correction.value, field="set_maximum"))
    else:
        raise CorrectionApplicationError(f"unsupported operation '{op.value}' for target_type 'threshold'")
    thresholds = list(model.grade_thresholds)
    thresholds[index] = updated
    return _replace_validated(model, grade_thresholds=[t.model_dump(mode="json") for t in thresholds])


def _apply_rule_correction(model: GradeModel, correction: GradeModelCorrection) -> GradeModel:
    if correction.rule_index is None or correction.rule_index >= len(model.rules):
        raise CorrectionApplicationError(f"unknown rule_index: {correction.rule_index}")
    index = correction.rule_index
    rule = model.rules[index]
    op = correction.operation
    if op == CorrectionOperation.REMOVE_RULE:
        rules = [r for i, r in enumerate(model.rules) if i != index]
        return _replace_validated(model, rules=[r.model_dump(mode="json") for r in rules])
    if op == CorrectionOperation.CONFIRM_RULE:
        # An explicit "student reviewed this and it's correct as extracted"
        # acknowledgment -- a legitimate correction-list entry even though
        # it changes nothing in the model itself.
        return model
    if op == CorrectionOperation.SET_SOURCE:
        updated = _replace_validated(rule, source=_require_str_or_none(correction.value, field="set_source"))
    elif op == CorrectionOperation.SET_TARGET:
        updated = _replace_validated(rule, target=_require_str_or_none(correction.value, field="set_target"))
    elif op == CorrectionOperation.SET_CONDITION:
        updated = _replace_validated(rule, condition=_require_str_or_none(correction.value, field="set_condition"))
    else:
        raise CorrectionApplicationError(f"unsupported operation '{op.value}' for target_type 'rule'")
    rules = list(model.rules)
    rules[index] = updated
    return _replace_validated(model, rules=[r.model_dump(mode="json") for r in rules])


def _apply_grading_method_correction(model: GradeModel, correction: GradeModelCorrection) -> GradeModel:
    if correction.operation != CorrectionOperation.SET_GRADING_METHOD:
        raise CorrectionApplicationError(
            f"unsupported operation '{correction.operation.value}' for target_type 'grading_method'"
        )
    value = _require_str(correction.value, field="set_grading_method")
    try:
        method = GradingMethod(value)
    except ValueError as exc:
        valid = ", ".join(m.value for m in GradingMethod)
        raise CorrectionApplicationError(f"invalid grading method '{value}'; must be one of: {valid}") from exc
    return _replace_validated(model, grading_method=method.value)


def _apply_warning_correction(model: GradeModel, correction: GradeModelCorrection) -> GradeModel:
    """Dismiss (remove) one ExtractionWarning by its position in
    GradeModel.warnings -- same index-based-identity limitation as rules
    (ExtractionWarning has no natural name either). A dismissed warning is
    simply gone from the candidate; it never comes back on the ORIGINAL
    extracted model.

    Dismissing a warning is often needed alongside removing/confirming its
    related rule: a `possible_curve` ExtractionWarning is independent of
    the CURVE GradingRule it describes (removing the rule does not clear
    the warning), and Phase 5 treats an un-dismissed WARNING-severity
    extraction warning as review-required regardless of what happened to
    any related rule.
    """
    if correction.operation != CorrectionOperation.DISMISS_WARNING:
        raise CorrectionApplicationError(f"unsupported operation '{correction.operation.value}' for target_type 'warning'")
    if correction.warning_index is None or correction.warning_index >= len(model.warnings):
        raise CorrectionApplicationError(f"unknown warning_index: {correction.warning_index}")
    warnings = [w for i, w in enumerate(model.warnings) if i != correction.warning_index]
    return _replace_validated(model, warnings=[w.model_dump(mode="json") for w in warnings])


_HANDLERS = {
    CorrectionTargetType.CATEGORY: _apply_category_correction,
    CorrectionTargetType.ASSESSMENT: _apply_assessment_correction,
    CorrectionTargetType.THRESHOLD: _apply_threshold_correction,
    CorrectionTargetType.RULE: _apply_rule_correction,
    CorrectionTargetType.GRADING_METHOD: _apply_grading_method_correction,
    CorrectionTargetType.WARNING: _apply_warning_correction,
}


def apply_grade_model_corrections(
    extracted_model: GradeModel,
    corrections: list[GradeModelCorrection],
) -> GradeModel:
    """Apply every correction, in order, to a copy of `extracted_model`.

    Never mutates `extracted_model`. Atomic: the first invalid correction
    raises CorrectionApplicationError before anything is returned -- there
    is no partially-corrected result.
    """
    candidate = extracted_model.model_copy(deep=True)
    for position, correction in enumerate(corrections):
        handler = _HANDLERS.get(correction.target_type)
        if handler is None:
            raise CorrectionApplicationError(f"unsupported target_type: {correction.target_type}")
        try:
            candidate = handler(candidate, correction)
        except CorrectionApplicationError as exc:
            raise CorrectionApplicationError(f"correction[{position}] ({correction.target_type.value}): {exc}") from exc
    return candidate
