import json

import pytest
from pydantic import ValidationError

from GradusIQ_career.ai.context import AgentContext, GroundingMetadata
from GradusIQ_career.ai.contracts import FitOutput, fit_output_is_valid
from GradusIQ_career.ai.errors import AIConfigError, AIRequestError
from GradusIQ_career.ai.runtime import AIRuntime
from GradusIQ_career.ai.types import AIResponse
from GradusIQ_career.features.fit import FitRunner
from GradusIQ_career.student_intelligence_profile import StudentIntelligenceProfile
from GradusIQ_career import api


VALID_DATA = {
    "role_matches": [
        {
            "role": "Software Engineer Intern",
            "fit_level": "medium",
            "rationale": "Confirmed Python work supports a developing fit.",
            "supporting_signals": ["Python"],
            "missing_signals": ["Production experience"],
            "hiring_signal": {"coverage": "unavailable", "employers": [], "posting_count": None},
        }
    ],
    "overall_fit_summary": "A realistic developing fit.",
}


def canonical_profile():
    return StudentIntelligenceProfile.model_validate(
        {
            "identity": {"student_id": "student-1", "name": "Student"},
            "institution": {"name": "Texas A&M University", "relationship": "home"},
            "academics": {
                "summary": {"major_current": "Computer Science", "major_intended": "Computer Science"},
                "terms": [],
                "courses": [],
                "gpa": {},
                "repeat_exclusions": [],
            },
            "career": {
                "confirmed": True,
                "target_roles": ["Software Engineering Intern"],
                "interests": ["backend"],
                "skills": {"technical": ["Python"], "soft": []},
                "work_experience": [],
                "projects": [],
                "certifications": [],
            },
            "completeness": {
                "career": {
                    "confirmed_profile": True,
                    "target_role_present": True,
                    "skills_present": True,
                    "certifications_present": False,
                    "work_experience_present": False,
                    "projects_present": False,
                    "ready_for_career_features": True,
                },
                "academics": {
                    "transcript_data_present": False,
                    "terms_present": False,
                    "gpa_computable": False,
                    "ready_for_academic_features": False,
                },
                "overall": "partial",
            },
            "provenance": {"career_profile": "confirmed_manual"},
        }
    )


def agent_context():
    return AgentContext(
        feature="FIT",
        canonical_profile=canonical_profile(),
        model_role="career",
        prompt_name="fit",
        prompt_version="1.0",
        grounding=GroundingMetadata(source_types=("student_confirmed", "onet_static")),
    )


class QueueClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return AIResponse(
            text=outcome,
            raw={"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
            model="resolved/model",
        )


def valid_response(summary="done"):
    return json.dumps({"summary": summary, "data": VALID_DATA})


def invoke(client, **kwargs):
    return AIRuntime(client, sleep=kwargs.get("sleep", lambda _: None)).invoke(
        context=agent_context(),
        messages=[{"role": "user", "content": "original grounded request"}],
        output_model=FitOutput,
    )


def test_context_has_canonical_input_and_reusable_execution_metadata():
    context = agent_context()
    assert isinstance(context.canonical_profile, StudentIntelligenceProfile)
    assert context.feature == "FIT"
    assert context.model_role == "career"
    assert context.prompt_name == "fit"
    assert context.prompt_version == "1.0"
    assert context.request_id
    assert context.grounding.trust_level == "trusted_reference"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.pop("overall_fit_summary"),
        lambda data: data["role_matches"][0].pop("rationale"),
        lambda data: data["role_matches"][0].update(role=123),
        lambda data: data.update(role_matches=[]),
        lambda data: data["role_matches"][0].update(fit_level="strong"),
    ],
)
def test_fit_contract_rejects_missing_nested_typed_bounded_and_enum_errors(mutation):
    data = json.loads(json.dumps(VALID_DATA))
    mutation(data)
    with pytest.raises(ValidationError):
        FitOutput.model_validate(data)
    assert not fit_output_is_valid(data)


def test_fit_contract_accepts_real_shaped_payload():
    assert FitOutput.model_validate(VALID_DATA).overall_fit_summary
    assert fit_output_is_valid(VALID_DATA)


