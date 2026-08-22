"""Tests for GET /api/v2/student/me/requirement-satisfaction (GradusIQ_career/api.py).

The Supabase client is fully mocked -- no network calls, no real Supabase
project involved. Follows the FakeClient pattern established in
tests/test_api_v2_gpa.py, extended with .in_() since
requirement_satisfaction_fetch.fetch_requirement_tree() needs it.

The success-path fixture is tests/fixtures/ethan_brooks_requirement_tree.json
-- the same real 23-group SMU CS-BS tree / 8 course_records ground truth
tests/test_requirement_satisfaction.py checks evaluate_requirement_tree()
against directly, reused here so this test exercises the real fetch ->
evaluate wiring rather than a second hand-built tree.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from GradusIQ_career import api

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ethan_brooks_requirement_tree.json"
SMU_INSTITUTION_ID = "inst-smu"
TAMU_INSTITUTION_ID = "inst-tamu"
CATALOG_YEAR = "2026-2027"
TEST_PROXY_SECRET = "test-proxy-secret"
PROXY_HEADERS = {api.PROXY_SECRET_HEADER: TEST_PROXY_SECRET}


# ---------------------------------------------------------------------------
# Fake Supabase client
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *args, **kwargs):
        return self

    def eq(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) == value]
        return self

    def in_(self, key, values):
        values = list(values)
        self._rows = [r for r in self._rows if r.get(key) in values]
        return self

    def execute(self):
        return FakeResponse(self._rows)


class FakeClient:
    def __init__(self, tables: dict):
        self._tables = tables

    def table(self, name):
        return FakeQuery(self._tables.get(name, []))


def _fixture():
    return json.loads(FIXTURE_PATH.read_text())


def _catalog_rows(catalog_by_gid, institution_id):
    return [
        {"institution_id": institution_id, "code": code, "coursedog_group_id": gid}
        for gid, code in catalog_by_gid.items()
    ]


def ethan_brooks_tables():
    fixture = _fixture()
    student_id = fixture["student_id"]
    program_id = fixture["program_id"]
    return {
        "students": [{"id": student_id, "name": "Ethan Brooks"}],
        "student_institutions": [
            {
                "student_id": student_id,
                "institution_id": SMU_INSTITUTION_ID,
                "relationship": "home",
                "catalog_year": CATALOG_YEAR,
            }
        ],
        "programs": [
            {"id": program_id, "institution_id": SMU_INSTITUTION_ID, "catalog_year": CATALOG_YEAR}
        ],
        "requirement_groups": fixture["groups"],
        "requirement_group_options": fixture["options"],
        "requirement_group_option_courses": fixture["option_courses"],
        "course_records": fixture["course_records"],
        "course_catalog": _catalog_rows(fixture["catalog_by_gid"], SMU_INSTITUTION_ID),
    }, student_id, program_id


def student_with_no_program_tables(student_id="stu-tamu"):
    """A student whose home institution has no matching `programs` row --
    the state every real student except Ethan Brooks is in today."""
    return {
        "students": [{"id": student_id, "name": "TAMU Student"}],
        "student_institutions": [
            {
                "student_id": student_id,
                "institution_id": TAMU_INSTITUTION_ID,
                "relationship": "home",
                "catalog_year": CATALOG_YEAR,
            }
        ],
        "programs": [],
        "requirement_groups": [],
        "requirement_group_options": [],
        "requirement_group_option_courses": [],
        "course_records": [],
        "course_catalog": [],
    }


def make_test_config(**overrides):
    values = {
        "proxy_secret": TEST_PROXY_SECRET,
        "allowed_origins": ("https://frontend.example",),
        "rate_limit_requests": 100,
        "rate_limit_window_seconds": 60.0,
        "max_concurrent_ai_requests": 2,
    }
    values.update(overrides)
    return api.APIConfig(**values)


@pytest.fixture
def client():
    return TestClient(api.create_app(make_test_config()), headers=PROXY_HEADERS)


def _patch_client(monkeypatch, tables):
    fake = FakeClient(tables)
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)
    return fake


URL = "/api/v2/student/me/requirement-satisfaction"


# 0. Missing proxy secret -> 401, matching every other v2 route.
def test_missing_proxy_secret_returns_401():
    unauth = TestClient(api.create_app(make_test_config()))
    response = unauth.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 401


# 1. Missing Authorization header -> 401.
def test_missing_authorization_header_returns_401(client):
    response = client.get(URL)
    assert response.status_code == 401


# 2. Malformed Authorization header -> 401.
@pytest.mark.parametrize("header_value", ["", "Token abc123", "Bearer", "Bearer   ", "abc123"])
def test_malformed_authorization_header_returns_401(client, header_value):
    response = client.get(URL, headers={"Authorization": header_value})
    assert response.status_code == 401


# 3. Valid token, no visible students row -> 404.
def test_no_visible_student_row_returns_404(client, monkeypatch):
    tables, _student_id, _program_id = ethan_brooks_tables()
    tables["students"] = []
    _patch_client(monkeypatch, tables)

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 404


# 4. Ethan Brooks / SMU CS-BS -> 200, full satisfaction result.
def test_ethan_brooks_returns_full_satisfaction_result(client, monkeypatch):
    tables, student_id, program_id = ethan_brooks_tables()
    _patch_client(monkeypatch, tables)

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()

    assert set(body.keys()) == {"student_id", "program_id", "groups"}
    assert body["student_id"] == student_id
    assert body["program_id"] == program_id

    def count_nodes(groups):
        return len(groups) + sum(count_nodes(g["children"]) for g in groups)

    assert len(body["groups"]) == 7  # top-level groups
    assert count_nodes(body["groups"]) == 23  # matches test_requirement_satisfaction.py

    by_name = {}

    def index(groups):
        for g in groups:
            by_name[g["name"]] = g
            index(g["children"])

    index(body["groups"])

    assert by_name["Lyle EDGE Curriculum (9-13 Credit Hours)"]["status"] == "IN_PROGRESS"
    assert by_name["Lyle EDGE Curriculum (9-13 Credit Hours)"]["detail"] == "2 of 6 children satisfied"
    assert by_name["AI Fundamentals (3 Credit Hours)"]["status"] == "SATISFIED"
    assert by_name["AI Fundamentals (3 Credit Hours)"]["matched_course_codes"] == ["CS 1311"]


# 5. A student whose institution has no matching `programs` row (every real
#    student today except Ethan Brooks) -> 200, skipped, not an error.
def test_no_program_data_returns_200_skipped(client, monkeypatch):
    _patch_client(monkeypatch, student_with_no_program_tables())

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()

    assert body["feature"] == "REQUIREMENT_SATISFACTION"
    assert body["status"] == "skipped"
    assert body["data"] == {}
    assert "not available" in body["summary"] or "isn't available" in body["summary"]
    assert body["missing_fields"]


# 6. A student with no home institution at all -> also 200, skipped.
def test_no_home_institution_returns_200_skipped(client, monkeypatch):
    tables = student_with_no_program_tables()
    tables["student_institutions"] = []
    _patch_client(monkeypatch, tables)

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "skipped"
