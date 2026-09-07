"""Deterministic GradeModel reconciliation and trust classification (Phase 5).

    source-grounded GradeModel -> reconcile_grade_model() -> GradeModelReconciliationResult

Phase 4 already confirmed every cited SourceEvidence's text exists on its
cited page. Phase 5 asks a different question: given a GradeModel that is
already source-grounded, is it coherent and complete enough to hand to a
future grade calculator?

    Phase 4: is this claim grounded in real syllabus text?
    Phase 5: is this grounded model coherent and trustworthy enough to use?

A claim can be perfectly source-grounded and still not be calculator-ready
-- "Grades may be curved upward" is real, source-grounded syllabus policy,
but has no deterministic formula. That uncertainty must survive
reconciliation, not be silently dropped or "fixed": this module only
evaluates the supplied GradeModel, it never mutates, repairs, or rewrites
it. No LLM calls, no network calls, no file I/O -- pure deterministic
Python over the model's own fields (plus a light defensive cross-check
against RelevantSyllabusContent.selected_pages; see _evidence_coverage).

Only two decision states exist in Phase 5 (see ReconciliationStatus):
ACCEPTED or NEEDS_STUDENT_REVIEW. There is no REJECTED state yet -- an
incomplete or ambiguous but source-grounded model still needs review, not
discarding.

ACCEPTANCE POLICY
------------------
Every check below returns zero or more ReconciliationFinding objects
(reusing ValidationSeverity from syllabus/validation.py; see the module
docstring there). The status is derived from those findings in exactly one
place (_derive_status), never set ad hoc inside an individual check:

    any ERROR-severity finding                         -> NEEDS_STUDENT_REVIEW
    any WARNING-severity finding NOT in                 -> NEEDS_STUDENT_REVIEW
        NON_BLOCKING_WARNING_CODES
    otherwise (only VALID findings, or WARNINGs that
        are expected/routine incompleteness)            -> ACCEPTED

NON_BLOCKING_WARNING_CODES is the entire policy for which WARNINGs are
"acceptable" vs "review-required" -- see its definition below for the
reasoning behind each entry.
"""

import re
from enum import Enum

from pydantic import Field

from GradusIQ_career.syllabus.models import (
    Assessment,
    GradeCategory,
    GradeModel,
    GradeThreshold,
    GradingMethod,
    GradingRule,
    GradingRuleType,
    SourceEvidence,
    StrictModel,
)
from GradusIQ_career.syllabus.relevance import RelevantSyllabusContent
from GradusIQ_career.syllabus.validation import ValidationSeverity, validate_grade_model

RECONCILIATION_SCHEMA_VERSION = "1"

# WARNING-severity finding codes that do NOT, by themselves, require
# student review -- genuine, expected incompleteness that a later
# calculator/UI can surface without blocking on it. Every other WARNING
# code (and every ERROR, regardless of code) is review-required. This set
# is the complete policy for WARNING-severity findings; do not add ad hoc
# status-changing branches anywhere else in this module.
#
# unknown_assessment_count / missing_grade_scale: an ExtractionWarning the
#   model itself already flagged as routine uncertainty (see
#   syllabus/models.py's ExtractionWarningType) that the calculator can
#   operate around -- an unknown quiz count doesn't block computing a
#   weighted grade from the categories that ARE known.
#
# non_deterministic_grading_rule / possible_curve / ambiguous_rule: a
#   correctly-extracted informational grading policy (a curve, a late-work
#   rule, a makeup-work rule) that has no deterministic formula the
#   calculator could execute -- see _is_rule_deterministic. Per the
#   syllabus-review redesign (planning-docs/syllabus-review-redesign-spec.md
#   §2C / §5), these are facts the student should SEE while calculating,
#   not ambiguities to resolve or block on: the calculator already leaves
#   the affected scores unmodified (calculator/rules.py) and simply
#   surfaces the rule text. They stay in `findings` for display; they no
#   longer force NEEDS_STUDENT_REVIEW on their own.
#
# unknown_weight: an LLM extraction-time self-report about the same fact
#   category_weight_validation (_wrap_weight_validation, delegating to
#   validation.validate_category_weights) already checks deterministically
#   -- whether declared category weights sum to ~100. That check fires its
#   own WARNING/ERROR whenever they don't, and it is NOT in this set, so it
#   still gates confirm on its own. unknown_weight itself is unfalsifiable
#   as a gate: it's an ExtractionWarning, and the only correction that
#   touches GradeModel.warnings is DISMISS_WARNING -- category/set_weight
#   (the correction that actually answers "what's the weight") never clears
#   it, so a student who supplies the missing weight is left blocked by a
#   note that is now factually stale. Keeping it here as informational (it
#   stays in `findings` for display) loses nothing category_weight_
#   validation wasn't already enforcing.
NON_BLOCKING_WARNING_CODES: frozenset[str] = frozenset(
    {
        "unknown_assessment_count",
        "missing_grade_scale",
        "non_deterministic_grading_rule",
        "possible_curve",
        "ambiguous_rule",
        "unknown_weight",
    }
)

