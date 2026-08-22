"""Non-persisted career-ranking preview for deterministic degree plans.

The academic planner remains authoritative.  This module only fingerprints
model-visible inputs, coordinates advisory ranking calls, and feeds validated
zero-based preferences back into the deterministic selector.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import Field

from GradusIQ_career.course_discovery.models import CareerSkillNeed, CourseCatalogRecord, StrictModel
from GradusIQ_career.course_discovery.requirement_candidate_ranking import (
    RequirementCandidateRanking,
    career_rank_map,
    validate_candidate_ranking,
)
from GradusIQ_career.course_discovery.requirement_candidates import RequirementCandidateSet
from GradusIQ_career.course_discovery.requirement_ranker import (
    REQUIREMENT_RANKING_CONTRACT_VERSION,
    REQUIREMENT_RANKING_PROMPT_VERSION,
)
from GradusIQ_career.course_discovery.scheduler import ScheduleResult


CAREER_OPTIMIZATION_CACHE_TTL_SECONDS = 15 * 60
CAREER_OPTIMIZATION_CACHE_MAX_ENTRIES = 128


class CareerOptimizationStatus(str, Enum):
    OPTIMIZED = "OPTIMIZED"
    PARTIAL = "PARTIAL"
    FALLBACK = "FALLBACK"
    SKIPPED = "SKIPPED"


class CareerSelectionBasis(str, Enum):
    CAREER_RANKED = "CAREER_RANKED"
    ACADEMIC_DEFAULT = "ACADEMIC_DEFAULT"


class CareerOptimizationCacheStatus(str, Enum):
    HIT = "HIT"
    MISS = "MISS"
    BYPASSED = "BYPASSED"


class RequirementRankingFailure(StrictModel):
    requirement_group_id: str
    requirement_name: str
    error_code: str
    detail: str


class CareerOptimizedScheduleResponse(StrictModel):
    feature: str = "CAREER_OPTIMIZED_SCHEDULE"
    status: CareerOptimizationStatus
    selection_basis: CareerSelectionBasis
    target_role: str | None = None
    fingerprint: str | None = None
    generated_at: str
    cache_status: CareerOptimizationCacheStatus
    academic_schedule: ScheduleResult
    optimized_schedule: ScheduleResult
    requirement_rankings: list[RequirementCandidateRanking] = Field(default_factory=list)
    ranking_failures: list[RequirementRankingFailure] = Field(default_factory=list)
    ranking_prompt_version: str = REQUIREMENT_RANKING_PROMPT_VERSION
    resolved_model: str
    summary: str | None = None


def _need_payload(need: CareerSkillNeed) -> dict[str, Any]:
    return {
        "need_id": need.need_id,
        "skill": need.skill,
        "category": need.category,
        "importance": need.importance,
        "evidence_state": need.evidence_state.value,
        "evidence_source": need.evidence_source,
        "confidence": need.confidence,
    }


def build_requirement_ranking_fingerprint(
    *,
    student_id: str,
    target_role: str,
    career_needs: Sequence[CareerSkillNeed],
    candidate_sets: Sequence[RequirementCandidateSet],
    catalog_by_code: Mapping[str, CourseCatalogRecord],
    resolved_model: str,
    contract_version: str = REQUIREMENT_RANKING_CONTRACT_VERSION,
    prompt_version: str = REQUIREMENT_RANKING_PROMPT_VERSION,
) -> str:
    """SHA-256 of canonical ranking semantics, independent of collection order."""
    requirements = []
    visible_codes: set[str] = set()
    for candidate_set in candidate_sets:
        candidates = []
        for candidate in candidate_set.feasible_candidates:
            codes = sorted(set(candidate.course_codes))
            visible_codes.update(codes)
            candidates.append({
                "candidate_id": candidate.candidate_id,
                "course_codes": codes,
                "additional_credits": candidate.additional_credits,
                "completion_term_index": candidate.completion_term_index,
                "limitations": sorted(candidate.limitations),
            })
        requirements.append({
            "requirement_group_id": candidate_set.requirement_group_id,
            "requirement_name": candidate_set.requirement_name,
            "feasible_candidates": sorted(candidates, key=lambda item: item["candidate_id"]),
        })
    catalog = []
    for code in sorted(visible_codes):
        record = catalog_by_code.get(code)
        catalog.append({
            "institution": record.institution.value if record else None,
            "course_code": code,
            "title": record.title if record else None,
            "description": record.description if record else None,
            "catalog_year": record.catalog_year if record else None,
        })
    payload = {
        "contract_version": contract_version,
        "ranking_prompt_version": prompt_version,
        "resolved_model": resolved_model,
        "student_id": str(student_id),
        "target_role": " ".join(target_role.split()),
        "career_needs": sorted(
            (_need_payload(need) for need in career_needs),
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        ),
        "requirements": sorted(requirements, key=lambda item: item["requirement_group_id"]),
        "catalog_courses": catalog,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CareerOptimizationCoordinator:
    """Bounded TTL result cache plus per-fingerprint synchronous single-flight."""

    def __init__(
        self,
        *,
        ttl_seconds: float = CAREER_OPTIMIZATION_CACHE_TTL_SECONDS,
        max_entries: int = CAREER_OPTIMIZATION_CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("cache TTL and bound must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._cache: OrderedDict[tuple[str, str], tuple[float, CareerOptimizedScheduleResponse]] = OrderedDict()
        self._inflight: dict[tuple[str, str], Future[CareerOptimizedScheduleResponse]] = {}
        self._lock = threading.Lock()

    def _cached(self, key: tuple[str, str]) -> CareerOptimizedScheduleResponse | None:
        now = self._clock()
        with self._lock:
            item = self._cache.get(key)
            if item is None:
                return None
            expires_at, response = item
            if expires_at <= now:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return response.model_copy(update={"cache_status": CareerOptimizationCacheStatus.HIT})

    def run(
        self,
        *,
        student_id: str,
        fingerprint: str,
        force_refresh: bool,
        compute: Callable[[CareerOptimizationCacheStatus], CareerOptimizedScheduleResponse],
    ) -> CareerOptimizedScheduleResponse:
        key = (str(student_id), fingerprint)
        if not force_refresh:
            hit = self._cached(key)
            if hit is not None:
                return hit
        requested_status = (
            CareerOptimizationCacheStatus.BYPASSED
            if force_refresh else CareerOptimizationCacheStatus.MISS
        )
        with self._lock:
            future = self._inflight.get(key)
            owner = future is None
            if owner:
                future = Future()
                self._inflight[key] = future
        assert future is not None
        if not owner:
            return future.result()
        try:
            response = compute(requested_status)
            if response.status == CareerOptimizationStatus.OPTIMIZED:
                with self._lock:
                    self._cache[key] = (self._clock() + self.ttl_seconds, response)
                    self._cache.move_to_end(key)
                    while len(self._cache) > self.max_entries:
                        self._cache.popitem(last=False)
            future.set_result(response)
            return response
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)

    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)


def skipped_response(
    *,
    academic_schedule: ScheduleResult,
    resolved_model: str,
    target_role: str | None,
    summary: str,
) -> CareerOptimizedScheduleResponse:
    return CareerOptimizedScheduleResponse(
        status=CareerOptimizationStatus.SKIPPED,
        selection_basis=CareerSelectionBasis.ACADEMIC_DEFAULT,
        target_role=target_role,
        generated_at=datetime.now(timezone.utc).isoformat(),
        cache_status=CareerOptimizationCacheStatus.MISS,
        academic_schedule=academic_schedule,
        optimized_schedule=academic_schedule,
        resolved_model=resolved_model,
        summary=summary,
    )


def compute_career_optimized_response(
    *,
    target_role: str,
    fingerprint: str,
    resolved_model: str,
    academic_schedule: ScheduleResult,
    rankable_candidate_sets: Sequence[RequirementCandidateSet],
    rank_batch: Callable[[Sequence[RequirementCandidateSet]], Sequence[RequirementCandidateRanking | None]],
    build_optimized_schedule: Callable[[Mapping[str, int]], ScheduleResult],
    cache_status: CareerOptimizationCacheStatus,
) -> CareerOptimizedScheduleResponse:
    """Validate each advisory result and fall back per group without failing planning."""
    rankings: list[RequirementCandidateRanking] = []
    failures: list[RequirementRankingFailure] = []
    try:
        returned = list(rank_batch(rankable_candidate_sets))
    except Exception as exc:  # provider/batch boundary: preserve academic plan
        returned = []
        failures.extend(
            RequirementRankingFailure(
                requirement_group_id=item.requirement_group_id,
                requirement_name=item.requirement_name,
                error_code="RANKING_UNAVAILABLE",
                detail=f"Career ranking was unavailable: {type(exc).__name__}.",
            )
            for item in rankable_candidate_sets
        )
    for index, candidate_set in enumerate(rankable_candidate_sets):
        ranking = returned[index] if index < len(returned) else None
        if ranking is None:
            if not any(f.requirement_group_id == candidate_set.requirement_group_id for f in failures):
                failures.append(RequirementRankingFailure(
                    requirement_group_id=candidate_set.requirement_group_id,
                    requirement_name=candidate_set.requirement_name,
                    error_code="INVALID_OR_UNAVAILABLE_RANKING",
                    detail="The provider result was unavailable or failed candidate validation.",
                ))
            continue
        try:
            rankings.append(validate_candidate_ranking(ranking, candidate_set))
        except Exception as exc:
            failures.append(RequirementRankingFailure(
                requirement_group_id=candidate_set.requirement_group_id,
                requirement_name=candidate_set.requirement_name,
                error_code="INVALID_RANKING",
                detail=str(exc),
            ))
    if not rankings:
        status = CareerOptimizationStatus.FALLBACK
        basis = CareerSelectionBasis.ACADEMIC_DEFAULT
        optimized = academic_schedule
    else:
        optimized = build_optimized_schedule(career_rank_map(rankings))
        status = (
            CareerOptimizationStatus.OPTIMIZED
            if len(rankings) == len(rankable_candidate_sets)
            else CareerOptimizationStatus.PARTIAL
        )
        basis = CareerSelectionBasis.CAREER_RANKED
    return CareerOptimizedScheduleResponse(
        status=status,
        selection_basis=basis,
        target_role=target_role,
        fingerprint=fingerprint,
        generated_at=datetime.now(timezone.utc).isoformat(),
        cache_status=cache_status,
        academic_schedule=academic_schedule,
        optimized_schedule=optimized,
        requirement_rankings=rankings,
        ranking_failures=failures,
        resolved_model=resolved_model,
    )
