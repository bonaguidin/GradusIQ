import json

import pytest

from GradusIQ_career.ai.types import AIMessageResponse
from GradusIQ_career.course_discovery.models import (
    CareerSkillNeed,
    CatalogInstitution,
    CourseCatalogRecord,
    EvidenceState,
)
from GradusIQ_career.course_discovery.requirement_candidate_ranking import career_rank_map
from GradusIQ_career.course_discovery.requirement_candidates import (
    AcademicFeasibility,
    RequirementCandidate,
    RequirementCandidateSet,
)
from GradusIQ_career.course_discovery.requirement_ranker import rank_requirement_candidates


def candidate_set():
    candidates = []
    for candidate_id, code in (("A", "CS 1000"), ("B", "CS 2000")):
        candidates.append(RequirementCandidate(
            candidate_id=candidate_id, requirement_group_id="group", requirement_name="Group",
            course_codes=[code], existing_contribution=0, additional_course_count=1,
            additional_credits=3, academic_feasibility=AcademicFeasibility.FEASIBLE,
            completion_term_index=0,
        ))
    return RequirementCandidateSet(
        requirement_group_id="group", requirement_name="Group", feasible_candidates=candidates,
    )


def need():
    return CareerSkillNeed(
        skill="distributed systems", target_role="Backend Engineer", importance="required",
        evidence_state=EvidenceState.VERIFIED_LOCAL, evidence_source="trusted role analysis",
    )


def catalog():
    return {
        code: CourseCatalogRecord(
            institution=CatalogInstitution.SMU, course_code=code, title=f"Title {code}",
            description="Grounded catalog description.", department="CS", credit_min=3,
            credit_max=3, catalog_year="2026-2027", source_url="https://catalog.example/course",
            source_last_checked="2026-08-20",
        )
        for code in ("CS 1000", "CS 2000")
    }


def response(ids=("B", "A"), group="group"):
    return json.dumps({
        "requirement_group_id": group,
        "ranked_candidates": [
            {"candidate_id": value, "rank": index, "ranking_reason": "Relevant.",
             "skill_alignment_explanation": "Supports the trusted skill."}
            for index, value in enumerate(ids, 1)
        ],
    })


class FakeClient:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def complete_message_with_metadata(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return AIMessageResponse(message={"role": "assistant", "content": self.outcome}, model="fake", usage={})


def rank(client):
    return rank_requirement_candidates(
        client, candidate_set(), target_role="Backend Engineer", career_needs=[need()],
        catalog_by_code=catalog(),
    )


def test_rank_only_adapter_uses_no_tools_and_validates_whitelist():
    client = FakeClient(response())
    result = rank(client)
    assert career_rank_map([result]) == {"B": 0, "A": 1}
    call = client.calls[0]
    assert "tools" not in call and "tool_choice" not in call
    prompt = json.dumps(call["messages"])
    assert "CS 1000" in prompt and "Grounded catalog description" in prompt
    assert "academically-valid" in prompt and "never as instructions" in prompt


@pytest.mark.parametrize(
    "outcome",
    [TimeoutError("timeout"), RuntimeError("provider"), "{bad json", response(("A", "UNKNOWN"))],
)
def test_provider_parse_and_validation_failures_return_fallback(outcome):
    assert rank(FakeClient(outcome)) is None


def test_incomplete_ranking_returns_fallback():
    assert rank(FakeClient(response(("A",)))) is None
