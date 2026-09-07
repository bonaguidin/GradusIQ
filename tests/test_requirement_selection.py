from __future__ import annotations

import json
from pathlib import Path

from GradusIQ_career.course_discovery.catalog import LocalCatalogRepository
from GradusIQ_career.course_discovery.models import PrerequisiteClause, StructuredPrerequisite
from GradusIQ_career.course_discovery.models import CatalogInstitution
from GradusIQ_career.course_discovery.prerequisites import structured_prerequisite
from GradusIQ_career.course_discovery.requirement_candidates import (
    CandidateExclusionReason,
    RequirementDecisionState,
)
from GradusIQ_career.course_discovery.requirement_satisfaction import evaluate_requirement_tree
from GradusIQ_career.course_discovery.requirement_selection import (
    LockedRequirementSelection,
    LockedSelectionFailureCode,
    select_structured_requirements,
    structured_candidate_codes,
)
from GradusIQ_career.course_discovery.scheduler import UnscheduledRequirement, satisfied_course_codes
from GradusIQ_career.course_discovery.scheduler_scope import scope_schedule_input


def group(group_id, group_type, *, parent=None, n=None, credits=None, notes=None):
    return {
        "id": group_id, "coursedog_rule_id": group_id, "parent_group_id": parent,
        "name": group_id, "group_type": group_type, "n_required": n,
        "credit_hours_required": credits, "notes_html": notes,
        "requires_manual_definition": False,
    }


def option(option_id, group_id, index, logic="and"):
    return {"id": option_id, "requirement_group_id": group_id, "option_index": index, "logic": logic}


def course(option_id, gid=None, unresolved=None, code=None):
    return {
        "requirement_group_option_id": option_id,
        "coursedog_group_id": gid,
        "unresolved_course_ref": unresolved,
        "course_code": code,
    }


def run(
    groups, options, option_courses, catalog, credits, *, catalog_by_code=None,
    records=None, prerequisites=None, max_terms=4, career_ranks=None,
    locks=None, excluded=None,
):
    records = records or []
    catalog_by_code = catalog_by_code or {}
    evaluated = evaluate_requirement_tree(
        groups, options, option_courses, records, catalog, catalog_by_code
    )
    deferred = [
        UnscheduledRequirement(
            requirement_group_id=item.id,
            name=item.name,
            reason="SELECTION_DEFERRED",
        )
        for item in evaluated
    ]
    return select_structured_requirements(
        evaluated, groups, options, option_courses, catalog, credits, [], deferred,
        prerequisites or {}, {r["course_code"] for r in records}, student_id="s", program_id="p",
        catalog_by_code=catalog_by_code,
        starting_year=2026, starting_season="Fall", max_terms=max_terms,
        career_rank_by_candidate_id=career_ranks,
        locked_selections=locks or (),
        excluded_group_ids=excluded or (),
    )


def selected(result):
    return [course.course_code for course in result.courses]


def decision(result, requirement_id):
    return next(item for item in result.decisions if item.requirement_group_id == requirement_id)


def lock_for(result, requirement_id, course_codes):
    candidate_set = next(
        item for item in result.candidate_sets
        if item.requirement_group_id == requirement_id
    )
    candidate = next(
        item for item in candidate_set.feasible_candidates
        if item.course_codes == course_codes
    )
    return LockedRequirementSelection(
        requirement_group_id=requirement_id,
        candidate_id=candidate.candidate_id,
        course_codes=tuple(course_codes),
    )


def two_requirement_fixture():
    groups = [
        group("g1", "enumerated_at_least_n", n=1),
        group("g2", "enumerated_at_least_n", n=1),
    ]
    options = [
        option("g1-shared", "g1", 0), option("g1-own", "g1", 1),
        option("g2-shared", "g2", 0), option("g2-own", "g2", 1),
    ]
    rows = [
        course("g1-shared", "shared"), course("g1-own", "a"),
        course("g2-shared", "shared"), course("g2-own", "b"),
    ]
    return groups, options, rows, {"shared": "X", "a": "A", "b": "B"}, {"X": 3, "A": 3, "B": 3}


def test_lock_schedules_selected_path_and_preserves_alternatives():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("oa", "pick", 0), option("ob", "pick", 1)]
    rows = [course("oa", "a"), course("ob", "b")]
    args = groups, options, rows, {"a": "A", "b": "B"}, {"A": 3, "B": 3}
    baseline = run(*args)
    lock = lock_for(baseline, "pick", ["B"])

    result = run(*args, locks=[lock])

    assert selected(result) == ["B"]
    assert result.unscheduled == []
    assert decision(result, "pick").state == RequirementDecisionState.LOCKED
    assert decision(result, "pick").selected_candidate_id == lock.candidate_id
    assert len(result.candidate_sets[0].feasible_candidates) == 2


def test_multi_course_lock_is_atomic():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("bundle", "pick", 0), option("single", "pick", 1)]
    rows = [course("bundle", "a"), course("bundle", "b"), course("single", "c")]
    args = groups, options, rows, {"a": "A", "b": "B", "c": "C"}, {"A": 3, "B": 3, "C": 3}
    baseline = run(*args)
    lock = lock_for(baseline, "pick", ["A", "B"])

    result = run(*args, locks=[lock])

    assert selected(result) == ["A", "B"]
    assert decision(result, "pick").state == RequirementDecisionState.LOCKED


def test_lock_narrows_another_requirement_and_unlock_restores_choice():
    args = two_requirement_fixture()
    baseline = run(*args)
    lock = lock_for(baseline, "g1", ["X"])

    result = run(*args, locks=[lock])

    assert selected(result) == ["X", "B"]
    assert decision(result, "g1").state == RequirementDecisionState.LOCKED
    assert decision(result, "g2").state == RequirementDecisionState.AUTO_SELECTED
    assert decision(baseline, "g2").state == RequirementDecisionState.CHOICE_REQUIRED
    assert len(baseline.candidate_sets[1].feasible_candidates) == 2


def test_career_rank_cannot_override_a_persisted_lock():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("oa", "pick", 0), option("ob", "pick", 1)]
    rows = [course("oa", "a"), course("ob", "b")]
    args = groups, options, rows, {"a": "A", "b": "B"}, {"A": 3, "B": 3}
    baseline = run(*args)
    lock = lock_for(baseline, "pick", ["A"])
    ids = {
        candidate.course_codes[0]: candidate.candidate_id
        for candidate in baseline.candidate_sets[0].feasible_candidates
    }

    result = run(*args, locks=[lock], career_ranks={ids["A"]: 100, ids["B"]: 0})

    assert selected(result) == ["A"]
    assert decision(result, "pick").state == RequirementDecisionState.LOCKED


