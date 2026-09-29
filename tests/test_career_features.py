from copy import deepcopy

import pytest

from GradusIQ_career.ai.types import AIResponse
from GradusIQ_career.features import gap as gap_module
from GradusIQ_career.features import run_career_feature
from GradusIQ_career.features.fit import FitRunner
from GradusIQ_career.features.gap import GapRunner
from GradusIQ_career.features.shift import ShiftRunner


class FakeClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return AIResponse(text=self.text, raw={"choices": []}, model="fake-model")


def sample_student():
    return {
        "student": {
            "id": 601,
            "name": "Jordan Reyes",
            "major_current": "Business Administration",
            "major_intended": "Finance",
            "classification": "Freshman",
            "expected_graduation": "2029-05",
        },
        "career": {
            "target_roles": ["Business Analyst Intern", "Operations Intern"],
            "interests": ["operations", "finance", "analytics"],
            "career_goals": "Explore business internships.",
            "geographic_preference": "DFW metro preferred",
            "ai_anxiety_level": "moderate",
            "skills_self_reported": {
                "technical": ["Excel", "PowerPoint"],
                "soft": ["communication", "team collaboration"],
                "ai_exposure": "informal AI study support",
            },
            "certifications": [],
            "work_experience": [
                {
                    "employer": "Mays Business School",
                    "role": "Case Team Member",
                    "duration": "Spring 2026",
                }
            ],
            "projects": [
                {
                    "name": "Market Brief",
                    "description": "Prepared customer and competitor analysis.",
                }
            ],
        },
        "courses": [
            {
                "course_code": "BUSN 101",
                "name": "Freshman Business Initiative",
            }
        ],
    }


def test_fit_success_with_mocked_ai_json():
    client = FakeClient(
        """
        {
          "summary": "You have two realistic role directions.",
          "data": {
            "role_matches": [
              {
                "role": "Business Analyst Intern",
                "fit_level": "medium",
                "rationale": "Excel and business coursework align.",
                "supporting_signals": ["Excel", "business case project"],
                "missing_signals": ["SQL"]
              }
            ],
            "overall_fit_summary": "Business analyst is a moderate fit."
          }
        }
        """
    )

    result = FitRunner(client=client).run(sample_student())

    assert result["feature"] == "FIT"
    assert result["status"] == "success"
    assert result["summary"] == "You have two realistic role directions."
    assert result["data"]["role_matches"][0]["role"] == "Business Analyst Intern"
    assert client.calls[0]["role"] == "career"
    assert "FIT Prompt" in client.calls[0]["messages"][1]["content"]


def test_gap_success_with_mocked_ai_json():
    client = FakeClient(
        """
        {
          "summary": "Your main readiness gap is analytics depth.",
          "data": {
            "readiness_score": 6,
            "strengths": ["Excel", "presentation"],
            "must_have_gaps": [{"gap":"SQL","why_it_matters":"Required for analysis.","how_to_close":"Build a SQL project."}],
            "nice_to_have_gaps": [{"gap":"dashboarding","why_it_helps":"Makes findings visible.","how_to_close":"Build a dashboard."}],
            "recommended_next_steps": ["Build a small SQL project"]
          }
        }
        """
    )

    result = GapRunner(client=client).run(sample_student())

    assert result["feature"] == "GAP"
    assert result["status"] == "success"
    assert result["data"]["readiness_score"] == 6
    assert client.calls[0]["role"] == "career"
    assert "GAP Prompt" in client.calls[0]["messages"][1]["content"]


_GAP_SUCCESS_JSON = """
{
  "summary": "Your main readiness gap is analytics depth.",
  "data": {
    "readiness_score": 6,
    "strengths": ["Excel", "presentation"],
    "must_have_gaps": [{"gap":"SQL","why_it_matters":"Required for analysis.","how_to_close":"Build a SQL project."}],
    "nice_to_have_gaps": [{"gap":"dashboarding","why_it_helps":"Makes findings visible.","how_to_close":"Build a dashboard."}],
    "recommended_next_steps": ["Build a small SQL project"]
  }
}
"""


def _live_agent_requirements():
    # soc_code/soc_title are deliberately implausible/unlike the static
    # entry -- their presence here proves they're discarded, not just
    # coincidentally matching.
    return {
        "soc_code": "13-1111.00-LIVE",
        "soc_title": "Live-Researched Management Analysts",
        "must_have_skills": ["Live-researched must-have skill"],
        "nice_to_have_skills": [],
        "must_have_certifications": [],
        "nice_to_have_certifications": [],
    }


