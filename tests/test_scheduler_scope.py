"""Tests for course_discovery/scheduler_scope.py -- the classifier splitting
an evaluated requirement tree into the v1 scheduler's two inputs.

Case 1 replays the real 23-group SMU CS-BS tree (same fixture
test_requirement_satisfaction.py's ground-truth test uses) and asserts the
classification the build task's investigation validated by hand: every
no-choice course scope_schedule_input() produces matches the real curated
13-course v1 scope in tests/fixtures/ethan_brooks_scheduler_input.json, and
every deferred/skipped group matches too -- including the two corrections
the investigation found over a naive group_type-only rule (Statistical
Methods' hidden or-choice, and "Two Courses" staying one opaque
SELECTION_DEFERRED unit rather than being decomposed into its
individually-no-choice-looking children).
"""

from __future__ import annotations

import json
from pathlib import Path

from GradusIQ_career.course_discovery.requirement_satisfaction import evaluate_requirement_tree
from GradusIQ_career.course_discovery.scheduler_scope import scope_schedule_input

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ethan_brooks_requirement_tree.json"
SCHEDULE_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ethan_brooks_scheduler_input.json"


def _group(group_id, name, group_type, *, parent_group_id=None, coursedog_rule_id=None, n_required=None):
    return {
        "id": group_id,
        "coursedog_rule_id": coursedog_rule_id or group_id,
        "parent_group_id": parent_group_id,
        "name": name,
        "group_type": group_type,
        "n_required": n_required if n_required is not None else (1 if group_type == "enumerated_at_least_n" else None),
        "credit_hours_required": None,
        "requires_manual_definition": False,
    }


def _option(option_id, group_id, index, logic="and"):
    return {"id": option_id, "requirement_group_id": group_id, "option_index": index, "logic": logic}


def _option_course(option_id, coursedog_group_id):
    return {
        "requirement_group_option_id": option_id,
        "coursedog_group_id": coursedog_group_id,
        "unresolved_course_ref": None,
    }


# ---------------------------------------------------------------------------
# 1. Ethan Brooks -- real 23-group tree, real 8 course_records, ground truth
# ---------------------------------------------------------------------------


def test_ethan_brooks_full_tree_matches_curated_v1_scope():
    fixture = json.loads(FIXTURE_PATH.read_text())
    groups = evaluate_requirement_tree(
        fixture["groups"], fixture["options"], fixture["option_courses"], fixture["course_records"],
        fixture["catalog_by_gid"],
    )

    # credit_min == credit_max for every one of Ethan's real remaining
    # courses (checked directly against data/catalog/smu/*.json), so a flat
    # code -> credit_min map is enough ground truth for this test.
    catalog_credit_by_code = {
        "ENGR 2112": 1.0, "MATH 3304": 3.0, "CS 2353": 3.0, "ENGR 3101": 1.0, "ENGR 4101": 1.0,
        "CS 2341": 3.0, "CS 3341": 3.0, "CS 3353": 3.0, "CS 5328": 3.0, "CS 5330": 3.0,
        "CS 5343": 3.0, "CS 5344": 3.0, "CS 5351": 3.0,
    }

    courses, unscheduled = scope_schedule_input(
        groups, fixture["options"], fixture["option_courses"], fixture["catalog_by_gid"], catalog_credit_by_code,
    )

    schedule_fixture = json.loads(SCHEDULE_FIXTURE_PATH.read_text())
    expected_courses = {row["course_code"] for row in schedule_fixture["courses"]}
    expected_unscheduled = {(row["name"], row["reason"]) for row in schedule_fixture["unscheduled"]}

    assert {course.course_code for course in courses} == expected_courses
    assert len(courses) == 13
    assert {(entry.name, entry.reason) for entry in unscheduled} == expected_unscheduled
    assert len(unscheduled) == 7

    # requirement_group_name is carried through for traceability, same as
    # scheduler.py's own CourseToSchedule contract requires.
    by_code = {course.course_code: course for course in courses}
    assert by_code["CS 2341"].requirement_group_name == "Computer Science Core (33 Credit Hours)"
    assert by_code["ENGR 3101"].requirement_group_name == "Interdisciplinary Projects (3 Credit Hours)"

    # The two corrections the investigation found, asserted explicitly:
    # Statistical Methods is enumerated_all but has a hidden or-choice, so it
    # must be deferred, not scheduled.
    assert "Statistical Methods" not in {course.requirement_group_name for course in courses}
    assert ("Statistical Methods", "SELECTION_DEFERRED") in {(e.name, e.reason) for e in unscheduled}
    # "Two Courses" (compound_any, not satisfied) is one opaque deferred
    # unit -- its enumerated_all children (Content Area 1 Biology, Content
    # Area 2 Chemistry) are never individually scheduled.
    assert ("Two Courses", "SELECTION_DEFERRED") in {(e.name, e.reason) for e in unscheduled}
    assert "Content Area 1, Biology" not in {e.name for e in unscheduled}
    assert "Content Area 2, Chemistry" not in {e.name for e in unscheduled}
    for name in ("Content Area 1, Biology", "Content Area 2, Chemistry", "Content Area 3, Geology", "Content Area 4, Physics"):
        assert name not in {course.requirement_group_name for course in courses}

    # Calculus Sequence (compound_any) is SATISFIED via Calculus I & II --
    # skipped entirely, not deferred, not decomposed.
    assert "Calculus Sequence" not in {e.name for e in unscheduled}
    assert "Calculus I & II" not in {e.name for e in unscheduled}
    assert "Consolidated Calculus" not in {e.name for e in unscheduled}
    assert "Calculus I & II" not in {course.requirement_group_name for course in courses}
    assert "Consolidated Calculus" not in {course.requirement_group_name for course in courses}

    # Already-SATISFIED leaves (AI Fundamentals, Leadership and Mentoring)
    # contribute nothing.
    assert "AI Fundamentals (3 Credit Hours)" not in {course.requirement_group_name for course in courses}
    assert "AI Fundamentals (3 Credit Hours)" not in {e.name for e in unscheduled}
    assert "Leadership and Mentoring (1-3 Credit Hours)" not in {course.requirement_group_name for course in courses}
    assert "Leadership and Mentoring (1-3 Credit Hours)" not in {e.name for e in unscheduled}