def test_career_rank_preserves_cee_cs_multi_course_lock_atomically():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("bundle", "pick", 0), option("alternative", "pick", 1)]
    rows = [
        course("bundle", "cee"), course("bundle", "cs"),
        course("alternative", "alt"),
    ]
    args = (
        groups, options, rows,
        {"cee": "CEE 2302", "cs": "CS 3377", "alt": "CS 9999"},
        {"CEE 2302": 3, "CS 3377": 3, "CS 9999": 3},
    )
    baseline = run(*args)
    lock = lock_for(baseline, "pick", ["CEE 2302", "CS 3377"])
    ranks = {
        candidate.candidate_id: (
            100 if candidate.course_codes == ["CEE 2302", "CS 3377"] else 0
        )
        for candidate in baseline.candidate_sets[0].feasible_candidates
    }

    result = run(*args, locks=[lock], career_ranks=ranks)

    assert selected(result) == ["CEE 2302", "CS 3377"]
    assert decision(result, "pick").state == RequirementDecisionState.LOCKED


def test_career_rank_only_chooses_inside_lock_compatible_space():
    args = two_requirement_fixture()
    baseline = run(*args)
    lock = lock_for(baseline, "g1", ["X"])
    ranks = {
        candidate.candidate_id: (0 if candidate.course_codes == ["X"] else 100)
        for candidate_set in baseline.candidate_sets
        for candidate in candidate_set.feasible_candidates
    }

    result = run(*args, locks=[lock], career_ranks=ranks)

    assert selected(result) == ["X", "B"]
    assert decision(result, "g1").state == RequirementDecisionState.LOCKED
    assert decision(result, "g2").state == RequirementDecisionState.AUTO_SELECTED


def test_individually_feasible_locks_can_be_globally_incompatible():
    args = two_requirement_fixture()
    baseline = run(*args)
    locks = [lock_for(baseline, "g1", ["X"]), lock_for(baseline, "g2", ["X"])]

    result = run(*args, locks=locks)

    assert selected(result) == []
    assert result.locked_selection_failure.code == LockedSelectionFailureCode.INCOMPATIBLE


def test_multiple_compatible_locks_are_honored_together():
    args = two_requirement_fixture()
    baseline = run(*args)
    locks = [lock_for(baseline, "g1", ["A"]), lock_for(baseline, "g2", ["B"])]

    result = run(*args, locks=locks)

    assert selected(result) == ["A", "B"]
    assert [item.state for item in result.decisions] == [
        RequirementDecisionState.LOCKED,
        RequirementDecisionState.LOCKED,
    ]


def test_lock_validation_failures_are_typed_and_fail_closed():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("oa", "pick", 0), option("ob", "pick", 1)]
    rows = [course("oa", "a"), course("ob", "b")]
    args = groups, options, rows, {"a": "A", "b": "B"}, {"A": 3, "B": 3}
    baseline = run(*args)
    valid = lock_for(baseline, "pick", ["A"])
    cases = [
        (LockedRequirementSelection(requirement_group_id="missing", candidate_id=valid.candidate_id, course_codes=("A",)), LockedSelectionFailureCode.REQUIREMENT_NOT_FOUND),
        (LockedRequirementSelection(requirement_group_id="pick", candidate_id="missing", course_codes=("A",)), LockedSelectionFailureCode.CANDIDATE_NOT_FOUND),
        (valid.model_copy(update={"course_codes": ("B",)}), LockedSelectionFailureCode.PATH_MISMATCH),
    ]
    for lock, expected in cases:
        result = run(*args, locks=[lock])
        assert selected(result) == []
        assert result.locked_selection_failure.code == expected

    duplicate = run(*args, locks=[valid, valid])
    assert duplicate.locked_selection_failure.code == LockedSelectionFailureCode.DUPLICATE_REQUIREMENT


def test_lock_rejects_excluded_and_no_longer_choice_candidates():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("oa", "pick", 0), option("ob", "pick", 1)]
    rows = [course("oa", "a"), course("ob", "b")]
    # A course-referencing needs_review clause (not .restrictions, which is
    # informational only per its own model contract and no longer excludes
    # a candidate -- see test_needs_review_gate_ignores_course_free_prose_
    # but_still_blocks_course_referencing_clauses) still legitimately
    # excludes: it may hide a real, unmodelled course prerequisite.
    restricted = {"B": StructuredPrerequisite(needs_review=["concurrent enrollment in ZZ 101"])}
    args = groups, options, rows, {"a": "A", "b": "B"}, {"A": 3, "B": 3}
    baseline = run(*args)
    excluded_lock = lock_for(baseline, "pick", ["B"])
    excluded = run(*args, prerequisites=restricted, locks=[excluded_lock])
    assert excluded.locked_selection_failure.code == LockedSelectionFailureCode.CANDIDATE_EXCLUDED

    sole_args = ([group("sole", "enumerated_at_least_n", n=1)], [option("oa", "sole", 0)], [course("oa", "a")], {"a": "A"}, {"A": 3})
    sole = run(*sole_args)
    stale = lock_for(sole, "sole", ["A"])
    no_longer_needed = run(*sole_args, locks=[stale])
    assert no_longer_needed.locked_selection_failure.code == LockedSelectionFailureCode.CHOICE_NO_LONGER_REQUIRED


def test_lock_resolves_against_current_path_after_existing_progress():
    groups = [group("pick", "enumerated_at_least_n", n=2)]
    options = [option("oa", "pick", 0), option("ob", "pick", 1), option("oc", "pick", 2)]
    rows = [course("oa", "a"), course("ob", "b"), course("oc", "c")]
    records = [{"course_code": "A", "status": "completed", "counts_toward_credit": True, "credit_hours": 3}]
    args = groups, options, rows, {"a": "A", "b": "B", "c": "C"}, {"A": 3, "B": 3, "C": 3}
    baseline = run(*args, records=records)
    lock = lock_for(baseline, "pick", ["C"])

    result = run(*args, records=records, locks=[lock])

    assert selected(result) == ["C"]
    assert decision(result, "pick").state == RequirementDecisionState.LOCKED


def test_lock_does_not_bypass_prerequisites_or_horizon():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("bundle", "pick", 0), option("single", "pick", 1)]
    rows = [course("bundle", "a"), course("bundle", "b"), course("single", "c")]
    args = groups, options, rows, {"a": "A", "b": "B", "c": "C"}, {"A": 3, "B": 3, "C": 3}
    baseline = run(*args, max_terms=2)
    lock = lock_for(baseline, "pick", ["A", "B"])
    prerequisites = {
        "B": StructuredPrerequisite(
            requires_all=[PrerequisiteClause(course_codes=["A"])]
        )
    }

    result = run(*args, prerequisites=prerequisites, max_terms=1, locks=[lock])

    assert selected(result) == []
    assert result.locked_selection_failure.code == LockedSelectionFailureCode.CANDIDATE_EXCLUDED


