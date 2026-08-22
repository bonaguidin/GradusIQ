"""Tests for data/catalog/fetch_smu_requirements.py.

Covers normalize_rule()'s condition -> group_type mapping, credit_hours_from_
name(), and parse_requisites()'s requirementLevel filtering. No network calls
-- every case here works from fixed input dicts, the literal rule objects
pulled live from SMU's CS-BS program (_id "CS-BS-2026-05-21") during this
session's filter-rule-shape audit (planning-docs/degree-planner-spec.md §8.3).
"""

from __future__ import annotations

from data.catalog import fetch_smu_requirements as reqs


# ── credit_hours_from_name() ────────────────────────────────────────────────


def test_credit_hours_from_name_simple():
    assert reqs.credit_hours_from_name("Technical Electives (9 Credit Hours)") == 9


def test_credit_hours_from_name_range_takes_lower_bound():
    assert reqs.credit_hours_from_name("Lyle EDGE Curriculum (9-13 Credit Hours)") == 9


def test_credit_hours_from_name_none_when_absent():
    # "Two Courses" -- the lab-science-sequence compound rule -- has no
    # credit-hour suffix in its own name; that's the real source data, not
    # an edge case invented for the test.
    assert reqs.credit_hours_from_name("Two Courses") is None


def test_credit_hours_from_name_singular_hour():
    assert reqs.credit_hours_from_name("Advanced Major Electives (3-5 Credit Hours)") == 3


# ── normalize_rule(): enumerated_all ────────────────────────────────────────
# Computer Science Core (33 Credit Hours) -- completedAllOf, confirmed live
# with 11 entries in value.values[]. Trimmed to 2 entries here for a readable
# fixture; the shape is what's under test, not the exact SMU course list.


def test_completed_all_of_becomes_enumerated_all():
    rule = {
        "id": "cscoreid1",
        "condition": "completedAllOf",
        "name": "Computer Science Core (33 Credit Hours)",
        "value": {
            "condition": "courses",
            "values": [
                {"value": ["0045691"], "logic": "and"},
                {"value": ["0045701"], "logic": "and"},
            ],
            "id": "someid",
            "subSelections": [],
        },
    }
    groups, warnings = reqs.normalize_rule(rule, parent_coursedog_rule_id=None)
    assert warnings == []
    assert len(groups) == 1
    group = groups[0]
    assert group["coursedog_rule_id"] == "cscoreid1"
    assert group["parent_coursedog_rule_id"] is None
    assert group["group_type"] == "enumerated_all"
    assert group["n_required"] is None
    assert group["credit_hours_required"] == 33
    assert group["requires_manual_definition"] is False
    assert group["options"] == [
        {"option_index": 0, "logic": "and", "coursedog_group_ids": ["0045691"]},
        {"option_index": 1, "logic": "and", "coursedog_group_ids": ["0045701"]},
    ]


def test_enumerated_all_and_pair_is_one_co_requisite_option():
    # Confirmed live on Mathematics and Science: an "and" entry like
    # ["0019411", "0019371"] is a lecture+lab bundle counted as ONE option,
    # not two alternatives -- option_index does not advance within a bundle.
    rule = {
        "id": "mathsciid",
        "condition": "completedAllOf",
        "name": "Mathematics and Science (24-26 Credit Hours)",
        "value": {
            "condition": "courses",
            "values": [{"value": ["0019411", "0019371"], "logic": "and"}],
        },
    }
    groups, warnings = reqs.normalize_rule(rule, parent_coursedog_rule_id=None)
    assert warnings == []
    assert len(groups[0]["options"]) == 1
    assert groups[0]["options"][0]["coursedog_group_ids"] == ["0019411", "0019371"]


# ── normalize_rule(): enumerated_at_least_n ─────────────────────────────────
# Engineering Leadership (6 Credit Hours) -- completedAtLeastXOf, restriction
# 2, 6 enumerated options, confirmed live.


