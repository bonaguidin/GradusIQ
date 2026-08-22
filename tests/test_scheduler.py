"""Tests for course_discovery/scheduler.py -- the v1 degree-requirement
scheduler (planning-docs/degree-planner-spec.md §10/§10.1).

Case 1 (test_ethan_brooks_13_course_v1_scope) replays the real corrected
13-course v1 scope against real prerequisite text pulled live this
session from data/catalog/smu/*.json, checked into
tests/fixtures/ethan_brooks_scheduler_input.json -- the same
live-data-fixture discipline test_requirement_satisfaction.py and
test_structured_prerequisite.py already use. Cases 2-4 hand-build minimal
inputs for the OR-clause, over-constrained, and cycle-detection paths, no
catalog data involved.
"""

from __future__ import annotations

import json
from pathlib import Path

from GradusIQ_career.action_planning.models import PlanFailure
from GradusIQ_career.course_discovery.models import (
    CatalogInstitution,
    CourseCatalogRecord,
    PrerequisiteClause,
    StructuredPrerequisite,
)
from GradusIQ_career.course_discovery.prerequisites import structured_prerequisite
from GradusIQ_career.course_discovery.scheduler import (
    CourseToSchedule,
    UnscheduledRequirement,
    satisfied_course_codes,
    schedule_courses,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ethan_brooks_scheduler_input.json"


# ---------------------------------------------------------------------------
# 1. Ethan Brooks -- real 13-course v1 scope, real prerequisite text, real
#    computed schedule (run and verified, not hand-predicted)
# ---------------------------------------------------------------------------


def _catalog_record(course_code: str, prereq: dict) -> CourseCatalogRecord:
    return CourseCatalogRecord(
        institution=CatalogInstitution.SMU,
        course_code=course_code,
        title=course_code,
        description="",
        department="",
        credit_min=0,
        credit_max=0,
        prerequisite_text=prereq["text"],
        prerequisite_courses=prereq["courses"],
        restrictions=[],
        cross_listings=[],
        catalog_year="2026-2027",
        source_url="https://catalog.smu.edu",
        source_last_checked="2026-08-19",
    )


def _load_ethan_brooks_case():
    fixture = json.loads(FIXTURE_PATH.read_text())
    courses = [CourseToSchedule(**row) for row in fixture["courses"]]
    prerequisites = {
        code: structured_prerequisite(_catalog_record(code, prereq))
        for code, prereq in fixture["prerequisites"].items()
    }
    satisfied = satisfied_course_codes(fixture["course_records"])
    unscheduled = [UnscheduledRequirement(**row) for row in fixture["unscheduled"]]
    return fixture, courses, prerequisites, satisfied, unscheduled


def test_ethan_brooks_13_course_v1_scope():
    """Real computed schedule for the corrected 13-course scope, 15-credit
    cap, starting 2026-Fall (today, per system context, sits right at that
    term's boundary -- see spec §10's term-horizon discussion).

    Reflects the bare-comma-as-OR parsing fix (prerequisites.py's
    _clauses_for_codes()): CS 3353's real text "C- or better in CS 2341,
    CS 2353." now correctly splits into two hard AND edges instead of one
    dropped-and-flagged OR-set clause, so CS 3353 lands strictly after CS
    2341/CS 2353 (2027-Spring), not in the same term as them -- see the
    fixture's own _notes for the before/after. CS 5330's real "..., CS
    2341, CS 2353, and CS 3341." similarly now carries all three as real
    edges, with no limitations left on either course.
    """
    fixture, courses, prerequisites, satisfied, unscheduled = _load_ethan_brooks_case()

    result = schedule_courses(
        student_id=fixture["student_id"],
        program_id=fixture["program_id"],
        courses=courses,
        prerequisites=prerequisites,
        already_satisfied=satisfied,
        unscheduled=unscheduled,
        starting_year=2026,
        starting_season="Fall",
        max_terms=6,
        credit_hour_cap=15.0,
    )

    assert result.status == "SCHEDULED"
    assert result.failure is None
    assert result.student_id == fixture["student_id"]
    assert result.program_id == fixture["program_id"]

    # Every one of the 13 courses is scheduled exactly once.
    scheduled_codes = [c.course_code for term in result.terms for c in term.courses]
    assert sorted(scheduled_codes) == sorted(c.course_code for c in courses)
    assert len(scheduled_codes) == len(set(scheduled_codes)) == 13

    # Real computed term plan -- now 4 terms, well inside Ethan's 6-term
    # horizon to Spring 2029. Correct explicit-corequisite semantics let
    # CS 5328 share 2027-Fall with CS 5330 (while CS 3341 remains a strict
    # earlier-term prerequisite), which in turn unlocks CS 5351 one term
    # earlier. No course was added, removed, or specially placed for Ethan.
    assert [term.term_key for term in result.terms] == [
        "2026-Fall", "2027-Spring", "2027-Fall", "2028-Spring",
    ]
    by_term = {term.term_key: sorted(c.course_code for c in term.courses) for term in result.terms}
    assert by_term["2026-Fall"] == [
        "CS 2341", "CS 2353", "ENGR 2112", "ENGR 3101", "ENGR 4101", "MATH 3304",
    ]
    assert by_term["2027-Spring"] == ["CS 3341", "CS 3353"]
    assert by_term["2027-Fall"] == ["CS 5328", "CS 5330", "CS 5343", "CS 5344"]
    assert by_term["2028-Spring"] == ["CS 5351"]

    # Credit totals per term, none exceeding the 15-credit cap.
    totals = {term.term_key: term.total_credit_hours for term in result.terms}
    assert totals == {
        "2026-Fall": 12.0, "2027-Spring": 6.0, "2027-Fall": 12.0,
        "2028-Spring": 3.0,
    }
    assert sum(totals.values()) == 33.0
    assert all(total <= 15.0 for total in totals.values())

    # No limitations anywhere -- every real prerequisite among these 13
    # courses now resolves to either an already-satisfied clause or a
    # clean hard AND edge; the bare-comma-as-OR bug that used to leave
    # CS 3353/CS 5330 flagged is fixed.
    limitations_by_code = {
        c.course_code: c.limitations for term in result.terms for c in term.courses
    }
    assert all(lims == [] for lims in limitations_by_code.values())

    # CS Core's real prereq chain is respected: CS 2341 before CS 3341
    # AND before CS 3353 (now a real edge, not dropped), CS 3341 before
    # its dependents, CS 5328 before CS 5351.
    term_index = {code: i for i, term in enumerate(result.terms) for code in by_term[term.term_key]}
    assert term_index["CS 2341"] < term_index["CS 3341"]
    assert term_index["CS 2341"] < term_index["CS 3353"]
    assert term_index["CS 2353"] < term_index["CS 3353"]
    assert term_index["CS 3341"] < term_index["CS 5330"]
    assert term_index["CS 3341"] < term_index["CS 5328"]
    assert term_index["CS 5330"] <= term_index["CS 5328"]
    assert term_index["CS 3341"] < term_index["CS 5344"]
    assert term_index["CS 5328"] < term_index["CS 5351"]

    # Deferred groups pass through unchanged, never silently dropped.
    assert len(result.unscheduled) == 7
    assert {u.reason for u in result.unscheduled} == {"SELECTION_DEFERRED", "FREEFORM_MANUAL_REVIEW"}
    assert result.unscheduled == unscheduled


# ---------------------------------------------------------------------------
# 2. OR-clause: dropped and flagged, never silently resolved either way
# ---------------------------------------------------------------------------


def test_or_clause_edge_is_dropped_and_flagged_not_resolved():
    """C requires (A or B); neither A nor B is satisfied or scheduled.
    Per §10.1's decision: no hard edge synthesized (C must not wait on
    both, nor be silently treated as free of the requirement), and the
    fact is recorded as a limitation."""
    courses = [
        CourseToSchedule(course_code="A", credit_hours=3, requirement_group_id="g1", requirement_group_name="A"),
        CourseToSchedule(course_code="B", credit_hours=3, requirement_group_id="g1", requirement_group_name="B"),
        CourseToSchedule(course_code="C", credit_hours=3, requirement_group_id="g2", requirement_group_name="C"),
    ]
    prerequisites = {
        "C": StructuredPrerequisite(requires_all=[PrerequisiteClause(course_codes=["A", "B"])]),
    }

    result = schedule_courses(
        student_id="stu-1", program_id="prog-1",
        courses=courses, prerequisites=prerequisites, already_satisfied=set(), unscheduled=[],
        starting_year=2026, starting_season="Fall", max_terms=4,
    )

    assert result.status == "SCHEDULED"
    # No edge: A, B, and C are all immediately ready and land in the same
    # first term -- not "resolved" toward requiring either alternative.
    assert len(result.terms) == 1
    assert sorted(c.course_code for c in result.terms[0].courses) == ["A", "B", "C"]
    c_course = next(c for c in result.terms[0].courses if c.course_code == "C")
    assert c_course.limitations == [
        "prerequisite (A or B) not modeled as a hard ordering edge -- "
        "OR-clause, not tracked to a single alternative"
    ]
    a_course = next(c for c in result.terms[0].courses if c.course_code == "A")
    assert a_course.limitations == []


def test_or_clause_trivially_satisfied_by_already_completed_alternative():
    """C requires (A or B); A is already satisfied. The clause is met --
    no edge, no limitation -- since at least one real alternative is
    already done, unlike the previous case where neither was."""
    courses = [
        CourseToSchedule(course_code="C", credit_hours=3, requirement_group_id="g2", requirement_group_name="C"),
    ]
    prerequisites = {
        "C": StructuredPrerequisite(requires_all=[PrerequisiteClause(course_codes=["A", "B"])]),
    }

    result = schedule_courses(
        student_id="stu-1", program_id="prog-1",
        courses=courses, prerequisites=prerequisites, already_satisfied={"A"}, unscheduled=[],
        starting_year=2026, starting_season="Fall", max_terms=4,
    )

    assert result.status == "SCHEDULED"
    assert len(result.terms) == 1
    assert result.terms[0].courses[0].limitations == []


# ---------------------------------------------------------------------------
# 3. Over-constrained: fails closed, no partial/silently-wrong plan
# ---------------------------------------------------------------------------


def test_over_constrained_fails_closed_not_silently_truncated():
    """4 independent 15-credit courses (the cap itself), only 1 term
    available -- 3 of the 4 can never be placed. Must fail closed with a
    populated PlanFailure, not silently return a 1-term plan missing 3
    required courses."""
    courses = [
        CourseToSchedule(course_code=code, credit_hours=15, requirement_group_id="g", requirement_group_name="g")
        for code in ("A", "B", "C", "D")
    ]

    result = schedule_courses(
        student_id="stu-1", program_id="prog-1",
        courses=courses, prerequisites={}, already_satisfied=set(), unscheduled=[],
        starting_year=2026, starting_season="Fall", max_terms=1, credit_hour_cap=15.0,
    )

    assert result.status == "ERROR"
    assert isinstance(result.failure, PlanFailure)
    assert result.failure.error_class == "OverConstrained"
    assert result.terms == []
    assert result.unscheduled == []


def test_single_course_exceeding_cap_fails_closed():
    """A course whose own credit_hours exceeds the cap can never be
    scheduled at all -- distinct failure reason from the general
    over-constrained case, still fails closed the same way."""
    courses = [
        CourseToSchedule(course_code="A", credit_hours=18, requirement_group_id="g", requirement_group_name="g"),
    ]

    result = schedule_courses(
        student_id="stu-1", program_id="prog-1",
        courses=courses, prerequisites={}, already_satisfied=set(), unscheduled=[],
        starting_year=2026, starting_season="Fall", max_terms=4, credit_hour_cap=15.0,
    )

    assert result.status == "ERROR"
    assert result.failure.error_class == "CreditHourCapTooSmall"
    assert result.terms == []


# ---------------------------------------------------------------------------
# 4. Cycle detection: fails closed rather than looping or crashing
# ---------------------------------------------------------------------------


def test_two_course_cycle_fails_closed():
    """A requires B, B requires A -- adapted from
    test_action_planning_query.py's own two-node-cycle case. Confirms
    detect_cycles() is genuinely reused (not reimplemented) by exercising
    the same failure shape that module's own tests check for."""
    courses = [
        CourseToSchedule(course_code="A", credit_hours=3, requirement_group_id="g", requirement_group_name="g"),
        CourseToSchedule(course_code="B", credit_hours=3, requirement_group_id="g", requirement_group_name="g"),
    ]
    prerequisites = {
        "A": StructuredPrerequisite(requires_all=[PrerequisiteClause(course_codes=["B"])]),
        "B": StructuredPrerequisite(requires_all=[PrerequisiteClause(course_codes=["A"])]),
    }

    result = schedule_courses(
        student_id="stu-1", program_id="prog-1",
        courses=courses, prerequisites=prerequisites, already_satisfied=set(), unscheduled=[],
        starting_year=2026, starting_season="Fall", max_terms=4,
    )

    assert result.status == "ERROR"
    assert result.failure.error_class == "CycleDetected"
    assert result.terms == []
    assert result.unscheduled == []


def test_three_course_cycle_fails_closed():
    courses = [
        CourseToSchedule(course_code=code, credit_hours=3, requirement_group_id="g", requirement_group_name="g")
        for code in ("A", "B", "C")
    ]
    prerequisites = {
        "A": StructuredPrerequisite(requires_all=[PrerequisiteClause(course_codes=["B"])]),
        "B": StructuredPrerequisite(requires_all=[PrerequisiteClause(course_codes=["C"])]),
        "C": StructuredPrerequisite(requires_all=[PrerequisiteClause(course_codes=["A"])]),
    }

    result = schedule_courses(
        student_id="stu-1", program_id="prog-1",
        courses=courses, prerequisites=prerequisites, already_satisfied=set(), unscheduled=[],
        starting_year=2026, starting_season="Fall", max_terms=4,
    )

    assert result.status == "ERROR"
    assert result.failure.error_class == "CycleDetected"


# ---------------------------------------------------------------------------
# 5. Corequisites: same-term eligible without weakening strict prerequisites
# ---------------------------------------------------------------------------


def _course_to_schedule(code: str, credits: float = 3) -> CourseToSchedule:
    return CourseToSchedule(
        course_code=code,
        credit_hours=credits,
        requirement_group_id="g",
        requirement_group_name="g",
    )


def test_corequisite_pair_may_share_the_same_term():
    courses = [_course_to_schedule("A"), _course_to_schedule("B")]
    prerequisites = {"B": StructuredPrerequisite(coreq_allowed=["A"])}

    result = schedule_courses(
        student_id="stu-1", program_id="prog-1",
        courses=courses, prerequisites=prerequisites, already_satisfied=set(), unscheduled=[],
        starting_year=2026, starting_season="Fall", max_terms=2,
    )

    assert result.status == "SCHEDULED"
    assert [[course.course_code for course in term.courses] for term in result.terms] == [["A", "B"]]


def test_mutual_corequisites_form_same_term_component_not_false_cycle():
    courses = [_course_to_schedule("A"), _course_to_schedule("B")]
    prerequisites = {
        "A": StructuredPrerequisite(coreq_allowed=["B"]),
        "B": StructuredPrerequisite(
            requires_all=[PrerequisiteClause(course_codes=["A"])],
            coreq_allowed=["A"],
        ),
    }

    result = schedule_courses(
        student_id="stu-1", program_id="prog-1",
        courses=courses, prerequisites=prerequisites, already_satisfied=set(), unscheduled=[],
        starting_year=2026, starting_season="Fall", max_terms=2,
    )

    assert result.status == "SCHEDULED"
    assert sorted(course.course_code for course in result.terms[0].courses) == ["A", "B"]


def test_mixed_strict_and_corequisite_graph_preserves_earlier_term_boundary():
    courses = [_course_to_schedule(code) for code in ("A", "B", "C")]
    prerequisites = {
        "B": StructuredPrerequisite(
            requires_all=[PrerequisiteClause(course_codes=["A"])],
            coreq_allowed=["C"],
        ),
        "C": StructuredPrerequisite(
            requires_all=[PrerequisiteClause(course_codes=["A"])],
        ),
    }

    result = schedule_courses(
        student_id="stu-1", program_id="prog-1",
        courses=courses, prerequisites=prerequisites, already_satisfied=set(), unscheduled=[],
        starting_year=2026, starting_season="Fall", max_terms=3,
    )

    assert result.status == "SCHEDULED"
    term_index = {
        course.course_code: index
        for index, term in enumerate(result.terms)
        for course in term.courses
    }
    assert term_index["A"] < term_index["B"]
    assert term_index["C"] == term_index["B"]


def test_corequisite_capacity_places_one_way_corequisite_earlier():
    courses = [_course_to_schedule("A", 9), _course_to_schedule("B", 9)]
    prerequisites = {"B": StructuredPrerequisite(coreq_allowed=["A"])}

    result = schedule_courses(
        student_id="stu-1", program_id="prog-1",
        courses=courses, prerequisites=prerequisites, already_satisfied=set(), unscheduled=[],
        starting_year=2026, starting_season="Fall", max_terms=2, credit_hour_cap=15,
    )

    assert result.status == "SCHEDULED"
    assert [[course.course_code for course in term.courses] for term in result.terms] == [["A"], ["B"]]
    assert all(term.total_credit_hours <= 15 for term in result.terms)


def test_mutual_corequisite_pair_that_exceeds_cap_fails_closed():
    courses = [_course_to_schedule("A", 9), _course_to_schedule("B", 9)]
    prerequisites = {
        "A": StructuredPrerequisite(coreq_allowed=["B"]),
        "B": StructuredPrerequisite(coreq_allowed=["A"]),
    }

    result = schedule_courses(
        student_id="stu-1", program_id="prog-1",
        courses=courses, prerequisites=prerequisites, already_satisfied=set(), unscheduled=[],
        starting_year=2026, starting_season="Fall", max_terms=2, credit_hour_cap=15,
    )

    assert result.status == "ERROR"
    assert result.failure.error_class == "OverConstrained"


# ---------------------------------------------------------------------------
# Small direct-unit coverage for the pieces not exercised enough above
# ---------------------------------------------------------------------------


def test_satisfied_course_codes_counts_in_progress_as_cleared():
    """§10.1's in-progress-counts-as-cleared decision -- a deliberate
    divergence from evaluate_prerequisites()'s conservative real-time
    gate, documented on the function itself."""
    records = [
        {"course_code": "A", "status": "completed"},
        {"course_code": "B", "status": "in_progress"},
        {"course_code": "C", "status": "planned"},
        {"course_code": "D", "status": "dropped"},
    ]
    assert satisfied_course_codes(records) == {"A", "B"}


def test_empty_course_list_schedules_trivially():
    result = schedule_courses(
        student_id="stu-1", program_id="prog-1",
        courses=[], prerequisites={}, already_satisfied=set(), unscheduled=[],
        starting_year=2026, starting_season="Fall", max_terms=4,
    )
    assert result.status == "SCHEDULED"
    assert result.terms == []


def test_unsupported_starting_season_raises():
    courses = [
        CourseToSchedule(course_code="A", credit_hours=3, requirement_group_id="g", requirement_group_name="g"),
        CourseToSchedule(course_code="B", credit_hours=3, requirement_group_id="g", requirement_group_name="g"),
    ]
    prerequisites = {"B": StructuredPrerequisite(requires_all=[PrerequisiteClause(course_codes=["A"])])}
    import pytest

    with pytest.raises(ValueError, match="Unsupported starting season"):
        schedule_courses(
            student_id="stu-1", program_id="prog-1",
            courses=courses, prerequisites=prerequisites, already_satisfied=set(), unscheduled=[],
            starting_year=2026, starting_season="Summer", max_terms=4,
        )