def test_transient_failures_retry_and_later_success_has_trace():
    delays = []
    client = QueueClient([
        AIRequestError("timeout", transient=True),
        AIRequestError("rate limited", transient=True),
        valid_response(),
    ])
    result = invoke(client, sleep=delays.append)
    assert result.output is not None
    assert len(client.calls) == 3
    assert delays == [0.25, 0.75]
    assert result.trace.attempt_count == 3
    assert result.trace.resolved_model == "resolved/model"
    assert result.trace.provider_usage == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }
    assert result.trace.latency_ms >= 0
    assert result.trace.validation_status == "success"


def test_transient_retry_budget_is_initial_plus_two():
    client = QueueClient([AIRequestError("busy", transient=True)] * 3)
    result = invoke(client)
    assert result.output is None
    assert len(client.calls) == 3
    assert result.trace.error_class == "transient_provider_error"


@pytest.mark.parametrize("error", [AIRequestError("bad request"), AIConfigError("bad config")])
def test_non_transient_failures_do_not_retry(error):
    client = QueueClient([error])
    result = invoke(client)
    assert result.output is None
    assert len(client.calls) == 1


def test_first_success_makes_one_call_and_captures_safe_trace():
    client = QueueClient([valid_response()])
    result = invoke(client)
    trace = result.trace.to_dict()
    assert len(client.calls) == 1
    assert trace["request_id"]
    assert trace["prompt_version"] == "1.0"
    assert trace["attempt_count"] == 1
    assert trace["repair_count"] == 0
    assert trace["final_status"] == "success"
    serialized = json.dumps(trace)
    assert "canonical_profile" not in serialized
    assert "original grounded request" not in serialized


@pytest.mark.parametrize(
    "first",
    ["{not-json", json.dumps({"data": {"role_matches": [], "overall_fit_summary": "x"}})],
)
def test_parse_or_validation_failure_gets_exactly_one_successful_repair(first):
    client = QueueClient([first, valid_response("repaired")])
    result = invoke(client)
    assert result.output is not None
    assert result.summary == "repaired"
    assert len(client.calls) == 2
    assert result.trace.repair_count == 1
    assert "Validation problems:" in client.calls[1]["messages"][-1]["content"]
    assert client.calls[1]["messages"][0]["content"] == "original grounded request"


def test_failed_repair_stops_after_second_model_response():
    client = QueueClient(["bad", "still bad"])
    result = invoke(client)
    assert result.output is None
    assert len(client.calls) == 2
    assert result.trace.repair_count == 1
    assert result.trace.error_class == "parse_error"


def test_fit_runner_builds_grounding_once_across_repair(monkeypatch):
    calls = {"market": 0, "signals": 0}

    def market(_roles):
        calls["market"] += 1
        return {"source": "onet_static", "by_role": {}}

    def signals(_roles):
        calls["signals"] += 1
        return {"source": "onet_static", "by_role": {}}

    monkeypatch.setattr("GradusIQ_career.features.fit.get_market_requirements", market)
    monkeypatch.setattr("GradusIQ_career.features.fit.get_shift_signals", signals)
    client = QueueClient(["bad", valid_response()])
    legacy = {
        "student": {"major_intended": "Computer Science", "major_current": "Computer Science"},
        "career": {
            "target_roles": ["Software Engineering Intern"],
            "interests": ["backend"],
            "skills_self_reported": {"technical": ["Python"]},
        },
    }
    runner = FitRunner(client=client, runtime_factory=lambda c: AIRuntime(c, sleep=lambda _: None))
    result = runner.run_canonical(canonical_profile(), legacy)
    assert result["status"] == "success"
    assert calls == {"market": 1, "signals": 1}
    assert runner.last_trace["prompt_version"] == "1.0"


def test_same_fit_contract_is_used_by_runner_and_cache_validator():
    runner = FitRunner(client=QueueClient([]))
    assert runner.validate_data(VALID_DATA, {}) == []
    assert fit_output_is_valid(VALID_DATA)
    malformed = {"role_matches": [{}], "overall_fit_summary": "x"}
    assert runner.validate_data(malformed, {})
    assert not fit_output_is_valid(malformed)


def test_valid_and_malformed_cached_fit_use_strict_contract():
    cached = {
        "feature": "FIT",
        "status": "success",
        "summary": "cached",
        "data": VALID_DATA,
        "errors": [],
    }
    assert api._valid_cached_feature_result("FIT", cached)
    malformed = json.loads(json.dumps(cached))
    malformed["data"]["role_matches"][0].pop("rationale")
    assert not api._valid_cached_feature_result("FIT", malformed)
