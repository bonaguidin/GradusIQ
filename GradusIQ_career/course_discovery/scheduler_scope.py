"""Splits an evaluated requirement tree into the v1 scheduler's two inputs:
which leaves are no-choice (schedulable) and which are deferred.

Validated against the real 23-group SMU CS-BS tree before being written --
see the build task's investigation report for the full classification table
and the two corrections it found over the naive group_type-only rule:

  - Statistical Methods is group_type == 'enumerated_all' (which every other
    leaf of that type treats as no-choice) but its one option is
    logic == 'or' over 3 alternative courses -- a real per-course choice
    group_type alone does not reveal. Every option under a leaf must be
    logic == 'and' for it to be genuinely no-choice.
  - compound_any nodes (e.g. "Two Courses", a choice among 4 content areas)
    are not decomposed into their children's own group_types even though
    some of those children are individually no-choice -- doing so would
    schedule courses for content areas the student has not chosen. A
    compound_any is skipped if already SATISFIED (resolved by the student's
    real history) and otherwise deferred as a single opaque unit.

Pure: consumes evaluate_requirement_tree()'s output plus the same raw
options/option_courses/catalog_by_gid rows
requirement_satisfaction_fetch.fetch_requirement_tree() already returns --
no new fetch, no Client.
"""

from __future__ import annotations

from typing import Any, Mapping

from .requirement_satisfaction import RequirementGroupResult, RequirementGroupStatus
from .scheduler import CourseToSchedule, UnscheduledRequirement, UnscheduledReason

_SELECTION_LEAF_TYPES = {"enumerated_at_least_n", "enumerated_credit_threshold"}


def _options_have_choice(options: list[dict], courses_by_option: dict[str, list[dict]]) -> bool:
    """True if any option offers a genuine OR among multiple alternative
    courses -- the Statistical Methods case."""
    return any(
        option.get("logic") == "or" and len(courses_by_option.get(option["id"], [])) > 1 for option in options
    )


def _leaf_course_requirements(
    options: list[dict],
    courses_by_option: dict[str, list[dict]],
    catalog_by_gid: Mapping[str, str],
    catalog_by_code: Mapping[str, list[str]] | None = None,
) -> list[frozenset[str]]:
    """One entry per requirement_group_option_courses row, each entry the
    set of course codes that would satisfy that ONE row -- resolves via
    coursedog_group_id (SMU) or course_code (TAMU, any future
    non-Coursedog school), same additive pattern established in
    course_discovery/requirement_satisfaction.py's _resolve_option_codes().

    Normally a singleton set. Exactly 2 codes only for a course_code row
    that is a "/"-joined cross-listing (e.g. "ENGR 216/PHYS 216",
    resolved to both real codes by catalog_by_code) -- that is ONE course
    requirement satisfiable under either department code, not two
    separate courses to schedule. Renamed from the pre-course_code
    _leaf_course_codes(), which returned a flat set() -- that shape
    cannot represent "these 2 codes are the same requirement" and would
    silently double-schedule a cross-listed course under both codes if
    naively extended; callers must treat each list entry as one
    requirement, never flatten it into a single set.
    """
    catalog_by_code = catalog_by_code or {}
    requirements: list[frozenset[str]] = []
    for option in options:
        for course in courses_by_option.get(option["id"], []):
            gid = course.get("coursedog_group_id")
            if gid:
                code = catalog_by_gid.get(gid)
                if code:
                    requirements.append(frozenset({code}))
                continue
            course_code = course.get("course_code")
            if course_code:
                codes = catalog_by_code.get(course_code, [])
                if codes:
                    requirements.append(frozenset(codes))
    return requirements


