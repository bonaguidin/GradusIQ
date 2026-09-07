from __future__ import annotations

import json
from pathlib import Path

from GradusIQ_career.course_discovery.catalog import LocalCatalogRepository
from GradusIQ_career.course_discovery.models import CatalogInstitution, PrerequisiteClause, StructuredPrerequisite
from GradusIQ_career.course_discovery.prerequisites import structured_prerequisite
from GradusIQ_career.course_discovery.requirement_candidates import (
    AcademicFeasibility,
    CandidateExclusionReason,
    stable_candidate_id,
)
from GradusIQ_career.course_discovery.requirement_satisfaction import evaluate_requirement_tree
from GradusIQ_career.course_discovery.requirement_selection import select_structured_requirements
from GradusIQ_career.course_discovery.scheduler import satisfied_course_codes
from GradusIQ_career.course_discovery.scheduler_scope import scope_schedule_input


FIXTURE = Path(__file__).parent / "fixtures" / "ethan_brooks_requirement_tree.json"


def _ethan_result(*, reverse_input: bool = False):
    fixture = json.loads(FIXTURE.read_text())
    if reverse_input:
        fixture["groups"].reverse()
        fixture["options"].reverse()
        fixture["option_courses"].reverse()
    evaluated = evaluate_requirement_tree(
        fixture["groups"], fixture["options"], fixture["option_courses"],
        fixture["course_records"], fixture["catalog_by_gid"],
    )
    repository = LocalCatalogRepository()
    credits = {}
    prerequisites = {}
    for code in set(fixture["catalog_by_gid"].values()):
        record = repository.get(CatalogInstitution.SMU, code)
        if record is not None:
            credits[code] = float(record.credit_min)
            prerequisites[code] = structured_prerequisite(record)
    base, deferred = scope_schedule_input(
        evaluated, fixture["options"], fixture["option_courses"],
        fixture["catalog_by_gid"], credits,
    )
    return fixture, base, select_structured_requirements(
        evaluated, fixture["groups"], fixture["options"], fixture["option_courses"],
        fixture["catalog_by_gid"], credits, base, deferred, prerequisites,
        satisfied_course_codes(fixture["course_records"]),
        student_id=fixture["student_id"], program_id=fixture["program_id"],
        starting_year=2026, starting_season="Fall", max_terms=6,
    )


def test_ethan_exposes_all_five_candidate_sets_with_stable_order_and_ids():
    _, _, first = _ethan_result()
    _, _, second = _ethan_result()
    assert [item.requirement_name for item in first.candidate_sets] == [
        "Advanced/Domain Specific Use/Design of AI",
        "Experiential Learning (1-3 Credit Hours)",
        "Statistical Methods",
        "Two Courses",
        "Engineering Leadership (6 Credit Hours)",
    ]
    # AI set is (9, 2): CS 5331 is feasible because its OR-clause prereq
    # (CS 4340 or OREM 3340 or STAT 4340) is met within the same plan by
    # whichever course resolves Statistical Methods -- see
    # test_horizon_or_cycle_failure_is_not_misrepresented_as_feasible. The
    # AI/Two Courses/Engineering Leadership counts each moved up from a
    # prior baseline of (5, 6), (11, 5), (1, 7): StructuredPrerequisite.
    # restrictions is informational per its own model contract
    # (models.py:261-269, "not enforced by the scheduler") and no longer
    # excludes a candidate (e.g. CS 5312's "Prerequisites: Junior
    # standing"). CS 5325 (AI, UNSCHEDULABLE) and CS 5328 (AI,
    # DOUBLE_COUNTING_CONFLICT) still correctly exclude for unrelated
    # reasons; the CHEM 1113/1114/1303/1304 candidate (Two Courses) still
    # correctly excludes via PREREQUISITE_NEEDS_REVIEW -- CHEM 1303 mixes a
    # real course code with an unverifiable alternative path ("...or a
    # passing grade on the Chemistry Placement Exam"), which may hide a
    # real unresolved prerequisite (see needs_review's contract,
    # models.py:270-280) and is unaffected by the restrictions fix.
    assert [
        (len(item.feasible_candidates), len(item.excluded_candidates))
        for item in first.candidate_sets
    ] == [(9, 2), (6, 0), (3, 0), (13, 3), (6, 2)]
    assert first.candidate_sets == second.candidate_sets
    first_ids = [
        candidate.candidate_id for group in first.candidate_sets
        for candidate in group.feasible_candidates + group.excluded_candidates
    ]
    assert len(first_ids) == len(set(first_ids))