def test_completed_at_least_x_of_becomes_enumerated_at_least_n():
    rule = {
        "id": "engleadid",
        "condition": "completedAtLeastXOf",
        "restriction": 2,
        "name": "Engineering Leadership (6 Credit Hours)",
        "value": {
            "condition": "courses",
            "values": [{"value": [f"027563{i}"], "logic": "and"} for i in range(6)],
        },
    }
    groups, warnings = reqs.normalize_rule(rule, parent_coursedog_rule_id=None)
    assert warnings == []
    group = groups[0]
    assert group["group_type"] == "enumerated_at_least_n"
    assert group["n_required"] == 2
    assert len(group["options"]) == 6


def test_completed_at_least_x_of_missing_restriction_is_a_warning_not_a_crash():
    rule = {
        "id": "badid",
        "condition": "completedAtLeastXOf",
        "name": "Broken Rule",
        "value": {"condition": "courses", "values": [{"value": ["1"], "logic": "and"}]},
    }
    groups, warnings = reqs.normalize_rule(rule, parent_coursedog_rule_id=None)
    assert groups == []
    assert len(warnings) == 1
    assert "restriction" in warnings[0]


# ── normalize_rule(): completedAnyOf ────────────────────────────────────────
# "Advanced/Domain Specific Use/Design of AI" -- the literal rule object
# confirmed live this session (Phase 3a dry-run's unhandled-condition audit).
# Structurally identical to completedAtLeastXOf's shape, but with no
# `restriction` field -- the condition itself fixes n_required at 1.


def test_completed_any_of_becomes_enumerated_at_least_n_with_n_required_one():
    rule = {
        "condition": "completedAnyOf",
        "value": {
            "condition": "courses",
            "values": [
                {"value": ["0275631"], "logic": "and"},
                {"value": ["0278621"], "logic": "and"},
                {"value": ["0225131"], "logic": "and"},
                {"value": ["0225761"], "logic": "and"},
                {"value": ["0046401"], "logic": "and"},
                {"value": ["0275611"], "logic": "and"},
                {"value": ["0258761"], "logic": "and"},
                {"value": ["0268171"], "logic": "and"},
                {"value": ["0283371"], "logic": "and"},
                {"value": ["0278081"], "logic": "and"},
                {"value": ["0237421"], "logic": "and"},
            ],
            "id": "g5IoOfGH",
            "subSelections": [],
        },
        "id": "zivoTpLT",
        "name": "Advanced/Domain Specific Use/Design of AI",
        "description": (
            "<p>Students will fulfill this requirement by taking one of the "
            "courses listed below as part of their major requirements. The "
            "credit hours for this requirement are included in the major "
            "requirements and not the EDGE requirements.</p>"
        ),
    }
    groups, warnings = reqs.normalize_rule(rule, parent_coursedog_rule_id=None)
    assert warnings == []
    group = groups[0]
    assert group["group_type"] == "enumerated_at_least_n"
    assert group["n_required"] == 1
    assert len(group["options"]) == 11
    all_ids = [cid for option in group["options"] for cid in option["coursedog_group_ids"]]
    assert all_ids == [
        "0275631", "0278621", "0225131", "0225761", "0046401",
        "0275611", "0258761", "0268171", "0283371", "0278081", "0237421",
    ]


# ── normalize_rule(): completeVariableCoursesAndVariableCredits ────────────
# "Content Area 4, Physics" -- the literal rule object confirmed live this
# session, including the lecture+lab paired-ID ("and" logic) options already
# exercised by test_enumerated_all_and_pair_is_one_co_requisite_option above.
# minCredits/maxCredits sit directly on the rule; only minCredits is kept.
# group_type is enumerated_credit_threshold, not enumerated_all -- distinct
# satisfaction semantics (accumulate minCredits worth of options, not
# complete every option), added by supabase/migrations/20260819160000_
# requirement_groups_credit_threshold_group_type.sql after the requirement-
# satisfaction engine build surfaced the schema needed a 6th group_type to
# express this without a hardcoded coursedog_rule_id allowlist.


