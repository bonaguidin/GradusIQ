"""Tests for GET /api/v2/student/me/schedule (GradusIQ_career/api.py).

Mirrors test_api_v2_requirement_satisfaction.py's FakeClient/monkeypatch
convention exactly, reusing its ethan_brooks_tables() as the base and
extending it with the tables this route additionally needs: institutions
(for LocalCatalogRepository institution resolution), students.expected_
graduation, academic_term_dates (for the starting-term horizon), and
course_catalog rows widened with real credit_min/credit_max pulled from
data/catalog/smu/*.json (see the build task's investigation -- all 63
coursedog_group_ids in the shared fixture resolve cleanly against the real
catalog with matching codes).
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from GradusIQ_career import api
from GradusIQ_career.course_discovery.models import CareerSkillNeed, EvidenceState
from GradusIQ_career.course_discovery.requirement_candidate_ranking import (
    RankedRequirementCandidate,
    RequirementCandidateRanking,
)
from test_api_v2_me_routes import _canonical_profile
from test_api_v2_requirement_satisfaction import (
    CATALOG_YEAR,
    PROXY_HEADERS,
    SMU_INSTITUTION_ID,
    TEST_PROXY_SECRET,
    FakeClient,
    ethan_brooks_tables,
    make_test_config,
    student_with_no_program_tables,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ethan_brooks_requirement_tree.json"
SCHEDULE_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ethan_brooks_scheduler_input.json"
URL = "/api/v2/student/me/schedule"
OPTIMIZE_URL = "/api/v2/student/me/schedule/career-optimize"
TECHNICAL_ELECTIVES_URL = "/api/v2/student/me/degree-plan/technical-electives"

# Real credit_min/credit_max per coursedog_group_id, cross-referenced against
# every entry in the shared fixture's catalog_by_gid (63 gids, all resolve
# cleanly, all codes match) directly from data/catalog/smu/*.json.
_REAL_CREDIT_ROWS = json.loads((Path(__file__).parent / "fixtures" / "smu_catalog_credit_rows.json").read_text())

# Six long terms, Fall 2026 (the real upcoming term as of the fixture's
# 2026-08-19 pull date) through Spring 2029 -- matches spec §10.1's "5 terms,
# comfortably inside the 6-term horizon to Spring 2029" worked example.
_SMU_TERM_DATES = [
    {"institution_id": SMU_INSTITUTION_ID, "year": 2026, "season": "Fall", "label": "Fall 2026", "start_date": "2026-08-24", "end_date": "2026-12-12"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2027, "season": "Spring", "label": "Spring 2027", "start_date": "2027-01-19", "end_date": "2027-05-08"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2027, "season": "Fall", "label": "Fall 2027", "start_date": "2027-08-23", "end_date": "2027-12-11"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2028, "season": "Spring", "label": "Spring 2028", "start_date": "2028-01-18", "end_date": "2028-05-06"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2028, "season": "Fall", "label": "Fall 2028", "start_date": "2028-08-21", "end_date": "2028-12-09"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2029, "season": "Spring", "label": "Spring 2029", "start_date": "2029-01-16", "end_date": "2029-05-05"},
]


def _schedule_tables(expected_graduation="Spring 2029"):
    tables, student_id, program_id = ethan_brooks_tables()
    tables["institutions"] = [{"id": SMU_INSTITUTION_ID, "name": "Southern Methodist University"}]
    tables["students"][0]["expected_graduation"] = expected_graduation
    tables["academic_terms"] = []
    tables["academic_term_dates"] = _SMU_TERM_DATES
    tables["course_catalog"] = [
        {"institution_id": SMU_INSTITUTION_ID, "code": row["code"], "coursedog_group_id": row["coursedog_group_id"], "credit_min": row["credit_min"], "credit_max": row["credit_max"]}
        for row in _REAL_CREDIT_ROWS
    ]
    return tables, student_id, program_id


@pytest.fixture
def client():
    return TestClient(api.create_app(make_test_config()), headers=PROXY_HEADERS)


def _patch_client(monkeypatch, tables):
    fake = FakeClient(tables)
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)
    return fake


# 1. Ethan Brooks -- 200, full ScheduleResult including deterministic
#    structured choices while preserving the response contract.
def test_ethan_brooks_returns_full_schedule_result(client, monkeypatch):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()

    assert body["student_id"] == student_id
    assert body["program_id"] == program_id
    assert body["status"] == "SCHEDULED"
    assert body["failure"] is None

    assert {u["name"] for u in body["unscheduled"]} == {
        "Technical Electives (9 Credit Hours)",
        "Advanced Major Electives (3-5 Credit Hours)",
    }
    assert len(body["unscheduled"]) == 2

    scheduled_codes = {course["course_code"] for term in body["terms"] for course in term["courses"]}
    schedule_fixture = json.loads(SCHEDULE_FIXTURE_PATH.read_text())
    expected_codes = {row["course_code"] for row in schedule_fixture["courses"]}
    selected_codes = {
        "CS 5323", "ENGR 1199", "CS 4340", "BIOL 1301", "BIOL 1101",
        "BIOL 1302", "BIOL 1102", "CEE 2302", "CS 3377",
    }
    assert scheduled_codes == expected_codes | selected_codes
    assert len(scheduled_codes) == 22

    # Structured selection consumes the existing slack without extending
    # the corrected four-term plan.
    assert len(body["terms"]) == 4
    assert body["terms"][0]["term_key"] == "2026-Fall"
    by_term = {
        term["term_key"]: {course["course_code"] for course in term["courses"]}
        for term in body["terms"]
    }
    assert by_term == {
        "2026-Fall": {"BIOL 1101", "BIOL 1102", "BIOL 1301", "BIOL 1302", "CEE 2302", "CS 2341", "ENGR 1199"},
        "2027-Spring": {"CS 2353", "CS 3341", "CS 3377", "CS 4340", "CS 5323"},
        "2027-Fall": {"CS 3353", "CS 5328", "CS 5330", "CS 5344", "ENGR 2112", "ENGR 3101", "ENGR 4101"},
        "2028-Spring": {"CS 5343", "CS 5351", "MATH 3304"},
    }
    assert {"CS 5328", "CS 5330"} <= by_term["2027-Fall"]
    for term in body["terms"]:
        assert term["total_credit_hours"] <= 15.0


def test_ethan_technical_elective_pool_is_read_only_and_catalog_grounded(client, monkeypatch):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    before = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()

    response = client.get(TECHNICAL_ELECTIVES_URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == student_id
    assert body["program_id"] == program_id
    assert body["catalog_year"] == CATALOG_YEAR
    assert body["requirement_name"] == "Technical Electives (9 Credit Hours)"
    assert body["credits_required"] == 9
    assert body["review_required"] is True
    assert body["institution"] == "smu"
    assert body["candidates"]
    assert all(item["course_code"].startswith("CS ") for item in body["candidates"])
    assert all(int(item["course_code"].split()[1]) >= 3000 for item in body["candidates"])
    assert all(item["credit_max"] > 0 for item in body["candidates"])
    assert len(body["limitations"]) == 3
    assert body["stats"] == {
        "catalog_courses_considered": 3249,
        "cs_3000_plus_courses": 87,
        "excluded_already_used": 10,
        "excluded_zero_credit": 1,
        "excluded_restriction_or_review": 46,
        "candidate_count": 30,
    }

    after = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert after == before
    assert sum(len(term["courses"]) for term in after["terms"]) == 22
    assert sum(term["total_credit_hours"] for term in after["terms"]) == 54
    assert len(after["terms"]) == 4
    assert len(after["unscheduled"]) == 2


def test_technical_elective_endpoint_is_model_free(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("candidate GET must not build a model"))
    monkeypatch.setattr(
        api, "rank_requirement_candidates",
        lambda *args, **kwargs: pytest.fail("candidate GET must not invoke ranking"),
    )
    response = client.get(TECHNICAL_ELECTIVES_URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    assert response.json()["stats"]["candidate_count"] == 30


def test_missing_technical_elective_requirement_skips_safely(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables()
    tables["requirement_groups"] = [
        row for row in tables["requirement_groups"]
        if row.get("coursedog_rule_id") != "AjzAZTn4"
    ]
    _patch_client(monkeypatch, tables)
    response = client.get(TECHNICAL_ELECTIVES_URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"


def test_get_schedule_is_strictly_model_and_optimization_free(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("GET must not build a model client"))
    monkeypatch.setattr(
        api, "rank_requirement_candidates",
        lambda *args, **kwargs: pytest.fail("GET must not rank candidates"),
    )
    client.app.state.career_optimization = type("Forbidden", (), {
        "run": lambda *args, **kwargs: pytest.fail("GET must not touch optimization cache")
    })()
    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    assert len(response.json()["terms"]) == 4


def _trusted_need():
    return CareerSkillNeed(
        skill="Software design", category="skills",
        target_role="Software Engineering Intern", importance="required",
        evidence_state=EvidenceState.VERIFIED_LOCAL,
        evidence_source="O*NET trusted", confidence=.9,
    )


def _fake_valid_ranker(_client, candidate_set, **_kwargs):
    return RequirementCandidateRanking(
        requirement_group_id=candidate_set.requirement_group_id,
        ranked_candidates=[
            RankedRequirementCandidate(
                candidate_id=candidate.candidate_id, rank=index,
                ranking_reason="Synthetic test preference.",
                skill_alignment_explanation="Synthetic trusted-need alignment.",
            )
            for index, candidate in enumerate(reversed(candidate_set.feasible_candidates), 1)
        ],
    )


def _patch_career_context(monkeypatch, *, roles=("Software Engineering Intern",), confirmed=True):
    profile = _canonical_profile()
    profile.career.confirmed = confirmed
    profile.career.target_roles = list(roles)
    monkeypatch.setattr(api, "build_student_intelligence_profile", lambda client, student_id: profile)
    monkeypatch.setattr(api, "derive_career_skill_needs", lambda profile, role: [_trusted_need()])


def test_career_optimize_returns_typed_preview_and_cache_hit(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _patch_career_context(monkeypatch)
    monkeypatch.setattr(api, "build_client", lambda: object())
    calls = []
    monkeypatch.setattr(
        api, "rank_requirement_candidates",
        lambda *args, **kwargs: calls.append(args[1].requirement_group_id) or _fake_valid_ranker(*args, **kwargs),
    )
    first = client.post(
        OPTIMIZE_URL, json={"target_role": "Software Engineering Intern"},
        headers={"Authorization": "Bearer good-token"},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["feature"] == "CAREER_OPTIMIZED_SCHEDULE"
    assert body["status"] == "OPTIMIZED"
    assert body["selection_basis"] == "CAREER_RANKED"
    assert body["cache_status"] == "MISS"
    assert body["fingerprint"] and body["ranking_prompt_version"] == "1"
    assert len(body["academic_schedule"]["terms"]) == 4
    assert len(body["optimized_schedule"]["terms"]) == 4
    assert len(body["academic_schedule"]["unscheduled"]) == 2
    assert len(body["requirement_rankings"]) == len(calls) == 4
    initial_calls = len(calls)

    second = client.post(
        OPTIMIZE_URL, json={}, headers={"Authorization": "Bearer good-token"},
    )
    assert second.status_code == 200
    assert second.json()["cache_status"] == "HIT"
    assert len(calls) == initial_calls


def test_career_optimize_force_refresh_and_full_failure_preserve_ethan_baseline(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _patch_career_context(monkeypatch)
    monkeypatch.setattr(api, "build_client", lambda: object())
    monkeypatch.setattr(api, "rank_requirement_candidates", lambda *args, **kwargs: None)
    response = client.post(
        OPTIMIZE_URL, json={"force_refresh": True},
        headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FALLBACK"
    assert body["selection_basis"] == "ACADEMIC_DEFAULT"
    assert body["cache_status"] == "BYPASSED"
    assert body["optimized_schedule"] == body["academic_schedule"]
    schedule = body["academic_schedule"]
    courses = [course for term in schedule["terms"] for course in term["courses"]]
    assert len(courses) == 22
    assert sum(course["credit_hours"] for course in courses) == 54
    assert len(schedule["terms"]) == 4
    assert len(schedule["unscheduled"]) == 2


@pytest.mark.parametrize("roles,body,summary_fragment", [
    ((), {}, "Confirm a target role"),
    (("Software Engineering Intern", "Data Scientist Intern"), {}, "Choose which"),
    (("Software Engineering Intern",), {"target_role": "NVIDIA Robotics Engineer"}, "not confirmed"),
])
def test_career_optimize_handles_missing_ambiguous_and_unconfirmed_roles_safely(
    client, monkeypatch, roles, body, summary_fragment
):
    tables, _student_id, _program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _patch_career_context(monkeypatch, roles=roles)
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("skipped must not build a model"))
    response = client.post(
        OPTIMIZE_URL, json=body, headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SKIPPED"
    assert summary_fragment in response.json()["summary"]


@pytest.mark.parametrize("injection", [
    {"candidate_ids": ["fake"]}, {"course_codes": ["CS 9999"]},
    {"requirement_ids": ["fake"]}, {"student_id": "someone-else"},
])
def test_career_optimize_rejects_client_academic_authority(client, injection):
    response = client.post(
        OPTIMIZE_URL, json=injection, headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 422


# 2. No program data (every real student except Ethan Brooks) -> 200, skipped.
def test_no_program_data_returns_200_skipped(client, monkeypatch):
    _patch_client(monkeypatch, student_with_no_program_tables())

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "SCHEDULE"
    assert body["status"] == "skipped"


# 3. Program data present but no expected_graduation on record -> 200, skipped.
def test_no_expected_graduation_returns_200_skipped(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables(expected_graduation=None)
    _patch_client(monkeypatch, tables)

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "SCHEDULE"
    assert body["status"] == "skipped"
    assert body["missing_fields"][0]["path"] == "students.expected_graduation"


# 4. Over-constrained: an expected_graduation in the immediate past relative
#    to the starting term forces max_terms down to 0 against a non-empty
#    course list -- schedule_courses()'s own over-constrained detection
#    fires, and the route returns 200 with the ERROR payload intact, not a
#    4xx/5xx.
def test_over_constrained_returns_200_with_error_payload(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables(expected_graduation="Fall 2025")
    _patch_client(monkeypatch, tables)

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "ERROR"
    assert body["terms"] == []
    assert body["unscheduled"] == []
    assert body["failure"] is not None
    assert body["failure"]["error_class"]
