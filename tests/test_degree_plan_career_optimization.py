from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from GradusIQ_career.degree_plan_career_optimization import (
    CareerOptimizationCacheStatus,
    CareerOptimizationCoordinator,
    CareerOptimizationStatus,
    CareerSelectionBasis,
    build_requirement_ranking_fingerprint,
    compute_career_optimized_response,
)
from GradusIQ_career.course_discovery.models import (
    CareerSkillNeed,
    CatalogInstitution,
    CourseCatalogRecord,
    EvidenceState,
)
from GradusIQ_career.course_discovery.requirement_candidate_ranking import (
    RankedRequirementCandidate,
    RequirementCandidateRanking,
)
from GradusIQ_career.course_discovery.requirement_candidates import (
    AcademicFeasibility,
    RequirementCandidate,
    RequirementCandidateSet,
)
from GradusIQ_career.course_discovery.scheduler import ScheduleResult


def _need(skill="Distributed systems"):
    return CareerSkillNeed(
        skill=skill, category="skills", target_role="Backend Engineer",
        importance="required", evidence_state=EvidenceState.VERIFIED_LOCAL,
        evidence_source="O*NET trusted", confidence=.9,
    )


def _candidate(candidate_id, code, *, credits=3.0, term=0, limitations=()):
    return RequirementCandidate(
        candidate_id=candidate_id, requirement_group_id="group", requirement_name="Group",
        course_codes=[code], existing_contribution=0, additional_course_count=1,
        additional_credits=credits, academic_feasibility=AcademicFeasibility.FEASIBLE,
        completion_term_index=term, limitations=list(limitations), source_order=[0],
    )


def _set(order=("A", "B")):
    by_id = {"A": _candidate("A", "CS 1000"), "B": _candidate("B", "CS 2000")}
    return RequirementCandidateSet(
        requirement_group_id="group", requirement_name="Group",
        feasible_candidates=[by_id[value] for value in order],
    )


def _catalog(reverse=False):
    codes = ["CS 1000", "CS 2000"]
    if reverse:
        codes.reverse()
    return {
        code: CourseCatalogRecord(
            institution=CatalogInstitution.SMU, course_code=code, title=f"Title {code}",
            description=f"Description {code}", department="CS", credit_min=3,
            credit_max=3, catalog_year="2026-2027", source_url="https://example.test",
            source_last_checked="2026-08-20",
        )
        for code in codes
    }


def _fingerprint(**overrides):
    values = dict(
        student_id="student", target_role="Backend Engineer", career_needs=[_need()],
        candidate_sets=[_set()], catalog_by_code=_catalog(), resolved_model="model-1",
    )
    values.update(overrides)
    return build_requirement_ranking_fingerprint(**values)


def _schedule(program="program"):
    return ScheduleResult(student_id="student", program_id=program)


def _ranking(order=("B", "A")):
    return RequirementCandidateRanking(
        requirement_group_id="group",
        ranked_candidates=[
            RankedRequirementCandidate(
                candidate_id=value, rank=index, ranking_reason="Relevant.",
                skill_alignment_explanation="Matches a trusted need.",
            )
            for index, value in enumerate(order, 1)
        ],
    )


def _optimized_response(cache_status=CareerOptimizationCacheStatus.MISS):
    return compute_career_optimized_response(
        target_role="Backend Engineer", fingerprint="fingerprint", resolved_model="model-1",
        academic_schedule=_schedule(), rankable_candidate_sets=[_set()],
        rank_batch=lambda _sets: [_ranking()],
        build_optimized_schedule=lambda ranks: _schedule("optimized") if ranks == {"B": 0, "A": 1} else None,
        cache_status=cache_status,
    )


def test_fingerprint_is_canonical_and_order_independent():
    assert _fingerprint() == _fingerprint(
        career_needs=list(reversed([_need()])), candidate_sets=[_set(("B", "A"))],
        catalog_by_code=_catalog(reverse=True),
    )


@pytest.mark.parametrize("change", [
    "target_role", "career_need", "candidate_id", "course_membership", "credits",
    "completion", "limitation", "title", "description", "catalog_year",
    "prompt_version", "contract_version", "resolved_model",
])
def test_fingerprint_changes_for_every_ranking_semantic_input(change):
    baseline = _fingerprint()
    kwargs = {}
    if change == "target_role": kwargs["target_role"] = "Platform Engineer"
    elif change == "career_need": kwargs["career_needs"] = [_need("Databases")]
    elif change in {"candidate_id", "course_membership", "credits", "completion", "limitation"}:
        candidate = _candidate(
            "C" if change == "candidate_id" else "A",
            "CS 2000" if change == "course_membership" else "CS 1000",
            credits=4 if change == "credits" else 3,
            term=1 if change == "completion" else 0,
            limitations=("review",) if change == "limitation" else (),
        )
        kwargs["candidate_sets"] = [RequirementCandidateSet(
            requirement_group_id="group", requirement_name="Group",
            feasible_candidates=[candidate, _candidate("B", "CS 2000")],
        )]
    elif change in {"title", "description", "catalog_year"}:
        catalog = _catalog()
        record = catalog["CS 1000"]
        update = {change: "changed"}
        catalog["CS 1000"] = record.model_copy(update=update)
        kwargs["catalog_by_code"] = catalog
    else:
        kwargs[change] = "2"
    assert _fingerprint(**kwargs) != baseline


