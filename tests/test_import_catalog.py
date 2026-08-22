"""Tests for data/catalog/import_catalog.py's course -> course_catalog row
mapping, specifically that coursedog_group_id survives the trip from a
normalized catalog JSON record into the dict handed to Supabase's upsert.

No network calls, no Supabase client construction -- to_row() and
NOT_NULL_COLUMNS are pure functions/data over plain dicts.
"""

from __future__ import annotations

from data.catalog import import_catalog


def _normalized_course(**overrides):
    """A record shaped like one entry in data/catalog/smu/*.json."""
    base = {
        "code": "CS 1341",
        "prefix": "CS",
        "number": "1341",
        "title": "Computer Science I",
        "description": "Introduction to computer science and programming.",
        "department": "Computer Science",
        "course_level": 100,
        "credit_min": 3,
        "credit_max": 3,
        "prerequisites": None,
        "catalog_year": "2026-2027",
        "source_last_checked": "2026-08-17",
        "coursedog_group_id": "0045691",
    }
    base.update(overrides)
    return base


def test_to_row_persists_coursedog_group_id():
    row = import_catalog.to_row(_normalized_course(), institution_id="inst-123")
    assert row["coursedog_group_id"] == "0045691"


def test_to_row_coursedog_group_id_null_for_tamu_style_record():
    # TAMU's catalog JSON has no coursedog_group_id key at all (CourseLeaf,
    # not Coursedog) -- to_row() must not KeyError, and must map it to None.
    course = _normalized_course()
    del course["coursedog_group_id"]
    row = import_catalog.to_row(course, institution_id="inst-123")
    assert row["coursedog_group_id"] is None


def test_coursedog_group_id_is_nullable_not_required():
    # Confirms it's deliberately absent from NOT_NULL_COLUMNS: a course
    # record with no coursedog_group_id must not fail validate_row().
    course = _normalized_course()
    del course["coursedog_group_id"]
    row = import_catalog.to_row(course, institution_id="inst-123")
    problems = import_catalog.validate_row(row, label="test")
    assert not any("coursedog_group_id" in problem for problem in problems)