def test_candidate_identity_and_order_survive_input_iteration_order():
    _, _, normal = _ethan_result()
    _, _, reversed_input = _ethan_result(reverse_input=True)
    assert {
        item.requirement_group_id: item for item in normal.candidate_sets
    } == {
        item.requirement_group_id: item for item in reversed_input.candidate_sets
    }


def test_stable_candidate_id_ignores_semantically_irrelevant_course_iteration_order():
    assert stable_candidate_id("requirement", (2, 4), ("BIOL 1301", "BIOL 1101")) == stable_candidate_id(
        "requirement", (2, 4), ("BIOL 1101", "BIOL 1301")
    )
    assert stable_candidate_id("requirement", (2,), ("A",)) != stable_candidate_id(
        "requirement", (3,), ("A",)
    )


def test_real_multi_course_paths_are_atomic_and_expose_burden_and_completion():
    _, _, result = _ethan_result()
    by_name = {item.requirement_name: item for item in result.candidate_sets}
    biology = next(
        candidate for candidate in by_name["Two Courses"].feasible_candidates
        if set(candidate.course_codes) == {"BIOL 1101", "BIOL 1102", "BIOL 1301", "BIOL 1302"}
    )
    assert biology.additional_course_count == 4
    assert biology.additional_credits == 8
    assert biology.completion_term_index is not None
    assert biology.academic_feasibility == AcademicFeasibility.FEASIBLE

    leadership = next(
        candidate for candidate in by_name["Engineering Leadership (6 Credit Hours)"].feasible_candidates
        if set(candidate.course_codes) == {"CEE 2302", "CS 3377"}
    )
    assert leadership.additional_course_count == 2
    assert leadership.additional_credits == 6


def test_real_exclusions_are_typed_and_unresolved_references_remain_visible():
    _, _, result = _ethan_result()
    by_name = {item.requirement_name: item for item in result.candidate_sets}
    # CS 5312 ("Prerequisites: Junior standing", StructuredPrerequisite.
    # restrictions) is feasible now -- that field is informational per its
    # own model contract (models.py:261-269, "not enforced by the
    # scheduler") and no longer excludes. The still-genuinely-excluded
    # example moves to "Two Courses": CHEM 1303's prerequisite text mixes a
    # real course code (CHEM 1302) with an unverifiable alternative path
    # ("...or a passing grade on the Chemistry Placement Exam"), the exact
    # shape StructuredPrerequisite.needs_review's contract describes
    # (models.py:270-280) -- it may hide a real unresolved course
    # prerequisite, so it correctly stays excluded.
    two_courses = by_name["Two Courses"]
    needs_review = next(
        candidate for candidate in two_courses.excluded_candidates
        if set(candidate.course_codes) == {"CHEM 1113", "CHEM 1114", "CHEM 1303", "CHEM 1304"}
    )
    assert needs_review.exclusion_reasons == [CandidateExclusionReason.PREREQUISITE_NEEDS_REVIEW]
    assert needs_review.completion_term_index is None

    leadership = by_name["Engineering Leadership (6 Credit Hours)"]
    unresolved = [
        candidate for candidate in leadership.excluded_candidates
        if CandidateExclusionReason.UNRESOLVED_COURSE in candidate.exclusion_reasons
    ]
    assert len(unresolved) == 2
    assert all(candidate.course_codes == [] and candidate.additional_credits is None for candidate in unresolved)
    assert all(candidate.unresolved_course_codes for candidate in unresolved)