def test_partial_and_full_failure_preserve_academic_fallback():
    second = _set()
    second = second.model_copy(update={"requirement_group_id": "group-2", "requirement_name": "Group 2"})
    # Candidate rows must carry their owning group for validation in real data;
    # this test only needs the batch failure boundary, so both groups fail.
    result = compute_career_optimized_response(
        target_role="Backend Engineer", fingerprint="fp", resolved_model="model",
        academic_schedule=_schedule(), rankable_candidate_sets=[_set(), second],
        rank_batch=lambda _sets: [None, None], build_optimized_schedule=lambda _ranks: _schedule("bad"),
        cache_status=CareerOptimizationCacheStatus.MISS,
    )
    assert result.status == CareerOptimizationStatus.FALLBACK
    assert result.selection_basis == CareerSelectionBasis.ACADEMIC_DEFAULT
    assert result.optimized_schedule == result.academic_schedule
    assert len(result.ranking_failures) == 2


def test_valid_and_failed_groups_produce_partial_result():
    result = compute_career_optimized_response(
        target_role="Backend Engineer", fingerprint="fp", resolved_model="model",
        academic_schedule=_schedule(), rankable_candidate_sets=[_set(), _set()],
        rank_batch=lambda _sets: [_ranking(), None],
        build_optimized_schedule=lambda ranks: _schedule("optimized"),
        cache_status=CareerOptimizationCacheStatus.MISS,
    )
    assert result.status == CareerOptimizationStatus.PARTIAL
    assert result.selection_basis == CareerSelectionBasis.CAREER_RANKED
    assert result.optimized_schedule.program_id == "optimized"
    assert len(result.requirement_rankings) == 1 and len(result.ranking_failures) == 1


def test_cache_hit_expiry_force_refresh_only_optimized_and_bound():
    now = [0.0]
    coordinator = CareerOptimizationCoordinator(ttl_seconds=10, max_entries=2, clock=lambda: now[0])
    calls = []

    def compute(status):
        calls.append(status)
        return _optimized_response(status)

    first = coordinator.run(student_id="s", fingerprint="a", force_refresh=False, compute=compute)
    assert first.cache_status == CareerOptimizationCacheStatus.MISS
    hit = coordinator.run(student_id="s", fingerprint="a", force_refresh=False, compute=compute)
    assert hit.cache_status == CareerOptimizationCacheStatus.HIT and len(calls) == 1
    coordinator.run(student_id="s", fingerprint="a", force_refresh=True, compute=compute)
    assert calls[-1] == CareerOptimizationCacheStatus.BYPASSED
    now[0] = 11
    coordinator.run(student_id="s", fingerprint="a", force_refresh=False, compute=compute)
    assert len(calls) == 3
    coordinator.run(student_id="s", fingerprint="b", force_refresh=False, compute=compute)
    coordinator.run(student_id="s", fingerprint="c", force_refresh=False, compute=compute)
    assert coordinator.cache_size() == 2

    for status in (
        CareerOptimizationStatus.PARTIAL,
        CareerOptimizationStatus.FALLBACK,
        CareerOptimizationStatus.SKIPPED,
    ):
        uncached_calls = []
        uncached = _optimized_response().model_copy(update={"status": status})
        other = CareerOptimizationCoordinator()
        other.run(student_id="s", fingerprint=status.value, force_refresh=False, compute=lambda _: uncached)
        other.run(
            student_id="s", fingerprint=status.value, force_refresh=False,
            compute=lambda _: uncached_calls.append(1) or uncached,
        )
        assert uncached_calls == [1]


def test_single_flight_deduplicates_identical_force_refresh_and_cleans_failure():
    coordinator = CareerOptimizationCoordinator()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def compute(status):
        calls.append(status)
        entered.set()
        assert release.wait(2)
        return _optimized_response(status)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(coordinator.run, student_id="s", fingerprint="same", force_refresh=True, compute=compute)
        assert entered.wait(1)
        second = pool.submit(coordinator.run, student_id="s", fingerprint="same", force_refresh=True, compute=compute)
        release.set()
        assert first.result() == second.result()
    assert len(calls) == 1

    attempts = []
    def fail(_status):
        attempts.append(1)
        raise TimeoutError("provider")
    with pytest.raises(TimeoutError):
        coordinator.run(student_id="s", fingerprint="failure", force_refresh=False, compute=fail)
    with pytest.raises(TimeoutError):
        coordinator.run(student_id="s", fingerprint="failure", force_refresh=False, compute=fail)
    assert len(attempts) == 2


def test_different_fingerprints_do_not_share_single_flight():
    coordinator = CareerOptimizationCoordinator()
    barrier = threading.Barrier(2)
    calls = []
    def compute(status):
        calls.append(status)
        barrier.wait(timeout=2)
        return _optimized_response(status)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(coordinator.run, student_id="s", fingerprint=key, force_refresh=False, compute=compute)
            for key in ("a", "b")
        ]
        [future.result() for future in futures]
    assert len(calls) == 2