def scope_schedule_input(
    groups: list[RequirementGroupResult],
    options: list[Mapping[str, Any]],
    option_courses: list[Mapping[str, Any]],
    catalog_by_gid: Mapping[str, str],
    catalog_credit_by_code: Mapping[str, float],
    catalog_by_code: Mapping[str, list[str]] | None = None,
    transcript_course_codes: set[str] | None = None,
    excluded_group_ids: set[str] | None = None,
) -> tuple[list[CourseToSchedule], list[UnscheduledRequirement]]:
    catalog_by_code = catalog_by_code or {}
    transcript_course_codes = transcript_course_codes or set()
    excluded_group_ids = excluded_group_ids or set()
    options_by_group: dict[str, list[dict]] = {}
    for option in options:
        options_by_group.setdefault(option["requirement_group_id"], []).append(dict(option))

    courses_by_option: dict[str, list[dict]] = {}
    for course in option_courses:
        courses_by_option.setdefault(course["requirement_group_option_id"], []).append(dict(course))

    courses: list[CourseToSchedule] = []
    unscheduled: list[UnscheduledRequirement] = []

    def defer(group: RequirementGroupResult, reason: UnscheduledReason) -> None:
        unscheduled.append(
            UnscheduledRequirement(requirement_group_id=group.id, name=group.name, reason=reason)
        )

    def visit(group: RequirementGroupResult) -> None:
        is_leaf = len(group.children) == 0

        if not is_leaf:
            if group.group_type == "compound_all":
                for child in group.children:
                    visit(child)
                return
            if group.group_type == "compound_any":
                if group.status != RequirementGroupStatus.SATISFIED:
                    defer(group, "SELECTION_DEFERRED")
                return
            # No other non-leaf group_type exists in the schema today; fail
            # closed rather than silently guessing at one this was never
            # validated against.
            defer(group, "SELECTION_DEFERRED")
            return

        if group.status == RequirementGroupStatus.SATISFIED:
            return

        if group.group_type == "freeform":
            defer(group, "FREEFORM_MANUAL_REVIEW")
            return

        if group.group_type in _SELECTION_LEAF_TYPES:
            defer(group, "SELECTION_DEFERRED")
            return

        if group.group_type != "enumerated_all":
            defer(group, "SELECTION_DEFERRED")
            return

        group_options = options_by_group.get(group.id, [])
        if _options_have_choice(group_options, courses_by_option):
            defer(group, "SELECTION_DEFERRED")
            return

        # A genuinely no-choice leaf the student has deliberately set aside:
        # defer it as SELECTION_DEFERRED instead of scheduling its courses, so
        # select_structured_requirements() picks it up as `structured` and
        # forces the EXCLUDED decision. Placed AFTER the SATISFIED early-return
        # and the real-choice checks above -- exclusion only ever diverts the
        # single-mandatory auto-schedule path, never a satisfied or a
        # choice-shaped group.
        if group.id in excluded_group_ids:
            defer(group, "SELECTION_DEFERRED")
            return

        group_requirements = _leaf_course_requirements(
            group_options, courses_by_option, catalog_by_gid, catalog_by_code
        )
        matched = set(group.matched_course_codes)
        # `seen` guards the same de-duplication the old flat set() gave for
        # free: if two rows happen to resolve to the identical single code
        # (or share a code with an already-scheduled cross-listing), only
        # the first is scheduled, not one CourseToSchedule per row.
        seen: set[str] = set()
        for requirement_codes in sorted(group_requirements, key=lambda codes: sorted(codes)):
            if requirement_codes & matched:
                continue
            if requirement_codes & seen:
                continue
            # A cross-listed requirement (>1 code) picks whichever
            # alternative has usable catalog credit-hours -- it is ONE
            # course under two department codes, so exactly one
            # CourseToSchedule is emitted, never one per code (see
            # _leaf_course_requirements' docstring on why the flat-set
            # shape this replaced would have double-scheduled it). An alias
            # on the student's transcript is preferred (so this schedules
            # under the code the student will actually see); otherwise the
            # lexicographically-first with usable credit data. In practice a
            # transcript alias also makes `requirement_codes & matched`
            # above true and the requirement is skipped before reaching
            # here, so this is a belt-and-braces tie-break.
            chosen_code: str | None = None
            chosen_credit: float | None = None
            for candidate in sorted(
                requirement_codes, key=lambda code: (code not in transcript_course_codes, code)
            ):
                credit_hours = catalog_credit_by_code.get(candidate)
                if credit_hours is not None and credit_hours > 0:
                    chosen_code = candidate
                    chosen_credit = credit_hours
                    break
            seen.update(requirement_codes)
            if chosen_code is None:
                # No usable catalog credit-hours row for any alternative --
                # CourseToSchedule requires credit_hours > 0. Does not occur
                # for any of Ethan Brooks' or Deepak's real remaining
                # courses; a defensive skip so one unmapped course doesn't
                # take down the whole schedule, matching this module's
                # fail-closed posture elsewhere.
                continue
            courses.append(
                CourseToSchedule(
                    course_code=chosen_code,
                    credit_hours=chosen_credit,
                    requirement_group_id=group.id,
                    requirement_group_name=group.name,
                )
            )

    for group in groups:
        visit(group)

    return courses, unscheduled