def test_role_requirements_for_uses_agent_skills_but_static_soc_code(monkeypatch):
    # Operations Intern (13-1199.00) is the only demo role that reaches the
    # agent: no O*NET ratings AND no related occupations to borrow from.
    # Finance Intern used to qualify, but now borrows from a rated neighbour.
    agent_data = _live_agent_requirements()
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: agent_data if role == "Operations Intern" else None,
    )

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(["Operations Intern"])
    entry = result["Operations Intern"]

    # soc_code/soc_title always come from the static file, never the agent.
    assert entry["soc_code"] == "13-1199.00"
    assert entry["soc_title"] == "Business Operations Specialists, All Other"
    # must_have_skills comes from the agent (non-empty agent list wins).
    assert entry["must_have_skills"] == ["Live-researched must-have skill"]
    assert entry["requirements_source"] == "agent"


def test_role_requirements_for_agent_empty_list_does_not_clobber_populated_static_list(monkeypatch):
    # Operations Intern's static entry has a non-empty
    # nice_to_have_certifications; an agent result with an empty list for
    # that field must not blank it out.
    agent_data = dict(_live_agent_requirements(), nice_to_have_certifications=[])
    monkeypatch.setattr(gap_module.role_research_agent, "get_role_requirements", lambda role: agent_data)

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(["Operations Intern"])
    entry = result["Operations Intern"]

    assert entry["nice_to_have_certifications"] == ["Six Sigma Yellow Belt"]
    assert entry["must_have_skills"] == ["Live-researched must-have skill"]  # agent's non-empty list still wins
    assert entry["requirements_source"] == "agent"


def test_role_requirements_for_falls_back_to_static_when_agent_returns_none(monkeypatch):
    monkeypatch.setattr(gap_module.role_research_agent, "get_role_requirements", lambda role: None)

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(["Business Analyst Intern"])

    assert result["Business Analyst Intern"]["soc_code"] == "13-1111.00"
    assert "Excel modeling" in result["Business Analyst Intern"]["must_have_skills"]
    assert result["Business Analyst Intern"]["requirements_source"] == "static"


def test_gap_run_produces_identical_feature_result_shape_regardless_of_role_requirements_source(monkeypatch):
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: _live_agent_requirements() if role == "Business Analyst Intern" else None,
    )
    agent_result = GapRunner(client=FakeClient(_GAP_SUCCESS_JSON)).run(sample_student())

    monkeypatch.setattr(gap_module.role_research_agent, "get_role_requirements", lambda role: None)
    fallback_result = GapRunner(client=FakeClient(_GAP_SUCCESS_JSON)).run(sample_student())

    assert agent_result.keys() == fallback_result.keys()
    assert agent_result["status"] == fallback_result["status"] == "success"
    assert agent_result["data"] == fallback_result["data"]
    assert agent_result["summary"] == fallback_result["summary"]


def test_role_requirements_for_reports_unmatched_when_agent_and_static_both_miss(monkeypatch):
    monkeypatch.setattr(gap_module.role_research_agent, "get_role_requirements", lambda role: None)

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(["Quantum Widget Intern"])

    assert result == {"_unmatched_roles": ["Quantum Widget Intern"]}


def test_role_requirements_for_handles_mixed_agent_and_static_results_across_roles(monkeypatch):
    # Operations Intern reaches the agent and its research wins; Business
    # Analyst Intern has its own O*NET ratings so the agent never runs and it
    # keeps the static lists.
    agent_data = _live_agent_requirements()
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: agent_data if role == "Operations Intern" else None,
    )

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(
        ["Operations Intern", "Business Analyst Intern"]
    )

    assert result["Operations Intern"]["soc_code"] == "13-1199.00"
    assert result["Operations Intern"]["must_have_skills"] == ["Live-researched must-have skill"]
    assert result["Operations Intern"]["requirements_source"] == "agent"
    assert result["Business Analyst Intern"]["soc_code"] == "13-1111.00"
    assert result["Business Analyst Intern"]["requirements_source"] == "static"
    assert "_unmatched_roles" not in result


def test_agent_is_not_called_for_roles_onet_already_rates(monkeypatch):
    """The core of the gap-fill change: research is spent only where it is needed.

    The agent used to run for every role while the prompt forbade using its
    skill lists wherever O*NET data existed -- research paid for and discarded.
    """
    called: list[str] = []

    def _spy(role):
        called.append(role)
        return _live_agent_requirements()

    monkeypatch.setattr(gap_module.role_research_agent, "get_role_requirements", _spy)

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(
        ["Business Analyst Intern", "Finance Intern", "Operations Intern"]
    )

    # 13-1111.00 has its own ratings -> skipped. 13-2051.00 borrows from a rated
    # neighbour -> also skipped. Only 13-1199.00, with neither, is researched.
    assert called == ["Operations Intern"]
    assert result["Business Analyst Intern"]["requirements_source"] == "static"
    # Borrowed, so the agent never ran for it and the static lists stand.
    assert result["Finance Intern"]["requirements_source"] == "static"
    assert result["Operations Intern"]["requirements_source"] == "agent"