def test_lock_retains_excluded_evidence_and_stable_candidate_ids():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("oa", "pick", 0), option("ob", "pick", 1), option("oc", "pick", 2)]
    rows = [course("oa", "a"), course("ob", "b"), course("oc", "c")]
    restrictions = {"C": StructuredPrerequisite(restrictions=["department approval"])}
    args = groups, options, rows, {"a": "A", "b": "B", "c": "C"}, {"A": 3, "B": 3, "C": 3}
    baseline = run(*args, prerequisites=restrictions)
    lock = lock_for(baseline, "pick", ["A"])

    result = run(*args, prerequisites=restrictions, locks=[lock])

    before = baseline.candidate_sets[0]
    after = result.candidate_sets[0]
    assert [item.candidate_id for item in after.feasible_candidates] == [
        item.candidate_id for item in before.feasible_candidates
    ]
    assert [item.candidate_id for item in after.excluded_candidates] == [
        item.candidate_id for item in before.excluded_candidates
    ]


def test_choose_one_preserves_all_feasible_options_as_student_choice():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option(f"o{i}", "pick", i) for i in range(3)]
    rows = [course(f"o{i}", f"g{i}") for i in range(3)]
    result = run(groups, options, rows, {f"g{i}": f"C {i}" for i in range(3)}, {f"C {i}": 3 for i in range(3)})
    assert selected(result) == []
    assert decision(result, "pick").state == RequirementDecisionState.CHOICE_REQUIRED
    assert decision(result, "pick").selected_candidate_id is None


def test_career_rank_changes_only_an_academically_tied_choice_and_is_stable():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("o0", "pick", 0), option("o1", "pick", 1)]
    rows = [course("o0", "g0"), course("o1", "g1")]
    catalog = {"g0": "A", "g1": "B"}
    credits = {"A": 3, "B": 3}
    baseline = run(groups, options, rows, catalog, credits)
    ids = {item.course_codes[0]: item.candidate_id for item in baseline.candidate_sets[0].feasible_candidates}
    ranks = {ids["A"]: 1, ids["B"]: 0}
    assert selected(run(groups, options, rows, catalog, credits, career_ranks=ranks)) == ["B"]
    assert selected(run(groups, options, rows, catalog, credits, career_ranks=dict(reversed(list(ranks.items()))))) == ["B"]


def test_career_rank_cannot_override_fewer_credits():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("o0", "pick", 0), option("o1", "pick", 1)]
    rows = [course("o0", "g0"), course("o1", "g1")]
    catalog = {"g0": "A", "g1": "B"}
    baseline = run(groups, options, rows, catalog, {"A": 3, "B": 4})
    ids = {item.course_codes[0]: item.candidate_id for item in baseline.candidate_sets[0].feasible_candidates}
    result = run(groups, options, rows, catalog, {"A": 3, "B": 4}, career_ranks={ids["A"]: 1, ids["B"]: 0})
    assert selected(result) == ["A"]


def test_career_rank_remains_global_and_cannot_force_double_counting():
    groups = [
        group("g1", "enumerated_at_least_n", n=1),
        group("g2", "enumerated_at_least_n", n=1),
    ]
    options = [
        option("g1-shared", "g1", 0), option("g1-own", "g1", 1),
        option("g2-shared", "g2", 0), option("g2-own", "g2", 1),
    ]
    rows = [
        course("g1-shared", "shared"), course("g1-own", "a"),
        course("g2-shared", "shared"), course("g2-own", "b"),
    ]
    catalog = {"shared": "X", "a": "A", "b": "B"}
    credits = {"X": 3, "A": 3, "B": 3}
    baseline = run(groups, options, rows, catalog, credits)
    assert selected(baseline) == []
    assert [item.state for item in baseline.decisions] == [
        RequirementDecisionState.CHOICE_REQUIRED,
        RequirementDecisionState.CHOICE_REQUIRED,
    ]
    assert [len(item.feasible_candidates) for item in baseline.candidate_sets] == [2, 2]
    assert baseline.search_stats.candidate_combinations_after_structural_pruning == 3
    ids = {
        (candidate.requirement_group_id, candidate.course_codes[0]): candidate.candidate_id
        for candidate_set in baseline.candidate_sets
        for candidate in candidate_set.feasible_candidates
    }
    ranks = {
        ids[("g1", "X")]: 0, ids[("g1", "A")]: 1,
        ids[("g2", "X")]: 0, ids[("g2", "B")]: 1,
    }
    result = run(groups, options, rows, catalog, credits, career_ranks=ranks)
    assert selected(result) == ["X", "B"]
    assert selected(result).count("X") == 1
    assert result.search_stats.candidate_combinations_before_pruning == 4
    assert result.search_stats.candidate_combinations_after_structural_pruning == 3


def test_choose_n_preserves_distinct_feasible_options_for_student_choice():
    groups = [group("pick", "enumerated_at_least_n", n=2)]
    options = [option(f"o{i}", "pick", i) for i in range(6)]
    rows = [course(f"o{i}", f"g{i}") for i in range(6)]
    result = run(groups, options, rows, {f"g{i}": f"C {i}" for i in range(6)}, {f"C {i}": 3 for i in range(6)})
    assert selected(result) == []
    assert decision(result, "pick").state == RequirementDecisionState.CHOICE_REQUIRED


def test_or_identity_requires_choice_instead_of_selecting_source_order():
    groups = [group("or", "enumerated_all")]
    options = [option("o", "or", 0, "or")]
    rows = [course("o", "ga"), course("o", "gb"), course("o", "gc")]
    result = run(groups, options, rows, {"ga": "A", "gb": "B", "gc": "C"}, {"A": 3, "B": 3, "C": 3})
    assert selected(result) == []
    assert decision(result, "or").state == RequirementDecisionState.CHOICE_REQUIRED


def test_compound_any_preserves_feasible_branches_for_student_choice():
    groups = [group("parent", "compound_any"), group("a", "enumerated_all", parent="parent"), group("b", "enumerated_all", parent="parent")]
    options = [option("oa", "a", 0), option("ob", "b", 0)]
    rows = [course("oa", "ga"), course("ob", "gb")]
    result = run(groups, options, rows, {"ga": "A", "gb": "B"}, {"A": 3, "B": 3})
    assert selected(result) == []
    assert decision(result, "parent").state == RequirementDecisionState.CHOICE_REQUIRED


def test_credit_threshold_preserves_multiple_sufficient_paths_for_student_choice():
    groups = [group("credits", "enumerated_credit_threshold", credits=7)]
    options = [option("o0", "credits", 0), option("o1", "credits", 1), option("o2", "credits", 2)]
    rows = [course("o0", "g0"), course("o1", "g1"), course("o2", "g2")]
    result = run(groups, options, rows, {"g0": "A", "g1": "B", "g2": "C"}, {"A": 4, "B": 4, "C": 3})
    assert selected(result) == []
    assert decision(result, "credits").state == RequirementDecisionState.CHOICE_REQUIRED


def test_existing_progress_reduces_burden_but_preserves_remaining_choice():
    groups = [group("pick", "enumerated_at_least_n", n=2)]
    options = [option("o0", "pick", 0), option("o1", "pick", 1), option("o2", "pick", 2)]
    rows = [course("o0", "g0"), course("o1", "g1"), course("o2", "g2")]
    records = [{"course_code": "A", "status": "in_progress", "counts_toward_credit": True, "credit_hours": 3}]
    result = run(groups, options, rows, {"g0": "A", "g1": "B", "g2": "C"}, {"A": 3, "B": 3, "C": 3}, records=records)
    assert selected(result) == []
    assert decision(result, "pick").state == RequirementDecisionState.CHOICE_REQUIRED