# ---------------------------------------------------------------------------
# 2. compound_any, hand-built minimal cases
# ---------------------------------------------------------------------------


def test_compound_any_satisfied_is_skipped_not_decomposed():
    """A compound_any resolved by the student's real history contributes
    nothing -- not even a scan of which branch was taken."""
    raw_groups = [
        _group("parent", "Either Track", "compound_any"),
        _group("done", "Track A", "enumerated_all", parent_group_id="parent"),
        _group("open", "Track B", "enumerated_all", parent_group_id="parent"),
    ]
    options = [_option("opt-done", "done", 0), _option("opt-open", "open", 0)]
    option_courses = [_option_course("opt-done", "gidA"), _option_course("opt-open", "gidB")]
    course_records = [{"course_code": "AAA 1", "status": "completed", "counts_toward_credit": True}]
    catalog_by_gid = {"gidA": "AAA 1", "gidB": "BBB 1"}

    groups = evaluate_requirement_tree(raw_groups, options, option_courses, course_records, catalog_by_gid)
    courses, unscheduled = scope_schedule_input(groups, options, option_courses, catalog_by_gid, {"BBB 1": 3.0})

    assert courses == []
    assert unscheduled == []


def test_compound_any_in_progress_is_one_deferred_unit_not_decomposed():
    """A compound_any with partial progress on one branch (but no branch
    fully SATISFIED) is still deferred as a whole -- the choice among
    branches remains unresolved, so nothing is scheduled out of either
    branch. This is the case the prior investigation flagged as
    constructible-but-never-hit-in-real-data; confirming it here."""
    raw_groups = [
        _group("parent", "Either Track", "compound_any"),
        _group("partial", "Track A", "enumerated_all", parent_group_id="parent"),
        _group("open", "Track B", "enumerated_all", parent_group_id="parent"),
    ]
    options = [
        _option("opt-partial-1", "partial", 0),
        _option("opt-partial-2", "partial", 1),
        _option("opt-open", "open", 0),
    ]
    option_courses = [
        _option_course("opt-partial-1", "gidA1"),
        _option_course("opt-partial-2", "gidA2"),
        _option_course("opt-open", "gidB"),
    ]
    # Track A has one of its two required courses in progress -- IN_PROGRESS,
    # not SATISFIED, so the compound_any parent is IN_PROGRESS too (see
    # requirement_satisfaction.py's any_progress branch), never SATISFIED.
    course_records = [{"course_code": "AAA 1", "status": "in_progress", "counts_toward_credit": True}]
    catalog_by_gid = {"gidA1": "AAA 1", "gidA2": "AAA 2", "gidB": "BBB 1"}

    groups = evaluate_requirement_tree(raw_groups, options, option_courses, course_records, catalog_by_gid)
    parent = next(g for g in groups if g.name == "Either Track")
    assert parent.status.value == "IN_PROGRESS"

    courses, unscheduled = scope_schedule_input(
        groups, options, option_courses, catalog_by_gid, {"AAA 2": 3.0, "BBB 1": 3.0},
    )

    assert courses == []
    assert [(e.name, e.reason) for e in unscheduled] == [("Either Track", "SELECTION_DEFERRED")]


# ---------------------------------------------------------------------------
# 3. enumerated_all leaf with a hidden or-choice, isolated
# ---------------------------------------------------------------------------


