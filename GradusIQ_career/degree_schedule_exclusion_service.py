"""Authenticated Degree Schedule requirement-exclusion write orchestration.

The mirror of degree_schedule_choice_service for the opposite intent: persisting
the set of otherwise no-choice requirement groups a student has set aside. HTTP
auth and student resolution stay in ``api.py``; this module owns the
snapshot/version/lock/CAS sequence and has no provider or model dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable

from GradusIQ_career.degree_schedule_semantics import DegreeScheduleSemanticSnapshot
from GradusIQ_career.degree_schedule_version import build_degree_schedule_version


class ExclusionWriteConflictCode(str, Enum):
    SCHEDULE_VERSION_CONFLICT = "SCHEDULE_VERSION_CONFLICT"
    ACADEMIC_REVISION_CONFLICT = "ACADEMIC_REVISION_CONFLICT"
    UNKNOWN_REQUIREMENT = "UNKNOWN_REQUIREMENT"


class ExclusionWriteStatus(str, Enum):
    APPLIED = "APPLIED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True)
class ExclusionWriteOutcome:
    status: ExclusionWriteStatus | None = None
    conflict: ExclusionWriteConflictCode | None = None
    schedule_version: str | None = None
    excluded_group_ids: tuple[str, ...] = ()
    unknown_group_ids: tuple[str, ...] = ()


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


def _known_group_ids(groups: Iterable[Any]) -> set[str]:
    known: set[str] = set()
    stack = list(groups)
    while stack:
        group = stack.pop()
        known.add(str(group.id))
        stack.extend(getattr(group, "children", ()) or ())
    return known


def write_degree_schedule_exclusions(
    *,
    service_client: Any,
    student_id: str,
    program_id: str,
    institution_id: str,
    semantic_snapshot: DegreeScheduleSemanticSnapshot,
    submitted_schedule_version: str,
    excluded_group_ids: Iterable[str],
    reconstruct: Callable[[], Any],
) -> ExclusionWriteOutcome:
    desired = tuple(dict.fromkeys(str(gid) for gid in excluded_group_ids))
    _sync_semantics(service_client, institution_id, semantic_snapshot)
    revisions = _capture_revisions(service_client, student_id, program_id)

    state = reconstruct()
    if (
        state.student_id != student_id
        or state.program_id != program_id
        or state.semantic_snapshot != semantic_snapshot
    ):
        return ExclusionWriteOutcome(
            conflict=ExclusionWriteConflictCode.ACADEMIC_REVISION_CONFLICT
        )

    current_version = build_degree_schedule_version(state)
    if current_version != submitted_schedule_version:
        return ExclusionWriteOutcome(
            conflict=ExclusionWriteConflictCode.SCHEDULE_VERSION_CONFLICT
        )

    unknown = tuple(gid for gid in desired if gid not in _known_group_ids(state.groups))
    if unknown:
        return ExclusionWriteOutcome(
            conflict=ExclusionWriteConflictCode.UNKNOWN_REQUIREMENT,
            unknown_group_ids=unknown,
        )

    # A different process identity may advance the institution revision here.
    # Expected revisions stay as captured before reconstruction, matching
    # write_degree_schedule_choices.
    _sync_semantics(service_client, institution_id, semantic_snapshot)
    cas = _rpc_data(service_client, "replace_degree_requirement_exclusions", {
        "p_student_id": student_id,
        "p_program_id": program_id,
        "p_expected_student_revision": int(revisions["student_revision"]),
        "p_expected_program_revision": int(revisions["program_revision"]),
        "p_expected_institution_revision": int(revisions["institution_revision"]),
        "p_schedule_version": current_version,
        "p_excluded_group_ids": list(desired),
    })
    if cas.get("status") == "REVISION_CONFLICT":
        return ExclusionWriteOutcome(
            conflict=ExclusionWriteConflictCode.ACADEMIC_REVISION_CONFLICT
        )
    if cas.get("status") not in {"APPLIED", "UNCHANGED"}:
        raise RuntimeError("exclusion CAS returned an unknown status")

    stored = tuple(str(gid) for gid in (cas.get("excluded_group_ids") or ()))
    # Unlike write_degree_schedule_choices (which patches the in-memory state),
    # the exclusion set feeds scope_schedule_input() upstream of state
    # construction, so a fresh reconstruction is the honest way to report the
    # post-write schedule_version.
    post_state = reconstruct()
    return ExclusionWriteOutcome(
        status=ExclusionWriteStatus(str(cas["status"])),
        schedule_version=build_degree_schedule_version(post_state),
        excluded_group_ids=stored,
    )
