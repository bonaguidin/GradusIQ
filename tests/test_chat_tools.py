import json
from datetime import date

from GradusIQ_career.ai import chat_tools
from GradusIQ_career.ai.context import AgentContext, GroundingMetadata
from GradusIQ_career.ai.contracts import ChatOutput
from GradusIQ_career.ai.runtime import AIRuntime
from GradusIQ_career.ai.types import AIMessageResponse
from tests.test_ai_runtime_chat import canonical_profile


def _context():
    return AgentContext(
        feature="chat", canonical_profile=canonical_profile(), model_role="chat", prompt_name="chat",
        prompt_version="test", grounding=GroundingMetadata(source_types=("student_confirmed",)),
    )


def _tool_call(name, arguments, call_id="c1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


class ScriptedAI:
    """Returns the scripted messages in order and records what it was sent."""

    def __init__(self, *messages):
        self.script = list(messages)
        self.calls = []

    def complete_message_with_metadata(self, **kwargs):
        self.calls.append({"extra_body": kwargs.get("extra_body"), "messages": list(kwargs["messages"])})
        return AIMessageResponse(
            message=self.script.pop(0), model="fake-model", usage={"prompt_tokens": 10, "completion_tokens": 2}
        )


def _run(ai, run_tool, *, monotonic=None, rounds=chat_tools.MAX_TOOL_ROUNDS):
    runtime = AIRuntime(ai, monotonic=monotonic) if monotonic else AIRuntime(ai)
    return runtime.invoke_text(
        context=_context(),
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "q"}],
        output_model=ChatOutput,
        tools=chat_tools.TOOLS,
        run_tool=run_tool,
        max_tool_rounds=rounds,
    )


def test_tool_loop_runs_the_tool_then_answers():
    ai = ScriptedAI(
        {"role": "assistant", "content": None, "tool_calls": [_tool_call("search_courses", '{"query": "STAT"}')]},
        {"role": "assistant", "content": "STAT 2331 fits."},
    )
    seen = []

    result = _run(ai, lambda name, args: seen.append((name, args)) or '{"results": []}')

    assert result.output.content == "STAT 2331 fits."
    assert seen == [("search_courses", {"query": "STAT"})]
    assert result.tool_calls == ["search_courses"]
    assert ai.calls[0]["extra_body"]["tools"] == list(chat_tools.TOOLS)
    assert ai.calls[1]["messages"][-1] == {"role": "tool", "tool_call_id": "c1", "content": '{"results": []}'}
    # Usage from both calls is counted.
    assert result.trace.usage.input_tokens == 20


def test_tool_loop_withholds_tools_on_the_last_round():
    ask = {"role": "assistant", "content": "", "tool_calls": [_tool_call("get_degree_plan", "{}")]}
    ai = ScriptedAI(ask, ask, {"role": "assistant", "content": "Here is your plan."})

    result = _run(ai, lambda name, args: "{}")

    assert result.output.content == "Here is your plan."
    assert [bool(call["extra_body"]) for call in ai.calls] == [True, True, False]
    assert ai.calls[2]["messages"][-1]["content"].startswith("No more lookups")
    assert result.tool_calls == ["get_degree_plan", "get_degree_plan"]


def test_tool_loop_ignores_tool_calls_once_tools_are_withheld():
    ask = {"role": "assistant", "content": "Let me check.", "tool_calls": [_tool_call("get_degree_plan", "{}")]}
    ai = ScriptedAI(ask, ask)

    result = _run(ai, lambda name, args: "{}", rounds=1)

    # The final round offered no tools, so its text is the reply.
    assert result.output.content == "Let me check."
    assert len(ai.calls) == 2


def test_tool_loop_stops_offering_tools_after_the_time_budget():
    # Time jumps past the budget once the first lookup has run.
    ran = []

    def clock():
        return 50.0 if ran else 0.0

    ai = ScriptedAI(
        {"role": "assistant", "content": "", "tool_calls": [_tool_call("get_degree_plan", "{}")]},
        {"role": "assistant", "content": "Done."},
    )

    result = _run(ai, lambda name, args: ran.append(name) or "{}", monotonic=clock)

    assert result.output.content == "Done."
    assert ai.calls[1]["extra_body"] is None


def test_tool_loop_reports_bad_arguments_without_running_the_tool():
    ai = ScriptedAI(
        {"role": "assistant", "content": "", "tool_calls": [_tool_call("search_courses", "not json")]},
        {"role": "assistant", "content": "Sorry."},
    )

    result = _run(ai, lambda name, args: (_ for _ in ()).throw(AssertionError("must not run")))

    assert result.output.content == "Sorry."
    assert json.loads(ai.calls[1]["messages"][-1]["content"]) == {"error": "Arguments must be a JSON object."}
    assert result.tool_calls == []


def test_tool_loop_fails_cleanly_on_an_empty_answer():
    ai = ScriptedAI({"role": "assistant", "content": ""})

    result = _run(ai, lambda name, args: "{}")

    assert result.output is None
    assert result.trace.error_class == "parse_error"


def test_tool_names_and_labels_line_up():
    assert chat_tools.TOOL_NAMES == set(chat_tools.TOOL_LABELS)
    assert chat_tools.lookup_labels(["get_deadlines", "unknown", "get_deadlines", "search_jobs"]) == [
        "your Canvas calendar",
        "job postings",
    ]


def test_results_are_cut_to_size():
    text = chat_tools.to_result({"rows": ["x" * 100] * 200})
    assert len(text) < chat_tools.MAX_RESULT_CHARS + 50
    assert text.endswith('"(cut: result too long)"')


