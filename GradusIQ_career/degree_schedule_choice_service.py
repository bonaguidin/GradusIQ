"""Authenticated Degree Schedule complete-set choice orchestration.

HTTP authentication and student resolution remain in ``api.py``. This module
owns the deterministic snapshot/version/lock/CAS sequence and has no provider
or model dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable, Iterable

from GradusIQ_career.course_discovery.requirement_selection import (
    LockedRequirementSelection,
    LockedSelectionFailureCode,
    select_structured_requirements,
)
from GradusIQ_career.degree_schedule_semantics import DegreeScheduleSemanticSnapshot
from GradusIQ_career.degree_schedule_version import build_degree_schedule_version
from GradusIQ_career.planning.requirement_selections import RequirementSelectionIdentity
from GradusIQ_career.course_discovery.scheduler import schedule_courses


class ChoiceWriteConflictCode(str, Enum):
    SCHEDULE_VERSION_CONFLICT = "SCHEDULE_VERSION_CONFLICT"
    ACADEMIC_REVISION_CONFLICT = "ACADEMIC_REVISION_CONFLICT"


class ChoiceWriteStatus(str, Enum):
    APPLIED = "APPLIED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True)
class ChoiceWriteOutcome:
    status: ChoiceWriteStatus | None = None
    conflict: ChoiceWriteConflictCode | LockedSelectionFailureCode | None = None
    schedule_version: str | None = None
    selections: tuple[RequirementSelectionIdentity, ...] = ()
    exclusion_reasons: tuple[str, ...] = ()


def _rpc_data(client: Any, name: str, params: dict[str, Any]) -> dict[str, Any]:
    data = client.rpc(name, params).execute().data
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        return data[0]
    if not isinstance(data, dict):
        raise RuntimeError(f"{name} returned an invalid result")
    return data


def _sync_semantics(
    client: Any, institution_id: str, snapshot: DegreeScheduleSemanticSnapshot
) -> dict[str, Any]:
    return _rpc_data(client, "sync_degree_schedule_institution_semantics", {
        "p_institution_id": institution_id,
        "p_local_catalog_fingerprint": snapshot.local_catalog_fingerprint,
        "p_planner_contract_version": snapshot.planner_contract_version,
    })


def _capture_revisions(client: Any, student_id: str, program_id: str) -> dict[str, Any]:
    return _rpc_data(client, "get_degree_schedule_revisions", {
        "p_student_id": student_id,
        "p_program_id": program_id,
    })


def write_degree_schedule_choices(
    *,
    service_client: Any,
    student_id: str,
    program_id: str,
    institution_id: str,
    semantic_snapshot: DegreeScheduleSemanticSnapshot,
    submitted_schedule_version: str,
    desired_selections: Iterable[LockedRequirementSelection],
    reconstruct: Callable[[], Any],
) -> ChoiceWriteOutcome:
    desired = tuple(desired_selections)
    _sync_semantics(service_client, institution_id, semantic_snapshot)
    revisions = _capture_revisions(service_client, student_id, program_id)

    state = reconstruct()
    if (
        state.student_id != student_id
        or state.program_id != program_id
        or state.semantic_snapshot != semantic_snapshot
    ):
        return ChoiceWriteOutcome(conflict=ChoiceWriteConflictCode.ACADEMIC_REVISION_CONFLICT)

    current_version = build_degree_schedule_version(state)
    if current_version != submitted_schedule_version:
        return ChoiceWriteOutcome(
            conflict=ChoiceWriteConflictCode.SCHEDULE_VERSION_CONFLICT
        )

    raw = state.raw
    validated = select_structured_requirements(
        state.groups,
        raw.groups,
        raw.options,
        raw.option_courses,
        raw.catalog_by_gid,
        raw.catalog_credit_by_code,
        state.base_courses,
        state.base_unscheduled,
        state.prerequisites,
        state.already_satisfied,
        student_id=state.student_id,
        program_id=state.program_id,
        catalog_by_code=raw.catalog_by_code,
        starting_year=state.starting_year,
        starting_season=state.starting_season,
        max_terms=state.max_terms,
        locked_selections=desired,
        excluded_group_ids=set(getattr(state, "active_exclusions", ())),
    )
    if validated.locked_selection_failure is not None:
        failure = validated.locked_selection_failure
        return ChoiceWriteOutcome(
            conflict=failure.code,
            exclusion_reasons=tuple(reason.value for reason in failure.exclusion_reasons),
        )

    candidates = {
        (candidate_set.requirement_group_id, candidate.candidate_id): candidate
        for candidate_set in validated.candidate_sets
        for candidate in candidate_set.feasible_candidates
    }
    authoritative = tuple(
        RequirementSelectionIdentity(
            program_id=program_id,
            requirement_group_id=lock.requirement_group_id,
            candidate_id=lock.candidate_id,
            course_codes=tuple(
                candidates[(lock.requirement_group_id, lock.candidate_id)].course_codes
            ),
        )
        for lock in desired
    )

    # A different process identity advances the institution revision here.
    # Expected revisions deliberately remain those captured before validation.
    _sync_semantics(service_client, institution_id, semantic_snapshot)
    cas = _rpc_data(service_client, "replace_degree_requirement_selections", {
        "p_student_id": student_id,
        "p_program_id": program_id,
        "p_expected_student_revision": int(revisions["student_revision"]),
        "p_expected_program_revision": int(revisions["program_revision"]),
        "p_expected_institution_revision": int(revisions["institution_revision"]),
        "p_schedule_version": current_version,
        "p_selections": [
            {
                "requirement_group_id": item.requirement_group_id,
                "candidate_id": item.candidate_id,
                "course_codes": list(item.course_codes),
            }
            for item in authoritative
        ],
    })
    if cas.get("status") == "REVISION_CONFLICT":
        return ChoiceWriteOutcome(
            conflict=ChoiceWriteConflictCode.ACADEMIC_REVISION_CONFLICT
        )
    if cas.get("status") not in {"APPLIED", "UNCHANGED"}:
        raise RuntimeError("selection CAS returned an unknown status")

    canonical = tuple(sorted(
        authoritative,
        key=lambda item: (item.requirement_group_id, item.candidate_id),
    ))
    post_write_schedule = schedule_courses(
        state.student_id, state.program_id, validated.courses, state.prerequisites,
        state.already_satisfied, validated.unscheduled,
        starting_year=state.starting_year,
        starting_season=state.starting_season,
        max_terms=state.max_terms,
    )
    post_write_state = replace(
        state,
        academic_selection=validated,
        academic_schedule=post_write_schedule,
        active_selections=canonical,
        selection_state_status="APPLIED" if canonical else "NONE",
        selection_state_failure=None,
    )
    return ChoiceWriteOutcome(
        status=ChoiceWriteStatus(str(cas["status"])),
        schedule_version=build_degree_schedule_version(post_write_state),
        selections=canonical,
    )
