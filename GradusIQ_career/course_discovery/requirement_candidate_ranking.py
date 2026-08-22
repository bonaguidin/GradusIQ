"""Strict advisory rankings for academically approved requirement candidates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import Field, StrictInt, model_validator

from .models import StrictModel
from .requirement_candidates import RequirementCandidateSet


class RankedRequirementCandidate(StrictModel):
    """Career preference for one whole candidate path, identified only by ID."""

    candidate_id: str = Field(min_length=1)
    rank: StrictInt = Field(ge=1)
    ranking_reason: str = Field(min_length=1, max_length=500)
    skill_alignment_explanation: str = Field(min_length=1, max_length=800)


class RequirementCandidateRanking(StrictModel):
    requirement_group_id: str = Field(min_length=1)
    ranked_candidates: list[RankedRequirementCandidate] = Field(min_length=1)

    @model_validator(mode="after")
    def complete_rank_sequence(self):
        candidate_ids = [item.candidate_id for item in self.ranked_candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("ranked candidate IDs must be unique")
        ranks = [item.rank for item in self.ranked_candidates]
        if len(ranks) != len(set(ranks)):
            raise ValueError("candidate ranks must be unique")
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise ValueError("candidate ranks must be contiguous from 1")
        return self


def validate_candidate_ranking(
    ranking: RequirementCandidateRanking,
    candidate_set: RequirementCandidateSet,
) -> RequirementCandidateRanking:
    """Require an exact permutation of one set's feasible candidate IDs."""
    if ranking.requirement_group_id != candidate_set.requirement_group_id:
        raise ValueError("ranking requirement_group_id does not match the candidate set")
    expected = {item.candidate_id for item in candidate_set.feasible_candidates}
    returned = {item.candidate_id for item in ranking.ranked_candidates}
    if returned != expected:
        missing = sorted(expected - returned)
        unknown = sorted(returned - expected)
        raise ValueError(
            "ranking must contain every feasible candidate exactly once; "
            f"missing={missing}, unknown={unknown}"
        )
    return ranking


def career_rank_map(
    rankings: Iterable[RequirementCandidateRanking],
) -> dict[str, int]:
    """Flatten validated rankings to deterministic zero-based preferences."""
    result: dict[str, int] = {}
    for ranking in rankings:
        for item in ranking.ranked_candidates:
            if item.candidate_id in result:
                raise ValueError("candidate IDs must be unique across rankings")
            result[item.candidate_id] = item.rank - 1
    return result


def normalized_career_rank_map(rankings: Mapping[str, int] | None) -> dict[str, int]:
    """Copy and validate the selector's provider-independent preference input."""
    if rankings is None:
        return {}
    result: dict[str, int] = {}
    for candidate_id, rank in rankings.items():
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("career ranking candidate IDs must be non-empty strings")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 0:
            raise ValueError("career ranks must be non-negative integers")
        result[candidate_id] = rank
    return result