def test_existing_progress_does_not_override_student_compound_branch_choice():
    groups = [
        group("parent", "compound_any"),
        group("partial", "enumerated_all", parent="parent"),
        group("empty", "enumerated_all", parent="parent"),
    ]
    options = [option("oa0", "partial", 0), option("oa1", "partial", 1), option("ob", "empty", 0)]
    rows = [course("oa0", "ga0"), course("oa1", "ga1"), course("ob", "gb")]
    records = [{"course_code": "A0", "status": "completed", "counts_toward_credit": True, "credit_hours": 3}]
    result = run(
        groups, options, rows, {"ga0": "A0", "ga1": "A1", "gb": "B"},
        {"A0": 3, "A1": 3, "B": 3}, records=records,
    )
    assert selected(result) == []
    assert decision(result, "parent").state == RequirementDecisionState.CHOICE_REQUIRED


def test_infeasible_candidate_loses_to_feasible_alternative():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("o0", "pick", 0), option("o1", "pick", 1)]
    rows = [course("o0", "g0"), course("o0", "gc"), course("o1", "g1")]
    prerequisites = {
        "A": StructuredPrerequisite(requires_all=[PrerequisiteClause(course_codes=["C"])]),
        "C": StructuredPrerequisite(requires_all=[PrerequisiteClause(course_codes=["A"])]),
        "B": StructuredPrerequisite(),
    }
    result = run(
        groups, options, rows, {"g0": "A", "gc": "C", "g1": "B"},
        {"A": 3, "B": 3, "C": 3}, prerequisites=prerequisites,
    )
    assert selected(result) == ["B"]


def test_unresolved_alternative_is_excluded_and_surfaced():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("o0", "pick", 0), option("o1", "pick", 1)]
    rows = [course("o0", unresolved="missing"), course("o1", "g1")]
    result = run(groups, options, rows, {"g1": "B"}, {"B": 3})
    assert selected(result) == ["B"]
    assert "unresolved course alternatives" in result.courses[0].selection_limitations[0]


def test_manual_selection_semantics_remain_deferred():
    groups = [group("pick", "enumerated_at_least_n", n=1, notes="Courses selected in consultation with the adviser.")]
    options = [option("o0", "pick", 0)]
    result = run(groups, options, [course("o0", "g0")], {"g0": "A"}, {"A": 3})
    assert selected(result) == []
    assert [u.requirement_group_id for u in result.unscheduled] == ["pick"]


def test_ethan_real_tree_resolves_five_structured_groups_globally():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "ethan_brooks_requirement_tree.json").read_text())
    evaluated = evaluate_requirement_tree(
        fixture["groups"], fixture["options"], fixture["option_courses"], fixture["course_records"],
        fixture["catalog_by_gid"],
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
        evaluated, fixture["options"], fixture["option_courses"], fixture["catalog_by_gid"], credits,
    )
    result = select_structured_requirements(
        evaluated, fixture["groups"], fixture["options"], fixture["option_courses"],
        fixture["catalog_by_gid"], credits, base, deferred, prerequisites,
        satisfied_course_codes(fixture["course_records"]), student_id=fixture["student_id"],
        program_id=fixture["program_id"], starting_year=2026, starting_season="Fall", max_terms=6,
    )

    base_codes = {course.course_code for course in base}
    # Engineering Leadership no longer AUTO_SELECTS a sole feasible
    # candidate: CS 5312's "Prerequisites: Junior standing" (and the other
    # candidates' similar non-course prerequisite text) is
    # StructuredPrerequisite.restrictions, informational by its own model
    # contract (models.py:261-269, "not enforced by the scheduler"). With
    # that no longer excluding, 6 candidates are genuinely feasible and the
    # group is a real CHOICE_REQUIRED -- nothing beyond the base no-choice
    # courses is auto-scheduled here.
    assert {course.course_code for course in result.courses} - base_codes == set()
    decisions = {item.requirement_name: item for item in result.decisions}
    candidate_sets = {item.requirement_name: item for item in result.candidate_sets}
    assert decisions["Engineering Leadership (6 Credit Hours)"].state == RequirementDecisionState.CHOICE_REQUIRED
    assert decisions["Engineering Leadership (6 Credit Hours)"].selected_candidate_id is None
    assert decisions["Statistical Methods"].state == RequirementDecisionState.CHOICE_REQUIRED
    assert decisions["Two Courses"].state == RequirementDecisionState.CHOICE_REQUIRED
    assert (
        len(candidate_sets["Engineering Leadership (6 Credit Hours)"].feasible_candidates),
        len(candidate_sets["Engineering Leadership (6 Credit Hours)"].excluded_candidates),
    ) == (6, 2)
    assert (
        len(candidate_sets["Statistical Methods"].feasible_candidates),
        len(candidate_sets["Statistical Methods"].excluded_candidates),
    ) == (3, 0)
    # 13 feasible / 3 excluded, not 11/5: candidates that carried only an
    # informational restriction (e.g. a campus note) are no longer
    # wrongly excluded. The CHEM 1113/1114/1303/1304 candidate is still
    # excluded -- CHEM 1303's "...or a passing grade on the Chemistry
    # Placement Exam" mixes a real course code (CHEM 1302) with an
    # unverifiable alternative path, exactly the shape
    # StructuredPrerequisite.needs_review's contract describes
    # (models.py:270-280), so it may still hide a real, unresolved course
    # prerequisite and correctly stays excluded under the narrowed gate.
    assert (
        len(candidate_sets["Two Courses"].feasible_candidates),
        len(candidate_sets["Two Courses"].excluded_candidates),
    ) == (13, 3)
    # Engineering Leadership now joins unscheduled too -- see above.
    assert {entry.name for entry in result.unscheduled} == {
        "Advanced/Domain Specific Use/Design of AI", "Experiential Learning (1-3 Credit Hours)",
        "Statistical Methods", "Two Courses", "Engineering Leadership (6 Credit Hours)",
        "Technical Electives (9 Credit Hours)", "Advanced Major Electives (3-5 Credit Hours)",
    }
    # More genuinely-feasible candidates (Engineering Leadership 1->6, Two
    # Courses 11->13) multiply the combinatorial search space.
    assert result.search_stats.candidate_combinations_before_pruning == 19008
    assert result.search_stats.candidate_combinations_after_structural_pruning == 15390
    assert result.search_stats.candidate_combinations_evaluated == 15390


# ---------------------------------------------------------------------------
# course_code path (TAMU, or any future non-Coursedog school) --
# supabase/migrations/20260823140000_requirement_group_option_courses_
# course_code.sql.
# ---------------------------------------------------------------------------