def test_gap_context_marks_agent_filled_roles_with_agent_provenance(monkeypatch):
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: _live_agent_requirements() if role == "Operations Intern" else None,
    )
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern", "Finance Intern", "Operations Intern"]

    context = GapRunner(client=FakeClient("{}")).build_student_context(student)
    by_role = context["market_requirements"]["by_role"]

    assert by_role["Business Analyst Intern"]["provenance"] == "onet"
    # Borrowed from a rated neighbour rather than researched: 13-2051.00 has no
    # O*NET ratings of its own but 13-2052.00 is in its related list, and
    # neighbour borrowing is decided in market_data before the agent is
    # consulted. Was "agent" before that change landed.
    assert by_role["Finance Intern"]["provenance"] == "onet_neighbor"
    # Upgraded from "none" because the agent supplied this role's requirements.
    # Operations Intern carries that case now: Finance Intern borrows from a
    # rated neighbour, so it never reaches the agent at all.
    assert by_role["Operations Intern"]["provenance"] == "agent"


def test_shift_success_with_mocked_ai_json():
    client = FakeClient(
        """
        {
          "summary": "Your target roles are shifting toward AI-assisted analysis.",
          "data": {
            "role_evolution_summary": "Business roles increasingly expect AI-assisted analysis.",
            "task_shifts": [{"task":"first-pass spreadsheet analysis","changing":"AI drafts it.","meaning":"Review matters more."}],
            "durable_skills": [{"task":"judgment","reason":"Context remains human."}],
            "adjacent_paths": [{"path":"operations analytics","relevance":"Uses current skills.","driver":"More automation."}],
            "ai_fluency_guidance": ["Describe how you use AI to check assumptions"]
          }
        }
        """
    )

    result = ShiftRunner(client=client).run(sample_student())

    assert result["feature"] == "SHIFT"
    assert result["status"] == "success"
    assert result["data"]["durable_skills"][0]["task"] == "judgment"
    assert client.calls[0]["role"] == "career"
    assert "SHIFT Prompt" in client.calls[0]["messages"][1]["content"]


def test_shift_runs_without_ai_anxiety_level():
    """The field calibrates SHIFT's tone; it is not one of its inputs.

    It was a required_path, so a student who had never answered that question
    got no trend guidance at all -- the analysis withheld to punish an
    incomplete profile. It is now optional, and its absence must reach the
    model as an absent key rather than as an empty string the model would feel
    obliged to characterize.
    """
    student = sample_student()
    student["career"].pop("ai_anxiety_level")
    client = FakeClient('{"summary":"ok","data":{"role_evolution_summary":"ok","task_shifts":[],"durable_skills":[],"adjacent_paths":[],"ai_fluency_guidance":[]}}')

    result = ShiftRunner(client=client).run(student)

    assert result["status"] == "success"
    assert result["missing_fields"] == []
    assert len(client.calls) == 1

    context = ShiftRunner(client=FakeClient("{}")).build_student_context(student)
    assert "ai_anxiety_level" not in context
    # Everything SHIFT actually reasons over is still there.
    assert context["target_roles"] == student["career"]["target_roles"]
    assert context["skills_self_reported"]


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_shift_omits_a_blank_ai_anxiety_level(blank):
    """Present-but-empty is the same as absent, not a level of its own."""
    student = sample_student()
    student["career"]["ai_anxiety_level"] = blank

    context = ShiftRunner(client=FakeClient("{}")).build_student_context(student)

    assert "ai_anxiety_level" not in context


def test_shift_sends_a_reported_ai_anxiety_level():
    student = sample_student()
    student["career"]["ai_anxiety_level"] = "moderate"

    context = ShiftRunner(client=FakeClient("{}")).build_student_context(student)

    assert context["ai_anxiety_level"] == "moderate"


@pytest.mark.parametrize(
    ("runner_class", "feature", "remove_path"),
    [
        (FitRunner, "FIT", ("career", "target_roles")),
        (GapRunner, "GAP", ("student", "expected_graduation")),
        (ShiftRunner, "SHIFT", ("career", "skills_self_reported")),
    ],
)
def test_runner_skips_when_required_fields_are_missing(runner_class, feature, remove_path):
    student = sample_student()
    parent = student[remove_path[0]]
    parent.pop(remove_path[1])
    client = FakeClient('{"data": {}}')

    result = runner_class(client=client).run(student)

    assert result["feature"] == feature
    assert result["status"] == "skipped"
    assert result["summary"] == "Missing required fields for this feature."
    assert result["errors"]
    assert client.calls == []


# ------------------------------------------------------------- field labels
# What a student reads when an analysis will not run. These assertions are the
# reason FIELD_LABELS exists in one place: GAP, FIT, SHIFT and
# PROFESSOR_COMMENTS all skip through the same gate, so a label is either right
# for all of them or wrong for all of them.


