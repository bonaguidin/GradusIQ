"""Storage contract for persisted structured-requirement exclusions.

Parallel to requirement_selections.py. A row here is the student's intent to
remove an otherwise no-choice requirement group from their Degree Schedule; it
is not proof the requirement stopped applying. Reconstruction revalidates the
current requirement tree before an exclusion is allowed to affect scheduling.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# PostgREST / Postgres signals for "the relation isn't there": PGRST205 is
# PostgREST's schema-cache miss, 42P01 is Postgres' undefined_table. Either one
# means the exclusions migration has not reached this database yet.
_MISSING_RELATION_SIGNALS = ("PGRST205", "42P01", "does not exist", "schema cache")


def _looks_like_missing_relation(exc: Exception) -> bool:
    haystack = " ".join(
        str(part)
        for part in (exc, getattr(exc, "code", ""), getattr(exc, "message", ""))
        if part
    )
    return any(signal in haystack for signal in _MISSING_RELATION_SIGNALS)


def load_requirement_exclusion_group_ids(
    client: Any, student_id: str, program_id: str
) -> tuple[str, ...]:
    """The requirement group ids this student has set aside for this program.

    Runs under the caller's own session client -- the owner SELECT RLS policy
    (degree_requirement_exclusions_owner_select) is the real access control;
    the explicit student_id filter is belt-and-braces alongside it, the same
    posture load_requirement_selection_identities takes.

    Defense-in-depth: if the degree_requirement_exclusions relation is missing
    (its migration written and shipped in code but not yet applied to this
    database), degrade to "no exclusions" rather than let an uncaught error
    take down every schedule route that calls _reconstruct_academic_schedule.
    An absent table is functionally identical to a student with zero exclusion
    rows. Any other error still propagates.
    """
    try:
        rows = (
            client.table("degree_requirement_exclusions")
            .select("requirement_group_id")
            .eq("student_id", student_id)
            .eq("program_id", program_id)
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001 -- narrowed below, re-raised otherwise
        if _looks_like_missing_relation(exc):
            logger.warning(
                "degree_requirement_exclusions unavailable (%s); treating as no "
                "exclusions. Apply the migration to restore exclusion support.",
                exc,
            )
            return ()
        raise
    return tuple(sorted(str(row["requirement_group_id"]) for row in rows))
