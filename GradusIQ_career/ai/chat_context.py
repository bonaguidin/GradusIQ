"""Grounding for the authenticated chat beyond the canonical profile.

The canonical projection (api.canonical_chat_projection) covers who the
student is and what they have confirmed. This module shapes the rest of what
a student reasonably expects the assistant to know -- their saved GAP/FIT/
SHIFT results, degree progress, planned courses, upcoming Canvas due dates --
plus a short guide to the app itself. Each piece is compacted to what helps
an answer: the prompt is resent on every turn, so internal ids, URLs and
bookkeeping fields are dropped here rather than paid for on every message.

Everything here is pure shaping. Fetching lives in api.py, where each source
is loaded best effort: a source that fails is simply left out of the prompt.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence


PLATFORM_GUIDE_PATH = Path(__file__).resolve().parents[1] / "gradus_iq_chat_platform_guide.md"

ANALYSIS_FEATURES = ("GAP", "FIT", "SHIFT")

# The dashboard's Canvas list looks 21 days ahead (calendar_feed.UPCOMING_WINDOW);
# chat reuses that window and caps the count so a busy term can't swamp the prompt.
MAX_DEADLINES = 25


@lru_cache(maxsize=1)
def platform_guide() -> str:
    return PLATFORM_GUIDE_PATH.read_text(encoding="utf-8").strip()


def compact_analysis(results: Mapping[str, Mapping[str, Any] | None]) -> dict:
    """Saved FeatureResult dicts -> {FEATURE: {summary, data}} for successes only.

    A skipped or failed result carries no findings worth citing, and its
    errors/missing_fields are UI bookkeeping, so it is left out entirely.
    """
    compact: dict[str, dict] = {}
    for feature in ANALYSIS_FEATURES:
        result = results.get(feature)
        if not isinstance(result, Mapping) or result.get("status") != "success":
            continue
        compact[feature] = {"summary": result.get("summary"), "data": result.get("data") or {}}
    return compact


def _leaf_counts(group: Mapping[str, Any]) -> tuple[int, int]:
    # Mirrors frontend/src/lib/requirementProgress.mjs so the number the
    # assistant quotes matches the Overview progress ring.
    children = group.get("children") or []
    if not children:
        return (1 if group.get("status") == "SATISFIED" else 0), 1
    satisfied = total = 0
    for child in children:
        s, t = _leaf_counts(child)
        satisfied, total = satisfied + s, total + t
    return satisfied, total


def compact_requirements(result: Mapping[str, Any]) -> dict:
    """RequirementSatisfactionResult dict -> progress counts + a two-level outline."""
    groups = result.get("groups") or []
    satisfied = total = 0
    outline = []
    for group in groups:
        s, t = _leaf_counts(group)
        satisfied, total = satisfied + s, total + t
        entry: dict[str, Any] = {"name": group.get("name"), "status": group.get("status")}
        if group.get("detail"):
            entry["detail"] = group["detail"]
        children = [
            {"name": child.get("name"), "status": child.get("status")}
            for child in group.get("children") or []
        ]
        if children:
            entry["children"] = children
        outline.append(entry)
    return {"satisfied": satisfied, "total": total, "groups": outline}


def compact_planned(rows: Sequence[Mapping[str, Any]], term_labels: Mapping[str, str]) -> list[dict]:
    planned = []
    for row in rows:
        item: dict[str, Any] = {"course_code": row.get("course_code")}
        if row.get("title"):
            item["title"] = row["title"]
        if row.get("credit_hours") is not None:
            item["credit_hours"] = row["credit_hours"]
        label = term_labels.get(str(row.get("term_id")))
        if label:
            item["term"] = label
        planned.append(item)
    return planned


def compact_deadlines(events: Sequence[Mapping[str, Any]]) -> list[dict]:
    """calendar_feed.upcoming() events -> what, which course, when."""
    deadlines = []
    for event in events[:MAX_DEADLINES]:
        item: dict[str, Any] = {
            "title": event.get("title"),
            "kind": event.get("kind"),
            "when": event.get("starts_at"),
        }
        if event.get("course_label"):
            item["course"] = event["course_label"]
        if event.get("all_day"):
            item["all_day"] = True
        if event.get("likely_exam"):
            item["likely_exam"] = True
        deadlines.append(item)
    return deadlines