def test_structured_candidate_codes_course_code_path():
    raw_groups = [group("g1", "enumerated_all")]
    evaluated = evaluate_requirement_tree(
        raw_groups, [option("o1", "g1", 0)], [course("o1", code="CHEM 107")], [], {}, {"CHEM 107": ["CHEM 107"]}
    )
    codes = structured_candidate_codes(
        evaluated, raw_groups, [option("o1", "g1", 0)], [course("o1", code="CHEM 107")], {},
        {"CHEM 107": ["CHEM 107"]},
    )
    assert codes == {"CHEM 107"}


def test_structured_candidate_codes_cross_listing_includes_both_halves():
    """Unlike scheduler_scope.py's per-requirement list, this function
    returns a flat candidate set -- both halves of a cross-listing belong
    in it (no double-counting risk here, see module docstring note)."""
    raw_groups = [group("g1", "enumerated_all")]
    option_courses = [course("o1", code="ENGR 216/PHYS 216")]
    catalog_by_code = {"ENGR 216/PHYS 216": ["ENGR 216", "PHYS 216"]}
    evaluated = evaluate_requirement_tree(
        raw_groups, [option("o1", "g1", 0)], option_courses, [], {}, catalog_by_code
    )
    codes = structured_candidate_codes(
        evaluated, raw_groups, [option("o1", "g1", 0)], option_courses, {}, catalog_by_code
    )
    assert codes == {"ENGR 216", "PHYS 216"}


def test_structured_candidate_codes_coursedog_group_id_path_unaffected():
    """Explicit proof the new optional catalog_by_code param doesn't
    change SMU's existing coursedog_group_id resolution."""
    raw_groups = [group("g1", "enumerated_all")]
    option_courses = [course("o1", gid="g-a")]
    catalog_by_gid = {"g-a": "AAA 100"}
    evaluated = evaluate_requirement_tree(raw_groups, [option("o1", "g1", 0)], option_courses, [], catalog_by_gid)

    without_param = structured_candidate_codes(
        evaluated, raw_groups, [option("o1", "g1", 0)], option_courses, catalog_by_gid
    )
    with_unrelated_param = structured_candidate_codes(
        evaluated, raw_groups, [option("o1", "g1", 0)], option_courses, catalog_by_gid,
        {"SOME OTHER CODE": ["SOME OTHER CODE"]},
    )
    assert without_param == with_unrelated_param == {"AAA 100"}


def test_structured_candidate_codes_walks_full_tree_depth_not_just_two_levels():
    """Regression: TAMU Computer Engineering nests its course-bearing leaves
    three deep -- compound_all year -> compound_all season -> enumerated_*
    leaf -- and every course row lives on the leaf. A traversal that stopped
    at roots + direct children collected nothing for such a program, so the
    caller's catalog-enrichment lookup never loaded those codes and their
    candidate_courses rendered with no title and no credits. The walk must
    reach every non-satisfied group at any depth, matching
    select_structured_requirements' own fully-recursive group index.
    """
    raw_groups = [
        group("Second Year", "compound_all"),
        group("Second Year — Spring", "compound_all", parent="Second Year"),
        group("Second Year — Spring — Required Courses", "enumerated_all",
              parent="Second Year — Spring"),
        group("Second Year — Spring — Select one of the following",
              "enumerated_at_least_n", n=1, parent="Second Year — Spring"),
    ]
    required_id = "Second Year — Spring — Required Courses"
    choose_id = "Second Year — Spring — Select one of the following"
    options = [
        option("o-csce-221", required_id, 0),
        option("o-ecen-303", required_id, 1, "or"),
        option("o-math-308", required_id, 2),
        option("o-engl-210", choose_id, 0),
        option("o-comm-205", choose_id, 1),
    ]
    option_courses = [
        course("o-csce-221", code="CSCE 221"),
        course("o-ecen-303", code="ECEN 303"),
        course("o-ecen-303", code="STAT 211"),
        course("o-math-308", code="MATH 308"),
        course("o-engl-210", code="ENGL 210"),
        course("o-comm-205", code="COMM 205"),
    ]
    catalog_by_code = {
        "CSCE 221": ["CSCE 221"], "ECEN 303": ["ECEN 303"], "STAT 211": ["STAT 211"],
        "MATH 308": ["MATH 308"], "ENGL 210": ["ENGL 210"], "COMM 205": ["COMM 205"],
    }
    evaluated = evaluate_requirement_tree(
        raw_groups, options, option_courses, [], {}, catalog_by_code
    )
    # The leaves really are at depth 2 (roots -> season -> leaf).
    assert [g.id for g in evaluated] == ["Second Year"]
    assert [g.id for g in evaluated[0].children] == ["Second Year — Spring"]
    assert {g.id for g in evaluated[0].children[0].children} == {required_id, choose_id}

    codes = structured_candidate_codes(
        evaluated, raw_groups, options, option_courses, {}, catalog_by_code
    )
    assert codes == {
        "CSCE 221", "ECEN 303", "STAT 211", "MATH 308", "ENGL 210", "COMM 205",
    }


def test_tamu_mixed_fixed_and_or_requirement_preserves_complete_candidate_paths():
    groups = [group("First Year — Fall — Required Courses", "enumerated_all")]
    options = [
        option("chem-107", groups[0]["id"], 0),
        option("chem-117", groups[0]["id"], 1),
        option("engl", groups[0]["id"], 2, "or"),
        option("engr-102", groups[0]["id"], 3),
        option("math-151", groups[0]["id"], 4),
    ]
    rows = [
        course("chem-107", code="CHEM 107"),
        course("chem-117", code="CHEM 117"),
        course("engl", code="ENGL 103"),
        course("engl", code="ENGL 104"),
        course("engr-102", code="ENGR 102"),
        course("math-151", code="MATH 151"),
    ]
    codes = {row["course_code"] for row in rows}
    catalog_by_code = {code: [code] for code in codes}
    result = run(
        groups, options, rows, {}, {code: 3 for code in codes},
        catalog_by_code=catalog_by_code,
    )

    candidates = result.candidate_sets[0]
    assert len(candidates.feasible_candidates) == 2
    assert candidates.excluded_candidates == []
    assert {tuple(candidate.course_codes) for candidate in candidates.feasible_candidates} == {
        ("CHEM 107", "CHEM 117", "ENGL 103", "ENGR 102", "MATH 151"),
        ("CHEM 107", "CHEM 117", "ENGL 104", "ENGR 102", "MATH 151"),
    }
    assert selected(result) == []
    assert decision(result, groups[0]["id"]).state == RequirementDecisionState.CHOICE_REQUIRED