_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_POINTS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:points|pts)\b", re.IGNORECASE)
_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)")
_VALUE_TOLERANCE = 0.01

# Canonical A-F letter-grade ordering (lower rank == higher grade). Public
# because cutoff_resolution.py's "higher grade wins the tie" function is
# defined over this same ordering; kept here as the single source of truth.
CANONICAL_LETTER_RANK = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
_CANONICAL_LETTER_RANK = CANONICAL_LETTER_RANK  # backward-compatible alias


class ReconciliationStatus(str, Enum):
    ACCEPTED = "accepted"
    NEEDS_STUDENT_REVIEW = "needs_student_review"


class ReconciliationFinding(StrictModel):
    """A single Phase 5 finding.

    Deliberately not syllabus/validation.py's ValidationFinding: this needs
    a stable machine-readable `code` in addition to severity/message/field,
    and adding that to ValidationFinding would touch the Phase 1 validation
    contract for a Phase-5-only need. Reuses ValidationSeverity (the actual
    shared severity concept) rather than inventing a parallel one.
    """

    code: str = Field(min_length=1)
    severity: ValidationSeverity
    message: str = Field(min_length=1)
    field: str | None = None


class EvidenceCoverage(StrictModel):
    total_claims: int = Field(ge=0)
    supported_claims: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0, le=1)
    unsupported_claims: list[str] = Field(default_factory=list)


class GradeModelReconciliationResult(StrictModel):
    schema_version: str = RECONCILIATION_SCHEMA_VERSION
    status: ReconciliationStatus
    grade_model: GradeModel
    findings: list[ReconciliationFinding] = Field(default_factory=list)
    evidence_coverage: EvidenceCoverage


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


# ---------------------------------------------------------------------------
# Existing weight validation (reused, not duplicated)
# ---------------------------------------------------------------------------


def _wrap_weight_validation(grade_model: GradeModel) -> list[ReconciliationFinding]:
    """Delegate entirely to syllabus/validation.py -- see module docstring
    there for why a non-100% total is a WARNING (review-worthy) rather than
    a hard failure, and why an over-100 total is treated the same way
    (extra credit is a legitimate cause the validator already tolerates).
    """
    return [
        ReconciliationFinding(
            code="category_weight_validation",
            severity=finding.severity,
            message=finding.message,
            field=finding.field,
        )
        for finding in validate_grade_model(grade_model)
    ]


# ---------------------------------------------------------------------------
# Duplicate detection (report only -- never merge)
# ---------------------------------------------------------------------------