def test_every_gated_path_has_a_human_label():
    """No runner can gate on a path the student would see raw.

    Collected from the runners rather than listed by hand, so adding a
    required_path without a label fails here instead of surfacing as
    "career.ai_anxiety_level" in the UI.
    """
    from GradusIQ_career.features.academic import AcademicRunner
    from GradusIQ_career.features.base import FIELD_LABELS

    gated = {
        path
        for runner in (GapRunner, FitRunner, ShiftRunner, AcademicRunner)
        for path in runner.required_paths
    }

    assert gated <= set(FIELD_LABELS), f"unlabelled gated paths: {gated - set(FIELD_LABELS)}"


# ---------------------------------------------------- unsupported target role
# FIT has no research-agent fallback (unlike GAP/SHIFT below), so an unmatched
# role used to go straight into the prompt and produce a confident-looking
# judgement from pure model recall. additional_missing_fields() catches it
# before any provider call, the same way a genuinely empty target_roles list
# already does.


def test_fit_skips_when_every_target_role_is_unsupported():
    student = sample_student()
    student["career"]["target_roles"] = ["Software Engineer"]  # not in role_requirements.json
    client = FakeClient('{"data": {}}')

    result = FitRunner(client=client).run(student)

    assert result["status"] == "skipped"
    assert {"path": "career.target_roles", "label": "Target roles"} in result["missing_fields"]
    assert client.calls == []


_FIT_SUCCESS_JSON = """
{
  "summary": "You have two realistic role directions.",
  "data": {
    "role_matches": [
      {
        "role": "Business Analyst Intern",
        "fit_level": "medium",
        "rationale": "Excel and business coursework align.",
        "supporting_signals": ["Excel", "business case project"],
        "missing_signals": ["SQL"]
      }
    ],
    "overall_fit_summary": "Business analyst is a moderate fit."
  }
}
"""


def test_fit_runs_when_at_least_one_target_role_is_supported():
    student = sample_student()
    # One curated role alongside one that is not -- FIT should not block on
    # the mix; only "every role unsupported" is the gated condition.
    student["career"]["target_roles"] = ["Software Engineer", "Business Analyst Intern"]
    client = FakeClient(_FIT_SUCCESS_JSON)

    result = FitRunner(client=client).run(student)

    assert result["status"] == "success"
    assert len(client.calls) == 1


def test_fit_still_runs_normally_for_fully_supported_target_roles():
    """Existing supported-role behavior is unchanged by the new gate."""
    result = FitRunner(client=FakeClient(_FIT_SUCCESS_JSON)).run(sample_student())

    assert result["status"] == "success"


# GAP and SHIFT are deliberately NOT gated the same way: both already have a
# working fallback for an unmatched role (role_research_agent, exercised
# elsewhere in this file), so a hard skip here would remove real, tested
# functionality rather than fix a silent-failure mode. These two tests lock in
# that current behavior is unchanged by this task's FIT/Course-Discovery gate.
def test_gap_does_not_skip_for_an_unsupported_target_role(monkeypatch):
    student = sample_student()
    student["career"]["target_roles"] = ["Software Engineer"]
    monkeypatch.setattr(gap_module.role_research_agent, "get_role_requirements", lambda role: None)
    client = FakeClient(_GAP_SUCCESS_JSON)

    result = GapRunner(client=client).run(student)

    assert result["status"] != "skipped"


def test_shift_does_not_skip_for_an_unsupported_target_role():
    student = sample_student()
    student["career"]["target_roles"] = ["Software Engineer"]
    client = FakeClient('{"data": {"role_evolution_summary": "", "task_shifts": [], "durable_skills": [], "adjacent_paths": [], "ai_fluency_guidance": []}}')

    result = ShiftRunner(client=client).run(student)

    assert result["status"] != "skipped"


def test_skipped_result_reports_label_and_path_together():
    student = sample_student()
    student["career"].pop("target_roles")

    result = FitRunner(client=FakeClient('{"data": {}}')).run(student)

    assert {"path": "career.target_roles", "label": "Target roles"} in result["missing_fields"]
    assert "Missing required field: Target roles" in result["errors"]
    # The dotted path never reaches the message the student reads.
    assert not any("career.target_roles" in message for message in result["errors"])


def test_field_label_falls_back_to_a_readable_form():
    """An unlabelled path degrades to generic, never to a dotted path."""
    from GradusIQ_career.features.base import field_label

    assert field_label("career.ai_anxiety_level") == "AI comfort level"
    assert field_label("career.some_new_field") == "Some new field"
    assert field_label("submissions[].future_thing") == "Future thing"


def test_malformed_ai_json_returns_failed_result():
    client = FakeClient("{not-json")

    result = FitRunner(client=client).run(sample_student())

    assert result["feature"] == "FIT"
    assert result["status"] == "failed"
    assert result["data"] == {}
    assert "JSON" in result["errors"][0] or "object" in result["errors"][0]


def test_missing_prompt_file_is_handled_clearly(tmp_path):
    missing_prompt = tmp_path / "missing_prompt.md"
    client = FakeClient('{"data": {}}')

    result = FitRunner(client=client, prompt_path=missing_prompt).run(sample_student())

    assert result["feature"] == "FIT"
    assert result["status"] == "failed"
    assert "Prompt file not found" in result["errors"][0]
    assert client.calls == []