def test_tamu_mixed_requirement_keeps_cross_listing_atomic_and_applies_prerequisites():
    groups = [group("Second Year — Fall — Required Courses", "enumerated_all")]
    group_id = groups[0]["id"]
    options = [
        option("csce", group_id, 0), option("ecen", group_id, 1),
        option("math", group_id, 2, "or"), option("phys", group_id, 3),
        option("lab", group_id, 4),
    ]
    rows = [
        course("csce", code="CSCE 120"), course("ecen", code="ECEN 248"),
        course("math", code="MATH 251"), course("math", code="MATH 253"),
        course("phys", code="PHYS 207"),
        course("lab", code="PHYS 217/ENGR 217"),
    ]
    catalog_by_code = {
        "CSCE 120": ["CSCE 120"], "ECEN 248": ["ECEN 248"],
        "MATH 251": ["MATH 251"], "MATH 253": ["MATH 253"],
        "PHYS 207": ["PHYS 207"],
        "PHYS 217/ENGR 217": ["PHYS 217", "ENGR 217"],
    }
    credits = {code: 3 for values in catalog_by_code.values() for code in values}
    prerequisites = {
        "ECEN 248": StructuredPrerequisite(
            requires_all=[PrerequisiteClause(course_codes=["CSCE 120"])]
        )
    }
    result = run(
        groups, options, rows, {}, credits, catalog_by_code=catalog_by_code,
        prerequisites=prerequisites,
    )

    candidates = result.candidate_sets[0]
    assert len(candidates.feasible_candidates) == 2
    assert candidates.excluded_candidates == []
    for candidate in candidates.feasible_candidates:
        assert {"CSCE 120", "ECEN 248", "PHYS 207", "ENGR 217"} <= set(candidate.course_codes)
        assert len({"PHYS 217", "ENGR 217"} & set(candidate.course_codes)) == 1
    assert {candidate.course_codes[-2] for candidate in candidates.feasible_candidates} == {"MATH 251", "MATH 253"}


def test_cross_listing_collapses_to_the_alias_on_the_student_transcript():
    """The student took the "PHYS 217/ENGR 217" cross-listed course under
    PHYS 217. The other option in the group is still open, so the group is
    deferred -- but the cross-listed slot must be recognised as done via
    the PHYS 217 alias, not re-proposed under ENGR 217 (the alias the
    lexical tie-break would otherwise pick). Candidates should cover only
    the genuinely-remaining option."""
    groups = [group("Second Year — Fall — Required Courses", "enumerated_all")]
    group_id = groups[0]["id"]
    options = [option("lab", group_id, 0), option("stat", group_id, 1, "or")]
    rows = [
        course("lab", code="PHYS 217/ENGR 217"),
        course("stat", code="ECEN 303"),
        course("stat", code="STAT 211"),
    ]
    catalog_by_code = {
        "PHYS 217/ENGR 217": ["PHYS 217", "ENGR 217"],
        "ECEN 303": ["ECEN 303"],
        "STAT 211": ["STAT 211"],
    }
    credits = {code: 3 for values in catalog_by_code.values() for code in values}
    records = [{"course_code": "PHYS 217", "status": "completed", "counts_toward_credit": True, "credit_hours": 3}]
    result = run(groups, options, rows, {}, credits, catalog_by_code=catalog_by_code, records=records)

    candidates = result.candidate_sets[0]
    every_code = {
        code
        for bucket in (candidates.feasible_candidates, candidates.excluded_candidates)
        for candidate in bucket
        for code in candidate.course_codes
    }
    assert "ENGR 217" not in every_code
    assert "PHYS 217" not in every_code  # already done, never re-proposed
    assert {tuple(c.course_codes) for c in candidates.feasible_candidates} == {("ECEN 303",), ("STAT 211",)}
    assert decision(result, group_id).state == RequirementDecisionState.CHOICE_REQUIRED


def test_direct_course_code_or_produces_both_feasible_candidates():
    groups = [group("pick", "enumerated_all")]
    options = [option("direct-or", "pick", 0, "or")]
    rows = [course("direct-or", code="A"), course("direct-or", code="B")]
    result = run(
        groups, options, rows, {}, {"A": 3, "B": 3},
        catalog_by_code={"A": ["A"], "B": ["B"]},
    )

    assert [candidate.course_codes for candidate in result.candidate_sets[0].feasible_candidates] == [["A"], ["B"]]
    assert selected(result) == []
    assert decision(result, "pick").state == RequirementDecisionState.CHOICE_REQUIRED


def test_tamu_sole_feasible_direct_code_is_auto_selected():
    groups = [group("pick", "enumerated_all")]
    options = [option("direct-or", "pick", 0, "or")]
    rows = [course("direct-or", code="A"), course("direct-or", code="B")]
    # B's exclusion must come from a course-referencing needs_review clause,
    # not .restrictions -- restrictions is informational per its own model
    # contract (models.py:261-269, "not enforced by the scheduler") and no
    # longer excludes a candidate on its own (a bare "Majors only." on B
    # would leave both A and B feasible, i.e. CHOICE_REQUIRED -- see
    # test_direct_course_code_or_produces_both_feasible_candidates).
    result = run(
        groups, options, rows, {}, {"A": 3, "B": 3},
        catalog_by_code={"A": ["A"], "B": ["B"]},
        prerequisites={"B": StructuredPrerequisite(needs_review=["consult the department re: ZZ 202 equivalency"])},
    )

    requirement_decision = decision(result, "pick")
    assert requirement_decision.state == RequirementDecisionState.AUTO_SELECTED
    assert requirement_decision.selected_candidate_id is not None
    assert selected(result) == ["A"]
    assert len(result.candidate_sets[0].feasible_candidates) == 1
    assert len(result.candidate_sets[0].excluded_candidates) == 1


def test_unresolved_direct_course_code_fails_closed_with_typed_exclusion():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option("missing", "pick", 0)]
    result = run(
        groups, options, [course("missing", code="MISSING 999")], {}, {},
        catalog_by_code={"MISSING 999": []},
    )

    candidates = result.candidate_sets[0]
    assert candidates.feasible_candidates == []
    assert len(candidates.excluded_candidates) == 1
    assert candidates.excluded_candidates[0].course_codes == []
    assert candidates.excluded_candidates[0].unresolved_course_codes == ["MISSING 999"]
    assert [reason.value for reason in candidates.excluded_candidates[0].exclusion_reasons] == [
        "UNRESOLVED_COURSE"
    ]
    assert selected(result) == []
    assert [item.requirement_group_id for item in result.unscheduled] == ["pick"]
    assert decision(result, "pick").state == RequirementDecisionState.DATA_UNRESOLVED


def test_zero_feasible_needs_review_evidence_requires_adviser_review():
    """Renamed from ...restriction_evidence...: .restrictions no longer
    excludes a candidate (informational per its own model contract), so
    zero-feasible-by-restriction is no longer a reachable state. The
    equivalent needs_review shape (both candidates carry an unresolved,
    course-referencing clause) still is."""
    groups = [group("pick", "enumerated_all")]
    options = [option("direct-or", "pick", 0, "or")]
    rows = [course("direct-or", code="A"), course("direct-or", code="B")]
    result = run(
        groups, options, rows, {}, {"A": 3, "B": 3},
        catalog_by_code={"A": ["A"], "B": ["B"]},
        prerequisites={
            "A": StructuredPrerequisite(needs_review=["consult the department re: ZZ 101 equivalency"]),
            "B": StructuredPrerequisite(needs_review=["consult the department re: ZZ 202 equivalency"]),
        },
    )

    assert selected(result) == []
    assert decision(result, "pick").state == RequirementDecisionState.ADVISER_REVIEW