def test_complete_variable_courses_and_variable_credits_becomes_credit_threshold():
    rule = {
        "condition": "completeVariableCoursesAndVariableCredits",
        "value": {
            "condition": "courses",
            "values": [
                {"value": ["0139911", "0139861"], "logic": "and"},
                {"value": ["0139921", "0139871"], "logic": "and"},
                {"value": ["0140111"], "logic": "and"},
            ],
            "id": "HwIQ10H6",
            "subSelections": [],
        },
        "id": "T6z1BLsv",
        "minCredits": 7,
        "maxCredits": 8,
        "name": "Content Area 4, Physics",
    }
    groups, warnings = reqs.normalize_rule(rule, parent_coursedog_rule_id=None)
    assert warnings == []
    group = groups[0]
    assert group["group_type"] == "enumerated_credit_threshold"
    assert group["n_required"] is None
    # minCredits kept, maxCredits intentionally discarded (see the code
    # comment on this branch in normalize_rule()).
    assert group["credit_hours_required"] == 7
    assert len(group["options"]) == 3
    assert group["options"][0]["coursedog_group_ids"] == ["0139911", "0139861"]
    assert group["options"][0]["logic"] == "and"
    assert group["options"][1]["coursedog_group_ids"] == ["0139921", "0139871"]
    assert group["options"][2]["coursedog_group_ids"] == ["0140111"]


# ── normalize_rule(): freeform ──────────────────────────────────────────────
# Technical Electives (9 Credit Hours) -- the literal rule object confirmed
# live this session. This is the central finding of the filter-rule-shape
# audit: no structured department/level filter exists anywhere in the
# payload, only this prose in `notes`.


def test_freeform_text_technical_electives():
    rule = {
        "id": "AjzAZTn4",
        "condition": "freeformText",
        "value": "Complete the following:",
        "name": "Technical Electives (9 Credit Hours)",
        "notes": (
            "<p data-indent=\"1\">Nine credit hours of CS courses at the "
            "3000 level or above as approved by the adviser. The adviser "
            "may approve other sufficiently technical courses from other "
            "departments to satisfy the Technical elective requirements. "
            "Technical electives cannot be satisfied by courses that are "
            "part of the student’s chosen track.</p>"
        ),
    }
    groups, warnings = reqs.normalize_rule(rule, parent_coursedog_rule_id=None)
    assert warnings == []
    group = groups[0]
    assert group["group_type"] == "freeform"
    assert group["requires_manual_definition"] is True
    assert group["credit_hours_required"] == 9
    assert group["options"] == []
    assert "Nine credit hours of CS courses" in group["notes_html"]


# ── normalize_rule(): compound (allOf / anyOf) ──────────────────────────────
# "Two Courses" -- the lab-science-sequence choice, condition anyOf, two
# subRules each a completedAllOf enumerated bundle. Trimmed from the live
# 2-subRule example (Biology, Chemistry) confirmed this session.


def _two_courses_rule():
    return {
        "id": "mcAsXWxO",
        "condition": "anyOf",
        "name": "Two Courses",
        "subRules": [
            {
                "id": "bBp5BF7P",
                "condition": "completedAllOf",
                "name": "Content Area 1, Biology",
                "value": {
                    "condition": "courses",
                    "values": [{"value": ["0019411", "0019371"], "logic": "and"}],
                },
            },
            {
                "id": "chemSubRuleId",
                "condition": "completedAllOf",
                "name": "Content Area 1, Chemistry",
                "value": {
                    "condition": "courses",
                    "values": [{"value": ["0033981", "0033911"], "logic": "and"}],
                },
            },
        ],
    }


def test_any_of_becomes_compound_any_with_children():
    groups, warnings = reqs.normalize_rule(_two_courses_rule(), parent_coursedog_rule_id=None)
    assert warnings == []
    assert len(groups) == 3  # the compound row itself + 2 subRule rows
    compound = groups[0]
    assert compound["coursedog_rule_id"] == "mcAsXWxO"
    assert compound["group_type"] == "compound_any"
    assert compound["parent_coursedog_rule_id"] is None
    assert compound["options"] == []

    children = groups[1:]
    assert {c["coursedog_rule_id"] for c in children} == {"bBp5BF7P", "chemSubRuleId"}
    for child in children:
        assert child["parent_coursedog_rule_id"] == "mcAsXWxO"
        assert child["group_type"] == "enumerated_all"


