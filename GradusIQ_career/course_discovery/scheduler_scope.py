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


def _leaf_course_codes(
    options: list[dict],
    courses_by_option: dict[str, list[dict]],
    catalog_by_gid: Mapping[str, str],
) -> set[str]:
    codes: set[str] = set()
    for option in options:
        for course in courses_by_option.get(option["id"], []):
            gid = course.get("coursedog_group_id")
            code = catalog_by_gid.get(gid) if gid else None
            if code:
                codes.add(code)
    return codes


def scope_schedule_input(
    groups: list[RequirementGroupResult],
    options: list[Mapping[str, Any]],
    option_courses: list[Mapping[str, Any]],
    catalog_by_gid: Mapping[str, str],
    catalog_credit_by_code: Mapping[str, float],
) -> tuple[list[CourseToSchedule], list[UnscheduledRequirement]]:
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

        required = _leaf_course_codes(group_options, courses_by_option, catalog_by_gid)
        remaining = sorted(required - set(group.matched_course_codes))
        for code in remaining:
            credit_hours = catalog_credit_by_code.get(code)
            if credit_hours is None or credit_hours <= 0:
                # No usable catalog credit-hours row for this course --
                # CourseToSchedule requires credit_hours > 0. Does not occur
                # for any of Ethan Brooks' real remaining courses; a
                # defensive skip so one unmapped course doesn't take down
                # the whole schedule, matching this module's fail-closed
                # posture elsewhere.
                continue
            courses.append(
                CourseToSchedule(
                    course_code=code,
                    credit_hours=credit_hours,
                    requirement_group_id=group.id,
                    requirement_group_name=group.name,
                )
            )

    for group in groups:
        visit(group)

    return courses, unscheduled