def test_campus_note_or_classification_restriction_does_not_exclude_a_candidate():
    """Regression for the RESELECTION_REQUIRED false-positive a3c4746
    exposed: StructuredPrerequisite.restrictions is informational by its
    own model contract (models.py:261-269 -- "classification, ... campus
    notes, and similar ... not enforced by the scheduler"), so a candidate
    must not be excluded purely for carrying one. Covers the two live
    shapes this session found (a bare campus note on one course; a
    classification note alongside a real, satisfied prerequisite on
    another), not just the four TAMU/SMU courses that originally
    surfaced it."""
    groups = [group("pick", "enumerated_all")]
    options = [option("direct-or", "pick", 0, "or")]
    rows = [course("direct-or", code="A"), course("direct-or", code="B")]
    result = run(
        groups, options, rows, {}, {"A": 3, "B": 3},
        catalog_by_code={"A": ["A"], "B": ["B"]},
        prerequisites={
            "A": StructuredPrerequisite(restrictions=["also taught at Galveston and Qatar campuses"]),
            "B": StructuredPrerequisite(
                requires_all=[PrerequisiteClause(course_codes=["C"], grade_min="C")],
                restrictions=["Freshman or sophomore classification"],
            ),
        },
        records=[{"course_code": "C", "status": "completed", "counts_toward_credit": True, "credit_hours": 3}],
    )

    assert set(selected(result)) == set()
    assert decision(result, "pick").state == RequirementDecisionState.CHOICE_REQUIRED
    assert len(result.candidate_sets[0].feasible_candidates) == 2
    assert result.candidate_sets[0].excluded_candidates == []


def test_course_free_needs_review_prose_does_not_exclude_a_candidate():
    """The interim _NEEDS_REVIEW_COURSE_REF heuristic (requirement_
    selection.py) must not exclude a candidate for needs_review text that
    names no course -- e.g. TAMU MATH 308's "knowledge of computer
    algebra system", a competency note the parser currently files under
    needs_review only because it has no rule recognizing it as non-course
    (a gap logged as a follow-up: it belongs in .restrictions, like
    "also taught at ... campuses" already does). Such text cannot hide an
    unmodelled course dependency, so it must not gate."""
    groups = [group("pick", "enumerated_all")]
    options = [option("direct-or", "pick", 0, "or")]
    rows = [course("direct-or", code="A"), course("direct-or", code="B")]
    result = run(
        groups, options, rows, {}, {"A": 3, "B": 3},
        catalog_by_code={"A": ["A"], "B": ["B"]},
        prerequisites={"B": StructuredPrerequisite(needs_review=["knowledge of computer algebra system"])},
    )

    assert decision(result, "pick").state == RequirementDecisionState.CHOICE_REQUIRED
    assert len(result.candidate_sets[0].feasible_candidates) == 2
    assert result.candidate_sets[0].excluded_candidates == []


def test_course_referencing_needs_review_prose_still_excludes_a_candidate():
    """Contrast case for the test above: needs_review text that DOES name
    a course (e.g. real SMU CHEM 1303's "...or a passing grade on the
    Chemistry Placement Exam", which mixes CHEM 1302 with an unverifiable
    alternative path) may hide a real, unmodelled course prerequisite --
    StructuredPrerequisite.needs_review's own contract (models.py:270-280)
    is exactly this case, unlike .restrictions. It must keep excluding."""
    groups = [group("pick", "enumerated_all")]
    options = [option("direct-or", "pick", 0, "or")]
    rows = [course("direct-or", code="A"), course("direct-or", code="B")]
    result = run(
        groups, options, rows, {}, {"A": 3, "B": 3},
        catalog_by_code={"A": ["A"], "B": ["B"]},
        prerequisites={
            "B": StructuredPrerequisite(needs_review=["C- or better in ZZ 101, or a passing grade on the placement exam"]),
        },
    )

    decision_ = decision(result, "pick")
    assert decision_.state == RequirementDecisionState.AUTO_SELECTED
    assert selected(result) == ["A"]
    assert len(result.candidate_sets[0].feasible_candidates) == 1
    excluded = result.candidate_sets[0].excluded_candidates
    assert len(excluded) == 1
    assert excluded[0].exclusion_reasons == [CandidateExclusionReason.PREREQUISITE_NEEDS_REVIEW]


def test_or_clause_prereq_satisfied_within_the_same_combination_is_not_unschedulable():
    """Regression for the TAMU ECEN 314 collapse: a course with an
    "X or Y" prerequisite (here C -> "A or B") used to emit a blocking
    "prerequisite (A or B) not modeled..." limitation on every candidate
    combination, even when an alternative (B) was itself scheduled by
    another requirement in the same combination. select_structured_
    requirements treated that advisory as a hard scheduling failure, so
    every combination was rejected and every structured group collapsed
    to ADVISER_REVIEW. With the OR-clause in-scope check, B being present
    in the combination clears the advisory and both groups resolve."""
    groups = [
        group("needs-or-prereq", "enumerated_all"),
        group("supplies-B", "enumerated_all"),
    ]
    options = [
        option("opt-c", "needs-or-prereq", 0),
        option("opt-b", "supplies-B", 0),
    ]
    rows = [course("opt-c", code="C"), course("opt-b", code="B")]
    prerequisites = {
        "C": StructuredPrerequisite(requires_all=[PrerequisiteClause(course_codes=["A", "B"])]),
    }
    result = run(
        groups, options, rows, {}, {"C": 3, "B": 3},
        catalog_by_code={"C": ["C"], "B": ["B"]},
        prerequisites=prerequisites,
    )

    assert decision(result, "needs-or-prereq").state == RequirementDecisionState.AUTO_SELECTED
    assert decision(result, "supplies-B").state == RequirementDecisionState.AUTO_SELECTED
    assert sorted(selected(result)) == ["B", "C"]


def test_or_clause_prereq_with_no_alternative_anywhere_still_blocks():
    """Negative control for the fix above: when NEITHER alternative of an
    "X or Y" prerequisite is satisfied or present anywhere in the plan,
    the advisory is still emitted and the candidate is still correctly
    unschedulable -- the fix only suppresses the advisory when an
    alternative is genuinely in the scheduled set."""
    groups = [group("needs-or-prereq", "enumerated_all")]
    options = [option("opt-c", "needs-or-prereq", 0)]
    rows = [course("opt-c", code="C")]
    prerequisites = {
        "C": StructuredPrerequisite(requires_all=[PrerequisiteClause(course_codes=["A", "B"])]),
    }
    result = run(
        groups, options, rows, {}, {"C": 3},
        catalog_by_code={"C": ["C"]},
        prerequisites=prerequisites,
    )

    assert selected(result) == []
    assert decision(result, "needs-or-prereq").state == RequirementDecisionState.ADVISER_REVIEW