def test_compact_degree_plan_names_courses_and_requirements():
    plan = chat_tools.compact_degree_plan(
        terms=[{"term_key": "2027-Spring", "total_credit_hours": 6.0, "courses": [
            {"course_code": "CS 3353", "credit_hours": 3.0, "requirement_group_id": "g1"},
            {"course_code": "MATH 3304", "credit_hours": 3.0, "requirement_group_id": "g2"},
        ]}],
        unscheduled=[{"requirement_group_id": "g3", "name": "Free electives", "reason": "FREEFORM_MANUAL_REVIEW"}],
        choices=[{"requirement": "Science elective", "term": "2027-Fall"}],
        titles={"CS 3353": "Data Structures", "MATH 3304": None},
        requirement_names={"g1": "Core CS"},
    )
    assert plan == {
        "terms": [{"term": "2027-Spring", "credits": 6.0, "courses": [
            {"course": "CS 3353", "title": "Data Structures", "credits": 3.0, "requirement": "Core CS"},
            {"course": "MATH 3304", "credits": 3.0},
        ]}],
        "choices_to_make": [{"requirement": "Science elective", "term": "2027-Fall"}],
        "not_placed": [{"requirement": "Free electives", "reason": "FREEFORM_MANUAL_REVIEW"}],
    }


def test_compact_catalog_shows_credit_ranges():
    rows = [
        {"code": "CS 1340", "title": "Intro", "credit_min": 3, "credit_max": 3},
        {"code": "CS 4V98", "title": "Research", "credit_min": 1, "credit_max": 6},
        {"code": "CS 5000", "title": "No credits"},
    ]
    assert chat_tools.compact_catalog(rows) == [
        {"course": "CS 1340", "title": "Intro", "credits": 3},
        {"course": "CS 4V98", "title": "Research", "credits": "1-6"},
        {"course": "CS 5000", "title": "No credits"},
    ]


def test_deadlines_in_range_filters_sorts_and_caps():
    events = [
        {"title": "B", "kind": "assignment", "starts_at": "2026-12-09T15:00:00Z", "course_label": "CS 3353"},
        {"title": "A", "kind": "event", "starts_at": "2026-12-02", "all_day": True},
        {"title": "Out", "kind": "event", "starts_at": "2027-01-15"},
        {"title": "Broken", "kind": "event", "starts_at": "soon"},
    ]
    matched, truncated = chat_tools.deadlines_in_range(events, date(2026, 12, 1), date(2026, 12, 31))
    assert [e["title"] for e in matched] == ["A", "B"]
    assert matched[0]["all_day"] is True and matched[1]["course"] == "CS 3353"
    assert truncated is False

    many = [{"title": str(i), "kind": "event", "starts_at": "2026-12-05"} for i in range(60)]
    matched, truncated = chat_tools.deadlines_in_range(many, date(2026, 12, 1), date(2026, 12, 31))
    assert len(matched) == chat_tools.MAX_RANGE_DEADLINES and truncated is True


def test_compact_jobs_filters_by_location_and_keeps_only_https_links():
    postings = [
        {"title": "Data Intern", "employer": "Acme", "locations": ["Dallas, TX"], "posted_date": "2026-10-20",
         "url": "https://jobs.acme.com/1", "family": "Data Analyst"},
        {"title": "Analyst Intern", "employer": "Beta", "locations": ["Remote"], "url": "javascript:alert(1)"},
    ]
    assert chat_tools.compact_jobs(postings, "dallas") == [
        {"title": "Data Intern", "employer": "Acme", "locations": ["Dallas, TX"], "posted": "2026-10-20",
         "family": "Data Analyst", "url": "https://jobs.acme.com/1"},
    ]
    assert "url" not in chat_tools.compact_jobs(postings, "remote")[0]


def test_compact_course_grade_and_matching():
    cards = [
        {"id": "p1", "course_code": "CS 3353", "course_title": "Data Structures", "calculator_ready": True,
         "current_grade": 88.456, "current_letter_grade": "B+",
         "components": [{"name": "Exams", "weight_percent": 50, "effective_score": 85.0},
                        {"name": "Final", "weight_percent": 30, "effective_score": None}]},
        {"id": "p2", "course_code": "HIST 2311", "course_title": None, "calculator_ready": False},
    ]
    assert chat_tools.compact_course_grade(cards[0]) == {
        "course": "CS 3353", "title": "Data Structures", "current_grade": 88.5, "letter": "B+",
        "components": [{"name": "Exams", "weight_percent": 50, "score": 85.0},
                       {"name": "Final", "weight_percent": 30, "score": "not graded yet"}],
    }
    assert chat_tools.compact_course_grade(cards[1]) == {
        "course": "HIST 2311", "status": "grading model not confirmed yet"
    }
    assert chat_tools.match_course(cards, "cs  3353")["id"] == "p1"
    assert chat_tools.match_course(cards, "data structures")["id"] == "p1"
    assert chat_tools.match_course(cards, "HIST")["id"] == "p2"
    assert chat_tools.match_course(cards, "BIO 1401") is None


def test_compact_target_keeps_the_answer_and_notes():
    result = {"target_component": "Final", "target_grade": 80.0, "target_label": "B", "required_score": 72.345,
              "feasible": True, "already_achieved": False, "warnings": ["w1", "w2", "w3", "w4"]}
    assert chat_tools.compact_target(result) == {
        "component": "Final", "target": "B", "feasible": True, "required_score_percent": 72.3,
        "notes": ["w1", "w2", "w3"],
    }