@pytest.mark.parametrize(
    ("feature_name", "expected_runner"),
    [
        ("FIT", "FIT"),
        ("gap", "GAP"),
        ("Shift", "SHIFT"),
    ],
)
def test_run_career_feature_helper(feature_name, expected_runner):
    payload = '{"summary": "done", "data": {}}'
    if expected_runner == "FIT":
        payload = '''{"summary":"done","data":{"role_matches":[{"role":"Business Analyst Intern","fit_level":"medium","rationale":"Relevant foundation.","supporting_signals":[],"missing_signals":[]}],"overall_fit_summary":"A developing fit."}}'''
    elif expected_runner == "GAP":
        payload = _GAP_SUCCESS_JSON
    elif expected_runner == "SHIFT":
        payload = '''{"summary":"done","data":{"role_evolution_summary":"Roles are changing.","task_shifts":[],"durable_skills":[],"adjacent_paths":[],"ai_fluency_guidance":[]}}'''
    client = FakeClient(payload)

    result = run_career_feature(feature_name, sample_student(), client)

    assert result["feature"] == expected_runner
    assert result["status"] == "success"
    assert client.calls[0]["role"] == "career"


def test_run_career_feature_rejects_invalid_feature():
    with pytest.raises(ValueError, match="Unsupported career feature"):
        run_career_feature("ACADEMIC", sample_student(), FakeClient('{"data": {}}'))


def test_test_student_factory_is_isolated_between_tests():
    first = sample_student()
    second = deepcopy(first)

    first["career"]["target_roles"].append("Changed")

    assert second["career"]["target_roles"] == ["Business Analyst Intern", "Operations Intern"]


# ---------------------------------------------------------------- SHIFT grounding
# SHIFT used to send the model nothing but student self-report, so every
# role-specific claim was recall. These cover the two blocks that replaced that.

def test_shift_signals_ground_adjacent_paths_tools_and_tasks():
    from GradusIQ_career.features.market_data import get_shift_signals

    signals = get_shift_signals(["Business Analyst Intern"])
    entry = signals["by_role"]["Business Analyst Intern"]

    assert entry["soc_code"] == "13-1111.00"
    assert entry["grounded"] is True
    # Five Primary-Short related occupations, each with a resolved title --
    # this is what adjacent_paths must be drawn from instead of invented.
    assert len(entry["related"]) == 5
    assert all(r["soc"] and r["title"] for r in entry["related"])
    assert entry["hot_software"]
    assert entry["core_tasks"]


def test_shift_signals_survive_an_occupation_with_no_ratings():
    """Finance Intern has no O*NET importance scores but does have tools.

    SHIFT consumes tools/tasks/neighbours, not ratings, so it stays grounded
    for a role GAP has to fall back to the research agent for.
    """
    from GradusIQ_career.features.market_data import get_shift_signals

    entry = get_shift_signals(["Finance Intern"])["by_role"]["Finance Intern"]

    assert entry["soc_code"] == "13-2051.00"
    assert entry["hot_software"]
    assert entry["grounded"] is True


def test_shift_context_carries_both_grounding_blocks(monkeypatch):
    from GradusIQ_career.features import shift as shift_module

    trends = {
        "role_evolution": "Shifting toward validating model output.",
        "task_shifts": ["Routine variance analysis is increasingly automated"],
        "emerging_skills": ["Prompt-assisted modeling"],
        "sources": ["https://example.org/report"],
    }
    monkeypatch.setattr(
        shift_module.role_research_agent,
        "get_role_trends",
        lambda role, client=None: trends if role == "Business Analyst Intern" else None,
    )
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern", "Operations Intern"]

    context = ShiftRunner(client=FakeClient("{}")).build_student_context(student)

    assert context["shift_signals"]["by_role"]["Business Analyst Intern"]["grounded"] is True
    assert context["role_trends"]["Business Analyst Intern"] == trends
    # A role research missed is named, not silently absent -- the prompt keys
    # off this to stay generic instead of improvising a trend.
    assert context["role_trends"]["_unresearched_roles"] == ["Operations Intern"]


def test_shift_reports_every_role_when_trend_research_is_unavailable(monkeypatch):
    from GradusIQ_career.features import shift as shift_module

    monkeypatch.setattr(
        shift_module.role_research_agent, "get_role_trends", lambda role, client=None: None
    )
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern"]

    context = ShiftRunner(client=FakeClient("{}")).build_student_context(student)

    assert context["role_trends"] == {"_unresearched_roles": ["Business Analyst Intern"]}
    # Local O*NET grounding is unaffected by the research outage.
    assert context["shift_signals"]["by_role"]["Business Analyst Intern"]["related"]