# ---------------------------------------------------------------------------
# Student-excluded (set-aside) single-mandatory requirements --
# supabase/migrations/20260903120000_degree_requirement_exclusions.sql
# ---------------------------------------------------------------------------


def _solo_mandatory_fixture():
    """One genuinely no-choice enumerated_all group: exactly one option, one
    course, logic 'and'. Without exclusion this is the textbook
    sole-feasible -> AUTO_SELECTED case."""
    groups = [group("solo", "enumerated_all")]
    options = [option("solo-opt", "solo", 0)]
    rows = [course("solo-opt", code="SOLO 101")]
    return groups, options, rows, {}, {"SOLO 101": 3}, {"SOLO 101": ["SOLO 101"]}


def test_excluded_single_mandatory_group_resolves_to_excluded_not_auto_selected():
    """The AUTO_SELECTED trap regression. A single-mandatory group with
    exactly one feasible candidate, once excluded, must resolve to EXCLUDED
    with the candidate held off the feasible-count -- it must never silently
    re-derive AUTO_SELECTED, on this reconstruction or any repeat of it."""
    groups, options, rows, catalog, credits, by_code = _solo_mandatory_fixture()

    baseline = run(groups, options, rows, catalog, credits, catalog_by_code=by_code)
    assert decision(baseline, "solo").state == RequirementDecisionState.AUTO_SELECTED
    assert selected(baseline) == ["SOLO 101"]
    auto_candidate_id = decision(baseline, "solo").selected_candidate_id
    assert auto_candidate_id is not None

    result = run(
        groups, options, rows, catalog, credits,
        catalog_by_code=by_code, excluded=["solo"],
    )
    solo = decision(result, "solo")
    assert solo.state == RequirementDecisionState.EXCLUDED
    # Held off the feasible-count -- this is what stops the AUTO_SELECTED
    # re-derivation.
    assert solo.feasible_candidate_ids == []
    assert solo.selected_candidate_id is None
    # Underlying candidate preserved for the one-click restore.
    assert auto_candidate_id in solo.excluded_candidate_ids
    # Not scheduled, still surfaced for review.
    assert "SOLO 101" not in selected(result)
    assert "solo" in {item.requirement_group_id for item in result.unscheduled}

    # Idempotent across repeated reconstructions -- still EXCLUDED, never
    # flips back to AUTO_SELECTED.
    again = run(
        groups, options, rows, catalog, credits,
        catalog_by_code=by_code, excluded=["solo"],
    )
    assert decision(again, "solo").state == RequirementDecisionState.EXCLUDED
    assert "SOLO 101" not in selected(again)


def test_excluded_group_is_not_scheduled_even_on_the_career_ranked_path():
    """Career Optimization schedules the full winning combination, so the
    exclusion has to be enforced there too -- an excluded group's course must
    not appear in the ranked schedule, and the group must still surface as
    unscheduled."""
    groups, options, rows, catalog, credits, by_code = _solo_mandatory_fixture()
    result = run(
        groups, options, rows, catalog, credits,
        catalog_by_code=by_code, excluded=["solo"], career_ranks={},
    )
    assert decision(result, "solo").state == RequirementDecisionState.EXCLUDED
    assert "SOLO 101" not in selected(result)
    assert "solo" in {item.requirement_group_id for item in result.unscheduled}


def test_excluding_one_group_does_not_touch_a_sibling_choice_required_group():
    """The forced-EXCLUDED branch runs before the feasible-count branching
    and must only affect the named group -- a multi-candidate sibling keeps
    its CHOICE_REQUIRED state and all its feasible candidates untouched."""
    groups = [
        group("solo", "enumerated_all"),
        group("pick", "enumerated_at_least_n", n=1),
    ]
    options = [
        option("solo-opt", "solo", 0),
        option("pick-a", "pick", 0), option("pick-b", "pick", 1),
    ]
    rows = [
        course("solo-opt", code="SOLO 101"),
        course("pick-a", code="PICK 1"), course("pick-b", code="PICK 2"),
    ]
    by_code = {"SOLO 101": ["SOLO 101"], "PICK 1": ["PICK 1"], "PICK 2": ["PICK 2"]}
    credits = {"SOLO 101": 3, "PICK 1": 3, "PICK 2": 3}

    baseline = run(groups, options, rows, {}, credits, catalog_by_code=by_code)
    assert decision(baseline, "pick").state == RequirementDecisionState.CHOICE_REQUIRED

    result = run(groups, options, rows, {}, credits, catalog_by_code=by_code, excluded=["solo"])
    assert decision(result, "solo").state == RequirementDecisionState.EXCLUDED
    pick = decision(result, "pick")
    assert pick.state == RequirementDecisionState.CHOICE_REQUIRED
    assert len(pick.feasible_candidate_ids) == 2
    pick_set = next(s for s in result.candidate_sets if s.requirement_group_id == "pick")
    assert len(pick_set.feasible_candidates) == 2


def test_scope_schedule_input_diverts_only_the_excluded_no_choice_leaf():
    """The scheduler-scope half of the mechanism: an excluded no-choice leaf
    is deferred as SELECTION_DEFERRED instead of scheduled, while a
    non-excluded sibling still schedules normally."""
    raw_groups = [
        {"id": "keep", "coursedog_rule_id": "keep", "parent_group_id": None, "name": "Keep",
         "group_type": "enumerated_all", "n_required": None, "credit_hours_required": None,
         "requires_manual_definition": False},
        {"id": "drop", "coursedog_rule_id": "drop", "parent_group_id": None, "name": "Drop",
         "group_type": "enumerated_all", "n_required": None, "credit_hours_required": None,
         "requires_manual_definition": False},
    ]
    options = [
        {"id": "keep-opt", "requirement_group_id": "keep", "option_index": 0, "logic": "and"},
        {"id": "drop-opt", "requirement_group_id": "drop", "option_index": 0, "logic": "and"},
    ]
    option_courses = [
        {"requirement_group_option_id": "keep-opt", "coursedog_group_id": None,
         "unresolved_course_ref": None, "course_code": "KEEP 1"},
        {"requirement_group_option_id": "drop-opt", "coursedog_group_id": None,
         "unresolved_course_ref": None, "course_code": "DROP 1"},
    ]
    by_code = {"KEEP 1": ["KEEP 1"], "DROP 1": ["DROP 1"]}

    evaluated = evaluate_requirement_tree(raw_groups, options, option_courses, [], {}, by_code)
    courses, unscheduled = scope_schedule_input(
        evaluated, options, option_courses, {}, {"KEEP 1": 3.0, "DROP 1": 3.0}, by_code,
        excluded_group_ids={"drop"},
    )

    assert [c.course_code for c in courses] == ["KEEP 1"]
    assert [(u.name, u.reason) for u in unscheduled] == [("Drop", "SELECTION_DEFERRED")]
