"""Action buttons on assistant chat replies (chat overhaul, Phase 3).

The model may end a reply with one line naming up to three destinations from
a fixed list, e.g. ``ACTIONS: gpa-calculator, transcript``. The server strips
that line, keeps only known ids, and returns them beside the reply; the
frontend (lib/chatActions.mjs) owns each id's label and where it goes. So the
model can only ever point at a page that exists, never invent a URL.

Plain text rather than JSON mode on purpose: the chat model is a cheap flash
model, a trailing line is easy for it to follow, and if it gets the line wrong
the reply still arrives, just without buttons.
"""

from __future__ import annotations

import re

MAX_ACTIONS = 3

# id -> what the destination is for, as the model reads it. Ids mirror
# frontend/src/lib/chatActions.mjs (a test checks both lists match).
CHAT_ACTIONS: dict[str, str] = {
    "gpa-calculator": "GPA Calculator: official and projected GPA, per-term chart, what-if grades",
    "grade-calculator": "Grade Calculator: the grade needed on remaining work in a course, from its syllabus weights",
    "course-discovery": "Course Discovery: courses at their school that build toward their target role",
    "degree-progress": "Academic overview: degree requirement progress and current courses",
    "career-intelligence": "Career Intelligence: run or view FIT, GAP and SHIFT",
    "job-search": "Job Search: internships and jobs for their target roles",
    "career-profile": "Career Profile: edit target roles, skills, experience and interests",
    "transcript": "Transcript upload: add or fix courses and grades from a transcript",
    "resume": "Resume upload: add experience, projects and skills from a resume",
    "canvas-calendar": "Canvas calendar: connect, reconnect or refresh Canvas; use whenever due dates are missing, wrong or stopped showing",
    "report-issue": "Report a bug or suggest a feature to the GradusIQ team; use whenever the student says something is broken or asks how to report it",
}

# Demo personas have no account rows, so these pages would only error for them.
ACCOUNT_ONLY_ACTIONS = frozenset({"transcript", "resume", "canvas-calendar"})

DEMO_ACTIONS = tuple(key for key in CHAT_ACTIONS if key not in ACCOUNT_ONLY_ACTIONS)
ACCOUNT_ACTIONS = tuple(CHAT_ACTIONS)

# A trailing "ACTIONS: a, b" line, tolerating the wrappers a model adds
# (bold, backticks, brackets) and "Action:" / "actions -".
_ACTIONS_LINE = re.compile(r"^[\s*_`\[(]*actions?\s*[:\-]\s*(.*?)[\s*_`\])]*$", re.IGNORECASE)
_ID = re.compile(r"[a-z][a-z-]*")


def action_instructions(allowed: tuple[str, ...]) -> str:
    """The trusted prompt section that lists the destinations."""
    lines = "\n".join(f"- {key}: {CHAT_ACTIONS[key]}" for key in allowed)
    return (
        "<ACTION_BUTTONS>\n"
        "When a page in GradusIQ would help the student act on your answer, end the reply "
        "with one final line naming up to three of these destinations, most useful first, "
        "e.g. `ACTIONS: gpa-calculator, transcript`. The app shows them as buttons, so do not "
        "also write links or describe how to click. If your reply sends the student to one of "
        "these pages, its id must be on the line: a button, never directions to find it. Use "
        "only ids from this list; leave the line out when no page helps (small talk, general "
        "advice).\n"
        f"{lines}\n"
        "</ACTION_BUTTONS>"
    )


# A trailing "REMEMBER: <fact>" line: the assistant proposing a memory note
# (ai/chat_memory.py). Same wrapper tolerance as the ACTIONS line.
_REMEMBER_LINE = re.compile(r"^[\s*_`\[(]*remember\s*[:\-][\s*_`]*(.*?)[\s*_`\])]*$", re.IGNORECASE)


def split_reply(text: str, allowed: tuple[str, ...]) -> tuple[str, list[str], str | None]:
    """Strip the trailing ACTIONS and REMEMBER lines from a reply.

    Returns (reply, known action ids, proposed memory note or None). The
    lines may come in either order; anything above them is the reply.
    """
    lines = text.rstrip().split("\n")
    found: list[str] = []
    remember: str | None = None
    while lines:
        last = lines[-1].strip()
        actions_match = _ACTIONS_LINE.match(last)
        remember_match = None if actions_match else _REMEMBER_LINE.match(last)
        if not (actions_match or remember_match):
            break
        lines.pop()
        if actions_match:
            # Earlier lines come first in the reply, so prepend.
            found = _ID.findall(actions_match.group(1).lower()) + found
        elif remember is None:
            remember = remember_match.group(1).strip() or None
        while lines and not lines[-1].strip():
            lines.pop()
    reply = "\n".join(lines).strip()
    allowed_set = set(allowed)
    actions: list[str] = []
    for key in found:
        if key in allowed_set and key not in actions:
            actions.append(key)
    actions = actions[:MAX_ACTIONS]
    if not reply:
        # The model wrote only the trailing lines.
        if actions:
            reply = "This page can help."
        elif remember:
            reply = "Got it."
        else:
            reply = text.strip()
    return reply, actions, remember