def test_enumerated_all_leaf_with_or_option_defers_not_schedules():
    """Statistical Methods' exact real shape, isolated: group_type ==
    'enumerated_all' but its one option is logic == 'or' over 3 alternative
    courses -- a real choice group_type alone hides."""
    raw_groups = [_group("stat", "Statistical Methods", "enumerated_all")]
    options = [_option("opt", "stat", 0, logic="or")]
    option_courses = [
        _option_course("opt", "gid1"),
        _option_course("opt", "gid2"),
        _option_course("opt", "gid3"),
    ]
    catalog_by_gid = {"gid1": "STAT 1", "gid2": "STAT 2", "gid3": "STAT 3"}

    groups = evaluate_requirement_tree(raw_groups, options, option_courses, [], catalog_by_gid)
    courses, unscheduled = scope_schedule_input(
        groups, options, option_courses, catalog_by_gid, {"STAT 1": 3.0, "STAT 2": 3.0, "STAT 3": 3.0},
    )

    assert courses == []
    assert [(e.name, e.reason) for e in unscheduled] == [("Statistical Methods", "SELECTION_DEFERRED")]


def test_enumerated_all_leaf_with_only_and_options_schedules_remaining_courses():
    """Contrast case: every option logic == 'and' (a true no-choice chain,
    like Interdisciplinary Projects' 3 required options) schedules whatever
    remains unmatched."""
    raw_groups = [_group("proj", "Interdisciplinary Projects", "enumerated_all")]
    options = [_option("opt0", "proj", 0), _option("opt1", "proj", 1), _option("opt2", "proj", 2)]
    option_courses = [
        _option_course("opt0", "gid0"), _option_course("opt1", "gid1"), _option_course("opt2", "gid2"),
    ]
    catalog_by_gid = {"gid0": "ENGR 2101", "gid1": "ENGR 3101", "gid2": "ENGR 4101"}
    course_records = [{"course_code": "ENGR 2101", "status": "completed", "counts_toward_credit": True}]

    groups = evaluate_requirement_tree(raw_groups, options, option_courses, course_records, catalog_by_gid)
    courses, unscheduled = scope_schedule_input(
        groups, options, option_courses, catalog_by_gid, {"ENGR 3101": 1.0, "ENGR 4101": 1.0},
    )

    assert unscheduled == []
    assert {course.course_code for course in courses} == {"ENGR 3101", "ENGR 4101"}
    assert all(course.requirement_group_name == "Interdisciplinary Projects" for course in courses)


# ---------------------------------------------------------------------------
# 4. Freeform and at-least-n leaves, satisfied vs. not
# ---------------------------------------------------------------------------


def test_freeform_leaf_always_deferred():
    raw_groups = [_group("elective", "Technical Electives", "freeform")]
    groups = evaluate_requirement_tree(raw_groups, [], [], [], {})
    courses, unscheduled = scope_schedule_input(groups, [], [], {}, {})
    assert courses == []
    assert [(e.name, e.reason) for e in unscheduled] == [("Technical Electives", "FREEFORM_MANUAL_REVIEW")]


def test_enumerated_at_least_n_leaf_deferred_unless_satisfied():
    raw_groups = [_group("lead", "Engineering Leadership", "enumerated_at_least_n")]
    options = [_option("opt0", "lead", 0), _option("opt1", "lead", 1)]
    option_courses = [_option_course("opt0", "gid0"), _option_course("opt1", "gid1")]
    catalog_by_gid = {"gid0": "ENGR 5301", "gid1": "ENGR 5302"}

    not_satisfied = evaluate_requirement_tree(raw_groups, options, option_courses, [], catalog_by_gid)
    courses, unscheduled = scope_schedule_input(not_satisfied, options, option_courses, catalog_by_gid, {})
    assert courses == []
    assert [(e.name, e.reason) for e in unscheduled] == [("Engineering Leadership", "SELECTION_DEFERRED")]

    satisfied = evaluate_requirement_tree(
        raw_groups, options, option_courses,
        [{"course_code": "ENGR 5301", "status": "completed", "counts_toward_credit": True}],
        catalog_by_gid,
    )
    courses, unscheduled = scope_schedule_input(satisfied, options, option_courses, catalog_by_gid, {})
    assert courses == []
    assert unscheduled == []


# ---------------------------------------------------------------------------
# 5. compound_all recurses regardless of the parent's own status
# ---------------------------------------------------------------------------


def test_compound_all_recurses_into_every_child_regardless_of_status():
    raw_groups = [
        _group("parent", "Math and Science", "compound_all"),
        _group("done", "Linear Algebra", "enumerated_all", parent_group_id="parent"),
        _group("open", "Discrete Structures", "enumerated_all", parent_group_id="parent"),
    ]
    options = [_option("opt-done", "done", 0), _option("opt-open", "open", 0)]
    option_courses = [_option_course("opt-done", "gidA"), _option_course("opt-open", "gidB")]
    course_records = [{"course_code": "MATH 3304", "status": "completed", "counts_toward_credit": True}]
    catalog_by_gid = {"gidA": "MATH 3304", "gidB": "CS 2353"}

    groups = evaluate_requirement_tree(raw_groups, options, option_courses, course_records, catalog_by_gid)
    parent = next(g for g in groups if g.name == "Math and Science")
    assert parent.status.value == "IN_PROGRESS"

    courses, unscheduled = scope_schedule_input(
        groups, options, option_courses, catalog_by_gid, {"CS 2353": 3.0},
    )

    assert unscheduled == []
    assert {course.course_code for course in courses} == {"CS 2353"}
    assert courses[0].requirement_group_name == "Discrete Structures"
