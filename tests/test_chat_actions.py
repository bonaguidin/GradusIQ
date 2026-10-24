import re
from pathlib import Path

from GradusIQ_career import api
from GradusIQ_career.ai import chat_actions

ALL = chat_actions.ACCOUNT_ACTIONS


def test_trailing_actions_line_is_stripped_and_kept():
    reply, actions = chat_actions.split_actions(
        "Your GPA is **3.42**.\n\nACTIONS: gpa-calculator, transcript", ALL
    )
    assert reply == "Your GPA is **3.42**."
    assert actions == ["gpa-calculator", "transcript"]


def test_wrapped_and_lowercase_variants_parse():
    for line in ("**Actions:** gpa-calculator", "`ACTIONS: gpa-calculator`", "[actions - gpa-calculator]"):
        reply, actions = chat_actions.split_actions(f"Done.\n{line}", ALL)
        assert (reply, actions) == ("Done.", ["gpa-calculator"]), line


def test_unknown_duplicate_and_extra_ids_are_dropped():
    _, actions = chat_actions.split_actions(
        "Hi\nACTIONS: https://evil.example, gpa-calculator, gpa-calculator, delete-account, "
        "job-search, resume, transcript",
        ALL,
    )
    assert actions == ["gpa-calculator", "job-search", "resume"]


def test_demo_cannot_get_account_only_pages():
    _, actions = chat_actions.split_actions("Hi\nACTIONS: transcript, canvas-calendar, job-search", chat_actions.DEMO_ACTIONS)
    assert actions == ["job-search"]


def test_reply_without_line_is_unchanged():
    text = "Some actions: are worth it.\nKeep going."
    assert chat_actions.split_actions(text, ALL) == (text, [])


def test_reply_that_is_only_the_line_still_has_text():
    reply, actions = chat_actions.split_actions("ACTIONS: transcript", ALL)
    assert reply and actions == ["transcript"]


def test_prompts_list_only_the_allowed_destinations():
    real = api.build_canonical_chat_messages(_profile(), api.ChatRequest(message="hi"))[0]["content"]
    demo = api.build_chat_messages({}, {}, api.ChatRequest(message="hi"))[0]["content"]
    assert "- transcript:" in real and "- transcript:" not in demo
    assert "- gpa-calculator:" in demo


def test_frontend_registry_matches_backend():
    source = Path(__file__).resolve().parents[1].joinpath("frontend/src/lib/chatActions.mjs").read_text()
    frontend_ids = set(re.findall(r"^  '([a-z-]+)': \{", source, re.MULTILINE))
    assert frontend_ids == set(chat_actions.CHAT_ACTIONS)


def _profile():
    from test_chat_context import canonical_profile

    return canonical_profile()