def test_existing_contribution_and_no_double_counting_are_exposed():
    # The real fixture has no contribution in the five open groups, but every
    # candidate must carry that deterministic fact explicitly.
    _, _, result = _ethan_result()
    assert all(
        candidate.existing_contribution == 0
        for group in result.candidate_sets
        for candidate in group.feasible_candidates + group.excluded_candidates
    )
    ai = next(item for item in result.candidate_sets if item.requirement_name.startswith("Advanced/"))
    used_elsewhere = next(candidate for candidate in ai.excluded_candidates if candidate.course_codes == ["CS 5328"])
    assert CandidateExclusionReason.DOUBLE_COUNTING_CONFLICT in used_elsewhere.exclusion_reasons


def test_completed_course_is_existing_contribution_not_additional_burden():
    groups = [{
        "id": "pick", "coursedog_rule_id": "pick", "parent_group_id": None,
        "name": "Pick two", "group_type": "enumerated_at_least_n", "n_required": 2,
        "credit_hours_required": None, "notes_html": None,
        "requires_manual_definition": False,
    }]
    options = [
        {"id": "o0", "requirement_group_id": "pick", "option_index": 0, "logic": "and"},
        {"id": "o1", "requirement_group_id": "pick", "option_index": 1, "logic": "and"},
    ]
    option_courses = [
        {"requirement_group_option_id": "o0", "coursedog_group_id": "g0", "unresolved_course_ref": None},
        {"requirement_group_option_id": "o1", "coursedog_group_id": "g1", "unresolved_course_ref": None},
    ]
    records = [{
        "course_code": "A", "status": "completed", "counts_toward_credit": True,
        "credit_hours": 3,
    }]
    evaluated = evaluate_requirement_tree(groups, options, option_courses, records, {"g0": "A", "g1": "B"})
    base, deferred = scope_schedule_input(evaluated, options, option_courses, {"g0": "A", "g1": "B"}, {"A": 3, "B": 3})
    result = select_structured_requirements(
        evaluated, groups, options, option_courses, {"g0": "A", "g1": "B"},
        {"A": 3, "B": 3}, base, deferred, {}, {"A"}, student_id="s",
        program_id="p", starting_year=2026, starting_season="Fall", max_terms=2,
    )
    candidate = result.candidate_sets[0].feasible_candidates[0]
    assert candidate.existing_contribution == 1
    assert candidate.course_codes == ["B"]
    assert candidate.additional_course_count == 1
    assert candidate.additional_credits == 3


def test_horizon_or_cycle_failure_is_not_misrepresented_as_feasible():
    # CS 5325's sole prerequisite is CS 5324 -- another course in this same
    # "choose one" AI requirement, so no single combination can contain
    # both. It genuinely cannot join any complete global schedule and must
    # stay UNSCHEDULABLE, not be surfaced as feasible.
    #
    # CS 5331 is the contrast: its OR-clause prerequisite (CS 4340 or
    # OREM 3340 or STAT 4340) is met within the plan by whichever course
    # resolves Statistical Methods, so it IS feasible -- an in-plan
    # alternative to an OR-clause is not an unschedulable blocker.
    _, _, result = _ethan_result()
    ai = next(item for item in result.candidate_sets if item.requirement_name.startswith("Advanced/"))
    unschedulable = {candidate.course_codes[0] for candidate in ai.excluded_candidates if CandidateExclusionReason.UNSCHEDULABLE in candidate.exclusion_reasons}
    assert "CS 5325" in unschedulable
    assert "CS 5331" not in unschedulable
    assert "CS 5331" in {candidate.course_codes[0] for candidate in ai.feasible_candidates}


def test_structured_prerequisite_contract_used_without_a_second_export_schedule():
    # A small guard that the candidate API accepts the same prerequisite
    # evidence type as selection; academic evidence is not a parallel model.
    prerequisite = StructuredPrerequisite(
        requires_all=[PrerequisiteClause(course_codes=["A"])]
    )
    assert prerequisite.requires_all[0].course_codes == ["A"]