# ------------------------------------------------------- neighbour borrowing
# O*NET has never rated 122 of its 1,016 occupations. 29 of those have a rated
# occupation in their Primary-Short related list, so borrowing beats live web
# research there: instant, free, and traceable to a named occupation. The
# condition is disclosure -- these are a NEIGHBOUR's scores.
#
# Ported by hand from aab5927, whose own hunk could not be applied: its patch
# context was interleaved with 8d46afe's readiness-score tests and a5b5ae0's
# SHIFT concurrency additions, neither of which lands in this pass.
#
# The agent-skip test at the end of this block was held back from the FIT
# remap because it asserts GapRunner.role_requirements_for behaviour, and
# gap.py was not touched there. gap.py has since landed, so it is here.


def test_unrated_role_borrows_from_its_nearest_rated_neighbour():
    from GradusIQ_career.features.market_data import get_market_requirements

    entry = get_market_requirements(["Finance Intern"])["by_role"]["Finance Intern"]

    assert entry["provenance"] == "onet_neighbor"
    assert entry["borrowed_from"]["soc"] == "13-2052.00"
    assert entry["requirements"]["skills"], "borrowed ratings should be populated"
    assert entry["matched"] is True


def test_borrowing_keeps_the_targets_own_software_not_the_neighbours():
    """Only ratings are borrowed.

    Finance Intern has 33 hot technologies of its own despite having no
    ratings; swapping the whole entry would discard real data for a
    neighbour's.
    """
    from GradusIQ_career.features.market_data import get_market_requirements

    finance = get_market_requirements(["Finance Intern"])["by_role"]["Finance Intern"]

    assert finance["soc_code"] == "13-2051.00"  # still the target's own SOC
    assert finance["hot_software"]
    assert finance["soc_title"] == "Financial and Investment Analysts"


def test_borrowing_is_disclosed_in_notes():
    from GradusIQ_career.features.market_data import get_market_requirements

    notes = " ".join(get_market_requirements(["Finance Intern"])["notes"])

    assert "borrowed" in notes.lower()
    assert "13-2052.00" in notes
    assert "disclosed" in notes.lower()


def test_role_with_no_rated_neighbour_still_falls_through_to_research():
    from GradusIQ_career.features.market_data import get_market_requirements

    entry = get_market_requirements(["Operations Intern"])["by_role"]["Operations Intern"]

    # 13-1199.00 has no related occupations at all in the release.
    assert entry["provenance"] == "none"
    assert entry["borrowed_from"] is None


def test_agent_is_not_called_for_a_role_that_borrowed_from_a_neighbour(monkeypatch):
    """Borrowing must pre-empt research, not run alongside it."""
    called: list[str] = []
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: called.append(role) or None,
    )

    GapRunner(client=FakeClient("{}")).role_requirements_for(
        ["Finance Intern", "Operations Intern"]
    )

    assert called == ["Operations Intern"]


# ---------------------------------------------------- readiness-score guard
# Ported alongside gap.py's guard. The hook these exercise is
# base.CareerFeatureRunner.validate_data, whose signature is
# (data, student_profile) -> list[str]; GapRunner's override ignores the
# profile, academic.py's does not.


@pytest.mark.parametrize("score", ["0.32", "11", "-1", "7.5", '"8"', "true"])
def test_gap_rejects_out_of_scale_readiness_score(score):
    # A live run returned readiness_score 0.32 for a student whose roles mostly
    # lacked O*NET data. It passed every check that existed, because
    # api.py's _matches_contract only asks whether the value is a number.
    client = FakeClient('{"summary":"s","data":{"readiness_score":' + score + ',"strengths":[],"must_have_gaps":[],"nice_to_have_gaps":[],"recommended_next_steps":[]}}')

    result = GapRunner(client=client).run(sample_student())

    assert result["status"] == "failed"
    assert "readiness_score" in result["errors"][0]


@pytest.mark.parametrize("score", ["0", "7", "10"])
def test_gap_accepts_whole_numbers_on_the_zero_to_ten_scale(score):
    client = FakeClient('{"summary":"s","data":{"readiness_score":' + score + ',"strengths":[],"must_have_gaps":[],"nice_to_have_gaps":[],"recommended_next_steps":[]}}')

    assert GapRunner(client=client).run(sample_student())["status"] == "success"


def test_gap_rejects_a_missing_readiness_score_under_strict_contract():
    client = FakeClient('{"summary":"s","data":{"strengths":[],"must_have_gaps":[],"nice_to_have_gaps":[],"recommended_next_steps":[]}}')
    result = GapRunner(client=client).run(sample_student())
    assert result["status"] == "failed"
    assert "readiness_score" in result["errors"][0]


# ----------------------------------------------------------- FIT grounding
# FIT used to build its context from the student profile alone, so every fit
# judgement was the model's own recall presented as analysis -- and its prompt
# asked for a "DFW market signal" it was never given, so it invented employers.
# These assert the market data is actually in the context, which is the whole
# of the fix: the prompt can only cite what the runner hands it.