def test_all_of_becomes_compound_all():
    rule = {
        "id": "lyleid",
        "condition": "allOf",
        "name": "Lyle EDGE Curriculum (9-13 Credit Hours)",
        "subRules": [
            {
                "id": "childid",
                "condition": "freeformText",
                "value": "Complete the following:",
                "name": "AI Fundamentals",
                "notes": "<p>Some narrative requirement.</p>",
            }
        ],
    }
    groups, warnings = reqs.normalize_rule(rule, parent_coursedog_rule_id=None)
    assert warnings == []
    assert groups[0]["group_type"] == "compound_all"
    assert groups[0]["credit_hours_required"] == 9
    assert groups[1]["parent_coursedog_rule_id"] == "lyleid"
    assert groups[1]["group_type"] == "freeform"


def test_compound_missing_sub_rules_warns_but_keeps_the_parent_row():
    rule = {"id": "brokenparent", "condition": "allOf", "name": "Broken Compound"}
    groups, warnings = reqs.normalize_rule(rule, parent_coursedog_rule_id=None)
    assert len(groups) == 1
    assert groups[0]["group_type"] == "compound_all"
    assert len(warnings) == 1
    assert "subRules" in warnings[0]


# ── normalize_rule(): unknown condition ─────────────────────────────────────


def test_unknown_condition_is_skipped_with_a_warning():
    rule = {"id": "mystery", "condition": "someNewConditionType", "name": "Mystery Rule"}
    groups, warnings = reqs.normalize_rule(rule, parent_coursedog_rule_id=None)
    assert groups == []
    assert len(warnings) == 1
    assert "someNewConditionType" in warnings[0]


def test_enumerated_rule_with_non_courses_value_condition_is_skipped():
    rule = {
        "id": "weird",
        "condition": "completedAllOf",
        "name": "Weird Rule",
        "value": {"condition": "notCourses", "values": []},
    }
    groups, warnings = reqs.normalize_rule(rule, parent_coursedog_rule_id=None)
    assert groups == []
    assert len(warnings) == 1


# ── parse_requisites(): requirementLevel filtering ──────────────────────────


def test_parse_requisites_only_walks_program_requirements_level():
    program = {
        "requisites": {
            "requisitesSimple": [
                {
                    "id": "narrative",
                    "name": "Narrative Text",
                    "type": "Narrative Text",
                    "requirementLevel": "subplan",
                    "rules": [],
                },
                {
                    "id": "trackreq",
                    "name": "Requirements for the Specialization (9 Credit Hours)",
                    "requirementLevel": "subplan",
                    "rules": [
                        {
                            "id": "trackrule",
                            "condition": "completedAllOf",
                            "name": "Required Courses (9 Credit Hours)",
                            "value": {
                                "condition": "courses",
                                "values": [{"value": ["9999999"], "logic": "and"}],
                            },
                        }
                    ],
                },
                {
                    "id": "majorreq",
                    "name": "Requirements for the Major (95-99 Credit Hours)",
                    "requirementLevel": "programRequirements",
                    "rules": [
                        {
                            "id": "techelectives",
                            "condition": "freeformText",
                            "value": "Complete the following:",
                            "name": "Technical Electives (9 Credit Hours)",
                            "notes": "<p>9 CS credit hours at 3000+, adviser-approved.</p>",
                        }
                    ],
                },
            ]
        }
    }
    groups, warnings = reqs.parse_requisites(program)
    assert warnings == []
    # Only the programRequirements-level rule should appear -- the subplan
    # (specialization track) rule must not leak in.
    assert len(groups) == 1
    assert groups[0]["coursedog_rule_id"] == "techelectives"


def test_parse_requisites_missing_requisites_simple_warns_instead_of_crashing():
    groups, warnings = reqs.parse_requisites({"requisites": {}})
    assert groups == []
    assert len(warnings) == 1
    assert "requisitesSimple" in warnings[0]


def test_parse_requisites_no_program_requirements_entry_warns():
    program = {
        "requisites": {
            "requisitesSimple": [
                {"id": "x", "requirementLevel": "subplan", "rules": [{"id": "y", "condition": "allOf"}]}
            ]
        }
    }
    groups, warnings = reqs.parse_requisites(program)
    assert groups == []
    assert len(warnings) == 1
