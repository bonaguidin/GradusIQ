import re

from GradusIQ_career.course_discovery.models import CatalogInstitution, CourseCatalogRecord
from GradusIQ_career.course_discovery.technical_elective_candidates import (
    TechnicalElectiveEligibility,
    course_subject_and_number,
    generate_technical_elective_candidates,
)


def _course(code, *, credits=3, prerequisites=None, restrictions=None, year="2026-2027"):
    return CourseCatalogRecord(
        institution=CatalogInstitution.SMU,
        course_code=code,
        title=f"Title for {code}",
        description="",
        department=code.split()[0],
        credit_min=credits,
        credit_max=credits,
        course_level=int(code.split()[1][0]) * 100 if " " in code else None,
        prerequisite_text=prerequisites,
        prerequisite_courses=re.findall(r"[A-Z]{2,8}\s+\d{4}", prerequisites or ""),
        restrictions=restrictions or [],
        catalog_year=year,
        source_url="https://catalog.smu.edu/",
        source_last_checked="2026-08-22",
    )


def _generate(courses, *, completed=(), planned=()):
    return generate_technical_elective_candidates(
        student_id="student", program_id="program", requirement_group_id="technical",
        requirement_name="Technical Electives (9 Credit Hours)", catalog_year="2026-2027",
        catalog_courses=courses, completed_or_in_progress_codes=completed,
        planned_or_selected_codes=planned,
    )


def test_course_number_parser_is_exact_and_safe():
    assert course_subject_and_number("CS 1341") == ("CS", 1341)
    assert course_subject_and_number("CS 2341") == ("CS", 2341)
    assert course_subject_and_number("CS 3341") == ("CS", 3341)
    assert course_subject_and_number("CS 4341") == ("CS", 4341)
    assert course_subject_and_number("CS 5341") == ("CS", 5341)
    assert course_subject_and_number(" cs   5323 ") == ("CS", 5323)
    assert course_subject_and_number("CS 4340/STAT 4340") is None
    assert course_subject_and_number("CS 999") is None


def test_filters_subject_level_year_credit_usage_and_manual_restrictions():
    result = _generate([
        _course("CS 2341"), _course("CS 3341"), _course("MATH 3304"),
        _course("CS 4000", credits=0), _course("CS 4390", restrictions=["Permission required"]),
        _course("CS 5000", year="2025-2026"),
    ], completed={"CS 3341"})
    assert result.candidates == []
    assert result.stats.cs_3000_plus_courses == 3
    assert result.stats.excluded_already_used == 1
    assert result.stats.excluded_zero_credit == 1
    assert result.stats.excluded_restriction_or_review == 1


def test_prerequisite_states_and_order_are_deterministic():
    result = _generate([
        _course("CS 5002", prerequisites="Prerequisite: CS 4002."),
        _course("CS 5001"),
        _course("CS 5003", prerequisites="Prerequisite: CS 4003."),
    ], completed={"CS 4002"}, planned={"CS 4003"})
    assert [item.course_code for item in result.candidates] == ["CS 5001", "CS 5002", "CS 5003"]
    assert [item.eligibility for item in result.candidates] == [
        TechnicalElectiveEligibility.READY,
        TechnicalElectiveEligibility.READY,
        TechnicalElectiveEligibility.PREREQUISITES_PLANNED,
    ]
    assert result.candidates[2].planned_prerequisite_codes == ["CS 4003"]


def test_missing_prerequisite_is_visible_and_not_auto_added():
    result = _generate([_course("CS 5004", prerequisites="Prerequisite: CS 4004 or CS 4005.")])
    candidate = result.candidates[0]
    assert candidate.eligibility == TechnicalElectiveEligibility.PREREQUISITES_MISSING
    assert candidate.missing_prerequisite_options == [["CS 4004", "CS 4005"]]
    assert result.stats.candidate_count == 1


def test_order_is_stable_across_input_order():
    courses = [_course("CS 5003"), _course("CS 5001"), _course("CS 5002")]
    forward = _generate(courses)
    reverse = _generate(reversed(courses))
    assert [item.course_code for item in forward.candidates] == ["CS 5001", "CS 5002", "CS 5003"]
    assert forward == reverse
