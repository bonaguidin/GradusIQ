"""Pure deterministic resolution of machine-structured requirement choices.

The selector sits between scheduler scope classification and term scheduling.
It enumerates the small requirement-defined choice space, removes choices that
depend on unrepresented approval/restriction semantics, and asks the existing
scheduler to evaluate globally compatible combinations. It optionally consumes
validated career ranks as a subordinate tie-break, but remains provider-independent.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
import re
from typing import Any, Iterable, Mapping

from pydantic import Field

from .models import StrictModel, StructuredPrerequisite
from .requirement_candidates import (
    AcademicFeasibility,
    CandidateExclusionReason,
    RequirementCandidate,
    RequirementCandidateSet,
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


class SelectionSearchStats(StrictModel):
    candidate_combinations_before_pruning: int = 0
    candidate_combinations_after_structural_pruning: int = 0
    candidate_combinations_evaluated: int = 0


class RequirementSelectionResult(StrictModel):
    courses: list[CourseToSchedule] = Field(default_factory=list)
    unscheduled: list[UnscheduledRequirement] = Field(default_factory=list)
    search_stats: SelectionSearchStats = Field(default_factory=SelectionSearchStats)
    candidate_sets: list[RequirementCandidateSet] = Field(default_factory=list)


@dataclass(frozen=True)
class _Choice:
    owner_group_id: str
    owner_group_name: str
    courses: tuple[str, ...]
    option_order: tuple[int, ...]
    limitations: tuple[str, ...] = ()
    existing_contribution: int = 0

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
) -> tuple[list[tuple[str, ...]], bool]:
    rows = courses_by_option.get(str(option["id"]), [])
    codes = [catalog_by_gid.get(str(row["coursedog_group_id"])) for row in rows if row.get("coursedog_group_id")]
    unresolved = len(codes) != len(rows) or any(code is None for code in codes)
    resolved = tuple(str(code) for code in codes if code)
    if not resolved:
        return [], unresolved
    if option.get("logic") == "or":
        return [(code,) for code in resolved], unresolved
    return [resolved], unresolved


def _leaf_choices(
    group: RequirementGroupResult,
    raw_group: Mapping[str, Any],
    options_by_group: Mapping[str, list[dict[str, Any]]],
    courses_by_option: Mapping[str, list[dict[str, Any]]],
    catalog_by_gid: Mapping[str, str],
    credits: Mapping[str, float],
    satisfied: set[str],
) -> list[_Choice]:
    opts = options_by_group.get(group.id, [])
    variants: list[tuple[dict[str, Any], list[tuple[str, ...]], bool]] = []
    for option in opts:
        option_variants, unresolved = _option_variants(option, courses_by_option, catalog_by_gid)
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
                child, raw_by_id, options_by_group, courses_by_option, catalog_by_gid, credits, satisfied
            ):
                choices.append(
                    _Choice(
                        child.id, child.name, choice.courses, choice.option_order,
                        choice.limitations, choice.existing_contribution,
                    )
                )
        return choices
    if group.children:
        return []
    return _leaf_choices(group, raw, options_by_group, courses_by_option, catalog_by_gid, credits, satisfied)


def structured_candidate_codes(
    groups: list[RequirementGroupResult],
    raw_groups: list[Mapping[str, Any]],
    options: list[Mapping[str, Any]],
    option_courses: list[Mapping[str, Any]],
    catalog_by_gid: Mapping[str, str],
) -> set[str]:
    """All resolved codes under currently deferred structured groups."""
    deferred_ids = {group.id for group in groups if group.status != RequirementGroupStatus.SATISFIED}
    child_ids = {child.id for group in groups for child in group.children}
    relevant = deferred_ids | child_ids
    option_ids = {str(o["id"]) for o in options if str(o["requirement_group_id"]) in relevant}
    return {
        catalog_by_gid[str(row["coursedog_group_id"])]
        for row in option_courses
        if str(row["requirement_group_option_id"]) in option_ids
        and row.get("coursedog_group_id")
        and str(row["coursedog_group_id"]) in catalog_by_gid
    }


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
    student_id: str,
    program_id: str,
    starting_year: int,
    starting_season: str,
    max_terms: int,
    credit_hour_cap: float = 15.0,
    career_rank_by_candidate_id: Mapping[str, int] | None = None,
) -> RequirementSelectionResult:
    """Globally select among structured deferred requirements.

    Unknown double-counting rules are handled conservatively: a course may
    have only one requirement owner, including ownership by the existing
    no-choice schedule. Candidate prerequisites with unrepresented approval
    or standing restrictions are excluded. A combination must schedule with
    no prerequisite limitations inside the graduation horizon.
    """
    career_ranks = normalized_career_rank_map(career_rank_by_candidate_id)
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
            catalog_by_gid, catalog_credit_by_code, satisfied,
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
            if any(prerequisites.get(code, StructuredPrerequisite()).restrictions for code in choice.courses):
                evidence.exclusion_reasons.add(CandidateExclusionReason.RESTRICTION_REQUIRES_REVIEW)
                evidence.exclusion_details.add("one or more candidate courses carry an unrepresented restriction")
                continue
            if any(prerequisites.get(code, StructuredPrerequisite()).needs_review for code in choice.courses):
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
                    option, courses_by_option, catalog_by_gid
                )
                if not unresolved or variants:
                    continue
                choice = _Choice(
                    group_id,
                    by_id[group_id].name,
                    (),
                    (int(option["option_index"]),),
                    existing_contribution=len(by_id[group_id].matched_course_codes),
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
        return RequirementSelectionResult(
            courses=base_courses,
            unscheduled=unscheduled,
            search_stats=SelectionSearchStats(candidate_combinations_before_pruning=raw_count),
            candidate_sets=_candidate_sets(requirement_order, evidence_by_requirement),
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

    best: tuple[tuple[Any, ...], tuple[_Choice, ...], ScheduleResult] | None = None
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
        if best is None or score < best[0]:
            best = (score, combination, result)

    if best is None:
        return RequirementSelectionResult(
            courses=base_courses,
            unscheduled=unscheduled,
            search_stats=SelectionSearchStats(
                candidate_combinations_before_pruning=raw_count,
                candidate_combinations_after_structural_pruning=len(structurally_valid),
                candidate_combinations_evaluated=evaluated,
            ),
            candidate_sets=_candidate_sets(requirement_order, evidence_by_requirement),
        )

    _, winning, _ = best
    selected = [
        CourseToSchedule(
            course_code=code,
            credit_hours=float(catalog_credit_by_code[code]),
            requirement_group_id=choice.owner_group_id,
            requirement_group_name=choice.owner_group_name,
            selection_limitations=list(choice.limitations),
        )
        for choice in winning
        for code in choice.courses
    ]
    return RequirementSelectionResult(
        courses=base_courses + selected,
        unscheduled=manual,
        search_stats=SelectionSearchStats(
            candidate_combinations_before_pruning=raw_count,
            candidate_combinations_after_structural_pruning=len(structurally_valid),
            candidate_combinations_evaluated=evaluated,
        ),
        candidate_sets=_candidate_sets(requirement_order, evidence_by_requirement),
    )
