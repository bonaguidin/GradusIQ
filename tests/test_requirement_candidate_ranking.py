import pytest
from pydantic import ValidationError

from GradusIQ_career.course_discovery.requirement_candidate_ranking import (
    RankedRequirementCandidate,
    RequirementCandidateRanking,
    career_rank_map,
    validate_candidate_ranking,
)
from GradusIQ_career.course_discovery.requirement_candidates import (
    AcademicFeasibility,
    RequirementCandidate,
    RequirementCandidateSet,
)


def candidate(candidate_id, courses):
    return RequirementCandidate(
        candidate_id=candidate_id,
        requirement_group_id="group",
        requirement_name="Group",
        course_codes=courses,
        existing_contribution=0,
        additional_course_count=len(courses),
        additional_credits=3 * len(courses),
        academic_feasibility=AcademicFeasibility.FEASIBLE,
        completion_term_index=0,
    )


def candidate_set():
    return RequirementCandidateSet(
        requirement_group_id="group",
        requirement_name="Group",
        feasible_candidates=[candidate("A", ["CS 1"]), candidate("B", ["CS 2"]), candidate("C", ["CS 3", "CS 4"])],
    )


def ranking(ids=("C", "A", "B"), group="group", ranks=None):
    ranks = ranks or range(1, len(ids) + 1)
    return RequirementCandidateRanking(
        requirement_group_id=group,
        ranked_candidates=[
            RankedRequirementCandidate(
                candidate_id=value,
                rank=rank,
                ranking_reason="Grounded career preference.",
                skill_alignment_explanation="Catalog content supports the trusted need.",
            )
            for value, rank in zip(ids, ranks)
        ],
    )


def test_valid_complete_permutation_and_atomic_path():
    value = validate_candidate_ranking(ranking(), candidate_set())
    assert [item.candidate_id for item in value.ranked_candidates] == ["C", "A", "B"]
    assert value.ranked_candidates[0].candidate_id == "C"  # one entry owns CS 3 + CS 4
    assert career_rank_map([value]) == {"C": 0, "A": 1, "B": 2}


@pytest.mark.parametrize(
    "value",
    [
        ranking(("A", "B", "D")),
        ranking(("A", "B")),
        ranking(("A", "B", "C"), group="other"),
    ],
)
def test_unknown_missing_and_wrong_requirement_are_rejected(value):
    with pytest.raises(ValueError):
        validate_candidate_ranking(value, candidate_set())


def test_duplicate_candidate_is_rejected():
    with pytest.raises(ValidationError):
        ranking(("A", "A", "C"))


@pytest.mark.parametrize("ranks", [(1, 1, 2), (1, 2, 4), (0, 1, 2)])
def test_invalid_ranks_are_rejected(ranks):
    with pytest.raises(ValidationError):
        ranking(ranks=ranks)


def test_foreign_course_or_path_fields_are_rejected():
    payload = ranking().model_dump()
    payload["ranked_candidates"][0]["course_codes"] = ["INVENTED 9999"]
    with pytest.raises(ValidationError):
        RequirementCandidateRanking.model_validate(payload)
