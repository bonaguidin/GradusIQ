"""Tests for data/catalog/fetch_smu_catalog.py.

Covers split_description()'s REQUISITE_SENTENCE / PERMISSION_PHRASE
classification and build_course()'s field mapping. No network calls -- every
case here works from fixed input text, the same descriptions pulled live
during the prior SMU prerequisite-coverage audit.
"""

from __future__ import annotations

import pytest

from data.catalog import fetch_smu_catalog as smu


# ── split_description(): permission/approval phrasing (the fix) ────────────


def test_permission_required_independent_study_sentence_becomes_prerequisite():
    # CS 4190/4194/4392 and ~15 other CS 41xx-49xx independent-study
    # sections all carry this exact second sentence.
    text = (
        "An opportunity for the advanced undergraduate student to undertake "
        "independent investigation, design, or development. Written "
        "permission of the supervising faculty member is required before "
        "registration."
    )
    description, prerequisites = smu.split_description(text)
    assert description == (
        "An opportunity for the advanced undergraduate student to undertake "
        "independent investigation, design, or development."
    )
    assert prerequisites == (
        "Written permission of the supervising faculty member is required "
        "before registration."
    )


def test_instructor_permission_required_sentence_becomes_prerequisite():
    # ARHS 4302.
    text = (
        "Independent study for undergraduate majors under the direction and "
        "supervision of a faculty member. A directed study is a close "
        "collaboration between the professor and an advanced student who "
        "conducts a rigorous project that goes beyond the experience "
        "available in course offerings. Instructor permission required."
    )
    description, prerequisites = smu.split_description(text)
    assert prerequisites == "Instructor permission required."
    assert "Instructor permission required." not in description
    assert description.startswith("Independent study for undergraduate majors")


def test_deans_office_approved_single_sentence_stays_description_only():
    # ENGR 3390/4390-family (live: ENGR 3192, 3390, 3391, 3392, all four
    # sharing this exact description). Source text uses a curly apostrophe
    # (U+2019) in "Dean's", not a straight one -- the regex must match
    # either.
    #
    # The whole course description is a single sentence and it's entirely an
    # eligibility gate, so body is empty. Regression for the duplication bug:
    # description must keep the original text (a course with nothing else to
    # say still needs a NOT-NULL description), but prerequisites must be
    # None, not a byte-for-byte copy of the same text -- there is no other
    # content here for "moving" the sentence to clean up, unlike the
    # multi-sentence cases above.
    text = (
        "A proficient-level, multidisciplinary study of a specialized topic "
        "beyond regular course offerings, conducted with guidance from a "
        "Dean’s Office-approved faculty member."
    )
    description, prerequisites = smu.split_description(text)
    assert description == text
    assert prerequisites is None


@pytest.mark.parametrize("code", ["ENGR 3192", "ENGR 3390", "ENGR 3391", "ENGR 3392"])
def test_engr_independent_study_family_no_duplication(code):
    # Confirms the fix against all four live-affected codes, not just the
    # one representative string above -- these four rows were the actual
    # ones found duplicated during the full-catalog live diff.
    text = (
        "A proficient-level, multidisciplinary study of a specialized topic "
        "beyond regular course offerings, conducted with guidance from a "
        "Dean’s Office-approved faculty member."
    )
    description, prerequisites = smu.split_description(text)
    assert description == text
    assert prerequisites is None


# ── split_description(): "B.A." abbreviation false sentence-boundary ───────
# split_sentences() (data/catalog/normalize_catalog.py) was splitting right
# after "B.A." as if it ended the sentence, breaking the continuation
# ("in corporate communication and public affairs...") off as its own bogus
# fragment. Once the leading permission sentence correctly moves to
# prerequisites, that fragment became the ENTIRE description -- a broken,
# lowercase-starting string. Confirmed live against CCPA 5315/5320/5325's
# actual source text (5315 has no space after "B.A." in its second
# occurrence -- "B.A.in public relations" -- a real typo in SMU's own
# catalog text, included here rather than normalized away).
#
# Per the split_description() edge-case decision above: both sentences here
# match is_requisite_sentence ("written permission" and "Prerequisites:"),
# so body is empty and description keeps the whole original text, with
# prerequisites None -- same outcome as the ENGR family, and the correct one
# here too, since neither sentence is independent course-content prose.


@pytest.mark.parametrize(
    ("code", "text"),
    [
        (
            "CCPA 5315",
            "The student must secure written permission from the supervising "
            "instructor and return a completed directed studies form to the "
            "Division of Corporate Communication and Public Affairs before "
            "the drop/add date in the term during which the study is to be "
            "undertaken. Prerequisites: Permission of instructor and "
            "division chair and enrollment in the B.A. in corporate "
            "communication and public affairs, B.A.in public relations and "
            "strategic communication, or minor in corporate communication "
            "and public affairs program.",
        ),
        (
            "CCPA 5320",
            "The student must secure written permission from the supervising "
            "instructor and return a completed directed studies form to the "
            "Division of Corporate Communication and Public Affairs before "
            "the drop/add date in the term during which the study is to be "
            "undertaken. Prerequisites: Permission of instructor and "
            "division chair and enrollment in the B.A. in corporate "
            "communication and public affairs, B.A. in public relations and "
            "strategic communication, or minor in corporate communication "
            "and public affairs program.",
        ),
        (
            "CCPA 5325",
            "The student must secure written permission from the supervising "
            "instructor and return a completed directed studies form to the "
            "Division of Corporate Communication and Public Affairs before "
            "the drop/add date in the term during which the study is to be "
            "undertaken. Prerequisites: Permission of instructor and "
            "division chair and enrollment in the B.A. in corporate "
            "communication and public affairs, B.A. in public relations and "
            "strategic communication, or minor in corporate communication "
            "and public affairs program.",
        ),
    ],
)
def test_ba_abbreviation_does_not_break_description_mid_phrase(code, text):
    description, prerequisites = smu.split_description(text)
    assert description == text
    assert prerequisites is None
    # The regression this guards against: description used to start with
    # the orphaned lowercase continuation ("in corporate communication...")
    # once the leading sentence moved to prerequisites.
    assert description[0].isupper()


