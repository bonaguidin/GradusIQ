"""Tests for data/catalog/import_requirement_groups.py's pure mapping and
validation functions: to_program_row, to_requirement_group_row,
build_option_rows, and their validators.

No network calls, no Supabase client construction -- same posture as
test_import_catalog.py. The module itself imports `dotenv`/`supabase` at
top level (for its Supabase-touching functions), so those packages must be
installed for this file to import, but nothing here calls them.
"""

from __future__ import annotations

from data.catalog import import_requirement_groups as irg


# ── to_program_row / validate_program_row ───────────────────────────────────


def _program():
    return {
        "coursedog_program_id": "CS-BS-2026-05-21",
        "program_group_id": "CS-BS",
        "code": "CS-BS",
        "name": "Computer Science",
        "degree_designation": "BS - Bachelor of Science",
    }


def test_to_program_row_maps_fields():
    row = irg.to_program_row(_program(), institution_id="inst-123", catalog_year="2026-2027")
    assert row["institution_id"] == "inst-123"
    assert row["coursedog_program_id"] == "CS-BS-2026-05-21"
    assert row["program_group_id"] == "CS-BS"
    assert row["catalog_year"] == "2026-2027"


def test_validate_program_row_catches_missing_required_field():
    row = irg.to_program_row(_program(), institution_id="inst-123", catalog_year="2026-2027")
    row["code"] = None
    problems = irg.validate_program_row(row)
    assert any("code" in p for p in problems)


def test_validate_program_row_clean_row_has_no_problems():
    row = irg.to_program_row(_program(), institution_id="inst-123", catalog_year="2026-2027")
    assert irg.validate_program_row(row) == []


def test_validate_program_row_degree_designation_may_be_null():
    # Nullable by design -- not every program record carries one.
    row = irg.to_program_row(_program(), institution_id="inst-123", catalog_year="2026-2027")
    row["degree_designation"] = None
    assert irg.validate_program_row(row) == []


# ── to_requirement_group_row / validate_requirement_group_row ──────────────


def _enumerated_at_least_n_group(**overrides):
    base = {
        "coursedog_rule_id": "engleadid",
        "parent_coursedog_rule_id": None,
        "name": "Engineering Leadership (6 Credit Hours)",
        "group_type": "enumerated_at_least_n",
        "n_required": 2,
        "credit_hours_required": 6,
        "notes_html": None,
        "requires_manual_definition": False,
        "options": [],
    }
    base.update(overrides)
    return base


def test_to_requirement_group_row_maps_fields():
    row = irg.to_requirement_group_row(
        _enumerated_at_least_n_group(), program_id="prog-1", catalog_year="2026-2027"
    )
    assert row["program_id"] == "prog-1"
    assert row["coursedog_rule_id"] == "engleadid"
    assert row["group_type"] == "enumerated_at_least_n"
    assert row["n_required"] == 2


def test_validate_requirement_group_row_clean_row_has_no_problems():
    row = irg.to_requirement_group_row(
        _enumerated_at_least_n_group(), program_id="prog-1", catalog_year="2026-2027"
    )
    assert irg.validate_requirement_group_row(row, label="test") == []


def test_validate_requirement_group_row_rejects_unknown_group_type():
    row = irg.to_requirement_group_row(
        _enumerated_at_least_n_group(group_type="something_else"),
        program_id="prog-1",
        catalog_year="2026-2027",
    )
    problems = irg.validate_requirement_group_row(row, label="test")
    assert any("group_type" in p for p in problems)


def test_validate_requirement_group_row_n_required_required_for_at_least_n():
    row = irg.to_requirement_group_row(
        _enumerated_at_least_n_group(n_required=None), program_id="prog-1", catalog_year="2026-2027"
    )
    problems = irg.validate_requirement_group_row(row, label="test")
    assert any("n_required" in p for p in problems)


