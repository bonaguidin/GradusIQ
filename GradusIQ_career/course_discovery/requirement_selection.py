"""Pure deterministic resolution of machine-structured requirement choices.

The selector sits between scheduler scope classification and term scheduling.
It enumerates the small requirement-defined choice space, removes choices that
depend on unrepresented approval/restriction semantics, and asks the existing
scheduler to evaluate globally compatible combinations. It optionally consumes
validated career ranks as a subordinate tie-break, but remains provider-independent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations, product
import re
from typing import Any, Iterable, Iterator, Mapping

from pydantic import Field

from .models import StrictModel, StructuredPrerequisite
from .requirement_candidates import (
    AcademicFeasibility,
    CandidateExclusionReason,
    RequirementCandidate,
    RequirementCandidateSet,
    RequirementDecision,
    RequirementDecisionState,
    stable_candidate_id,
)
from .requirement_candidate_ranking import normalized_career_rank_map
from .requirement_satisfaction import RequirementGroupResult, RequirementGroupStatus
from .scheduler import CourseToSchedule, ScheduleResult, UnscheduledRequirement, schedule_courses


_UNSAFE_GROUP_NOTES = re.compile(
    r"selected in consultation with|listed courses? require(?:s)? (?:adviser|advisor|department) approval|"
    r"approval (?:is )?required for (?:the )?(?:listed )?courses",
    re.IGNORECASE,
)

# A course-code token (e.g. "CSCE 313", "MATH 251"). Used to tell a
# needs_review clause that may hide a real course prerequisite
# ("...or concurrent enrollment in CSCE 313") from one that is pure prose
# the parser simply had no rule for ("knowledge of computer algebra
# system") -- only the former is a scheduling obligation worth gating a
# candidate on. StructuredPrerequisite.restrictions is never gated at all
# (its own model contract: "Informational only -- not enforced by the
# scheduler").
#
# INTERIM HEURISTIC, not a permanent design: the real fix is upstream, in
# course_discovery/prerequisites.py's clause classifier -- course-free
# competency prose like "knowledge of computer algebra system" belongs in
# StructuredPrerequisite.restrictions (informational, per its own
# contract), not needs_review, the same way "also taught at Galveston and
# Qatar campuses" already does. That parser change is catalog-wide
# (affects every SMU/TAMU college's semantic fingerprint) and was
# deliberately deferred rather than bundled here. This regex is a
# consumer-local patch scoped to this one gate so a candidate isn't
# excluded today for text that will eventually be reclassified as
# .restrictions upstream; it should be retired (not extended) once that
# parser work lands, not treated as the intended long-term shape of this
# gate.
_NEEDS_REVIEW_COURSE_REF = re.compile(r"\b[A-Z]{2,4}\s?\d{3,4}\b")


def _needs_review_blocks_scheduling(
    prerequisites: Mapping[str, StructuredPrerequisite], course_codes: Iterable[str]
) -> bool:
    """True when a candidate course carries a needs_review clause that names
    a course -- the only shape that can hide an unmodelled scheduling
    dependency. A course-free needs_review clause is informational and does
    not exclude the candidate."""
    for code in course_codes:
        for clause in prerequisites.get(code, StructuredPrerequisite()).needs_review:
            if _NEEDS_REVIEW_COURSE_REF.search(clause):
                return True
    return False


class SelectionSearchStats(StrictModel):
    candidate_combinations_before_pruning: int = 0
    candidate_combinations_after_structural_pruning: int = 0
    candidate_combinations_evaluated: int = 0


class LockedSelectionFailureCode(str, Enum):
    DUPLICATE_REQUIREMENT = "LOCK_DUPLICATE_REQUIREMENT"
    REQUIREMENT_NOT_FOUND = "LOCK_REQUIREMENT_NOT_FOUND"
    CANDIDATE_NOT_FOUND = "LOCK_CANDIDATE_NOT_FOUND"
    CANDIDATE_EXCLUDED = "LOCK_CANDIDATE_EXCLUDED"
    PATH_MISMATCH = "LOCK_PATH_MISMATCH"
    CHOICE_NO_LONGER_REQUIRED = "LOCK_CHOICE_NO_LONGER_REQUIRED"
    INCOMPATIBLE = "LOCK_INCOMPATIBLE"


class LockedRequirementSelection(StrictModel):
    requirement_group_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    course_codes: tuple[str, ...] = Field(min_length=1)


class LockedSelectionFailure(StrictModel):
    code: LockedSelectionFailureCode
    requirement_group_id: str | None = None
    candidate_id: str | None = None
    current_course_codes: list[str] = Field(default_factory=list)
    submitted_course_codes: list[str] = Field(default_factory=list)
    exclusion_reasons: list[CandidateExclusionReason] = Field(default_factory=list)


class RequirementSelectionResult(StrictModel):
    courses: list[CourseToSchedule] = Field(default_factory=list)
    unscheduled: list[UnscheduledRequirement] = Field(default_factory=list)
    search_stats: SelectionSearchStats = Field(default_factory=SelectionSearchStats)
    candidate_sets: list[RequirementCandidateSet] = Field(default_factory=list)
    decisions: list[RequirementDecision] = Field(default_factory=list)
    locked_selection_failure: LockedSelectionFailure | None = None


@dataclass(frozen=True)
class _Choice:
    owner_group_id: str
    owner_group_name: str
    courses: tuple[str, ...]
    option_order: tuple[int, ...]
    limitations: tuple[str, ...] = ()
    existing_contribution: int = 0
    unresolved_course_codes: tuple[str, ...] = ()

@dataclass
class _CandidateEvidence:
    choice: _Choice
    requirement_group_id: str
    requirement_name: str
    credits: float | None
    completion_term_index: int | None = None
    exclusion_reasons: set[CandidateExclusionReason] | None = None
    exclusion_details: set[str] | None = None

    def __post_init__(self) -> None:
        if self.exclusion_reasons is None:
            self.exclusion_reasons = set()
        if self.exclusion_details is None:
            self.exclusion_details = set()


@dataclass(frozen=True)
class _ValidCombination:
    score: tuple[Any, ...]
    choices: tuple[_Choice, ...]
    schedule: ScheduleResult
    candidate_ids: tuple[str, ...]
    completion_terms: tuple[int, ...]


def _candidate(
    evidence: _CandidateEvidence, feasibility: AcademicFeasibility
) -> RequirementCandidate:
    choice = evidence.choice
    return RequirementCandidate(
        candidate_id=stable_candidate_id(
            evidence.requirement_group_id,
            choice.option_order,
            choice.courses,
            source_path=choice.owner_group_id,
        ),
        requirement_group_id=evidence.requirement_group_id,
        requirement_name=evidence.requirement_name,
        course_codes=list(choice.courses),
        unresolved_course_codes=list(choice.unresolved_course_codes),
        existing_contribution=choice.existing_contribution,
        additional_course_count=len(choice.courses),
        additional_credits=evidence.credits,
        academic_feasibility=feasibility,
        completion_term_index=evidence.completion_term_index,
        limitations=list(choice.limitations),
        source_order=list(choice.option_order),
        exclusion_reasons=sorted(evidence.exclusion_reasons, key=lambda item: item.value),
        exclusion_details=sorted(evidence.exclusion_details),
    )


def _candidate_sets(
    requirement_order: list[tuple[str, str]],
    evidence_by_requirement: Mapping[str, Mapping[str, _CandidateEvidence]],
) -> list[RequirementCandidateSet]:
    sets = []
    for requirement_id, requirement_name in requirement_order:
        evidence = sorted(
            evidence_by_requirement.get(requirement_id, {}).values(),
            key=lambda item: (
                item.choice.option_order,
                item.choice.courses,
                item.choice.owner_group_id,
            ),
        )
        feasible = [
            _candidate(item, AcademicFeasibility.FEASIBLE)
            for item in evidence
            if item.completion_term_index is not None
        ]
        excluded = []
        for item in evidence:
            if item.completion_term_index is not None:
                continue
            if not item.exclusion_reasons:
                item.exclusion_reasons.add(CandidateExclusionReason.UNSCHEDULABLE)
                item.exclusion_details.add(
                    "candidate did not participate in any feasible global schedule"
                )
            excluded.append(_candidate(item, AcademicFeasibility.EXCLUDED))
        sets.append(RequirementCandidateSet(
            requirement_group_id=requirement_id,
            requirement_name=requirement_name,
            feasible_candidates=feasible,
            excluded_candidates=excluded,
        ))
    return sets


_DATA_EXCLUSION_REASONS = {
    CandidateExclusionReason.UNRESOLVED_COURSE,
    CandidateExclusionReason.MISSING_CREDIT_DATA,
}


def _requirement_decisions(
    candidate_sets: list[RequirementCandidateSet],
    excluded_group_ids: set[str],
) -> list[RequirementDecision]:
    """Apply baseline 0/1/2+ semantics after global feasibility is final."""
    decisions: list[RequirementDecision] = []
    for candidate_set in candidate_sets:
        feasible_ids = [candidate.candidate_id for candidate in candidate_set.feasible_candidates]
        excluded_ids = [candidate.candidate_id for candidate in candidate_set.excluded_candidates]
        if candidate_set.requirement_group_id in excluded_group_ids:
            # The student set this requirement aside. It is still required, and
            # its underlying candidate is academically fine -- but the decision
            # is forced to EXCLUDED here, BEFORE the sole-feasible -> AUTO_SELECTED
            # branch below, so a single-mandatory group can never silently
            # re-derive AUTO_SELECTED on the next reconstruction. The candidate
            # ids are preserved under excluded_candidate_ids so a one-click
            # restore has the evidence it needs.
            decisions.append(RequirementDecision(
                requirement_group_id=candidate_set.requirement_group_id,
                requirement_name=candidate_set.requirement_name,
                state=RequirementDecisionState.EXCLUDED,
                feasible_candidate_ids=[],
                excluded_candidate_ids=feasible_ids + excluded_ids,
                selected_candidate_id=None,
            ))
            continue
        if len(feasible_ids) == 1:
            state = RequirementDecisionState.AUTO_SELECTED
            selected = feasible_ids[0]
        elif len(feasible_ids) > 1:
            state = RequirementDecisionState.CHOICE_REQUIRED
            selected = None
        else:
            exclusion_reasons = {
                reason
                for candidate in candidate_set.excluded_candidates
                for reason in candidate.exclusion_reasons
            }
            # Missing evidence and mixed data/manual causes both fail closed as
            # DATA_UNRESOLVED: the system cannot prove that adviser action,
            # rather than catalog/import repair, is the appropriate remedy.
            state = (
                RequirementDecisionState.DATA_UNRESOLVED
                if not exclusion_reasons or exclusion_reasons & _DATA_EXCLUSION_REASONS
                else RequirementDecisionState.ADVISER_REVIEW
            )
            selected = None
        decisions.append(RequirementDecision(
            requirement_group_id=candidate_set.requirement_group_id,
            requirement_name=candidate_set.requirement_name,
            state=state,
            feasible_candidate_ids=feasible_ids,
            excluded_candidate_ids=excluded_ids,
            selected_candidate_id=selected,
        ))
    return decisions


def _index_rows(
    options: Iterable[Mapping[str, Any]], option_courses: Iterable[Mapping[str, Any]]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    options_by_group: dict[str, list[dict[str, Any]]] = {}
    for row in options:
        options_by_group.setdefault(str(row["requirement_group_id"]), []).append(dict(row))
    for rows in options_by_group.values():
        rows.sort(key=lambda row: (int(row["option_index"]), str(row["id"])))
    courses_by_option: dict[str, list[dict[str, Any]]] = {}
    for row in option_courses:
        courses_by_option.setdefault(str(row["requirement_group_option_id"]), []).append(dict(row))
    return options_by_group, courses_by_option


def _option_variants(
    option: Mapping[str, Any],
    courses_by_option: Mapping[str, list[dict[str, Any]]],
    catalog_by_gid: Mapping[str, str],
    catalog_by_code: Mapping[str, list[str]],
    credits: Mapping[str, float],
    transcript_course_codes: set[str],
) -> tuple[list[tuple[str, ...]], bool]:
    """Resolve one option into academically equivalent course paths.

    Each option-course row names one course identity.  SMU rows resolve that
    identity through ``coursedog_group_id``; TAMU rows resolve it through the
    direct ``course_code`` mapping.  A direct row may map to multiple catalog
    codes when it is cross-listed, but it still represents one course: an AND
    option therefore takes one code from each row rather than flattening every
    alias into separately required courses.

    ``transcript_course_codes`` is the set of codes the student has on their
    own course_records (completed or in progress); a cross-listing collapses
    to whichever alias is on the transcript, so a course the student has
    already taken under one department's code is recognised as done rather
    than re-proposed under the other's.
    """
    rows = courses_by_option.get(str(option["id"]), [])
    resolved_rows: list[tuple[str, ...]] = []
    unresolved = False
    for row in rows:
        gid = row.get("coursedog_group_id")
        course_code = row.get("course_code")
        if gid:
            resolved = (str(catalog_by_gid[str(gid)]),) if str(gid) in catalog_by_gid else ()
        elif course_code:
            resolved = tuple(str(code) for code in catalog_by_code.get(str(course_code), []) if code)
            if len(resolved) > 1:
                # A slash-joined direct code is one cross-listed course, not
                # several separately selectable alternatives -- collapse to a
                # single canonical representative. Prefer the alias on the
                # student's transcript; else the first lexical alias with
                # usable credit data, matching scheduler_scope's rule.
                on_transcript = sorted(code for code in resolved if code in transcript_course_codes)
                usable = sorted(code for code in resolved if float(credits.get(code, 0)) > 0)
                resolved = (
                    on_transcript[0] if on_transcript
                    else usable[0] if usable
                    else sorted(resolved)[0],
                )
        else:
            resolved = ()
        if not resolved:
            unresolved = True
            continue
        resolved_rows.append(tuple(dict.fromkeys(resolved)))

    if not resolved_rows:
        return [], unresolved
    if option.get("logic") == "or":
        return [(code,) for codes in resolved_rows for code in codes], unresolved
    return [tuple(picked) for picked in product(*resolved_rows)], unresolved


def _leaf_choices(
    group: RequirementGroupResult,
    raw_group: Mapping[str, Any],
    options_by_group: Mapping[str, list[dict[str, Any]]],
    courses_by_option: Mapping[str, list[dict[str, Any]]],
    catalog_by_gid: Mapping[str, str],
    catalog_by_code: Mapping[str, list[str]],
    credits: Mapping[str, float],
    satisfied: set[str],
) -> list[_Choice]:
    opts = options_by_group.get(group.id, [])
    variants: list[tuple[dict[str, Any], list[tuple[str, ...]], bool]] = []
    for option in opts:
        option_variants, unresolved = _option_variants(
            option, courses_by_option, catalog_by_gid, catalog_by_code, credits, satisfied
        )
        variants.append((option, option_variants, unresolved))

    satisfied_options: set[str] = set()
    for option, option_variants, _ in variants:
        if any(all(code in satisfied for code in variant) for variant in option_variants):
            satisfied_options.add(str(option["id"]))

    limitation = ()
    if any(unresolved for _, _, unresolved in variants):
        limitation = ("source requirement contains unresolved course alternatives excluded from automatic selection",)

    def make(course_codes: Iterable[str], orders: Iterable[int]) -> _Choice:
        remaining = tuple(sorted(set(course_codes) - satisfied))
        return _Choice(
            group.id, group.name, remaining, tuple(orders), limitation,
            existing_contribution=len(group.matched_course_codes),
        )

    if group.group_type == "enumerated_all":
        per_option: list[list[tuple[str, ...]]] = []
        order: list[int] = []
        for option, option_variants, _ in variants:
            if str(option["id"]) in satisfied_options:
                continue
            if not option_variants:
                return []
            per_option.append(option_variants)
            order.append(int(option["option_index"]))
        if not per_option:
            return [make((), ())]
        return [make((code for variant in picked for code in variant), order) for picked in product(*per_option)]

    if group.group_type == "enumerated_at_least_n":
        needed = max(0, int(raw_group.get("n_required") or 0) - len(satisfied_options))
        available = [(option, variants_) for option, variants_, _ in variants if str(option["id"]) not in satisfied_options and variants_]
        choices: list[_Choice] = []
        for selected_options in combinations(available, needed):
            for picked in product(*(variants_ for _, variants_ in selected_options)):
                choices.append(
                    make(
                        (code for variant in picked for code in variant),
                        (int(option["option_index"]) for option, _ in selected_options),
                    )
                )
        return choices

    if group.group_type == "enumerated_credit_threshold":
        required = float(raw_group.get("credit_hours_required") or 0)
        satisfied_credits = sum(float(credits.get(code, 0)) for code in group.matched_course_codes)
        needed = max(0.0, required - satisfied_credits)
        available = [(option, variants_) for option, variants_, _ in variants if str(option["id"]) not in satisfied_options and variants_]
        choices = []
        for count in range(len(available) + 1):
            for selected_options in combinations(available, count):
                for picked in product(*(variants_ for _, variants_ in selected_options)):
                    chosen_codes = tuple(code for variant in picked for code in variant)
                    if sum(float(credits.get(code, 0)) for code in set(chosen_codes)) >= needed:
                        choices.append(
                            make(chosen_codes, (int(option["option_index"]) for option, _ in selected_options))
                        )
        return choices

    return []


def _choices_for_group(
    group: RequirementGroupResult,
    raw_by_id: Mapping[str, Mapping[str, Any]],
    options_by_group: Mapping[str, list[dict[str, Any]]],
    courses_by_option: Mapping[str, list[dict[str, Any]]],
    catalog_by_gid: Mapping[str, str],
    catalog_by_code: Mapping[str, list[str]],
    credits: Mapping[str, float],
    satisfied: set[str],
) -> list[_Choice]:
    raw = raw_by_id[group.id]
    if raw.get("requires_manual_definition") or _UNSAFE_GROUP_NOTES.search(str(raw.get("notes_html") or "")):
        return []
    if group.group_type == "compound_any":
        choices: list[_Choice] = []
        for child in group.children:
            for choice in _choices_for_group(
                child, raw_by_id, options_by_group, courses_by_option,
                catalog_by_gid, catalog_by_code, credits, satisfied
            ):
                choices.append(
                    _Choice(
                        child.id, child.name, choice.courses, choice.option_order,
                        choice.limitations, choice.existing_contribution,
                        choice.unresolved_course_codes,
                    )
                )
        return choices
    if group.children:
        return []
    return _leaf_choices(
        group, raw, options_by_group, courses_by_option,
        catalog_by_gid, catalog_by_code, credits, satisfied
    )


def _iter_groups_deep(
    groups: Iterable[RequirementGroupResult],
) -> Iterator[RequirementGroupResult]:
    """Every group in the tree, at any depth (pre-order).

    evaluate_requirement_tree returns only the roots, each carrying nested
    ``children``. TAMU's real trees run three levels deep (compound_all year
    -> compound_all season -> enumerated_* leaf), and the course rows live on
    the leaves, so any traversal that stops at a fixed depth silently misses
    them. This matches select_structured_requirements' own fully-recursive
    ``by_id`` index -- the two paths must agree on which groups exist.
    """
    for group in groups:
        yield group
        yield from _iter_groups_deep(group.children)


def structured_candidate_codes(
    groups: list[RequirementGroupResult],
    raw_groups: list[Mapping[str, Any]],
    options: list[Mapping[str, Any]],
    option_courses: list[Mapping[str, Any]],
    catalog_by_gid: Mapping[str, str],
    catalog_by_code: Mapping[str, list[str]] | None = None,
) -> set[str]:
    """All resolved codes under currently deferred structured groups.

    Resolves via coursedog_group_id (SMU) or course_code (TAMU, any future
    non-Coursedog school) -- same additive pattern established in
    course_discovery/requirement_satisfaction.py's _resolve_option_codes().
    Unlike scheduler_scope.py's _leaf_course_requirements(), this function
    already returns a flat set() by design (a candidate-code lookup set,
    not a per-row schedulable-requirement list), so a cross-listed
    course_code's 2 resolved codes are both added directly -- there is no
    "one CourseToSchedule per requirement" double-counting risk here,
    since nothing downstream of this set builds a schedule from it.

    The tree is walked to full depth: a non-satisfied group carries relevant
    candidate courses no matter how deeply it is nested (TAMU's leaves sit at
    depth 2). A fixed depth-1 walk here silently dropped every deep leaf's
    codes from the caller's catalog-enrichment lookup, so those candidate
    courses rendered with no title and no credits.
    """
    catalog_by_code = catalog_by_code or {}
    relevant = {
        group.id
        for group in _iter_groups_deep(groups)
        if group.status != RequirementGroupStatus.SATISFIED
    }
    option_ids = {str(o["id"]) for o in options if str(o["requirement_group_id"]) in relevant}
    codes: set[str] = set()
    for row in option_courses:
        if str(row["requirement_group_option_id"]) not in option_ids:
            continue
        gid = row.get("coursedog_group_id")
        if gid and str(gid) in catalog_by_gid:
            codes.add(catalog_by_gid[str(gid)])
            continue
        course_code = row.get("course_code")
        if course_code:
            codes.update(catalog_by_code.get(str(course_code), []))
    return codes


def _validate_locks(
    locks: Mapping[str, LockedRequirementSelection],
    current_requirement_ids: set[str],
    candidate_sets: list[RequirementCandidateSet],
    decisions: list[RequirementDecision],
) -> LockedSelectionFailure | None:
    sets_by_id = {item.requirement_group_id: item for item in candidate_sets}
    decisions_by_id = {item.requirement_group_id: item for item in decisions}
    for requirement_id, lock in locks.items():
        candidate_set = sets_by_id.get(requirement_id)
        if candidate_set is None:
            code = (
                LockedSelectionFailureCode.CHOICE_NO_LONGER_REQUIRED
                if requirement_id in current_requirement_ids
                else LockedSelectionFailureCode.REQUIREMENT_NOT_FOUND
            )
            return LockedSelectionFailure(
                code=code, requirement_group_id=requirement_id,
                candidate_id=lock.candidate_id,
            )
        feasible = {item.candidate_id: item for item in candidate_set.feasible_candidates}
        excluded = {item.candidate_id: item for item in candidate_set.excluded_candidates}
        if lock.candidate_id in excluded:
            candidate = excluded[lock.candidate_id]
            return LockedSelectionFailure(
                code=LockedSelectionFailureCode.CANDIDATE_EXCLUDED,
                requirement_group_id=requirement_id, candidate_id=lock.candidate_id,
                current_course_codes=candidate.course_codes,
                submitted_course_codes=list(lock.course_codes),
                exclusion_reasons=candidate.exclusion_reasons,
            )
        candidate = feasible.get(lock.candidate_id)
        if candidate is None:
            return LockedSelectionFailure(
                code=LockedSelectionFailureCode.CANDIDATE_NOT_FOUND,
                requirement_group_id=requirement_id, candidate_id=lock.candidate_id,
                submitted_course_codes=list(lock.course_codes),
            )
        if tuple(candidate.course_codes) != lock.course_codes:
            return LockedSelectionFailure(
                code=LockedSelectionFailureCode.PATH_MISMATCH,
                requirement_group_id=requirement_id, candidate_id=lock.candidate_id,
                current_course_codes=candidate.course_codes,
                submitted_course_codes=list(lock.course_codes),
            )
        if decisions_by_id[requirement_id].state != RequirementDecisionState.CHOICE_REQUIRED:
            return LockedSelectionFailure(
                code=LockedSelectionFailureCode.CHOICE_NO_LONGER_REQUIRED,
                requirement_group_id=requirement_id, candidate_id=lock.candidate_id,
                current_course_codes=candidate.course_codes,
                submitted_course_codes=list(lock.course_codes),
            )
    return None


def select_structured_requirements(
    evaluated_groups: list[RequirementGroupResult],
    raw_groups: list[Mapping[str, Any]],
    options: list[Mapping[str, Any]],
    option_courses: list[Mapping[str, Any]],
    catalog_by_gid: Mapping[str, str],
    catalog_credit_by_code: Mapping[str, float],
    base_courses: list[CourseToSchedule],
    unscheduled: list[UnscheduledRequirement],
    prerequisites: Mapping[str, StructuredPrerequisite],
    already_satisfied: Iterable[str],
    *,
    catalog_by_code: Mapping[str, list[str]] | None = None,
    student_id: str,
    program_id: str,
    starting_year: int,
    starting_season: str,
    max_terms: int,
    credit_hour_cap: float = 15.0,
    career_rank_by_candidate_id: Mapping[str, int] | None = None,
    locked_selections: Iterable[LockedRequirementSelection] = (),
    excluded_group_ids: Iterable[str] = (),
) -> RequirementSelectionResult:
    """Globally select among structured deferred requirements.

    Unknown double-counting rules are handled conservatively: a course may
    have only one requirement owner, including ownership by the existing
    no-choice schedule. Candidate prerequisites with unrepresented approval
    or standing restrictions are excluded. A combination must schedule with
    no prerequisite limitations inside the graduation horizon.

    ``excluded_group_ids`` are requirement groups the student deliberately set
    aside. Their candidates are still evaluated (so a restore has evidence),
    but the decision is forced to EXCLUDED and their courses are never
    scheduled -- including in the career-ranked full combination.
    """
    career_ranks = normalized_career_rank_map(career_rank_by_candidate_id)
    excluded_group_ids = set(excluded_group_ids)
    locks = tuple(locked_selections)
    locks_by_requirement: dict[str, LockedRequirementSelection] = {}
    for lock in locks:
        if lock.requirement_group_id in locks_by_requirement:
            return RequirementSelectionResult(
                courses=base_courses,
                unscheduled=unscheduled,
                locked_selection_failure=LockedSelectionFailure(
                    code=LockedSelectionFailureCode.DUPLICATE_REQUIREMENT,
                    requirement_group_id=lock.requirement_group_id,
                    candidate_id=lock.candidate_id,
                ),
            )
        locks_by_requirement[lock.requirement_group_id] = lock
    catalog_by_code = catalog_by_code or {}
    raw_by_id = {str(group["id"]): group for group in raw_groups}
    options_by_group, courses_by_option = _index_rows(options, option_courses)
    by_id: dict[str, RequirementGroupResult] = {}

    def index(group: RequirementGroupResult) -> None:
        by_id[group.id] = group
        for child in group.children:
            index(child)

    for group in evaluated_groups:
        index(group)

    structured = [u for u in unscheduled if u.reason == "SELECTION_DEFERRED" and u.requirement_group_id in by_id]
    manual = [u for u in unscheduled if u not in structured]
    satisfied = set(already_satisfied)
    choices_by_requirement: list[tuple[UnscheduledRequirement, list[_Choice]]] = []
    requirement_order = [(item.requirement_group_id, item.name) for item in structured]
    evidence_by_requirement: dict[str, dict[str, _CandidateEvidence]] = {
        item.requirement_group_id: {} for item in structured
    }
    retained_structured: list[UnscheduledRequirement] = []
    raw_count = 1
    for deferred in structured:
        choices = _choices_for_group(
            by_id[deferred.requirement_group_id], raw_by_id, options_by_group, courses_by_option,
            catalog_by_gid, catalog_by_code, catalog_credit_by_code, satisfied,
        )
        raw_count *= max(1, len(choices))
        safe = []
        for choice in choices:
            candidate_id = stable_candidate_id(
                deferred.requirement_group_id,
                choice.option_order,
                choice.courses,
                source_path=choice.owner_group_id,
            )
            credit_values = [catalog_credit_by_code.get(code) for code in choice.courses]
            evidence = _CandidateEvidence(
                choice=choice,
                requirement_group_id=deferred.requirement_group_id,
                requirement_name=deferred.name,
                credits=(
                    sum(float(value) for value in credit_values if value is not None)
                    if all(value is not None and float(value) > 0 for value in credit_values)
                    else None
                ),
            )
            evidence_by_requirement[deferred.requirement_group_id][candidate_id] = evidence
            if evidence.credits is None:
                evidence.exclusion_reasons.add(CandidateExclusionReason.MISSING_CREDIT_DATA)
                evidence.exclusion_details.add("one or more candidate courses have no positive credit value")
                continue
            if _needs_review_blocks_scheduling(prerequisites, choice.courses):
                evidence.exclusion_reasons.add(CandidateExclusionReason.PREREQUISITE_NEEDS_REVIEW)
                evidence.exclusion_details.add("one or more candidate prerequisites require manual review")
                continue
            safe.append(choice)

        # A source option with no resolvable course never becomes a _Choice,
        # but remains important evidence for a future caller.  Represent the
        # source path explicitly instead of silently dropping it.
        relevant_group_ids = {deferred.requirement_group_id}
        stack = list(by_id[deferred.requirement_group_id].children)
        while stack:
            child = stack.pop()
            relevant_group_ids.add(child.id)
            stack.extend(child.children)
        for group_id in sorted(relevant_group_ids):
            for option in options_by_group.get(group_id, []):
                variants, unresolved = _option_variants(
                    option, courses_by_option, catalog_by_gid, catalog_by_code,
                    catalog_credit_by_code, satisfied
                )
                if not unresolved or variants:
                    continue
                choice = _Choice(
                    group_id,
                    by_id[group_id].name,
                    (),
                    (int(option["option_index"]),),
                    existing_contribution=len(by_id[group_id].matched_course_codes),
                    unresolved_course_codes=tuple(
                        str(row.get("course_code") or row.get("unresolved_course_ref"))
                        for row in courses_by_option.get(str(option["id"]), [])
                        if row.get("course_code") or row.get("unresolved_course_ref")
                    ),
                )
                candidate_id = stable_candidate_id(
                    deferred.requirement_group_id,
                    choice.option_order,
                    choice.courses,
                    source_path=choice.owner_group_id,
                )
                evidence = _CandidateEvidence(
                    choice=choice,
                    requirement_group_id=deferred.requirement_group_id,
                    requirement_name=deferred.name,
                    credits=None,
                )
                evidence.exclusion_reasons.add(CandidateExclusionReason.UNRESOLVED_COURSE)
                evidence.exclusion_details.add("source option contains no resolvable catalog course")
                evidence_by_requirement[deferred.requirement_group_id][candidate_id] = evidence
        if safe:
            choices_by_requirement.append((deferred, safe))
        else:
            retained_structured.append(deferred)

    manual.extend(retained_structured)
    if not choices_by_requirement:
        candidate_sets = _candidate_sets(requirement_order, evidence_by_requirement)
        decisions = _requirement_decisions(candidate_sets, excluded_group_ids)
        failure = _validate_locks(
            locks_by_requirement, set(by_id), candidate_sets, decisions
        )
        return RequirementSelectionResult(
            courses=base_courses,
            unscheduled=unscheduled,
            search_stats=SelectionSearchStats(candidate_combinations_before_pruning=raw_count),
            candidate_sets=candidate_sets,
            decisions=decisions,
            locked_selection_failure=failure,
        )

    base_codes = {course.course_code for course in base_courses}
    structurally_valid: list[tuple[_Choice, ...]] = []
    for combination in product(*(choices for _, choices in choices_by_requirement)):
        flat = [code for choice in combination for code in choice.courses]
        if len(flat) != len(set(flat)) or set(flat) & base_codes:
            duplicate_codes = {code for code in flat if flat.count(code) > 1}
            for deferred, choice in zip((item for item, _ in choices_by_requirement), combination):
                candidate_id = stable_candidate_id(
                    deferred.requirement_group_id,
                    choice.option_order,
                    choice.courses,
                    source_path=choice.owner_group_id,
                )
                evidence = evidence_by_requirement[deferred.requirement_group_id][candidate_id]
                if set(choice.courses) & (base_codes | duplicate_codes):
                    evidence.exclusion_reasons.add(CandidateExclusionReason.DOUBLE_COUNTING_CONFLICT)
                    evidence.exclusion_details.add("candidate conflicts with another requirement owner")
            continue
        structurally_valid.append(combination)

    valid_combinations: list[_ValidCombination] = []
    evaluated = 0
    for combination in structurally_valid:
        selected_courses = [
            CourseToSchedule(
                course_code=code,
                credit_hours=float(catalog_credit_by_code[code]),
                requirement_group_id=choice.owner_group_id,
                requirement_group_name=choice.owner_group_name,
                selection_limitations=list(choice.limitations),
            )
            for choice in combination
            for code in choice.courses
        ]
        result = schedule_courses(
            student_id, program_id, base_courses + selected_courses, prerequisites, satisfied, manual,
            starting_year=starting_year, starting_season=starting_season, max_terms=max_terms,
            credit_hour_cap=credit_hour_cap,
        )
        evaluated += 1
        blocking_limitations = [
            note
            for term in result.terms
            for course in term.courses
            for note in course.limitations
            if note.startswith(("prerequisite ", "corequisite "))
        ]
        if result.status != "SCHEDULED" or blocking_limitations:
            continue
        last_term = max((i for i, term in enumerate(result.terms) if term.courses), default=-1)
        placement = {
            course.course_code: term_index
            for term_index, term in enumerate(result.terms)
            for course in term.courses
        }
        selected_completion_terms = [placement[course.course_code] for course in selected_courses]
        combination_completion_terms: list[int] = []
        for deferred, choice in zip((item for item, _ in choices_by_requirement), combination):
            candidate_id = stable_candidate_id(
                deferred.requirement_group_id,
                choice.option_order,
                choice.courses,
                source_path=choice.owner_group_id,
            )
            evidence = evidence_by_requirement[deferred.requirement_group_id][candidate_id]
            candidate_completion = max(
                (placement[code] for code in choice.courses), default=0
            )
            combination_completion_terms.append(candidate_completion)
            if (
                evidence.completion_term_index is None
                or candidate_completion < evidence.completion_term_index
            ):
                evidence.completion_term_index = candidate_completion
            # A candidate that participates in any globally feasible plan is
            # feasible. Conflicts recorded from other combinations do not
            # invalidate that positive evidence.
            evidence.exclusion_reasons.clear()
            evidence.exclusion_details.clear()
        additional_credits = sum(course.credit_hours for course in selected_courses)
        combination_candidate_ids = [
            stable_candidate_id(
                deferred.requirement_group_id,
                choice.option_order,
                choice.courses,
                source_path=choice.owner_group_id,
            )
            for (deferred, _), choice in zip(choices_by_requirement, combination)
        ]
        # Career relevance is below every academic objective. The sum is a global
        # preference; the stable per-requirement tuple resolves equal sums. Missing
        # rankings contribute zero, preserving the Phase 3 source/course fallback.
        career_score = sum(
            career_ranks.get(candidate_id, 0)
            for candidate_id in combination_candidate_ids
        )
        career_rank_tuple = tuple(
            rank
            for _, rank in sorted(
                (
                    deferred.requirement_group_id,
                    career_ranks.get(candidate_id, 0),
                )
                for (deferred, _), candidate_id in zip(
                    choices_by_requirement, combination_candidate_ids
                )
            )
        )
        score = (
            -sum(choice.existing_contribution for choice in combination),
            last_term,
            max(selected_completion_terms, default=-1),
            sum(selected_completion_terms),
            len(selected_courses),
            additional_credits,
            career_score,
            career_rank_tuple,
            tuple((choice.option_order, choice.courses) for choice in combination),
        )
        valid_combinations.append(_ValidCombination(
            score=score,
            choices=combination,
            schedule=result,
            candidate_ids=tuple(combination_candidate_ids),
            completion_terms=tuple(combination_completion_terms),
        ))

    unconstrained_candidate_sets = _candidate_sets(requirement_order, evidence_by_requirement)
    unconstrained_decisions = _requirement_decisions(
        unconstrained_candidate_sets, excluded_group_ids
    )
    lock_failure = _validate_locks(
        locks_by_requirement, set(by_id), unconstrained_candidate_sets,
        unconstrained_decisions,
    )
    if lock_failure is not None:
        return RequirementSelectionResult(
            courses=base_courses,
            unscheduled=unscheduled,
            search_stats=SelectionSearchStats(
                candidate_combinations_before_pruning=raw_count,
                candidate_combinations_after_structural_pruning=len(structurally_valid),
                candidate_combinations_evaluated=evaluated,
            ),
            candidate_sets=unconstrained_candidate_sets,
            decisions=unconstrained_decisions,
            locked_selection_failure=lock_failure,
        )

    constrained = valid_combinations
    if locks_by_requirement:
        choice_indexes = {
            deferred.requirement_group_id: index
            for index, (deferred, _) in enumerate(choices_by_requirement)
        }
        constrained = [
            item for item in valid_combinations
            if all(
                item.candidate_ids[choice_indexes[requirement_id]] == lock.candidate_id
                for requirement_id, lock in locks_by_requirement.items()
            )
        ]
        if not constrained:
            return RequirementSelectionResult(
                courses=base_courses,
                unscheduled=unscheduled,
                search_stats=SelectionSearchStats(
                    candidate_combinations_before_pruning=raw_count,
                    candidate_combinations_after_structural_pruning=len(structurally_valid),
                    candidate_combinations_evaluated=evaluated,
                ),
                candidate_sets=unconstrained_candidate_sets,
                decisions=unconstrained_decisions,
                locked_selection_failure=LockedSelectionFailure(
                    code=LockedSelectionFailureCode.INCOMPATIBLE,
                ),
            )

        # Feasibility for unlocked requirements is contextual: candidates
        # must participate in a complete schedule consistent with every lock.
        # Locked requirements retain their unconstrained alternatives so a
        # future change-choice UI can show the current academic option space.
        for requirement_id, evidence_items in evidence_by_requirement.items():
            if requirement_id in locks_by_requirement:
                continue
            for evidence in evidence_items.values():
                if evidence.completion_term_index is not None:
                    evidence.completion_term_index = None
                    evidence.exclusion_reasons.add(CandidateExclusionReason.UNSCHEDULABLE)
                    evidence.exclusion_details.add(
                        "candidate is incompatible with the current locked selections"
                    )
        for item in constrained:
            for index, (deferred, _) in enumerate(choices_by_requirement):
                if deferred.requirement_group_id in locks_by_requirement:
                    continue
                candidate_id = item.candidate_ids[index]
                evidence = evidence_by_requirement[deferred.requirement_group_id][candidate_id]
                completion = item.completion_terms[index]
                if evidence.completion_term_index is None or completion < evidence.completion_term_index:
                    evidence.completion_term_index = completion
                evidence.exclusion_reasons.clear()
                evidence.exclusion_details.clear()

    best = min(constrained, key=lambda item: item.score) if constrained else None
    if best is None:
        return RequirementSelectionResult(
            courses=base_courses,
            unscheduled=unscheduled,
            search_stats=SelectionSearchStats(
                candidate_combinations_before_pruning=raw_count,
                candidate_combinations_after_structural_pruning=len(structurally_valid),
                candidate_combinations_evaluated=evaluated,
            ),
            candidate_sets=unconstrained_candidate_sets,
            decisions=unconstrained_decisions,
        )

    winning = best.choices
    candidate_sets = _candidate_sets(requirement_order, evidence_by_requirement)
    decisions = _requirement_decisions(candidate_sets, excluded_group_ids)
    if locks_by_requirement:
        decisions = [
            RequirementDecision(
                requirement_group_id=item.requirement_group_id,
                requirement_name=item.requirement_name,
                state=RequirementDecisionState.LOCKED,
                feasible_candidate_ids=item.feasible_candidate_ids,
                excluded_candidate_ids=item.excluded_candidate_ids,
                selected_candidate_id=locks_by_requirement[
                    item.requirement_group_id
                ].candidate_id,
            )
            # A group the student excluded keeps its EXCLUDED decision even if a
            # stale lock row also names it -- the exclusion is the newer intent.
            if item.requirement_group_id in locks_by_requirement
            and item.state != RequirementDecisionState.EXCLUDED
            else item
            for item in decisions
        ]
    auto_selected_ids = {
        decision.requirement_group_id
        for decision in decisions
        if decision.state == RequirementDecisionState.AUTO_SELECTED
    }
    resolved_requirement_ids = (
        auto_selected_ids | set(locks_by_requirement)
    ) - excluded_group_ids
    # Career Optimization deliberately retains its existing behavior: after
    # academic feasibility has been established it may select the ranked full
    # combination. Baseline reconstruction selects only sole-feasible paths.
    # Either way, a group the student excluded is never scheduled.
    choices_to_schedule = tuple(
        choice
        for (deferred, _), choice in zip(choices_by_requirement, winning)
        if deferred.requirement_group_id not in excluded_group_ids
        and (
            career_rank_by_candidate_id is not None
            or deferred.requirement_group_id in resolved_requirement_ids
        )
    )
    selected = [
        CourseToSchedule(
            course_code=code,
            credit_hours=float(catalog_credit_by_code[code]),
            requirement_group_id=choice.owner_group_id,
            requirement_group_name=choice.owner_group_name,
            selection_limitations=list(choice.limitations),
        )
        for choice in choices_to_schedule
        for code in choice.courses
    ]
    if career_rank_by_candidate_id is not None:
        # The ranked path schedules the full winning combination, so its only
        # residual unscheduled items are the manual ones -- plus any group the
        # student excluded, which must still surface for review.
        excluded_deferred = [
            deferred
            for deferred, _ in choices_by_requirement
            if deferred.requirement_group_id in excluded_group_ids
        ]
        final_unscheduled = list(manual) + excluded_deferred
    else:
        final_unscheduled = [
            item
            for item in unscheduled
            if item.requirement_group_id not in resolved_requirement_ids
        ]
    return RequirementSelectionResult(
        courses=base_courses + selected,
        unscheduled=final_unscheduled,
        search_stats=SelectionSearchStats(
            candidate_combinations_before_pruning=raw_count,
            candidate_combinations_after_structural_pruning=len(structurally_valid),
            candidate_combinations_evaluated=evaluated,
        ),
        candidate_sets=candidate_sets,
        decisions=decisions,
    )
