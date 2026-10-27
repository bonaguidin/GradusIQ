import pytest

from GradusIQ_career import api
from GradusIQ_career.ai import chat_memory


class MissingTable(Exception):
    code = "PGRST205"


def test_clean_note_flattens_and_unquotes():
    assert chat_memory.clean_note('  "Aiming for\n remote   roles"  ') == "Aiming for remote roles"
    assert chat_memory.clean_note("“Considering a stats minor”") == "Considering a stats minor"


def test_proposal_rejects_empty_long_and_duplicate():
    assert chat_memory.clean_proposal(None, []) is None
    assert chat_memory.clean_proposal("x" * 200, []) is None
    assert chat_memory.clean_proposal("aiming for REMOTE roles", ["Aiming for remote roles"]) is None
    assert chat_memory.clean_proposal("Prefers morning classes", []) == "Prefers morning classes"


def test_missing_table_is_recognised():
    assert chat_memory.is_missing_table(MissingTable("nope"))
    assert chat_memory.is_missing_table(Exception('relation "student_memory_notes" does not exist'))
    assert not chat_memory.is_missing_table(Exception("permission denied"))


def test_memory_instructions_only_when_enabled():
    from test_chat_context import canonical_profile

    body = api.ChatRequest(message="hi")
    off = api.build_canonical_chat_messages(canonical_profile(), body)[0]["content"]
    on = api.build_canonical_chat_messages(canonical_profile(), body, memory_enabled=True)[0]["content"]
    assert "REMEMBER:" not in off and "REMEMBER:" in on
    assert on.index("<MEMORY>") < on.index("<STUDENT_PROFILE_DATA>\n")


def test_chat_without_memory_is_told_it_cannot_save():
    # The app guide describes memory either way; with memory off the model
    # once claimed a note was "saved under What GradusIQ remembers".
    from test_chat_context import canonical_profile

    body = api.ChatRequest(message="can you remember that?")
    off = api.build_canonical_chat_messages(canonical_profile(), body)[0]["content"]
    assert chat_memory.memory_off_instructions() in off
    assert "Never say or imply that a note was saved" in off
    on = api.build_canonical_chat_messages(canonical_profile(), body, memory_enabled=True)[0]["content"]
    assert chat_memory.memory_off_instructions() not in on
    assert "never say a note is saved" in on


def test_demo_chat_drops_remember_lines(monkeypatch):
    class Fake:
        def complete(self, messages, role):
            class R:
                text = "Sure.\nREMEMBER: Wants remote roles"
                model = "m"
            return R()

    monkeypatch.setattr(api, "build_client", lambda: Fake())
    result = api._complete_chat([{"role": "user", "content": "hi"}])
    assert result["reply"] == "Sure." and "remember" not in result


@pytest.mark.parametrize("raw", ["", "   ", "x" * 201])
def test_note_request_bounds(raw):
    note = chat_memory.clean_note(raw)
    assert not note or len(note) > chat_memory.MAX_NOTE_LENGTH