def test_validate_requirement_group_row_n_required_forbidden_outside_at_least_n():
    # Mirrors requirement_groups_n_required_matches_type in the migration:
    # n_required must be null for every group_type except enumerated_at_least_n.
    row = irg.to_requirement_group_row(
        _enumerated_at_least_n_group(group_type="enumerated_all", n_required=2),
        program_id="prog-1",
        catalog_year="2026-2027",
    )
    problems = irg.validate_requirement_group_row(row, label="test")
    assert any("n_required" in p for p in problems)


def test_validate_requirement_group_row_negative_credit_hours_rejected():
    row = irg.to_requirement_group_row(
        _enumerated_at_least_n_group(credit_hours_required=-1),
        program_id="prog-1",
        catalog_year="2026-2027",
    )
    problems = irg.validate_requirement_group_row(row, label="test")
    assert any("credit_hours_required" in p for p in problems)


def test_validate_requirement_group_row_freeform_group_is_clean_with_no_options():
    freeform_group = {
        "coursedog_rule_id": "AjzAZTn4",
        "parent_coursedog_rule_id": None,
        "name": "Technical Electives (9 Credit Hours)",
        "group_type": "freeform",
        "n_required": None,
        "credit_hours_required": 9,
        "notes_html": "<p>Nine credit hours of CS courses at 3000+.</p>",
        "requires_manual_definition": True,
        "options": [],
    }
    row = irg.to_requirement_group_row(freeform_group, program_id="prog-1", catalog_year="2026-2027")
    assert irg.validate_requirement_group_row(row, label="test") == []


# ── build_option_rows(): unresolved-course-ref handling ─────────────────────
# Per spec §8.3's already-decided "unresolved course IDs" item: a
# coursedog_group_id not present in course_catalog gets flagged
# (unresolved_course_ref), not dropped and not a failure.


def _enumerated_group_with_options():
    return {
        "coursedog_rule_id": "cscoreid",
        "group_type": "enumerated_all",
        "options": [
            {"option_index": 0, "logic": "and", "coursedog_group_ids": ["0045691", "0045701"]},
            {"option_index": 1, "logic": "and", "coursedog_group_ids": ["9999999"]},
        ],
    }


def test_build_option_rows_resolved_ids_pass_through():
    resolved = {"0045691", "0045701", "9999999"}
    option_rows, course_rows_by_option = irg.build_option_rows(_enumerated_group_with_options(), resolved)
    assert len(option_rows) == 2
    assert course_rows_by_option[0] == [
        {"coursedog_group_id": "0045691", "unresolved_course_ref": None},
        {"coursedog_group_id": "0045701", "unresolved_course_ref": None},
    ]


def test_build_option_rows_unresolved_id_flagged_not_dropped():
    # "9999999" is deliberately absent from `resolved` -- simulates the
    # ~5% inactive/renumbered-course rate the prior full-catalog audit
    # found (spec §3.1).
    resolved = {"0045691", "0045701"}
    _, course_rows_by_option = irg.build_option_rows(_enumerated_group_with_options(), resolved)
    # Both options still present -- an unresolved course does not drop the
    # option or the rest of the import.
    assert len(course_rows_by_option) == 2
    unresolved_option = course_rows_by_option[1]
    assert unresolved_option == [{"coursedog_group_id": None, "unresolved_course_ref": "9999999"}]


def test_build_option_rows_preserves_option_order_and_index():
    resolved = {"0045691", "0045701", "9999999"}
    option_rows, _ = irg.build_option_rows(_enumerated_group_with_options(), resolved)
    assert [row["option_index"] for row in option_rows] == [0, 1]


# ── validate_option_row() ────────────────────────────────────────────────────


def test_validate_option_row_clean():
    assert irg.validate_option_row({"option_index": 0, "logic": "and"}, label="test") == []


def test_validate_option_row_bad_logic_value():
    problems = irg.validate_option_row({"option_index": 0, "logic": "xor"}, label="test")
    assert any("logic" in p for p in problems)


def test_validate_option_row_negative_index():
    problems = irg.validate_option_row({"option_index": -1, "logic": "and"}, label="test")
    assert any("option_index" in p for p in problems)