def test_us_abbreviation_at_genuine_sentence_boundary_still_splits():
    # SPAN 3356 (live). The lowercase-continuation-only guard on the
    # abbreviation fix above must NOT suppress this split: "U.S." here ends
    # a real sentence, and "Prerequisite: C- or better in SPAN 3359." is a
    # genuine, separate, uppercase-starting next sentence. An earlier,
    # unconditional version of the abbreviation fix regressed this exact
    # case -- confirmed live during the post-fix re-diff -- by merging both
    # into one sentence and losing the prerequisite entirely.
    text = (
        "An advanced course intended primarily for bilingual students whose "
        "home language is Spanish but whose dominant intellectual language "
        "is English. Because of its emphasis on cultural readings and "
        "communication skills, the course if suitable for native speakers "
        "who would like to broaden their knowledge of the language, "
        "Hispanic culture, and the major Hispanic groups in the U.S. "
        "Prerequisite: C- or better in SPAN 3359. Not for non-native "
        "speakers of Spanish; non-native speakers should take SPAN 3355."
    )
    description, prerequisites = smu.split_description(text)
    assert prerequisites == "Prerequisite: C- or better in SPAN 3359."
    assert "Prerequisite:" not in description


# ── split_description(): regression against the pre-existing patterns ──────


def test_prerequisite_prefix_still_matches():
    text = (
        "Foundations of mathematics including logic and set theory. "
        "Prerequisite: Grade of C or better in MATH 1309 or equivalent."
    )
    description, prerequisites = smu.split_description(text)
    assert description == "Foundations of mathematics including logic and set theory."
    assert prerequisites == "Prerequisite: Grade of C or better in MATH 1309 or equivalent."


def test_corequisite_prefix_still_matches():
    text = "Lab component for the lecture course. Corequisite: CHEM 1113."
    description, prerequisites = smu.split_description(text)
    assert description == "Lab component for the lecture course."
    assert prerequisites == "Corequisite: CHEM 1113."


def test_restricted_to_prefix_still_matches():
    text = "An advanced seminar on leadership theory. Restricted to Lyle seniors."
    description, prerequisites = smu.split_description(text)
    assert description == "An advanced seminar on leadership theory."
    assert prerequisites == "Restricted to Lyle seniors."


def test_may_not_be_taken_prefix_still_matches():
    text = (
        "Survey of accounting principles for non-majors. May not be taken "
        "for credit by students who have completed ACCT 2301."
    )
    description, prerequisites = smu.split_description(text)
    assert description == "Survey of accounting principles for non-majors."
    assert prerequisites == (
        "May not be taken for credit by students who have completed ACCT 2301."
    )


def test_no_false_positive_on_unrelated_use_of_permission():
    # "permission" appears but not in a phrase PERMISSION_PHRASE matches, and
    # nothing here should be pulled into prerequisites.
    text = "Students submit permission slips for the required field trip."
    description, prerequisites = smu.split_description(text)
    assert description == text
    assert prerequisites is None


# ── build_course(): courseGroupId capture ───────────────────────────────────
#
# Coursedog's internal course-group ID (e.g. "0045691"), confirmed in the SMU
# requirement-ID resolution audit to be what catalog.smu.edu's degree-
# requirements payload references its required courses by. Present on every
# raw courses/search record already; this only checks it now reaches
# build_course()'s output instead of being dropped by the COLUMNS projection.


def _raw_record(**overrides):
    base = {
        "code": "CS1341",
        "subjectCode": "CS",
        "courseNumber": "1341",
        "name": "Computer Science I",
        "longName": "Computer Science I",
        "description": "Introduction to computer science and programming.",
        "departments": ["Computer Science"],
        "college": "SEAS - Lyle School of Engineering",
        "career": "Undergraduate",
        "credits": {"creditHours": {"min": 3, "max": 3}},
        "requisites": {},
        "status": "Active",
        "courseGroupId": "0045691",
    }
    base.update(overrides)
    return base


def test_columns_requests_course_group_id_from_coursedog():
    # Without this, courseGroupId never reaches build_course() at all --
    # Coursedog's default projection is 87 fields, and COLUMNS is what
    # narrows the request down.
    assert "courseGroupId" in smu.COLUMNS.split(",")


def test_build_course_captures_coursedog_group_id():
    course, warnings = smu.build_course(_raw_record(), source_last_checked="2026-08-17")
    assert warnings == []
    assert course["coursedog_group_id"] == "0045691"


def test_build_course_coursedog_group_id_none_when_absent():
    record = _raw_record()
    del record["courseGroupId"]
    course, _ = smu.build_course(record, source_last_checked="2026-08-17")
    assert course["coursedog_group_id"] is None
