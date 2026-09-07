"""POST /api/v2/student/me/planned-courses -- the force_planned year-view path.

The guarantee under test: force_planned=True must produce a planned_courses
row and never a course_records write, for ANY term, including one already
inside its 30-day activation window (where the default TermPlanner path
promotes straight to course_records as in_progress). The default path -- no
force_planned -- must keep that promotion behavior exactly.

Write-capable fake Supabase client, same shape as test_lifecycle.py's.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from GradusIQ_career import api


TEST_PROXY_SECRET = "test-proxy-secret"
PROXY_HEADERS = {api.PROXY_SECRET_HEADER: TEST_PROXY_SECRET}
AUTH = {"Authorization": "Bearer real-session-jwt"}
STUDENT = "stu-1"
INSTITUTION = "inst-1"


# ── fake client (select / insert / upsert / update / delete) ─────────────────


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table):
        self.table = table
        self.filters = []
        self.op = None
        self.payload = None
        self.on_conflict = None
        self.ignore_duplicates = False

    def select(self, *_a, **_k):
        self.op = self.op or "select"
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def upsert(self, payload, *, ignore_duplicates=False, on_conflict="", **_k):
        self.op = "upsert"
        self.payload = payload
        self.ignore_duplicates = ignore_duplicates
        self.on_conflict = on_conflict
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def _matches(self, row):
        return all(row.get(col) == val for col, val in self.filters)

    def execute(self):
        rows = self.table.rows
        if self.op in (None, "select"):
            return FakeResponse([dict(r) for r in rows if self._matches(r)])
        if self.op == "insert":
            row = dict(self.payload)
            row.setdefault("id", f"{self.table.name}-{len(rows) + 1}")
            rows.append(row)
            return FakeResponse([dict(row)])
        if self.op == "upsert":
            cols = tuple(c.strip() for c in (self.on_conflict or "").split(",") if c.strip())
            key = tuple(self.payload.get(c) for c in cols)
            for existing in rows:
                if tuple(existing.get(c) for c in cols) == key:
                    assert self.ignore_duplicates
                    return FakeResponse([])
            row = dict(self.payload)
            row.setdefault("id", f"{self.table.name}-{len(rows) + 1}")
            rows.append(row)
            return FakeResponse([dict(row)])
        if self.op == "update":
            updated = []
            for row in rows:
                if self._matches(row):
                    row.update(self.payload)
                    updated.append(dict(row))
            return FakeResponse(updated)
        if self.op == "delete":
            matched = [r for r in rows if self._matches(r)]
            for r in matched:
                rows.remove(r)
            return FakeResponse(matched)
        raise AssertionError(f"unsupported op {self.op}")


class FakeTable:
    def __init__(self, name, rows):
        self.name = name
        self.rows = list(rows)


class FakeClient:
    def __init__(self, **tables):
        self.tables = {name: FakeTable(name, rows) for name, rows in tables.items()}

    def table(self, name):
        self.tables.setdefault(name, FakeTable(name, []))
        return FakeQuery(self.tables[name])


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


def _fake(term_dates):
    return FakeClient(
        students=[{"id": STUDENT, "name": "Test"}],
        student_institutions=[
            {"student_id": STUDENT, "institution_id": INSTITUTION, "relationship": "home"}
        ],
        academic_terms=[],
        academic_term_dates=term_dates,
        planned_courses=[],
        course_records=[],
    )


def _dates_row(start: date):
    return {
        "institution_id": INSTITUTION,
        "year": 2099,
        "season": "Spring",
        "label": "Spring 2099",
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=100)).isoformat(),
    }


def _post(client, body):
    return client.post("/api/v2/student/me/planned-courses", headers=AUTH, json=body)


# ── the guarantee: force_planned never touches course_records ────────────────


def test_force_planned_inside_activation_window_writes_planned_not_course_records(client, monkeypatch):
    """The one that matters most. Term starts tomorrow -- well inside the
    30-day activation window -- so the DEFAULT path would promote straight to
    course_records. force_planned must still produce a planned_courses row."""
    inside_window = date.today() + timedelta(days=1)
    fake = _fake([_dates_row(inside_window)])
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)

    resp = _post(client, {
        "course_code": "CSCE 469",
        "year": 2099,
        "season": "Spring",
        "title": "Special Topics",
        "credit_hours": 3,
        "force_planned": True,
    })

    assert resp.status_code == 200, resp.text
    course = resp.json()["planned_course"]
    assert course["kind"] == "planned"
    assert course["course_code"] == "CSCE 469"

    planned_rows = fake.tables["planned_courses"].rows
    assert len(planned_rows) == 1
    # The term row was created and the planned row carries its id -- not null.
    assert planned_rows[0]["term_id"] == course["term_id"]
    assert planned_rows[0]["term_id"] is not None
    assert fake.tables["course_records"].rows == []


def test_force_planned_before_activation_also_writes_planned(client, monkeypatch):
    """Parity: outside the window force_planned behaves the same as the
    default would there -- a planned_courses row."""
    far_future = date.today() + timedelta(days=400)
    fake = _fake([_dates_row(far_future)])
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)

    resp = _post(client, {
        "course_code": "CSCE 469", "year": 2099, "season": "Spring",
        "credit_hours": 3, "force_planned": True,
    })

    assert resp.status_code == 200, resp.text
    assert resp.json()["planned_course"]["kind"] == "planned"
    assert len(fake.tables["planned_courses"].rows) == 1
    assert fake.tables["course_records"].rows == []


# ── TermPlanner's default path is unchanged ─────────────────────────────────


def test_default_path_inside_window_still_promotes_to_course_records(client, monkeypatch):
    """No force_planned -- the existing TermPlanner behavior: a term already
    inside its activation window is written straight to course_records as
    in_progress, never through planned_courses."""
    inside_window = date.today() + timedelta(days=1)
    fake = _fake([_dates_row(inside_window)])
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)

    resp = _post(client, {
        "course_code": "CSCE 469", "year": 2099, "season": "Spring", "credit_hours": 3,
    })

    assert resp.status_code == 200, resp.text
    course = resp.json()["planned_course"]
    assert course["kind"] == "in_progress"
    assert course["status"] == "in_progress"
    assert fake.tables["planned_courses"].rows == []
    [record] = fake.tables["course_records"].rows
    assert record["status"] == "in_progress"


def test_default_path_before_activation_writes_planned(client, monkeypatch):
    far_future = date.today() + timedelta(days=400)
    fake = _fake([_dates_row(far_future)])
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)

    resp = _post(client, {
        "course_code": "CSCE 469", "year": 2099, "season": "Spring", "credit_hours": 3,
    })

    assert resp.status_code == 200, resp.text
    assert resp.json()["planned_course"]["kind"] == "planned"
    assert len(fake.tables["planned_courses"].rows) == 1
    assert fake.tables["course_records"].rows == []
