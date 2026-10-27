"""Assistant memory notes (chat overhaul, Phase 4).

Instead of storing whole conversations, the assistant keeps a short list of
facts the student chose to have remembered ("Aiming for remote software
roles"). The model may end a reply with ``REMEMBER: <fact>`` when the student
says something lasting that is not already in their profile; the app shows it
as a "Remember this?" card, and only the student's click saves it. Saved
notes ride along in every later chat as part of the student context.

Storage is the student_memory_notes table (owner-only RLS). Until that
migration is applied, every read here reports the feature as unavailable
instead of failing, so chat keeps working without it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

TABLE = "student_memory_notes"
MAX_NOTES = 20
MAX_NOTE_LENGTH = 200
# Proposals are kept shorter than what a student may type themselves.
MAX_PROPOSAL_LENGTH = 160

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACE = re.compile(r"\s+")


class MemoryUnavailable(Exception):
    """The notes table does not exist yet (migration not applied)."""


def clean_note(text: str) -> str:
    """One line, single-spaced, no control characters, no wrapping quotes."""
    text = _SPACE.sub(" ", _CONTROL.sub(" ", text)).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    return text.strip("“”").strip()


def clean_proposal(raw: str | None, existing: Iterable[str]) -> str | None:
    """The model's REMEMBER line, or None when it should not be offered."""
    if not raw:
        return None
    note = clean_note(raw)
    if not note or len(note) > MAX_PROPOSAL_LENGTH:
        return None
    if note.casefold() in {clean_note(n).casefold() for n in existing}:
        return None
    return note


def memory_instructions() -> str:
    """The trusted prompt section about remembering things."""
    return (
        "<MEMORY>\n"
        "remembered_notes in the student context are facts this student asked you to remember "
        "in earlier chats. Use them, and do not ask again for what they already say.\n"
        "When the student tells you something lasting about themselves that is not already in "
        "their profile or remembered_notes (a goal, a preference, a constraint, a plan, e.g. "
        "wanting remote roles or considering a minor), you may end the reply with one final line "
        "`REMEMBER: <the fact in a few words, written about the student>`, e.g. "
        "`REMEMBER: Aiming for remote software roles`. The app asks the student before saving "
        "it. At most one per reply, under 120 characters. Never propose grades, passwords, "
        "the student's own health or medical details, or anything about other people, and "
        "never for one-off questions. A career interest is fine to propose even when its field "
        "is health care (e.g. `REMEMBER: Considering a switch to a health care major`).\n"
        "You cannot save anything yourself: never say a note is saved or will appear anywhere. "
        "If the student asks you to remember something, propose it with the REMEMBER line once "
        "and say they can tap Remember below to save it; do not ask them to confirm first.\n"
        "</MEMORY>"
    )


def memory_off_instructions() -> str:
    """The trusted prompt section for a chat with no memory to save into.

    The app guide still describes memory, so without this the model reads
    "the assistant can offer to remember" and improvises a save that never
    happens.
    """
    return (
        "<MEMORY>\n"
        "Memory is not available in this chat, so nothing the student says is saved after "
        "this conversation. If they ask you to remember something, say plainly that you can't "
        "save notes here yet, and suggest adding it to their Career Profile instead if it fits "
        "there. Never say or imply that a note was saved or will appear under \"What GradusIQ "
        "remembers\".\n"
        "</MEMORY>"
    )


def is_missing_table(exc: BaseException) -> bool:
    """True when PostgREST says the notes table is not there yet."""
    code = getattr(exc, "code", None)
    if code in {"PGRST205", "42P01"}:
        return True
    text = str(exc)
    return TABLE in text and ("schema cache" in text or "does not exist" in text)


def _rows(response: Any) -> list[dict]:
    data = getattr(response, "data", None)
    return list(data) if data else []


def list_notes(client, student_id: str) -> list[dict]:
    """Oldest first. Raises MemoryUnavailable before the migration."""
    try:
        response = (
            client.table(TABLE)
            .select("id,note,created_at")
            .eq("student_id", student_id)
            .order("created_at")
            .limit(MAX_NOTES)
            .execute()
        )
    except Exception as exc:
        if is_missing_table(exc):
            raise MemoryUnavailable from exc
        raise
    return _rows(response)


def add_note(client, student_id: str, note: str) -> dict:
    try:
        response = client.table(TABLE).insert({"student_id": student_id, "note": note}).execute()
    except Exception as exc:
        if is_missing_table(exc):
            raise MemoryUnavailable from exc
        raise
    rows = _rows(response)
    return rows[0] if rows else {"note": note}


def delete_note(client, student_id: str, note_id: str) -> None:
    try:
        client.table(TABLE).delete().eq("student_id", student_id).eq("id", note_id).execute()
    except Exception as exc:
        if is_missing_table(exc):
            raise MemoryUnavailable from exc
        raise