def test_fit_context_carries_market_requirements_and_role_context():
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern", "Finance Intern"]

    context = FitRunner(client=FakeClient("{}")).build_student_context(student)

    # Both providers, keyed per role. Without these the model has no market
    # facts at all and the prompt's citation rules have nothing to bind to.
    assert "market_requirements" in context, "FIT context must carry market data"
    assert "role_context" in context, "FIT context must carry occupation tasks"
    assert set(context["market_requirements"]["by_role"]) == {
        "Business Analyst Intern",
        "Finance Intern",
    }
    assert set(context["role_context"]["by_role"]) == {
        "Business Analyst Intern",
        "Finance Intern",
    }


def test_fit_context_carries_provenance_for_a_resolved_soc_role():
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern", "Finance Intern"]

    by_role = FitRunner(client=FakeClient("{}")).build_student_context(student)[
        "market_requirements"
    ]["by_role"]

    # 13-1111.00 is rated directly by O*NET.
    assert by_role["Business Analyst Intern"]["provenance"] == "onet"
    assert by_role["Business Analyst Intern"]["requirements"]["skills"]

    # 13-2051.00 is not, and borrows from 13-2052.00. FIT inherits the same
    # four provenance values GAP uses, so the prompt can disclose the borrowing
    # rather than presenting a neighbour's scores as this role's own.
    assert by_role["Finance Intern"]["provenance"] == "onet_neighbor"
    assert by_role["Finance Intern"]["borrowed_from"]["title"] == "Personal Financial Advisors"


def test_fit_context_carries_core_tasks_for_interest_matching():
    """core_tasks is the signal FIT matches interests against.

    A role title alone invites the model to reason from the name; the
    occupation's actual day-to-day work is what makes "does this student's
    interest genuinely match" answerable from data.
    """
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern"]

    entry = FitRunner(client=FakeClient("{}")).build_student_context(student)[
        "role_context"
    ]["by_role"]["Business Analyst Intern"]

    assert entry["core_tasks"], "core_tasks must be populated for a rated role"
    assert entry["soc_code"] == "13-1111.00"


def test_fit_runner_does_not_invoke_the_research_agent(monkeypatch):
    """FIT is a single call by design; matching does not justify a tool loop.

    NOT a regression check on the grounding change -- this passes against the
    pre-grounding runner too, which called nothing at all. It guards the
    decision going forward: the obvious way to "improve" FIT is to give it
    GAP's research agent, which would turn a ~30s call into a tool loop and
    contradict the prompt's claim that its two context blocks "are the only
    market facts you have".
    """
    called: list[str] = []
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: called.append(role) or None,
    )
    student = sample_student()
    student["career"]["target_roles"] = ["Finance Intern", "Operations Intern"]

    FitRunner(client=FakeClient("{}")).build_student_context(student)

    assert called == []


# --------------------------------------------------------- FIT posting data
# role_postings is its own context key, deliberately separate from
# market_requirements/role_context: postings are live and role-scoped, can be
# absent (no_market_data) or entirely unfetchable (status: "unavailable"),
# and the prompt has to tell those two apart.


class _FakePostingResponse:
    def __init__(self, data):
        self.data = data


class _FakePostingQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, columns):
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def neq(self, column, value):
        self.filters.append(("neq", column, value))
        return self

    def execute(self):
        data = [
            dict(row)
            for row in self.rows
            if all(
                (row.get(column) == value if op == "eq" else row.get(column) != value)
                for op, column, value in self.filters
            )
        ]
        return _FakePostingResponse(data)


class _FakePostingClient:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        return _FakePostingQuery(self.rows)


def _posting_row(role, **overrides):
    row = {
        "id": "p1",
        "posting_identity": "cluster-1",
        "company": "Acme",
        "title": "Intern",
        "location": "Dallas, TX",
        "url": "https://example.test/p1",
        "posted_date": "2026-09-10",
        "fetched_at": "2026-09-12T10:00:00+00:00",
        "source": "adzuna",
        "target_role": role,
        "is_dfw": True,
        "raw_payload": {"description": "desc"},
    }
    row.update(overrides)
    return row


def test_fit_context_carries_role_postings_when_provider_returns_data():
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern"]
    client = _FakePostingClient([_posting_row("Business Analyst Intern")])

    context = FitRunner(
        client=FakeClient("{}"), posting_client_factory=lambda: client
    ).build_student_context(student)

    role = context["role_postings"]["by_role"]["Business Analyst Intern"]
    assert role["coverage"] == "available"
    assert role["postings"][0]["posting_id"] == "p1"


def test_fit_context_degrades_safely_when_posting_provider_raises():
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern"]

    def _boom():
        raise RuntimeError("supabase unreachable")

    # build_student_context must not raise even though the posting provider does --
    # that's the whole point of the try/except boundary in _get_role_postings.
    context = FitRunner(
        client=FakeClient("{}"), posting_client_factory=_boom
    ).build_student_context(student)

    assert context["role_postings"] == {
        "status": "unavailable",
        "reason": "supabase unreachable",
    }
    # Distinguishable from a completed query that found nothing.
    assert "by_role" not in context["role_postings"]