def _check_duplicate_categories(grade_model: GradeModel) -> list[ReconciliationFinding]:
    groups: dict[str, list[str]] = {}
    for category in grade_model.categories:
        groups.setdefault(_normalize_name(category.name), []).append(category.name)
    return [
        ReconciliationFinding(
            code="duplicate_category",
            severity=ValidationSeverity.ERROR,
            message=f"multiple categories normalize to the same name: {names}",
            field=normalized,
        )
        for normalized, names in groups.items()
        if len(names) > 1
    ]


def _check_duplicate_assessments(grade_model: GradeModel) -> list[ReconciliationFinding]:
    """Conservative: two same-named assessments with different stated dates
    (e.g. "Quiz" on Sep 2 vs Sep 9) are NOT flagged -- the date genuinely
    distinguishes them. Only an exact (normalized name, normalized date)
    match counts as a duplicate.
    """
    groups: dict[tuple[str, str | None], list[str]] = {}
    for assessment in grade_model.assessments:
        date_key = _normalize_name(assessment.date) if assessment.date is not None else None
        key = (_normalize_name(assessment.name), date_key)
        groups.setdefault(key, []).append(assessment.name)
    return [
        ReconciliationFinding(
            code="duplicate_assessment",
            severity=ValidationSeverity.ERROR,
            message=f"multiple assessments share the same name and date: {names} (date={date_key!r})",
            # field includes date_key, not just normalized_name: two separate
            # duplicate groups can share a name and differ only by date (e.g.
            # "Quiz"/Sep 2 vs "Quiz"/Sep 9, each duplicated on its own date),
            # and normalized_name alone would collapse those distinct findings
            # onto the same field value.
            field=f"{normalized_name}:{date_key}",
        )
        for (normalized_name, date_key), names in groups.items()
        if len(names) > 1
    ]


# ---------------------------------------------------------------------------
# Grading-method coherence
# ---------------------------------------------------------------------------


