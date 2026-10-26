import re
from pathlib import Path

from GradusIQ_career import api
from GradusIQ_career.ai import chat_actions

ALL = chat_actions.ACCOUNT_ACTIONS


def test_trailing_actions_line_is_stripped_and_kept():
    reply, actions, _ = chat_actions.split_reply(
        "Your GPA is **3.42**.\n\nACTIONS: gpa-calculator, transcript", ALL
    )
    assert reply == "Your GPA is **3.42**."
    assert actions == ["gpa-calculator", "transcript"]


def test_wrapped_and_lowercase_variants_parse():
    for line in ("**Actions:** gpa-calculator", "`ACTIONS: gpa-calculator`", "[actions - gpa-calculator]"):
        reply, actions = chat_actions.split_reply(f"Done.\n{line}", ALL)[:2]
        assert (reply, actions) == ("Done.", ["gpa-calculator"]), line


def test_unknown_duplicate_and_extra_ids_are_dropped():
    _, actions, _ = chat_actions.split_reply(
        "Hi\nACTIONS: https://evil.example, gpa-calculator, gpa-calculator, delete-account, "
        "job-search, resume, transcript",
        ALL,
    )
    assert actions == ["gpa-calculator", "job-search", "resume"]


def test_demo_cannot_get_account_only_pages():
    _, actions = chat_actions.split_reply("Hi\nACTIONS: transcript, canvas-calendar, job-search", chat_actions.DEMO_ACTIONS)[:2]
    assert actions == ["job-search"]


def test_reply_without_line_is_unchanged():
    text = "Some actions: are worth it.\nKeep going."
    assert chat_actions.split_reply(text, ALL) == (text, [], None)


def test_reply_that_is_only_the_line_still_has_text():
    reply, actions = chat_actions.split_reply("ACTIONS: transcript", ALL)[:2]
    assert reply and actions == ["transcript"]


def test_remember_and_actions_lines_in_either_order():
    for tail in ("REMEMBER: Aiming for remote roles\nACTIONS: job-search", "ACTIONS: job-search\n**Remember:** Aiming for remote roles"):
        assert chat_actions.split_reply(f"Noted.\n\n{tail}", ALL) == ("Noted.", ["job-search"], "Aiming for remote roles")


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