def test_fit_context_role_with_no_market_data_reaches_the_prompt_intact():
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern"]
    client = _FakePostingClient([])  # no rows for any role

    context = FitRunner(
        client=FakeClient("{}"), posting_client_factory=lambda: client
    ).build_student_context(student)

    role = context["role_postings"]["by_role"]["Business Analyst Intern"]
    assert role["coverage"] == "no_market_data"
    assert role["no_market_data"] is True
    assert role["postings"] == []


# ------------------------------------------------------- O*NET catalog cache
# data/reference/onet_soc_requirements.json is 5.5MB, and every provider entry
# point reads it. These pin that it is parsed once per process rather than once
# per call, and that a failed read is not cached as an empty catalog.


def _reset_onet_cache():
    from GradusIQ_career.features import market_data

    market_data._onet_cache = None


def test_onet_catalog_is_parsed_once_across_many_provider_calls(monkeypatch):
    from GradusIQ_career.features import market_data

    _reset_onet_cache()
    parses = {"n": 0}
    real_path = market_data._DATA_PATH

    class _CountingPath:
        """Proxies the real Path, counting opens. Path forbids setattr."""

        def open(self, *args, **kwargs):
            parses["n"] += 1
            return real_path.open(*args, **kwargs)

    monkeypatch.setattr(market_data, "_DATA_PATH", _CountingPath())

    for _ in range(3):
        market_data.get_market_requirements(["Business Analyst Intern", "Finance Intern"])
        market_data.get_shift_signals(["Business Analyst Intern"])

    # Six provider calls, one parse. Before memoization this was six.
    assert parses["n"] == 1, f"expected a single parse, got {parses['n']}"
    _reset_onet_cache()


def test_onet_cache_returns_the_same_data_it_did_uncached():
    """Memoization must be a pure no-op on the returned value."""
    from GradusIQ_career.features import market_data

    _reset_onet_cache()
    first = market_data.get_market_requirements(["Business Analyst Intern", "Finance Intern"])
    second = market_data.get_market_requirements(["Business Analyst Intern", "Finance Intern"])

    assert first == second
    assert first["by_role"]["Business Analyst Intern"]["provenance"] == "onet"
    assert first["by_role"]["Finance Intern"]["provenance"] == "onet_neighbor"
    _reset_onet_cache()


def test_a_failed_onet_read_is_not_cached(monkeypatch, tmp_path):
    """A transient read failure must not pin an empty catalog for the process.

    Caching {} would silently degrade every role to provenance "none" until
    restart, with nothing to indicate why.
    """
    from GradusIQ_career.features import market_data

    _reset_onet_cache()
    missing = tmp_path / "not-there.json"
    monkeypatch.setattr(market_data, "_DATA_PATH", missing)

    assert market_data._load_onet() == {}
    assert market_data._onet_cache is None, "a failed load must not populate the cache"

    monkeypatch.undo()
    _reset_onet_cache()
    assert market_data._load_onet(), "the real catalog still loads afterwards"
    _reset_onet_cache()


# --------------------------------------------- target-role support boundary
# is_role_supported()/supported_target_roles() are the one shared place that
# answers "does the curated vocabulary recognize this exact role string" --
# the same exact-match lookup resolve_soc() already enforces, just exposed as
# a plain bool/list for callers (Course Discovery's skip check, FIT's
# additional_missing_fields, the /career-role-options endpoint) that don't
# need the SOC code itself.


def test_is_role_supported_true_for_a_curated_role():
    from GradusIQ_career.features.market_data import is_role_supported

    assert is_role_supported("Software Engineering Intern") is True


def test_is_role_supported_false_for_a_realistic_unsupported_role():
    from GradusIQ_career.features.market_data import is_role_supported

    assert is_role_supported("Software Engineer") is False


def test_is_role_supported_does_no_fuzzy_or_case_normalization():
    """Exact match only -- a same-looking title in different casing must not
    resolve. resolve_soc() already documents this; this pins the boolean
    wrapper inherits the same exact-match behavior rather than adding its
    own normalization on top."""
    from GradusIQ_career.features.market_data import is_role_supported

    assert is_role_supported("software engineering intern") is False
    assert is_role_supported(" Software Engineering Intern") is False
    assert is_role_supported("Software Engineering Interns") is False


def test_supported_target_roles_returns_the_curated_fourteen_sorted():
    from GradusIQ_career.features.market_data import supported_target_roles

    roles = supported_target_roles()

    assert len(roles) == 14
    assert roles == sorted(roles)
    assert "_notes" not in roles
    assert "Software Engineering Intern" in roles
    assert "Business Analyst Intern" in roles
    # Not a supported role -- the exact case this task exists to catch.
    assert "Software Engineer" not in roles
