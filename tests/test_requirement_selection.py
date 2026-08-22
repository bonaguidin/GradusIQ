from __future__ import annotations

import json
from pathlib import Path

from GradusIQ_career.course_discovery.catalog import LocalCatalogRepository
from GradusIQ_career.course_discovery.models import PrerequisiteClause, StructuredPrerequisite
from GradusIQ_career.course_discovery.models import CatalogInstitution
from GradusIQ_career.course_discovery.prerequisites import structured_prerequisite
from GradusIQ_career.course_discovery.requirement_satisfaction import evaluate_requirement_tree
from GradusIQ_career.course_discovery.requirement_selection import select_structured_requirements
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


def course(option_id, gid=None, unresolved=None):
    return {"requirement_group_option_id": option_id, "coursedog_group_id": gid, "unresolved_course_ref": unresolved}


def run(groups, options, option_courses, catalog, credits, *, records=None, prerequisites=None, max_terms=4, career_ranks=None):
    records = records or []
    evaluated = evaluate_requirement_tree(groups, options, option_courses, records, catalog)
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
        starting_year=2026, starting_season="Fall", max_terms=max_terms,
        career_rank_by_candidate_id=career_ranks,
    )


def selected(result):
    return [course.course_code for course in result.courses]


def test_choose_one_uses_stable_source_order():
    groups = [group("pick", "enumerated_at_least_n", n=1)]
    options = [option(f"o{i}", "pick", i) for i in range(3)]
    rows = [course(f"o{i}", f"g{i}") for i in range(3)]
    result = run(groups, options, rows, {f"g{i}": f"C {i}" for i in range(3)}, {f"C {i}": 3 for i in range(3)})
    assert selected(result) == ["C 0"]
    explicit_fallback = run(
        groups, options, rows,
        {f"g{i}": f"C {i}" for i in range(3)},
        {f"C {i}": 3 for i in range(3)},
        career_ranks=None,
    )
    assert explicit_fallback.model_dump(mode="json") == result.model_dump(mode="json")


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


def test_choose_n_selects_distinct_options():
    groups = [group("pick", "enumerated_at_least_n", n=2)]
    options = [option(f"o{i}", "pick", i) for i in range(6)]
    rows = [course(f"o{i}", f"g{i}") for i in range(6)]
    result = run(groups, options, rows, {f"g{i}": f"C {i}" for i in range(6)}, {f"C {i}": 3 for i in range(6)})
    assert selected(result) == ["C 0", "C 1"]


def test_or_identity_selects_one_not_all():
    groups = [group("or", "enumerated_all")]
    options = [option("o", "or", 0, "or")]
    rows = [course("o", "ga"), course("o", "gb"), course("o", "gc")]
    result = run(groups, options, rows, {"ga": "A", "gb": "B", "gc": "C"}, {"A": 3, "B": 3, "C": 3})
    assert selected(result) == ["A"]


def test_compound_any_selects_exactly_one_branch():
    groups = [group("parent", "compound_any"), group("a", "enumerated_all", parent="parent"), group("b", "enumerated_all", parent="parent")]
    options = [option("oa", "a", 0), option("ob", "b", 0)]
    rows = [course("oa", "ga"), course("ob", "gb")]
    result = run(groups, options, rows, {"ga": "A", "gb": "B"}, {"A": 3, "B": 3})
    assert selected(result) == ["A"]
    assert result.courses[0].requirement_group_id == "a"


def test_credit_threshold_chooses_minimum_sufficient_credits():
    groups = [group("credits", "enumerated_credit_threshold", credits=7)]
    options = [option("o0", "credits", 0), option("o1", "credits", 1), option("o2", "credits", 2)]
    rows = [course("o0", "g0"), course("o1", "g1"), course("o2", "g2")]
    result = run(groups, options, rows, {"g0": "A", "g1": "B", "g2": "C"}, {"A": 4, "B": 4, "C": 3})
    assert selected(result) == ["A", "C"]


def test_existing_progress_reduces_remaining_choice():
    groups = [group("pick", "enumerated_at_least_n", n=2)]
    options = [option("o0", "pick", 0), option("o1", "pick", 1), option("o2", "pick", 2)]
    rows = [course("o0", "g0"), course("o1", "g1"), course("o2", "g2")]
    records = [{"course_code": "A", "status": "in_progress", "counts_toward_credit": True, "credit_hours": 3}]
    result = run(groups, options, rows, {"g0": "A", "g1": "B", "g2": "C"}, {"A": 3, "B": 3, "C": 3}, records=records)
    assert selected(result) == ["B"]


def test_existing_progress_prefers_compound_branch():
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
    assert selected(result) == ["A1"]


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
    assert {course.course_code for course in result.courses} - base_codes == {
        "CS 5323", "ENGR 1199", "CS 4340", "BIOL 1301", "BIOL 1101",
        "BIOL 1302", "BIOL 1102", "CEE 2302", "CS 3377",
    }
    assert {entry.name for entry in result.unscheduled} == {
        "Technical Electives (9 Credit Hours)", "Advanced Major Electives (3-5 Credit Hours)",
    }
    assert result.search_stats.candidate_combinations_before_pruning == 19008
    assert result.search_stats.candidate_combinations_after_structural_pruning == 1080
    assert result.search_stats.candidate_combinations_evaluated == 1080
