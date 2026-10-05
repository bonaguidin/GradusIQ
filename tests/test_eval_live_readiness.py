import subprocess

import pytest
from pydantic import ValidationError

from GradusIQ_career.evals.models import EvalFeature, EvalScenario, SyntheticStudentInput
from GradusIQ_career.evals.profiles import build_synthetic_canonical_profile
from GradusIQ_career.evals.runner import PHASE_B_FEATURES, run_scenarios, select_controlled_live_scenarios
from GradusIQ_career.evals.scenarios import SCENARIOS
from GradusIQ_career.features import gap as gap_module
from GradusIQ_career.features.gap import GapRunner


def by_id(scenario_id):
    return next(item for item in SCENARIOS if item.scenario_id == scenario_id)


def test_controlled_selection_is_three_per_feature_and_twelve_total():
    selected = select_controlled_live_scenarios(SCENARIOS)
    assert len(selected) == 12
    assert {
        feature: sum(feature in scenario.features for scenario in selected)
        for feature in PHASE_B_FEATURES
    } == {feature: 3 for feature in PHASE_B_FEATURES}
    assert all(scenario.live_eligible and scenario.purpose and scenario.expectations for scenario in selected)


def test_fit_inputs_are_distinct_and_match_evidence_purposes():
    strong = by_id("fit_strong_role_match").synthetic_input
    mismatch = by_id("fit_skill_mismatch").synthetic_input
    trap = by_id("fit_market_claim_trap").synthetic_input
    assert len({value.safe_fingerprint() for value in (strong, mismatch, trap)}) == 3
    assert strong.technical_skills and strong.experience and strong.projects
    assert mismatch.technical_skills == [] and mismatch.experience == []
    trap_blob = trap.model_dump_json().lower()
    assert all(term not in trap_blob for term in ("posting", "dfw", "google", "amazon"))


def test_gap_local_and_missing_evidence_inputs_are_real():
    local = by_id("gap_local_onet_role").synthetic_input
    mismatch = by_id("gap_skill_experience_mismatch").synthetic_input
    market = gap_module.get_market_requirements(local.target_roles)
    assert market["by_role"][local.target_roles[0]]["provenance"] in {"onet", "onet_neighbor"}
    assert mismatch.technical_skills == []
    assert mismatch.experience[0].role == "Retail Associate"


def test_gap_research_fallback_reaches_mocked_established_path(monkeypatch):
    # "Operations Intern" (13-1199.00) was this scenario's example of a role
    # O*NET has no ratings AND no related occupations for -- the scenario's
    # own label is "controlled role research fallback". A manual_override
    # related-occupation entry (Logisticians, 13-1081.00, build_onet.py's
    # MANUAL_RELATED_OVERRIDES) has since given it a rated neighbour too, so
    # a live run of this scenario today would no longer actually reach the
    # agent -- it borrows instead, same as Finance Intern. The market is
    # built explicitly here (provenance forced to "none") so this unit test
    # still exercises the fallback path on purpose, decoupled from which real
    # role the live catalog happens to leave uncovered. The scenario's
    # synthetic_input/purpose stand as realistic fixture data regardless.
    scenario = by_id("gap_research_fallback")
    calls = []
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: calls.append(role) or {
            "must_have_skills": ["Process improvement"],
            "nice_to_have_skills": [],
            "must_have_certifications": [],
            "nice_to_have_certifications": [],
        },
    )
    runner = GapRunner(client=object())
    market = {"by_role": {"Operations Intern": {"provenance": "none"}}}
    result = runner.role_requirements_for(scenario.synthetic_input.target_roles, market)
    assert market["by_role"]["Operations Intern"]["provenance"] == "none"
    assert calls == ["Operations Intern"]
    assert result["Operations Intern"]["requirements_source"] == "agent"


def test_shift_has_three_distinct_live_purposes_and_safe_market_trap():
    shifts = [item for item in SCENARIOS if item.live_eligible and EvalFeature.SHIFT in item.features]
    assert len(shifts) == 3
    assert len({item.purpose for item in shifts}) == 3
    assert len({item.synthetic_input.safe_fingerprint() for item in shifts}) == 3
    trap = by_id("shift_market_claim_trap")
    blob = trap.synthetic_input.model_dump_json().lower()
    assert all(term not in blob for term in ("posting", "dfw", "%", "employer"))


def test_chat_inputs_preserve_canonical_and_untrusted_boundaries():
    normal = by_id("chat_normal_profile").synthetic_input
    incomplete = by_id("chat_incomplete_profile").synthetic_input
    adversarial = by_id("chat_adversarial_history").synthetic_input
    assert build_synthetic_canonical_profile(normal).career.target_roles
    profile = build_synthetic_canonical_profile(incomplete)
    assert profile.career.confirmed is False and profile.career.target_roles == []
    assert [turn.role for turn in adversarial.chat_history] == ["user", "assistant"]
    assert "Ignore prior instructions" in adversarial.chat_history[0].content


def test_safe_fingerprint_is_deterministic_and_not_profile_text():
    value = by_id("fit_strong_role_match").synthetic_input
    fingerprint = value.safe_fingerprint()
    assert fingerprint == value.model_copy(deep=True).safe_fingerprint()
    assert len(fingerprint) == 16
    assert "Computer" not in fingerprint and "Python" not in fingerprint


def test_malformed_synthetic_input_is_rejected():
    with pytest.raises(ValidationError):
        SyntheticStudentInput.model_validate({"completed_courses": [{"course_code": "X", "title": "X", "credit_hours": -1}]})


def test_non_live_excluded_and_shortage_fails_before_executor():
    selected = select_controlled_live_scenarios(SCENARIOS)
    assert all(item.scenario_id != "student_prompt_injection" for item in selected)
    calls = []
    too_short = [item for item in SCENARIOS if item.scenario_id != "shift_skill_transition"]
    with pytest.raises(ValueError, match="shift scenarios"):
        select_controlled_live_scenarios(too_short)
    assert calls == []


def test_live_runner_excludes_non_live_scenario():
    calls = []
    result = run_scenarios(
        [by_id("student_prompt_injection")], live=True,
        live_executor=lambda scenario, feature: calls.append(scenario.scenario_id),
    )
    assert result == [] and calls == []


def test_generated_output_is_ignored_but_scenarios_are_trackable():
    ignored = subprocess.run(
        ["git", "check-ignore", "eval-results/live-baseline.json"],
        check=False, capture_output=True, text=True,
    )
    source = subprocess.run(
        ["git", "check-ignore", "GradusIQ_career/evals/scenarios.py"],
        check=False, capture_output=True, text=True,
    )
    assert ignored.returncode == 0
    assert source.returncode == 1


def test_scenario_input_contract_is_required():
    payload = by_id("fit_strong_role_match").model_dump()
    payload.pop("synthetic_input")
    with pytest.raises(ValidationError):
        EvalScenario.model_validate(payload)


def test_live_scenario_must_target_one_feature():
    payload = by_id("fit_strong_role_match").model_dump()
    payload["features"] = {EvalFeature.FIT, EvalFeature.GAP}
    with pytest.raises(ValidationError, match="exactly one feature"):
        EvalScenario.model_validate(payload)