def _check_grading_method_coherence(grade_model: GradeModel) -> list[ReconciliationFinding]:
    """WEIGHTED-with-no-known-weights is already an ERROR from
    validate_grade_model (see _wrap_weight_validation) -- not repeated
    here. POINTS/HYBRID require no additional check (see module docstring
    on grading-method coherence in the Phase 5 task). UNKNOWN is a valid
    state that is never reinterpreted into another method, but it is not
    yet something a calculator can safely act on.
    """
    if grade_model.grading_method == GradingMethod.UNKNOWN:
        return [
            ReconciliationFinding(
                code="grading_method_unknown",
                severity=ValidationSeverity.WARNING,
                message="grading_method could not be determined from the syllabus",
                field="grading_method",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Grade-threshold consistency and ordering
# ---------------------------------------------------------------------------


def _check_grade_thresholds(
    grade_model: GradeModel,
    confirmed_cutoff_pairs: set[frozenset[str]] | None = None,
) -> list[ReconciliationFinding]:
    findings: list[ReconciliationFinding] = []
    thresholds = grade_model.grade_thresholds

    # A student may confirm the "higher grade wins the tie" default for an
    # overlapping cutoff pair (see cutoff_resolution.py + the
    # RESOLVE_CUTOFF_OVERLAP correction). We suppress the
    # overlapping_grade_thresholds ERROR for such a pair, but ONLY after
    # independently re-deriving that the pair is actually cleanly resolvable
    # (canonical A-F, rank-adjacent, single shared boundary point) -- the
    # confirmed set is never trusted blind, so a student cannot confirm past
    # a genuine multi-way or non-adjacent conflict.
    suppressible_pairs: set[frozenset[str]] = set()
    if confirmed_cutoff_pairs:
        from GradusIQ_career.syllabus.cutoff_resolution import resolve_cutoff_overlaps

        resolvable = {
            frozenset((r.winner, r.loser)) for r in resolve_cutoff_overlaps(thresholds).resolved
        }
        suppressible_pairs = {p for p in confirmed_cutoff_pairs if p in resolvable}

    # Phase 1's GradeThreshold model_validator already refuses to construct
    # minimum > maximum, so this is unreachable for any GradeModel built
    # through normal validation. Kept as a defensive check for direct or
    # hand-built callers, per this module's contract with malformed input.
    for threshold in thresholds:
        if (
            threshold.minimum is not None
            and threshold.maximum is not None
            and threshold.minimum > threshold.maximum
        ):
            findings.append(
                ReconciliationFinding(
                    code="reversed_grade_threshold",
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"threshold '{threshold.letter}' has minimum {threshold.minimum} "
                        f"greater than maximum {threshold.maximum}"
                    ),
                    field=threshold.letter,
                )
            )

    bounded = [t for t in thresholds if t.minimum is not None and t.maximum is not None]
    for i, a in enumerate(bounded):
        for b in bounded[i + 1 :]:
            if a.letter == b.letter:
                continue
            if max(a.minimum, b.minimum) <= min(a.maximum, b.maximum):
                if frozenset((a.letter, b.letter)) in suppressible_pairs:
                    continue
                findings.append(
                    ReconciliationFinding(
                        code="overlapping_grade_thresholds",
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"thresholds '{a.letter}' ({a.minimum}-{a.maximum}) and '{b.letter}' "
                            f"({b.minimum}-{b.maximum}) overlap"
                        ),
                        field=f"{a.letter},{b.letter}",
                    )
                )

    # Ordering is only checked for the canonical A/B/C/D/F letter set --
    # skipped entirely for any other scale (S/U, numeric, custom labels)
    # rather than guessing at an order, per this module's conservatism
    # requirement.
    letters = {t.letter for t in thresholds}
    if letters and letters <= set(_CANONICAL_LETTER_RANK):
        ranked = sorted(
            (t for t in thresholds if t.minimum is not None),
            key=lambda t: _CANONICAL_LETTER_RANK[t.letter],
        )
        for prev, curr in zip(ranked, ranked[1:]):
            if prev.minimum < curr.minimum:
                findings.append(
                    ReconciliationFinding(
                        code="grade_threshold_ordering_anomaly",
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"threshold '{prev.letter}' has a lower minimum ({prev.minimum}) than the "
                            f"generally-lower grade '{curr.letter}' ({curr.minimum})"
                        ),
                        field=f"{prev.letter},{curr.letter}",
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Rule reference validation and non-deterministic rule flagging
# ---------------------------------------------------------------------------


def _known_names(grade_model: GradeModel) -> set[str]:
    names = {_normalize_name(c.name) for c in grade_model.categories}
    names |= {_normalize_name(a.name) for a in grade_model.assessments}
    return names


def _check_rule_references(grade_model: GradeModel) -> list[ReconciliationFinding]:
    """Never auto-creates the missing category/assessment -- only reports."""
    known = _known_names(grade_model)
    findings: list[ReconciliationFinding] = []
    for rule in grade_model.rules:
        for role, value in (("source", rule.source), ("target", rule.target)):
            if value is not None and _normalize_name(value) not in known:
                findings.append(
                    ReconciliationFinding(
                        code="unresolved_rule_reference",
                        severity=ValidationSeverity.WARNING,
                        message=f"rule {role}='{value}' does not match any known category or assessment",
                        field=value,
                    )
                )
    return findings


def _is_rule_deterministic(rule: GradingRule) -> bool:
    """A rule is deterministic-enough-to-execute (later, in Phase 6) only
    when the schema actually captures what it needs to. REPLACEMENT/DROP
    are executable once both source and target are populated. CURVE,
    EXTRA_CREDIT, LATE_WORK, MAKEUP, and OTHER have no dedicated structured
    fields in the Phase 1 schema for the formula/amount/condition a
    calculator would need (a curve's magnitude, an extra-credit amount, a
    late penalty curve) -- description/source/target/condition strings are
    not enough to safely execute these, regardless of which are populated.
    """
    if rule.rule_type in (GradingRuleType.REPLACEMENT, GradingRuleType.DROP):
        return rule.source is not None and rule.target is not None
    return False


def _check_non_deterministic_rules(grade_model: GradeModel) -> list[ReconciliationFinding]:
    # field is the rule's own index, not rule.rule_type.value: multiple rules
    # of the same type (e.g. three "other" rules) previously collapsed onto
    # an identical field value, making them indistinguishable to any caller
    # trying to anchor a finding back to the one rule it's about.
    return [
        ReconciliationFinding(
            code="non_deterministic_grading_rule",
            severity=ValidationSeverity.WARNING,
            message=(
                f"{rule.rule_type.value} rule is not structured precisely enough to apply "
                f"deterministically: {rule.description}"
            ),
            field=f"rules[{index}]",
        )
        for index, rule in enumerate(grade_model.rules)
        if not _is_rule_deterministic(rule)
    ]


def _check_assessment_category_references(grade_model: GradeModel) -> list[ReconciliationFinding]:
    known_categories = {_normalize_name(c.name) for c in grade_model.categories}
    return [
        ReconciliationFinding(
            code="unresolved_assessment_category_reference",
            severity=ValidationSeverity.WARNING,
            message=(
                f"assessment '{assessment.name}' references category '{assessment.category}', "
                "which is not a known category"
            ),
            field=assessment.name,
        )
        for assessment in grade_model.assessments
        if assessment.category is not None and _normalize_name(assessment.category) not in known_categories
    ]


# ---------------------------------------------------------------------------
# Extraction warnings -> reconciliation findings
# ---------------------------------------------------------------------------


def _check_extraction_warnings(grade_model: GradeModel) -> list[ReconciliationFinding]:
    """Every ExtractionWarning becomes a finding whose `code` is the
    warning's own type value, so NON_BLOCKING_WARNING_CODES governs both
    these and this module's own internal WARNING codes uniformly.
    """
    return [
        ReconciliationFinding(
            code=warning.type.value,
            severity=ValidationSeverity.WARNING,
            message=warning.description,
            field=warning.related_field,
        )
        for warning in grade_model.warnings
    ]


# ---------------------------------------------------------------------------
# Evidence coverage: does every calculator-critical claim have evidence?
# ---------------------------------------------------------------------------


def _critical_claims(grade_model: GradeModel) -> list[tuple[str, SourceEvidence | None]]:
    """A 'calculator-critical claim' is a quantifiable or structural fact a
    future grade calculator would need: a known category weight, an
    assessment carrying a weight/points/date fact, every grade threshold
    (which always carries at least one bound), and every grading rule.
    Fields that are explicitly null (e.g. an unknown assessment count) are
    never claims and never require evidence -- only what was actually
    asserted does.
    """
    claims: list[tuple[str, SourceEvidence | None]] = []
    for category in grade_model.categories:
        if category.weight is not None:
            claims.append((f"category:{category.name}.weight", category.evidence))
    for assessment in grade_model.assessments:
        if assessment.weight is not None or assessment.points is not None or assessment.date is not None:
            claims.append((f"assessment:{assessment.name}", assessment.evidence))
    for threshold in grade_model.grade_thresholds:
        claims.append((f"threshold:{threshold.letter}", threshold.evidence))
    for rule in grade_model.rules:
        claims.append((f"rule:{rule.rule_type.value}:{rule.description[:40]}", rule.evidence))
    return claims


def _evidence_coverage(
    grade_model: GradeModel, content: RelevantSyllabusContent
) -> tuple[EvidenceCoverage, list[ReconciliationFinding]]:
    claims = _critical_claims(grade_model)
    known_pages = {page.page_number for page in content.selected_pages}

    supported = 0
    unsupported_labels: list[str] = []
    findings: list[ReconciliationFinding] = []

    for label, evidence in claims:
        if evidence is not None and evidence.text is not None:
            supported += 1
            # Phase 4 already verified the cited text is on the cited page
            # for models it produced. This is a lightweight defensive
            # sanity check for a GradeModel reconcile_grade_model did not
            # itself receive through Phase 4 -- not a re-run of Phase 4's
            # full text-on-page verification (see module docstring).
            if evidence.page is not None and evidence.page not in known_pages:
                findings.append(
                    ReconciliationFinding(
                        code="evidence_page_out_of_range",
                        severity=ValidationSeverity.WARNING,
                        message=f"{label} cites page {evidence.page}, which is not part of the selected syllabus content",
                        field=label,
                    )
                )
            continue

        unsupported_labels.append(label)
        if evidence is None:
            findings.append(
                ReconciliationFinding(
                    code="missing_claim_evidence",
                    severity=ValidationSeverity.WARNING,
                    message=f"{label} has no evidence at all",
                    field=label,
                )
            )
        else:
            findings.append(
                ReconciliationFinding(
                    code="partial_claim_evidence",
                    severity=ValidationSeverity.WARNING,
                    message=f"{label} has an evidence object but no citable text",
                    field=label,
                )
            )

    total = len(claims)
    coverage = EvidenceCoverage(
        total_claims=total,
        supported_claims=supported,
        coverage_ratio=(supported / total) if total else 1.0,
        unsupported_claims=unsupported_labels,
    )
    return coverage, findings


# ---------------------------------------------------------------------------
# Claim-to-evidence VALUE consistency (does the citation support the exact
# structured value, not just "does the citation exist")
# ---------------------------------------------------------------------------


def _mismatch_finding(label: str, claimed: str, cited: str, evidence_text: str) -> ReconciliationFinding:
    return ReconciliationFinding(
        code="claim_evidence_value_mismatch",
        severity=ValidationSeverity.ERROR,
        message=f"{label} claims {claimed}, but its cited evidence text ('{evidence_text}') states {cited}",
        field=label,
    )


def _unverifiable_finding(label: str, evidence_text: str) -> ReconciliationFinding:
    return ReconciliationFinding(
        code="claim_evidence_consistency_unverifiable",
        severity=ValidationSeverity.WARNING,
        message=f"could not deterministically verify {label} against its cited evidence text ('{evidence_text}')",
        field=label,
    )


def _check_category_weight_consistency(
    category: GradeCategory,
    confirmed_category_value_claims: set[str] | None = None,
) -> ReconciliationFinding | None:
    if category.weight is None or category.evidence is None or category.evidence.text is None:
        return None
    label = f"category:{category.name}.weight"
    match = _PERCENT_RE.search(category.evidence.text)
    if match is None:
        finding: ReconciliationFinding | None = _unverifiable_finding(label, category.evidence.text)
    else:
        cited = float(match.group(1))
        if abs(cited - category.weight) > _VALUE_TOLERANCE:
            finding = _mismatch_finding(label, str(category.weight), str(cited), category.evidence.text)
        else:
            finding = None

    # A student may affirm "this extracted weight IS what the syllabus
    # says" for a category whose value could not be deterministically
    # verified -- most commonly a category whose weight was just filled in
    # via a SET_WEIGHT correction while its `evidence` still carries the
    # text that originally supported a different fact (e.g. the category's
    # count), since GradeCategory has one shared evidence field, not
    # separate fields per fact. Suppression is per-category, re-derived
    # every run (mirrors _check_threshold_range_consistency's
    # confirmed_value_claims): only a finding this function was
    # independently about to emit is skipped. The category and its
    # verbatim evidence are left untouched (see
    # corrections.CONFIRM_CATEGORY_VALUE -- a validated no-op).
    #
    # Deliberately narrower than the threshold path: this only suppresses
    # claim_evidence_consistency_unverifiable (the checker couldn't parse a
    # percent out of the evidence text at all -- an affirmation supplies
    # information the checker lacked). It does NOT suppress
    # claim_evidence_value_mismatch (an ERROR: the evidence text WAS parsed
    # and it names a different number) -- a student affirmation doesn't
    # override a positive, cited contradiction. _check_threshold_range_
    # consistency's confirmed_value_claims suppresses both regardless of
    # which one fired; that's a known open issue there, not the model to
    # match here.
    if (
        finding is not None
        and finding.code == "claim_evidence_consistency_unverifiable"
        and confirmed_category_value_claims
        and _normalize_name(category.name) in confirmed_category_value_claims
    ):
        return None
    return finding


def _check_assessment_points_consistency(assessment: Assessment) -> ReconciliationFinding | None:
    if assessment.points is None or assessment.evidence is None or assessment.evidence.text is None:
        return None
    label = f"assessment:{assessment.name}.points"
    match = _POINTS_RE.search(assessment.evidence.text)
    if match is None:
        return _unverifiable_finding(label, assessment.evidence.text)
    cited = float(match.group(1))
    if abs(cited - assessment.points) > _VALUE_TOLERANCE:
        return _mismatch_finding(label, str(assessment.points), str(cited), assessment.evidence.text)
    return None


def _check_threshold_range_consistency(
    threshold: GradeThreshold,
    confirmed_value_claims: set[str] | None = None,
) -> ReconciliationFinding | None:
    # Only checked when BOTH bounds are stated -- a single-bound threshold
    # ("A: 90+") has no safe deterministic range pattern to compare against.
    if threshold.minimum is None or threshold.maximum is None:
        return None
    if threshold.evidence is None or threshold.evidence.text is None:
        return None
    label = f"threshold:{threshold.letter}"
    match = _RANGE_RE.search(threshold.evidence.text)
    if match is None:
        finding: ReconciliationFinding | None = _unverifiable_finding(label, threshold.evidence.text)
    else:
        lo, hi = sorted((float(match.group(1)), float(match.group(2))))
        claimed_lo, claimed_hi = sorted((threshold.minimum, threshold.maximum))
        if abs(lo - claimed_lo) > _VALUE_TOLERANCE or abs(hi - claimed_hi) > _VALUE_TOLERANCE:
            finding = _mismatch_finding(
                label, f"{threshold.minimum}-{threshold.maximum}", f"{match.group(1)}-{match.group(2)}", threshold.evidence.text
            )
        else:
            finding = None

    # A student may affirm "this extracted value IS what the syllabus says"
    # for a threshold whose value could not be deterministically verified,
    # or that the deterministic check read as a mismatch (e.g. a cutoff the
    # student themselves narrowed away from the verbatim "< 90%" text via a
    # SET_MAXIMUM correction). confirmed_value_claims is the set of such
    # affirmed threshold letters (normalized). Suppression is per-letter and
    # re-derived every run: only a finding this function was independently
    # about to emit is skipped, so a stale confirmation for a letter that
    # now verifies clean suppresses nothing. The extracted threshold and its
    # verbatim evidence are left untouched (see
    # corrections.CONFIRM_THRESHOLD_VALUE -- a validated no-op).
    if (
        finding is not None
        and confirmed_value_claims
        and threshold.letter.strip().lower() in confirmed_value_claims
    ):
        return None
    return finding


def _check_claim_evidence_consistency(
    grade_model: GradeModel,
    confirmed_value_claims: set[str] | None = None,
    confirmed_category_value_claims: set[str] | None = None,
) -> list[ReconciliationFinding]:
    findings: list[ReconciliationFinding] = []
    for category in grade_model.categories:
        finding = _check_category_weight_consistency(category, confirmed_category_value_claims)
        if finding is not None:
            findings.append(finding)
    for assessment in grade_model.assessments:
        finding = _check_assessment_points_consistency(assessment)
        if finding is not None:
            findings.append(finding)
    for threshold in grade_model.grade_thresholds:
        finding = _check_threshold_range_consistency(threshold, confirmed_value_claims)
        if finding is not None:
            findings.append(finding)
    return findings


# ---------------------------------------------------------------------------
# Status derivation (the ONLY place status is decided)
# ---------------------------------------------------------------------------


def _derive_status(findings: list[ReconciliationFinding]) -> ReconciliationStatus:
    for finding in findings:
        if finding.severity == ValidationSeverity.ERROR:
            return ReconciliationStatus.NEEDS_STUDENT_REVIEW
        if finding.severity == ValidationSeverity.WARNING and finding.code not in NON_BLOCKING_WARNING_CODES:
            return ReconciliationStatus.NEEDS_STUDENT_REVIEW
    return ReconciliationStatus.ACCEPTED


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def reconcile_grade_model(
    grade_model: GradeModel,
    content: RelevantSyllabusContent,
    confirmed_cutoff_pairs: set[frozenset[str]] | None = None,
    confirmed_value_claims: set[str] | None = None,
    confirmed_category_value_claims: set[str] | None = None,
) -> GradeModelReconciliationResult:
    """Evaluate (never repair) a source-grounded GradeModel.

    Deterministic and local only -- no LLM/network/file I/O. Does not
    mutate `grade_model` or `content`; the returned result carries a deep
    copy of `grade_model`, never the caller's own instance.

    `confirmed_cutoff_pairs` is the set of frozenset({winner, loser}) letter
    pairs a student has confirmed the higher-grade-wins default for. The
    overlapping_grade_thresholds ERROR is suppressed for such a pair only
    when it is independently re-derived as cleanly resolvable -- see
    _check_grade_thresholds.

    `confirmed_value_claims` is the set of normalized threshold letters a
    student has affirmed the extracted value for ("yes, that IS what the
    syllabus says"). The per-threshold claim_evidence_consistency_
    unverifiable / claim_evidence_value_mismatch finding is suppressed for
    such a letter -- pure suppression, the threshold and its verbatim
    evidence are never touched (see corrections.CONFIRM_THRESHOLD_VALUE and
    _check_threshold_range_consistency).

    `confirmed_category_value_claims` is the category equivalent: the set of
    normalized category names a student has affirmed the extracted weight
    for. A SEPARATE parameter from `confirmed_value_claims`, not a
    namespaced addition to it -- category names and threshold letters are
    different identifier spaces (a category name can collide with nothing
    a threshold letter would, and vice versa), and keeping them apart means
    neither check has to guess which kind of identifier it was handed.
    Narrower than `confirmed_value_claims`: it only suppresses
    claim_evidence_consistency_unverifiable, never claim_evidence_value_
    mismatch -- see _check_category_weight_consistency for why. See also
    corrections.CONFIRM_CATEGORY_VALUE.
    """
    findings: list[ReconciliationFinding] = []
    findings.extend(_wrap_weight_validation(grade_model))
    findings.extend(_check_duplicate_categories(grade_model))
    findings.extend(_check_duplicate_assessments(grade_model))
    findings.extend(_check_grading_method_coherence(grade_model))
    findings.extend(_check_grade_thresholds(grade_model, confirmed_cutoff_pairs))
    findings.extend(_check_rule_references(grade_model))
    findings.extend(_check_non_deterministic_rules(grade_model))
    findings.extend(_check_assessment_category_references(grade_model))
    findings.extend(_check_extraction_warnings(grade_model))
    findings.extend(
        _check_claim_evidence_consistency(grade_model, confirmed_value_claims, confirmed_category_value_claims)
    )

    coverage, coverage_findings = _evidence_coverage(grade_model, content)
    findings.extend(coverage_findings)

    return GradeModelReconciliationResult(
        status=_derive_status(findings),
        grade_model=grade_model.model_copy(deep=True),
        findings=findings,
        evidence_coverage=coverage,
    )
