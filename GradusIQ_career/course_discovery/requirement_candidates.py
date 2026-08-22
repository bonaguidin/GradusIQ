"""Public deterministic contracts for academically evaluated requirement choices.

These models are the boundary between Degree Planner's academic authority and
any future advisory ranking layer.  They deliberately contain no career or
model-authored fields.  Candidate feasibility is populated by the same global
combination search that selects the plan; callers never need to rerun the
scheduler to understand a candidate.
"""

from __future__ import annotations

from enum import Enum
import hashlib
import json

from pydantic import Field, model_validator

from .models import StrictModel


class AcademicFeasibility(str, Enum):
    FEASIBLE = "FEASIBLE"
    EXCLUDED = "EXCLUDED"


class CandidateExclusionReason(str, Enum):
    UNRESOLVED_COURSE = "UNRESOLVED_COURSE"
    RESTRICTION_REQUIRES_REVIEW = "RESTRICTION_REQUIRES_REVIEW"
    PREREQUISITE_NEEDS_REVIEW = "PREREQUISITE_NEEDS_REVIEW"
    DOUBLE_COUNTING_CONFLICT = "DOUBLE_COUNTING_CONFLICT"
    MISSING_CREDIT_DATA = "MISSING_CREDIT_DATA"
    UNSCHEDULABLE = "UNSCHEDULABLE"


def stable_candidate_id(
    requirement_group_id: str,
    source_order: tuple[int, ...],
    course_codes: tuple[str, ...],
    *,
    source_path: str | None = None,
) -> str:
    """Return a stable ID for one whole academic path, never one object."""
    identity = json.dumps(
        {
            "requirement_group_id": requirement_group_id,
            "source_order": list(source_order),
            "source_path": source_path,
            "course_codes": sorted(set(course_codes)),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "reqcand_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


class RequirementCandidate(StrictModel):
    candidate_id: str = Field(min_length=1)
    requirement_group_id: str = Field(min_length=1)
    requirement_name: str = Field(min_length=1)
    course_codes: list[str] = Field(default_factory=list)
    existing_contribution: int = Field(ge=0)
    additional_course_count: int = Field(ge=0)
    additional_credits: float | None = Field(default=None, ge=0)
    academic_feasibility: AcademicFeasibility
    completion_term_index: int | None = Field(default=None, ge=0)
    limitations: list[str] = Field(default_factory=list)
    source_order: list[int] = Field(default_factory=list)
    exclusion_reasons: list[CandidateExclusionReason] = Field(default_factory=list)
    exclusion_details: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def feasibility_contract(self):
        if self.additional_course_count != len(self.course_codes):
            raise ValueError("additional_course_count must match course_codes")
        if self.academic_feasibility == AcademicFeasibility.FEASIBLE:
            if self.completion_term_index is None:
                raise ValueError("a feasible candidate requires completion_term_index")
            if self.exclusion_reasons:
                raise ValueError("a feasible candidate cannot carry exclusion reasons")
        else:
            if not self.exclusion_reasons:
                raise ValueError("an excluded candidate requires an exclusion reason")
            if self.completion_term_index is not None:
                raise ValueError("an excluded candidate cannot have completion timing")
        return self


class RequirementCandidateSet(StrictModel):
    requirement_group_id: str = Field(min_length=1)
    requirement_name: str = Field(min_length=1)
    feasible_candidates: list[RequirementCandidate] = Field(default_factory=list)
    excluded_candidates: list[RequirementCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_candidate_ids(self):
        ids = [
            candidate.candidate_id
            for candidate in self.feasible_candidates + self.excluded_candidates
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique within a requirement")
        return self
