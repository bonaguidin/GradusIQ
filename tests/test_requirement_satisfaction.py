"""Tests for course_discovery/requirement_satisfaction.py's
evaluate_requirement_tree() -- the pure §9/§9.1 satisfaction evaluator.

No Client, no network, no Supabase -- same posture as
tests/test_structured_prerequisite.py and tests/test_import_catalog.py.

Case 1 (test_ethan_brooks_full_tree) replays the real 23-group SMU CS-BS
tree and Ethan Brooks' real 8 course_records rows, pulled live from the
linked database 2026-08-19 and checked in as
tests/fixtures/ethan_brooks_requirement_tree.json -- the ground-truth
integration-style fixture required by §9.1. Cases 2-3 hand-build minimal
trees using the real structure of Content Area 4 Physics (credit-
threshold) and Statistical Methods (option-level or-logic), per §9.1's
required test coverage. Cases 4+ are standard coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

from GradusIQ_career.course_discovery.requirement_satisfaction import (
    RequirementGroupStatus,
    evaluate_requirement_tree,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ethan_brooks_requirement_tree.json"


def _group(
    group_id,
    name,
    group_type,
    *,
    parent_group_id=None,
    n_required=None,
    credit_hours_required=None,
    requires_manual_definition=False,
    coursedog_rule_id=None,
):
    return {
        "id": group_id,
        "coursedog_rule_id": coursedog_rule_id or group_id,
        "parent_group_id": parent_group_id,
        "name": name,
        "group_type": group_type,
        "n_required": n_required,
        "credit_hours_required": credit_hours_required,
        "requires_manual_definition": requires_manual_definition,
    }


def _option(option_id, group_id, index, logic="and"):
    return {"id": option_id, "requirement_group_id": group_id, "option_index": index, "logic": logic}


def _option_course(option_id, coursedog_group_id=None, unresolved_course_ref=None):
    return {
        "requirement_group_option_id": option_id,
        "coursedog_group_id": coursedog_group_id,
        "unresolved_course_ref": unresolved_course_ref,
    }


def _course_record(course_code, status="completed", credit_hours=3.0, counts_toward_credit=True):
    return {
        "course_code": course_code,
        "status": status,
        "credit_hours": credit_hours,
        "counts_toward_credit": counts_toward_credit,
    }


def _index(results):
    """name -> result, flattened over the whole tree, for compact lookups."""
    out = {}

    def walk(result):
        out[result.name] = result
        for child in result.children:
            walk(child)

    for r in results:
        walk(r)
    return out


def _count_nodes(results):
    return len(results) + sum(_count_nodes(r.children) for r in results)


# ---------------------------------------------------------------------------
# 1. Ethan Brooks -- real 23-group tree, real 8 course_records, ground truth
# ---------------------------------------------------------------------------


def test_ethan_brooks_full_tree():
    fixture = json.loads(FIXTURE_PATH.read_text())
    results = evaluate_requirement_tree(
        fixture["groups"],
        fixture["options"],
        fixture["option_courses"],
        fixture["course_records"],
        fixture["catalog_by_gid"],
    )
    by_name = _index(results)

    assert len(results) == 7  # top-level groups: parent_group_id is null
    assert _count_nodes(results) == 23  # full tree, matching §9.1's live count

    # Lyle EDGE Curriculum and its 6 children
    assert by_name["Lyle EDGE Curriculum (9-13 Credit Hours)"].status == RequirementGroupStatus.IN_PROGRESS
    assert by_name["Lyle EDGE Curriculum (9-13 Credit Hours)"].detail == "2 of 6 children satisfied"

    assert by_name["Interdisciplinary Projects (3 Credit Hours)"].status == RequirementGroupStatus.IN_PROGRESS
    assert by_name["Interdisciplinary Projects (3 Credit Hours)"].matched_course_codes == ["ENGR 2101"]

    assert by_name["AI Fundamentals (3 Credit Hours)"].status == RequirementGroupStatus.SATISFIED
    assert by_name["AI Fundamentals (3 Credit Hours)"].matched_course_codes == ["CS 1311"]

    assert by_name["Advanced/Domain Specific Use/Design of AI"].status == RequirementGroupStatus.NOT_STARTED

    assert by_name["Leadership and Mentoring (1-3 Credit Hours)"].status == RequirementGroupStatus.SATISFIED
    assert by_name["Leadership and Mentoring (1-3 Credit Hours)"].matched_course_codes == ["ENGR 2111"]

    assert by_name["Innovation and Entrepreneurship (1 Credit Hour)"].status == RequirementGroupStatus.NOT_STARTED
    assert by_name["Experiential Learning (1-3 Credit Hours)"].status == RequirementGroupStatus.NOT_STARTED

    # Mathematics and Science and its 4 children
    assert by_name["Mathematics and Science (24-26 Credit Hours)"].status == RequirementGroupStatus.IN_PROGRESS
    assert by_name["Mathematics and Science (24-26 Credit Hours)"].detail == "1 of 4 children satisfied"

    assert by_name["Calculus Sequence"].status == RequirementGroupStatus.SATISFIED
    assert by_name["Calculus Sequence"].detail == "satisfied via Calculus I & II"
    assert by_name["Calculus I & II"].status == RequirementGroupStatus.SATISFIED
    assert by_name["Calculus I & II"].matched_course_codes == ["MATH 1337", "MATH 1338"]
    assert by_name["Consolidated Calculus"].status == RequirementGroupStatus.NOT_STARTED

    assert by_name["Linear Algebra"].status == RequirementGroupStatus.NOT_STARTED
    assert by_name["Discrete Computational Structures"].status == RequirementGroupStatus.NOT_STARTED
    assert by_name["Statistical Methods"].status == RequirementGroupStatus.NOT_STARTED

    # Two Courses and its 4 content areas -- Ethan hasn't touched any of them
    assert by_name["Two Courses"].status == RequirementGroupStatus.NOT_STARTED
    for area in (
        "Content Area 1, Biology",
        "Content Area 2, Chemistry",
        "Content Area 3, Geology",
        "Content Area 4, Physics",
    ):
        assert by_name[area].status == RequirementGroupStatus.NOT_STARTED
    assert by_name["Content Area 4, Physics"].detail == "0 of 7 credits"

    # Remaining top-level groups
    assert by_name["Computer Science Core (33 Credit Hours)"].status == RequirementGroupStatus.IN_PROGRESS
    assert by_name["Computer Science Core (33 Credit Hours)"].matched_course_codes == [
        "CS 1341",
        "CS 1342",
        "CS 2340",
    ]

    assert by_name["Technical Electives (9 Credit Hours)"].status == RequirementGroupStatus.MANUAL_REVIEW
    assert by_name["Advanced Major Electives (3-5 Credit Hours)"].status == RequirementGroupStatus.MANUAL_REVIEW

    assert by_name["Engineering Leadership (6 Credit Hours)"].status == RequirementGroupStatus.NOT_STARTED
    assert by_name["Engineering Leadership (6 Credit Hours)"].detail == "0 of 2 required options satisfied (6 available)"


# ---------------------------------------------------------------------------
# 2. Credit-threshold: Content Area 4, Physics (real structure)
# ---------------------------------------------------------------------------

_PHYSICS_GROUPS = [
    _group(
        "phys",
        "Content Area 4, Physics",
        "enumerated_credit_threshold",
        credit_hours_required=7,
        coursedog_rule_id="T6z1BLsv",
    )
]
_PHYSICS_OPTIONS = [
    _option("opt-1303-1105", "phys", 0, logic="and"),
    _option("opt-1304-1106", "phys", 1, logic="and"),
    _option("opt-3305", "phys", 2, logic="and"),
]
_PHYSICS_OPTION_COURSES = [
    _option_course("opt-1303-1105", coursedog_group_id="g-1303"),
    _option_course("opt-1303-1105", coursedog_group_id="g-1105"),
    _option_course("opt-1304-1106", coursedog_group_id="g-1304"),
    _option_course("opt-1304-1106", coursedog_group_id="g-1106"),
    _option_course("opt-3305", coursedog_group_id="g-3305"),
]
_PHYSICS_CATALOG = {
    "g-1303": "PHYS 1303",
    "g-1105": "PHYS 1105",
    "g-1304": "PHYS 1304",
    "g-1106": "PHYS 1106",
    "g-3305": "PHYS 3305",
}


def _evaluate_physics(course_records):
    results = evaluate_requirement_tree(
        _PHYSICS_GROUPS, _PHYSICS_OPTIONS, _PHYSICS_OPTION_COURSES, course_records, _PHYSICS_CATALOG
    )
    return results[0]


def test_physics_credit_threshold_not_started_at_zero_credits():
    result = _evaluate_physics([])
    assert result.status == RequirementGroupStatus.NOT_STARTED
    assert result.detail == "0 of 7 credits"
    assert result.matched_course_codes == []


def test_physics_credit_threshold_in_progress_partial_credits():
    course_records = [
        _course_record("PHYS 1303", credit_hours=3.0),
        _course_record("PHYS 1105", credit_hours=1.0),
    ]
    result = _evaluate_physics(course_records)
    assert result.status == RequirementGroupStatus.IN_PROGRESS
    assert result.detail == "4 of 7 credits"
    assert result.matched_course_codes == ["PHYS 1105", "PHYS 1303"]


def test_physics_credit_threshold_in_progress_lecture_only():
    """A single matched course (no completed lab yet) still contributes its
    own earned credit hours toward the threshold -- accumulation is per
    course, not gated on its AND-paired option being fully complete."""
    result = _evaluate_physics([_course_record("PHYS 1303", credit_hours=3.0)])
    assert result.status == RequirementGroupStatus.IN_PROGRESS
    assert result.detail == "3 of 7 credits"


def test_physics_credit_threshold_satisfied_crossing_minimum():
    course_records = [
        _course_record("PHYS 1303", credit_hours=3.0),
        _course_record("PHYS 1105", credit_hours=1.0),
        _course_record("PHYS 1304", credit_hours=3.0),
        _course_record("PHYS 1106", credit_hours=1.0),
    ]
    result = _evaluate_physics(course_records)
    assert result.status == RequirementGroupStatus.SATISFIED
    assert result.detail == "8 of 7 credits"


# ---------------------------------------------------------------------------
# 3. Option-level or-logic: Statistical Methods (real structure)
# ---------------------------------------------------------------------------

_STAT_GROUPS = [_group("stat", "Statistical Methods", "enumerated_all", credit_hours_required=3)]
_STAT_OPTIONS = [_option("stat-opt", "stat", 0, logic="or")]
_STAT_OPTION_COURSES = [
    _option_course("stat-opt", coursedog_group_id="g-cs4340"),
    _option_course("stat-opt", coursedog_group_id="g-stat4340"),
    _option_course("stat-opt", coursedog_group_id="g-orem3340"),
]
_STAT_CATALOG = {"g-cs4340": "CS 4340", "g-stat4340": "STAT 4340", "g-orem3340": "OREM 3340"}


def _evaluate_stat(course_records):
    results = evaluate_requirement_tree(
        _STAT_GROUPS, _STAT_OPTIONS, _STAT_OPTION_COURSES, course_records, _STAT_CATALOG
    )
    return results[0]


def test_or_logic_satisfied_by_exactly_one_of_three():
    result = _evaluate_stat([_course_record("STAT 4340")])
    assert result.status == RequirementGroupStatus.SATISFIED
    assert result.matched_course_codes == ["STAT 4340"]
    assert result.detail == "1 of 1 required options satisfied"


def test_or_logic_not_started_when_none_match():
    result = _evaluate_stat([_course_record("CS 1341")])  # unrelated course
    assert result.status == RequirementGroupStatus.NOT_STARTED
    assert result.matched_course_codes == []
    assert result.detail == "0 of 1 required options satisfied"


# ---------------------------------------------------------------------------
# 4. Standard coverage
# ---------------------------------------------------------------------------


def test_everything_not_started_with_no_course_records():
    groups = [
        _group("top", "Top", "compound_all"),
        _group("leaf-a", "Leaf A", "enumerated_all", parent_group_id="top"),
        _group("leaf-b", "Leaf B", "enumerated_all", parent_group_id="top"),
    ]
    options = [_option("opt-a", "leaf-a", 0), _option("opt-b", "leaf-b", 0)]
    option_courses = [
        _option_course("opt-a", coursedog_group_id="g-a"),
        _option_course("opt-b", coursedog_group_id="g-b"),
    ]
    catalog = {"g-a": "AAA 100", "g-b": "BBB 100"}

    results = evaluate_requirement_tree(groups, options, option_courses, [], catalog)
    assert len(results) == 1
    top = results[0]
    assert top.status == RequirementGroupStatus.NOT_STARTED
    assert top.detail == "0 of 2 children satisfied"
    assert all(child.status == RequirementGroupStatus.NOT_STARTED for child in top.children)


def test_compound_all_fully_satisfied():
    groups = [
        _group("top", "Top", "compound_all"),
        _group("leaf-a", "Leaf A", "enumerated_all", parent_group_id="top"),
        _group("leaf-b", "Leaf B", "enumerated_all", parent_group_id="top"),
    ]
    options = [_option("opt-a", "leaf-a", 0), _option("opt-b", "leaf-b", 0)]
    option_courses = [
        _option_course("opt-a", coursedog_group_id="g-a"),
        _option_course("opt-b", coursedog_group_id="g-b"),
    ]
    catalog = {"g-a": "AAA 100", "g-b": "BBB 100"}
    course_records = [_course_record("AAA 100"), _course_record("BBB 100", status="in_progress")]

    results = evaluate_requirement_tree(groups, options, option_courses, course_records, catalog)
    top = results[0]
    assert top.status == RequirementGroupStatus.SATISFIED
    assert top.detail == "2 of 2 children satisfied"


def test_compound_any_satisfied_via_one_path():
    groups = [
        _group("top", "Top", "compound_any"),
        _group("path-a", "Path A", "enumerated_all", parent_group_id="top"),
        _group("path-b", "Path B", "enumerated_all", parent_group_id="top"),
    ]
    options = [_option("opt-a", "path-a", 0), _option("opt-b", "path-b", 0)]
    option_courses = [
        _option_course("opt-a", coursedog_group_id="g-a"),
        _option_course("opt-b", coursedog_group_id="g-b"),
    ]
    catalog = {"g-a": "AAA 100", "g-b": "BBB 100"}
    course_records = [_course_record("AAA 100")]

    results = evaluate_requirement_tree(groups, options, option_courses, course_records, catalog)
    top = results[0]
    assert top.status == RequirementGroupStatus.SATISFIED
    assert top.detail == "satisfied via Path A"
    assert top.children[1].status == RequirementGroupStatus.NOT_STARTED  # Path B untouched


def test_counts_toward_credit_false_excludes_course():
    groups = [_group("leaf", "Leaf", "enumerated_all")]
    options = [_option("opt", "leaf", 0)]
    option_courses = [_option_course("opt", coursedog_group_id="g-a")]
    catalog = {"g-a": "AAA 100"}
    course_records = [_course_record("AAA 100", counts_toward_credit=False)]

    results = evaluate_requirement_tree(groups, options, option_courses, course_records, catalog)
    leaf = results[0]
    assert leaf.status == RequirementGroupStatus.NOT_STARTED
    assert leaf.matched_course_codes == []


def test_manual_review_freeform_group():
    groups = [_group("elective", "Technical Electives", "freeform", requires_manual_definition=True)]
    results = evaluate_requirement_tree(groups, [], [], [], {})
    assert results[0].status == RequirementGroupStatus.MANUAL_REVIEW
    assert results[0].matched_course_codes == []


def test_enumerated_at_least_n_partial_is_in_progress():
    groups = [_group("leadership", "Leadership", "enumerated_at_least_n", n_required=2)]
    options = [_option("opt-1", "leadership", 0), _option("opt-2", "leadership", 1)]
    option_courses = [
        _option_course("opt-1", coursedog_group_id="g-1"),
        _option_course("opt-2", coursedog_group_id="g-2"),
    ]
    catalog = {"g-1": "AAA 100", "g-2": "BBB 100"}
    course_records = [_course_record("AAA 100")]

    results = evaluate_requirement_tree(groups, options, option_courses, course_records, catalog)
    leaf = results[0]
    assert leaf.status == RequirementGroupStatus.IN_PROGRESS
    assert leaf.detail == "1 of 2 required options satisfied (2 available)"


def test_unresolved_course_ref_never_satisfies_an_and_option():
    """Mirrors Engineering Leadership's 2 real unresolved_course_ref rows --
    an option with no course_code can never be matched regardless of
    transcript contents."""
    groups = [_group("leaf", "Leaf", "enumerated_all")]
    options = [_option("opt", "leaf", 0)]
    option_courses = [_option_course("opt", unresolved_course_ref="0220321")]
    results = evaluate_requirement_tree(groups, options, option_courses, [_course_record("ANY 100")], {})
    leaf = results[0]
    assert leaf.status == RequirementGroupStatus.NOT_STARTED
    assert leaf.matched_course_codes == []
