"""Tests for the session-scoped /api/v2/student/me/* routes.

These serve real, Postgres-backed students. Identity comes from the bearer
token via RLS -- there is no slug in the path -- so they cover the half of the
space the slug-addressed routes structurally cannot reach.
"""

import json
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from GradusIQ_career import api
from GradusIQ_career.ai import chat_tools
from GradusIQ_career.ai.errors import AIRequestError
from GradusIQ_career.ai.types import AIMessageResponse, AIResponse
from GradusIQ_career.student_intelligence_profile import StudentIntelligenceProfile
from GradusIQ_career.supabase_client import SupabaseConfigError


TEST_PROXY_SECRET = "test-proxy-secret"
PROXY_HEADERS = {api.PROXY_SECRET_HEADER: TEST_PROXY_SECRET}
AUTH = {"Authorization": "Bearer real-session-jwt"}
STUDENT_UUID = "8f14e45f-ceea-467a-9f0e-1c2d3e4f5a6b"

ME_ROUTES = [
    ("post", "/api/v2/student/me/analyze/gap", None),
    ("post", "/api/v2/student/me/chat", {"message": "hi", "history": []}),
    ("get", "/api/v2/student/me/profile", None),
    ("post", "/api/v2/student/me/action-plan", None),
    ("get", "/api/v2/student/me/career-role-options", None),
    ("get", "/api/v2/student/me/job-search?role=Software+Engineering+Intern", None),
]
ME_IDS = ["analyze", "chat", "profile", "action-plan", "role-options", "job-search"]


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


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "CACHED_ANALYSIS_DIR", tmp_path)
    return tmp_path


FEATURE_JSON = json.dumps(
    {
        "summary": "LIVE-RESULT",
        "data": {
            "readiness_score": 6,
            "strengths": [],
            "must_have_gaps": [],
            "nice_to_have_gaps": [],
            "recommended_next_steps": [],
            "role_matches": [
                {
                    "role": "SWE Intern",
                    "fit_level": "medium",
                    "rationale": "Python experience supports the role.",
                    "supporting_signals": ["Python"],
                    "missing_signals": ["Production experience"],
                }
            ],
            "overall_fit_summary": "ok",
            "role_evolution_summary": "ok",
            "task_shifts": [],
            "durable_skills": [],
            "adjacent_paths": [],
            "ai_fluency_guidance": [],
            "themes": [],
            "overall_summary": "ok",
        },
    }
)

GAP_JSON = json.dumps(
    {
        "summary": "LIVE-RESULT",
        "data": {
            "readiness_score": 6,
            "strengths": [],
            "must_have_gaps": [],
            "nice_to_have_gaps": [],
            "recommended_next_steps": [],
        },
    }
)

SHIFT_JSON = json.dumps(
    {
        "summary": "LIVE-RESULT",
        "data": {
            "role_evolution_summary": "Roles are changing.",
            "task_shifts": [],
            "durable_skills": [],
            "adjacent_paths": [],
            "ai_fluency_guidance": [],
        },
    }
)


class ToolLoopCompat:
    """Authenticated chat offers lookup tools, so the runtime calls
    complete_message_with_metadata; these fakes answer it with plain text."""

    def complete_message_with_metadata(self, **kwargs):
        kwargs.pop("extra_body", None)
        response = self.complete(**kwargs)
        return AIMessageResponse(message={"role": "assistant", "content": response.text}, model=response.model)


class FakeAI(ToolLoopCompat):
    def __init__(self, text=None):
        self.text = text
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        text = self.text
        if text is None:
            blob = " ".join(message.get("content", "") for message in kwargs.get("messages", []))
            if '"feature": "GAP"' in blob:
                text = GAP_JSON
            elif '"feature": "SHIFT"' in blob:
                text = SHIFT_JSON
            else:
                text = FEATURE_JSON
        return AIResponse(text=text, raw={"choices": []}, model="fake-model")


def _full_profile():
    return {
        "student": {
            "id": STUDENT_UUID,
            "name": "Real Student",
            "classification": "Junior",
            "major_current": "Computer Science",
            "major_intended": "Computer Science",
            "expected_graduation": "2028-05",
            "onboarding_stage": 3,
            "institution": "Texas A&M University",
            "gpa_current": None,
        },
        "career": {
            "target_roles": ["Software Engineering Intern"],
            "interests": ["backend"],
            "career_goals": "Ship things.",
            "geographic_preference": "DFW",
            "ai_anxiety_level": "low",
            "skills_self_reported": {
                "technical": ["Python"],
                "soft": ["communication"],
                "ai_exposure": "some",
            },
            "certifications": [],
            "work_experience": [{"employer": "Acme", "role": "Intern"}],
            "projects": [],
        },
    }


def _canonical_profile():
    return StudentIntelligenceProfile.model_validate(
        {
            "identity": {
                "student_id": STUDENT_UUID,
                "name": "Real Student",
                "classification": "Junior",
                "expected_graduation": "2028-05",
            },
            "institution": {"name": "Texas A&M University"},
            "academics": {
                "summary": {
                    "major_current": "Computer Science",
                    "major_intended": "Computer Science",
                    "confirmed_course_count": 1,
                },
                "terms": [],
                "courses": [{
                    "id": "course-1", "course_code": "CSCE 120", "title": "Program Design",
                    "credit_hours": 4, "letter_grade": "A", "credit_type": "resident",
                    "status": "completed", "source": "transcript_parse",
                }],
                "gpa": {"official": 4.0, "projected": 4.0, "computable": True},
            },
            "career": {
                "confirmed": True,
                "target_roles": ["Software Engineering Intern"], "interests": ["backend"],
                "career_goals": "Ship things.", "geographic_preference": "DFW",
                "ai_anxiety_level": "low",
                "skills": {"technical": ["Python"], "soft": ["communication"], "ai_exposure": "some"},
                "work_experience": [{"employer": "Acme", "role": "Intern"}],
            },
            "completeness": {
                "career": {
                    "confirmed_profile": True, "target_role_present": True, "skills_present": True,
                    "certifications_present": False, "work_experience_present": True,
                    "projects_present": False, "ready_for_career_features": True,
                },
                "academics": {
                    "transcript_data_present": True, "terms_present": False,
                    "gpa_computable": True, "ready_for_academic_features": False,
                },
                "overall": "partial",
            },
            "provenance": {},
        }
    )


def _patch_session(monkeypatch, profile=None, student_rows=None):
    """Stub the session client + builder, leaving route logic real."""
    rows = [{"id": STUDENT_UUID}] if student_rows is None else student_rows

    class _Client:
        def table(self, name):
            return self

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def execute(self):
            class _R:
                data = rows

            return _R()

    monkeypatch.setattr(api, "build_client_for_token", lambda token: _Client())
    if profile is not None:
        monkeypatch.setattr(
            api,
            "build_profile_from_supabase",
            lambda client, sid: type("R", (), {"profile": profile})(),
        )
        monkeypatch.setattr(api, "build_student_intelligence_profile", lambda client, sid: _canonical_profile())
        monkeypatch.setattr(api, "canonical_to_legacy_profile", lambda canonical: profile)
    return rows


def _call(client, method, path, body):
    kwargs = {"headers": {**PROXY_HEADERS, **AUTH}}
    if body is not None:
        kwargs["json"] = body
    return getattr(client, method)(path, **kwargs)


# 1. No Authorization header -> 401.
@pytest.mark.parametrize(("method", "path", "body"), ME_ROUTES, ids=ME_IDS)
def test_no_authorization_is_401(method, path, body, client, monkeypatch):
    monkeypatch.setattr(
        api, "build_client_for_token", lambda t: pytest.fail("must not build a client")
    )
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401


# 2. Malformed Authorization -> 401.
@pytest.mark.parametrize("header_value", ["", "Token abc", "Bearer", "Bearer   ", "abc"])
@pytest.mark.parametrize(("method", "path", "body"), ME_ROUTES, ids=ME_IDS)
def test_malformed_authorization_is_401(method, path, body, header_value, client, monkeypatch):
    monkeypatch.setattr(
        api, "build_client_for_token", lambda t: pytest.fail("must not build a client")
    )
    kwargs = {"headers": {**PROXY_HEADERS, "Authorization": header_value}}
    if body is not None:
        kwargs["json"] = body
    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401


# 3. Valid token but no visible students row -> 404.
@pytest.mark.parametrize(("method", "path", "body"), ME_ROUTES, ids=ME_IDS)
def test_no_visible_student_row_is_404(method, path, body, client, monkeypatch):
    _patch_session(monkeypatch, student_rows=[])

    response = _call(client, method, path, body)

    assert response.status_code == 404
    assert "No student profile visible" in response.json()["detail"]


# 4. Valid token, full profile -> 200 with the right shape.
def test_me_profile_returns_the_profile(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())

    response = _call(client, "get", "/api/v2/student/me/profile", None)

    assert response.status_code == 200
    body = response.json()
    assert body["student"]["id"] == STUDENT_UUID
    assert body["student"]["institution"] == "Texas A&M University"
    assert body["career"]["target_roles"] == ["Software Engineering Intern"]
    assert body["intelligence_profile"]["contract_version"] == "1.0"


class _ProfileEditQuery:
    def __init__(self, owner, table):
        self.owner = owner
        self.table = table
        self.operation = "select"
        self.payload = None
        self.filters = []

    def select(self, *args, **kwargs):
        self.operation = "select"
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def in_(self, field, values):
        self.filters.append((field, tuple(values)))
        return self

    def execute(self):
        self.owner.calls.append((self.table, self.operation, self.payload, self.filters))
        if self.table == "student_analysis_cache" and self.owner.fail_cache_delete:
            raise RuntimeError("cache unavailable")
        if self.table == "students" and self.operation == "select":
            data = [{"id": STUDENT_UUID}]
        elif self.table == "career_profiles" and self.operation == "select":
            data = [{"id": "career-id"}]
        else:
            data = []
        return type("Response", (), {"data": data})()


class _ProfileEditClient:
    def __init__(self):
        self.calls = []
        self.fail_cache_delete = False

    def table(self, table):
        return _ProfileEditQuery(self, table)


def _patch_profile_edit(monkeypatch):
    database = _ProfileEditClient()
    monkeypatch.setattr(api, "build_client_for_token", lambda token: database)
    canonical = type(
        "Canonical", (), {"model_dump": lambda self, mode=None: {"contract_version": "1.0"}}
    )()
    monkeypatch.setattr(api, "build_student_intelligence_profile", lambda client, sid: canonical)
    monkeypatch.setattr(api, "canonical_to_legacy_profile", lambda value: _full_profile())
    return database


def test_profile_edit_is_partial_owned_and_refreshes_confirmation(client, monkeypatch):
    database = _patch_profile_edit(monkeypatch)

    response = _call(
        client,
        "patch",
        "/api/v2/student/me/profile",
        {
            "major_intended": "N/A",
            "expected_graduation": "Fall 2029",
            "target_roles": [" Software Engineer ", "Software Engineer", "Product Manager"],
        },
    )

    assert response.status_code == 200
    student_update = next(call for call in database.calls if call[:2] == ("students", "update"))
    assert student_update[2]["major_intended"] == "N/A"
    assert student_update[2]["expected_graduation"] == "Fall 2029"
    assert "major_current" not in student_update[2]
    assert ("id", STUDENT_UUID) in student_update[3]
    career_update = next(
        call for call in database.calls if call[:2] == ("career_profiles", "update")
    )
    assert career_update[2]["confirmed_at"]
    assert career_update[2]["target_roles"] == ["Software Engineer", "Product Manager"]
    assert "ai_anxiety_level" not in career_update[2]
    assert ("student_id", STUDENT_UUID) in career_update[3]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"expected_graduation": "2029-05"},
        {"expected_graduation": "Winter 2029"},
        {"ai_anxiety_level": "extreme"},
        {"major_intended": "   "},
        {"target_roles": [f"Role {i}" for i in range(31)]},
        {"skills_technical": [f"Skill {i}" for i in range(101)]},
    ],
)
def test_profile_edit_rejects_invalid_values_before_writing(client, monkeypatch, payload):
    database = _patch_profile_edit(monkeypatch)

    response = _call(client, "patch", "/api/v2/student/me/profile", payload)

    assert response.status_code == 422
    assert not any(call[1] in {"update", "insert"} for call in database.calls)


def test_profile_edit_accepts_skill_lists_as_long_as_resume_parsing_keeps(client, monkeypatch):
    # Resume parsing stores up to 100 skills; a Career Profile skills edit for
    # that student must save, not 422 on the 30-item cap other lists keep.
    database = _patch_profile_edit(monkeypatch)
    skills = [f"Skill {i}" for i in range(100)]

    response = _call(client, "patch", "/api/v2/student/me/profile", {"skills_technical": skills})

    assert response.status_code == 200
    career_update = next(
        call for call in database.calls if call[:2] == ("career_profiles", "update")
    )
    assert career_update[2]["skills_technical"] == skills


def _cache_deletes(database):
    return [call for call in database.calls if call[:2] == ("student_analysis_cache", "delete")]


@pytest.mark.parametrize("field", ["skills_technical", "skills_soft"])
def test_skills_edit_drops_the_cached_gap_and_fit_results(client, monkeypatch, field):
    # GAP and FIT read the skills lists but the cache key is only the role
    # set, so without this the old results keep being served after an edit.
    database = _patch_profile_edit(monkeypatch)

    response = _call(client, "patch", "/api/v2/student/me/profile", {field: ["Rust"]})

    assert response.status_code == 200
    deletes = _cache_deletes(database)
    assert len(deletes) == 1
    filters = deletes[0][3]
    assert ("student_id", STUDENT_UUID) in filters
    assert ("feature", ("gap", "fit")) in filters
    # Only after the edit itself was written.
    order = [call[:2] for call in database.calls]
    assert order.index(("career_profiles", "update")) < order.index(("student_analysis_cache", "delete"))


@pytest.mark.parametrize(
    "payload",
    [{"major_intended": "N/A"}, {"interests": ["Robotics"]}, {"ai_anxiety_level": "low"}],
)
def test_edits_that_gap_and_fit_do_not_read_keep_the_cache(client, monkeypatch, payload):
    database = _patch_profile_edit(monkeypatch)

    assert _call(client, "patch", "/api/v2/student/me/profile", payload).status_code == 200

    assert _cache_deletes(database) == []


def test_a_failed_cache_invalidation_does_not_fail_the_saved_edit(client, monkeypatch):
    database = _patch_profile_edit(monkeypatch)
    database.fail_cache_delete = True

    response = _call(client, "patch", "/api/v2/student/me/profile", {"skills_technical": ["Rust"]})

    assert response.status_code == 200
    assert _cache_deletes(database)


@pytest.mark.parametrize("feature", ["gap", "fit", "shift", "professor-comments"])
def test_me_analyze_returns_a_feature_result(feature, client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    fit_json = json.dumps(
        {
            "summary": "LIVE-RESULT",
            "data": {
                "role_matches": [
                    {
                        "role": "SWE Intern",
                        "fit_level": "medium",
                        "rationale": "Python experience supports the role.",
                        "supporting_signals": ["Python"],
                        "missing_signals": ["Production experience"],
                    }
                ],
                "overall_fit_summary": "ok",
            },
        }
    )
    payload = {"fit": fit_json, "gap": GAP_JSON, "shift": SHIFT_JSON}.get(feature, FEATURE_JSON)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(payload))

    response = _call(client, "post", f"/api/v2/student/me/analyze/{feature}", None)

    assert response.status_code == 200
    body = response.json()
    expected = {
        "gap": "GAP",
        "fit": "FIT",
        "shift": "SHIFT",
        "professor-comments": "PROFESSOR_COMMENTS",
    }[feature]
    assert body["feature"] == expected
    assert set(body) == {"feature", "status", "summary", "data", "errors", "missing_fields"}
    # Asserted per feature rather than as a blanket 200: professor comments
    # are NOT reachable for a real student. _full_profile() mirrors what
    # build_profile_from_supabase actually returns (student/career/courses),
    # and there is no submissions key in that shape -- nor any table behind
    # it -- so PROFESSOR_COMMENTS skips every time. Asserting only the status
    # code let this test pass while the feature never ran.
    assert body["status"] == {
        "gap": "success",
        "fit": "success",
        "shift": "success",
        "professor-comments": "skipped",
    }[feature]


@pytest.mark.parametrize("feature", ["fit", "gap", "shift"])
def test_authenticated_typed_features_remain_inside_ai_concurrency_gate(feature, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    app = api.create_app(make_test_config(max_concurrent_ai_requests=0))
    response = _call(
        TestClient(app), "post", f"/api/v2/student/me/analyze/{feature}", None
    )
    assert response.status_code == 429
    assert response.json()["detail"] == "AI service is busy; retry later."


@pytest.mark.parametrize("feature", ["fit", "gap", "shift"])
def test_authenticated_career_analysis_is_canonical_first(feature, client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    canonical = object()
    calls = []
    monkeypatch.setattr(
        api,
        "build_student_intelligence_profile",
        lambda client, sid: calls.append(("canonical", sid)) or canonical,
    )
    monkeypatch.setattr(
        api,
        "canonical_to_legacy_profile",
        lambda value: calls.append(("adapter", value)) or _full_profile(),
    )
    monkeypatch.setattr(
        api,
        "build_profile_from_supabase",
        lambda client, sid: pytest.fail("career analysis must not rebuild the legacy profile"),
    )
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())

    response = _call(client, "post", f"/api/v2/student/me/analyze/{feature}", None)

    assert response.status_code == 200
    assert calls == [("canonical", STUDENT_UUID), ("adapter", canonical)]
    assert set(response.json()) == {"feature", "status", "summary", "data", "errors", "missing_fields"}


def test_professor_comments_keeps_legacy_profile_path(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(
        api,
        "build_student_intelligence_profile",
        lambda client, sid: pytest.fail("professor comments are outside Phase 3"),
    )
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())

    response = _call(
        client, "post", "/api/v2/student/me/analyze/professor-comments", None
    )

    assert response.status_code == 200
    assert response.json()["feature"] == "PROFESSOR_COMMENTS"


def test_professor_comments_is_unreachable_for_a_real_student(client, monkeypatch):
    """The honest statement of today's behavior, kept deliberately explicit.

    A real student's profile comes from build_profile_from_supabase, whose
    dict has exactly student/career/courses -- Canvas submissions are mocked
    and no submissions/submission_comments table exists in the schema. So this
    route is live, authorized and rate-limited, and returns "skipped" for
    every real student, always, without ever calling the model.

    This asserts the gap rather than papering over it: if a real comment
    source is ever wired in, this test fails and must be updated
    deliberately. If the skip path silently breaks, it fails too.
    """
    _patch_session(monkeypatch, profile=_full_profile())
    ai = FakeAI()
    monkeypatch.setattr(api, "build_client", lambda: ai)

    response = _call(
        client, "post", "/api/v2/student/me/analyze/professor-comments", None
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "skipped"
    assert body["summary"] == "Missing required fields for this feature."
    # Human label over the wire, dotted path beside it. The route is a
    # passthrough, so this is also the assertion that missing_fields survives
    # FeatureResult.to_dict() and FastAPI's serialization.
    assert body["errors"] == ["Missing required field: Course submissions"]
    assert body["missing_fields"] == [
        {"path": "submissions", "label": "Course submissions"}
    ]
    assert body["data"] == {}
    assert ai.calls == []


def test_chat_uses_canonical_profile_path(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(
        api,
        "build_profile_from_supabase",
        lambda client, sid: pytest.fail("legacy builder must not be authoritative for chat"),
    )
    monkeypatch.setattr(api, "build_client", lambda: FakeAI("canonical chat"))

    response = _call(
        client, "post", "/api/v2/student/me/chat", {"message": "hi", "history": []}
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "canonical chat"


@pytest.mark.parametrize("feature", ["fit", "gap", "shift"])
def test_demo_career_analysis_does_not_build_a_canonical_profile(
    feature, client, monkeypatch
):
    profile = _full_profile()
    profile["student"]["id"] = 601
    monkeypatch.setattr(api, "load_profile_for_slug", lambda request, slug: profile)
    monkeypatch.setattr(
        api,
        "build_student_intelligence_profile",
        lambda client, sid: pytest.fail("demo analysis must remain static-JSON-backed"),
    )
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())

    response = client.post(f"/api/students/jordanReyes/analyze/{feature}")

    assert response.status_code == 200
    assert set(response.json()) == {"feature", "status", "summary", "data", "errors", "missing_fields"}


def test_me_chat_returns_a_reply(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    fake = FakeAI("Here is your advice.")
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(
        client, "post", "/api/v2/student/me/chat", {"message": "How ready am I?", "history": []}
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "Here is your advice."
    assert fake.calls[0]["role"] == "chat"
    assert "Real Student" in fake.calls[0]["messages"][0]["content"]


def test_me_chat_sends_gathered_context_to_the_model(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(
        api,
        "_gather_chat_context",
        lambda client, sid, canonical: {"today": "2026-10-24", "saved_analysis": {"GAP": {"summary": "CTX-GAP"}}},
    )
    fake = FakeAI("ok")
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "gaps?", "history": []})

    assert response.status_code == 200
    system = fake.calls[0]["messages"][0]["content"]
    assert "<STUDENT_CONTEXT_DATA>" in system and "CTX-GAP" in system


def test_me_chat_passes_the_open_page_to_the_model(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "_gather_chat_context", lambda client, sid, canonical: {})
    fake = FakeAI("ok")
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(
        client, "post", "/api/v2/student/me/chat",
        {"message": "what is this?", "history": [], "page": "career/intelligence"},
    )

    assert response.status_code == 200
    assert "Career Intelligence (FIT/GAP/SHIFT) page open" in fake.calls[0]["messages"][0]["content"]


def test_me_chat_returns_action_buttons_separately(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "_gather_chat_context", lambda client, sid, canonical: {})
    monkeypatch.setattr(api, "build_client", lambda: FakeAI("Your GPA is 3.4.\nACTIONS: gpa-calculator, made-up"))

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "gpa?", "history": []})

    assert response.status_code == 200
    assert response.json()["reply"] == "Your GPA is 3.4."
    assert response.json()["actions"] == ["gpa-calculator"]


def test_me_chat_requires_a_message(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("must not reach the AI client"))

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "  ", "history": []})

    assert response.status_code == 400


# 5. Unrecognized feature -> 404, not 500.
#
# Values are deliberately single-segment and URL-safe. A value containing "/"
# (e.g. "gap/../fit") cannot reach {feature} as one path segment anyway, and
# sending one makes TestClient follow a redirect chain that never terminates --
# a client artifact, not a route behavior. Traversal is therefore not
# expressible here; the mapping is a dict lookup with four exact keys.
#
# "GAP" and "professor_comments" are the near-misses that matter: the first is
# the internal name leaking into a URL, the second is what
# normalize_feature_name would have accepted. Both must 404.
@pytest.mark.parametrize("bad", ["nope", "GAP", "professor_comments", "Gap", "chat", "profile"])
def test_unknown_feature_is_404_not_500(bad, client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())

    response = _call(client, "post", f"/api/v2/student/me/analyze/{bad}", None)

    assert response.status_code == 404
    assert response.status_code != 500


# 6. A demo cache file for a DIFFERENT numeric-id student must not leak.
def test_uuid_profile_does_not_read_another_students_cache(client, monkeypatch, isolated_cache):
    (isolated_cache / "analysis_jordanReyes.json").write_text(
        json.dumps(
            {
                "student_id": 601,
                "results": {
                    "GAP": {
                        "feature": "GAP",
                        "status": "success",
                        "summary": "CACHED-601-MUST-NOT-APPEAR",
                        "errors": [],
                        "data": {
                            "readiness_score": 9,
                            "strengths": [],
                            "must_have_gaps": [],
                            "nice_to_have_gaps": [],
                            "recommended_next_steps": [],
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    _patch_session(monkeypatch, profile=_full_profile())
    fake = FakeAI()
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(client, "post", "/api/v2/student/me/analyze/gap", None)

    assert response.status_code == 200
    assert "CACHED-601" not in response.text
    assert response.json()["summary"] == "LIVE-RESULT"
    assert len(fake.calls) == 1  # live call was made


# 7. /me/chat must never consult the demo analysis bundles.
def test_me_chat_never_calls_load_analysis_bundle(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(
        api,
        "load_analysis_bundle",
        lambda slug: pytest.fail("me/chat must not read demo analysis bundles"),
    )
    monkeypatch.setattr(api, "build_client", lambda: FakeAI("ok"))

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "hi", "history": []})

    assert response.status_code == 200
    # The prompt carries an empty prior-analysis section, not another
    # student's bundle.
    assert response.json()["reply"] == "ok"


def test_me_chat_retries_inside_concurrency_slot_and_releases(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())

    class TrackingGate:
        active = False
        entries = 0
        exits = 0

        @contextmanager
        def slot(self):
            self.entries += 1
            self.active = True
            try:
                yield
            finally:
                self.active = False
                self.exits += 1

    gate = TrackingGate()
    client.app.state.ai_concurrency = gate
    attempts = 0

    class RetryingAI(ToolLoopCompat):
        def complete(self, **kwargs):
            nonlocal attempts
            attempts += 1
            assert gate.active is True
            if attempts < 3:
                raise AIRequestError("temporary", transient=True)
            return AIResponse(text="recovered", raw={"choices": []}, model="fake-model")

    monkeypatch.setattr(api, "build_client", RetryingAI)
    monkeypatch.setattr("GradusIQ_career.ai.runtime.time.sleep", lambda _: None)

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "hi", "history": []})

    assert response.status_code == 200
    assert attempts == 3
    assert (gate.entries, gate.exits, gate.active) == (1, 1, False)


def test_me_chat_releases_concurrency_slot_after_retry_exhaustion(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())

    class TrackingGate:
        active = False
        exits = 0

        @contextmanager
        def slot(self):
            self.active = True
            try:
                yield
            finally:
                self.active = False
                self.exits += 1

    gate = TrackingGate()
    client.app.state.ai_concurrency = gate

    class FailingAI(ToolLoopCompat):
        def complete(self, **kwargs):
            assert gate.active is True
            raise AIRequestError("temporary", transient=True)

    monkeypatch.setattr(api, "build_client", FailingAI)
    monkeypatch.setattr("GradusIQ_career.ai.runtime.time.sleep", lambda _: None)

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "hi", "history": []})

    assert response.status_code == 502
    assert (gate.exits, gate.active) == (1, False)


@pytest.mark.parametrize(
    "path", ["/api/v2/student/me/analyze/course-discovery", "/api/v2/student/me/action-plan"],
)
def test_unsupported_target_role_skips_before_any_agent_run(path, client, monkeypatch):
    """A confirmed, real target role that role_requirements.json has no
    curated entry for must be distinguished from "no role chosen": the
    student sees a typed skip explaining GradusIQ has no analysis coverage
    for the role, not an empty-looking success. Regression test for the
    exact live E2E finding: Course Discovery silently returned zero verified/
    blocked/unresolved candidates for "Software Engineer", which reads
    identically to "nothing relevant to recommend" -- the real reason was the
    role itself, not the student's profile.
    """
    _patch_session(monkeypatch, profile=_full_profile())
    # _patch_session hardcodes build_student_intelligence_profile to
    # _canonical_profile(); course-discovery/action-plan resolve target_role
    # from THAT canonical model, not the legacy profile dict, so the
    # unsupported role has to be injected there.
    unsupported_canonical = _canonical_profile().model_copy(
        update={"career": _canonical_profile().career.model_copy(update={"target_roles": ["Software Engineer"]})}
    )
    monkeypatch.setattr(api, "build_student_intelligence_profile", lambda client, sid: unsupported_canonical)
    monkeypatch.setattr(api, "list_planned", lambda client, sid: [])
    monkeypatch.setattr(api, "CourseDiscoveryAgent", lambda *a, **k: pytest.fail("must skip before any agent run"))
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("must skip before building an AI client"))

    response = _call(client, "post", path, {"target_role": "Software Engineer"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "skipped"
    assert body["summary"] == "Career analysis isn't available for this target role yet."
    assert body["missing_fields"][0]["path"] == "career.target_roles"
    assert "supported target role" in body["missing_fields"][0]["label"].lower()
    # Not a generic "add this" -- the role IS present, just unsupported.
    assert "Software Engineer" not in body["missing_fields"][0]["label"]


def test_supported_target_role_is_unaffected_by_the_new_gate(client, monkeypatch):
    """The exact same request shape that already worked (curated role)
    continues to reach the agent -- the new gate only intercepts unsupported
    roles, it does not change resolution for supported ones."""
    _patch_session(monkeypatch, profile=_full_profile())  # target_roles: ["Software Engineering Intern"]
    monkeypatch.setattr(api, "list_planned", lambda client, sid: [])

    class Result:
        summary = "ok"

        def model_dump(self, **kwargs):
            return {"target_role": "Software Engineering Intern", "verified_recommendations": []}

    class Agent:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, *, needs, target_role):
            return SimpleNamespace(errors=[], result=Result())

    monkeypatch.setattr(api, "CourseDiscoveryAgent", Agent)
    monkeypatch.setattr(api, "build_client", lambda: object())

    response = _call(
        client, "post", "/api/v2/student/me/analyze/course-discovery",
        {"target_role": "Software Engineering Intern"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_career_role_options_returns_the_curated_vocabulary(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())

    response = _call(client, "get", "/api/v2/student/me/career-role-options", None)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"roles"}
    assert "Software Engineering Intern" in body["roles"]
    assert "Software Engineer" not in body["roles"]
    assert body["roles"] == sorted(body["roles"])


def test_course_discovery_uses_trusted_scope_and_ai_gate(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "list_planned", lambda client, sid: [])

    class Gate:
        active = False
        entries = exits = 0

        @contextmanager
        def slot(self):
            self.entries += 1
            self.active = True
            try:
                yield
            finally:
                self.active = False
                self.exits += 1

    gate = Gate()
    client.app.state.ai_concurrency = gate

    class Result:
        summary = "No verified course matched."

        def model_dump(self, **kwargs):
            return {"target_role": "Software Engineering Intern", "verified_recommendations": []}

    class Agent:
        def __init__(self, service, provider):
            assert service.context.student_id == STUDENT_UUID
            assert service.context.institution.value == "tamu"

        def run(self, *, needs, target_role):
            assert gate.active is True
            assert target_role == "Software Engineering Intern"
            return SimpleNamespace(errors=[], result=Result())

    monkeypatch.setattr(api, "CourseDiscoveryAgent", Agent)
    # The handler builds a real AI client to hand the agent; with the agent
    # mocked, that client is never used, but build_client() still runs and
    # needs OPENROUTER_API_KEY. Stub it so the test exercises trusted scope and
    # the gate without a live-key dependency (CI runs with no env). Same pattern
    # as tests/test_api.py.
    monkeypatch.setattr(api, "build_client", lambda: object())
    response = _call(
        client, "post", "/api/v2/student/me/analyze/course-discovery",
        {"target_role": "Software Engineering Intern"},
    )
    assert response.status_code == 200
    assert set(response.json()) == {"feature", "status", "summary", "data", "errors", "missing_fields"}
    assert (gate.entries, gate.exits, gate.active) == (1, 1, False)


def test_course_discovery_rejects_client_student_id_and_releases_gate_on_failure(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    rejected = _call(
        client, "post", "/api/v2/student/me/analyze/course-discovery",
        {"target_role": "Software Engineering Intern", "student_id": "other-student"},
    )
    assert rejected.status_code == 422

    monkeypatch.setattr(api, "list_planned", lambda client, sid: [])

    class Gate:
        active = False
        exits = 0

        @contextmanager
        def slot(self):
            self.active = True
            try:
                yield
            finally:
                self.active = False
                self.exits += 1

    gate = Gate()
    client.app.state.ai_concurrency = gate

    class Agent:
        def __init__(self, *args):
            pass

        def run(self, **kwargs):
            assert gate.active is True
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(api, "CourseDiscoveryAgent", Agent)
    monkeypatch.setattr(api, "build_client", lambda: object())
    response = _call(
        client, "post", "/api/v2/student/me/analyze/course-discovery",
        {"target_role": "Software Engineering Intern"},
    )
    assert response.status_code == 502
    assert (gate.exits, gate.active) == (1, False)


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v2/student/me/analyze/course-discovery", {"target_role": "Software Engineering Intern"}),
        ("/api/v2/student/me/action-plan", {"target_role": "Software Engineering Intern"}),
    ],
)
def test_course_discovery_and_action_plan_gate_exhaustion_stays_429(path, body, monkeypatch):
    """The concurrency gate's own HTTPException(429) must reach the caller
    unchanged, not be relabeled 502 by _run_course_discovery_agent's except
    Exception -- the same guarantee every other ai_concurrency.slot() call
    site in this file already has (see the "must reach the caller unchanged"
    comment on the chat/typed-feature/resume/transcript handlers). Regression
    test for a real bug found during live E2E validation: with capacity=0 the
    real AIConcurrencyGate.slot() raises HTTPException(429) on entry, which
    _run_course_discovery_agent's bare `except Exception` was swallowing and
    rewrapping as a misleading 502 "Course discovery is unavailable" --
    masking a retryable "busy" state as a hard failure for both the
    Course Discovery panel and the Action Plan preview it feeds.
    """
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "list_planned", lambda client, sid: [])
    app = api.create_app(make_test_config(max_concurrent_ai_requests=0))
    response = _call(TestClient(app), "post", path, body)
    assert response.status_code == 429
    assert response.json()["detail"] == "AI service is busy; retry later."


# 8. SupabaseConfigError -> 503 on all three.
@pytest.mark.parametrize(("method", "path", "body"), ME_ROUTES, ids=ME_IDS)
def test_supabase_config_error_is_503(method, path, body, client, monkeypatch):
    monkeypatch.setattr(
        api,
        "build_client_for_token",
        lambda t: (_ for _ in ()).throw(SupabaseConfigError("SUPABASE_URL is not set.")),
    )

    response = _call(client, method, path, body)

    assert response.status_code == 503
    assert response.status_code != 500
    assert "SUPABASE_URL" in response.json()["detail"]


# Proxy secret still required (these routes carry authorize_proxy_request).
@pytest.mark.parametrize(("method", "path", "body"), ME_ROUTES, ids=ME_IDS)
def test_me_routes_still_require_the_proxy_secret(method, path, body, monkeypatch):
    unauth = TestClient(api.create_app(make_test_config()))
    kwargs = {"headers": AUTH}
    if body is not None:
        kwargs["json"] = body

    response = getattr(unauth, method)(path, **kwargs)

    assert response.status_code == 401


# 10. Plant a cache file at the EXACT path a UUID slug would produce, then
#     assert it is never opened -- pinning the isalnum() rejection mechanism
#     itself, not merely its outcome.
def test_uuid_named_cache_file_is_never_read(client, monkeypatch, isolated_cache):
    planted = isolated_cache / f"analysis_{STUDENT_UUID}.json"
    planted.write_text(
        json.dumps(
            {
                "student_id": STUDENT_UUID,
                "results": {
                    "GAP": {
                        "feature": "GAP",
                        "status": "success",
                        "summary": "PLANTED-UUID-CACHE-MUST-NOT-APPEAR",
                        "errors": [],
                        "data": {
                            "readiness_score": 1,
                            "strengths": [],
                            "must_have_gaps": [],
                            "nice_to_have_gaps": [],
                            "recommended_next_steps": [],
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert planted.exists(), "the file must really be on disk for this test to mean anything"

    # Spy on the read itself, not just the returned value.
    reads: list[str] = []
    original_read_text = Path.read_text

    def spying_read_text(self, *args, **kwargs):
        reads.append(str(self))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spying_read_text)

    _patch_session(monkeypatch, profile=_full_profile())
    fake = FakeAI()
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(client, "post", "/api/v2/student/me/analyze/gap", None)

    assert response.status_code == 200
    # The planted file was never opened -- isalnum() rejected the UUID slug
    # before any path was built.
    assert str(planted) not in reads, f"planted cache file WAS read: {reads}"
    # And its content never surfaced.
    assert "PLANTED-UUID-CACHE" not in response.text
    # A live call happened instead.
    assert len(fake.calls) == 1
    assert response.json()["summary"] == "LIVE-RESULT"


def test_uuid_slug_is_rejected_by_isalnum_directly():
    """The mechanism this route relies on, asserted in isolation."""
    assert not STUDENT_UUID.isalnum()  # hyphens
    assert len(STUDENT_UUID) <= 64  # length alone would have passed
    assert api.load_cached_feature_result(STUDENT_UUID, "GAP", STUDENT_UUID) is None
    assert api.load_analysis_bundle(STUDENT_UUID) == {}


# --- POST /api/v2/student/me/action-plan (feat: expose read-only action-plan preview) ---
# CourseDiscoveryAgent is mocked at the exact same boundary the existing
# course-discovery tests above use (monkeypatch api.CourseDiscoveryAgent),
# but returning a REAL CourseDiscoveryResult so build_action_plan()/
# dependency_order() -- both unmodified, already-tested pure functions --
# actually run for real inside the route.

from GradusIQ_career.action_planning.models import (
    DependencyOrderResult,
    PlanFailure,
    UnifiedActionPlan,
)
from GradusIQ_career.course_discovery.agent_models import (
    CourseDiscoveryResult,
    PrerequisiteBlockedCourse,
    UnresolvedCourseCandidate,
    VerifiedCourseRecommendation,
)
from GradusIQ_career.course_discovery.models import (
    CareerSkillNeed,
    CatalogInstitution,
    CatalogProvenance,
    CourseEligibilityStatus,
    EvidenceState,
    MatchKind,
    PrerequisiteEvaluation,
    PrerequisiteMode,
    PrerequisiteRequirement,
    PrerequisiteStatus,
    StudentCourseState,
)

ACTION_PLAN_TARGET_ROLE = "Software Engineering Intern"  # matches _canonical_profile()'s confirmed target role


def _ap_need(skill="Python"):
    return CareerSkillNeed(
        skill=skill, category="skills", target_role=ACTION_PLAN_TARGET_ROLE,
        importance="required", evidence_state=EvidenceState.VERIFIED_LOCAL,
        evidence_source="O*NET 15-1252.00 onet",
    )


def _ap_provenance(course_code):
    return CatalogProvenance(
        institution=CatalogInstitution.TAMU, course_code=course_code,
        catalog_year="2026-2027",
        source_url="https://catalog.tamu.edu/undergraduate/course-descriptions/",
        source_last_checked="2026-06-20",
    )


def _ap_verified(course_code, need, *, prerequisite_evaluation=None, student_status=StudentCourseState.NOT_TAKEN):
    evaluation = prerequisite_evaluation or PrerequisiteEvaluation(
        status=PrerequisiteStatus.ELIGIBLE, requirement=PrerequisiteRequirement(mode=PrerequisiteMode.NONE),
    )
    return VerifiedCourseRecommendation(
        institution=CatalogInstitution.TAMU, course_code=course_code, title=f"{course_code} title",
        description="Course description.", credit_min=3.0, credit_max=3.0,
        matched_needs=[need], match_kinds=[MatchKind.TITLE], matched_terms=["match"],
        student_status=student_status, prerequisite_status=evaluation.status,
        prerequisite_evaluation=evaluation, eligibility_status=CourseEligibilityStatus.ELIGIBLE,
        provenance=_ap_provenance(course_code), ranking_reason="Direct match.",
        skill_alignment_explanation="Covers the need directly.",
    )


def _ap_blocked(course_code, need, evaluation):
    return PrerequisiteBlockedCourse(
        institution=CatalogInstitution.TAMU, course_code=course_code, title=f"{course_code} title",
        matched_needs=[need], match_kinds=[MatchKind.TITLE],
        eligibility_status=CourseEligibilityStatus.INELIGIBLE,
        prerequisite_status=evaluation.status, prerequisite_evaluation=evaluation,
        provenance=_ap_provenance(course_code),
    )


def _ap_unresolved(course_code, need):
    evaluation = PrerequisiteEvaluation(
        status=PrerequisiteStatus.UNRESOLVED,
        requirement=PrerequisiteRequirement(mode=PrerequisiteMode.UNRESOLVED, unresolved_reasons=["mixed grammar"]),
    )
    return UnresolvedCourseCandidate(
        institution=CatalogInstitution.TAMU, course_code=course_code, title=f"{course_code} title",
        matched_needs=[need], match_kinds=[MatchKind.TITLE],
        eligibility_status=CourseEligibilityStatus.UNRESOLVED, reasons=["ambiguous restriction"],
        prerequisite_evaluation=evaluation, provenance=_ap_provenance(course_code),
    )


def _ap_result(need, *, verified_recs=None, blocked_recs=None, unresolved_recs=None):
    return CourseDiscoveryResult(
        target_role=ACTION_PLAN_TARGET_ROLE, current_major="Computer Science",
        intended_major="Computer Science", career_needs=[need],
        verified_recommendations=verified_recs or [], requires_verification=unresolved_recs or [],
        prerequisite_blocked=blocked_recs or [], summary="Test fixture.",
    )


def _stub_action_plan_agent(monkeypatch, client, need, result):
    monkeypatch.setattr(api, "list_planned", lambda client, sid: [])
    monkeypatch.setattr(api, "derive_career_skill_needs", lambda profile, role: [need])
    monkeypatch.setattr(api, "build_client", lambda: object())

    class Agent:
        def __init__(self, service, provider):
            pass

        def run(self, *, needs, target_role):
            assert needs == [need]
            assert target_role == ACTION_PLAN_TARGET_ROLE
            return SimpleNamespace(errors=[], result=result)

    monkeypatch.setattr(api, "CourseDiscoveryAgent", Agent)


def test_action_plan_simple_verified_recommendation_is_complete(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    need = _ap_need()
    result = _ap_result(need, verified_recs=[_ap_verified("CSCE 110", need)])
    _stub_action_plan_agent(monkeypatch, client, need, result)

    response = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})

    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "ACTION_PLAN" and body["status"] == "success"
    assert body["dependency_order"]["completeness"] == "COMPLETE"
    assert body["dependency_order"]["status"] == "ORDERED"
    assert len(body["action_plan"]["nodes"]) == 2  # skill_need + course
    assert body["action_plan"]["edges"][0]["relation"] == "satisfies"


def test_action_plan_all_mode_blocked_prerequisite_orders_prerequisite_before_dependent(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    need = _ap_need()
    evaluation = PrerequisiteEvaluation(
        status=PrerequisiteStatus.INELIGIBLE,
        requirement=PrerequisiteRequirement(mode=PrerequisiteMode.ALL, course_codes=["FINC 351"]),
        missing_courses=["FINC 351"],
    )
    result = _ap_result(need, blocked_recs=[_ap_blocked("FINC 446", need, evaluation)])
    _stub_action_plan_agent(monkeypatch, client, need, result)

    response = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})

    assert response.status_code == 200
    body = response.json()
    from GradusIQ_career.action_planning.builder import course_node_id
    target_id = course_node_id(CatalogInstitution.TAMU, "FINC 446")
    prereq_id = course_node_id(CatalogInstitution.TAMU, "FINC 351")
    node_ids = {n["node_id"] for n in body["action_plan"]["nodes"]}
    assert target_id in node_ids and prereq_id in node_ids
    requires = [e for e in body["action_plan"]["edges"] if e["relation"] == "requires"]
    assert requires == [{"from_node_id": target_id, "to_node_id": prereq_id, "relation": "requires"}]
    ordered = body["dependency_order"]["ordered_node_ids"]
    assert ordered.index(prereq_id) < ordered.index(target_id)
    assert body["dependency_order"]["completeness"] == "COMPLETE"


def test_action_plan_blocked_course_retains_satisfies_edge(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    need = _ap_need()
    evaluation = PrerequisiteEvaluation(
        status=PrerequisiteStatus.INELIGIBLE,
        requirement=PrerequisiteRequirement(mode=PrerequisiteMode.ALL, course_codes=["FINC 351"]),
        missing_courses=["FINC 351"],
    )
    result = _ap_result(need, blocked_recs=[_ap_blocked("FINC 446", need, evaluation)])
    _stub_action_plan_agent(monkeypatch, client, need, result)

    response = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})

    from GradusIQ_career.action_planning.builder import course_node_id, skill_need_node_id
    target_id = course_node_id(CatalogInstitution.TAMU, "FINC 446")
    satisfies = [e for e in response.json()["action_plan"]["edges"] if e["relation"] == "satisfies"]
    assert satisfies == [{
        "from_node_id": target_id, "to_node_id": skill_need_node_id(need.need_id), "relation": "satisfies",
    }]


def test_action_plan_any_mode_blocked_is_provisional_with_no_fake_edges(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    need = _ap_need()
    evaluation = PrerequisiteEvaluation(
        status=PrerequisiteStatus.INELIGIBLE,
        requirement=PrerequisiteRequirement(mode=PrerequisiteMode.ANY, course_codes=["ACCT 209", "ACCT 229"]),
        missing_courses=["ACCT 209", "ACCT 229"],
    )
    result = _ap_result(need, blocked_recs=[_ap_blocked("ACCT 210", need, evaluation)])
    _stub_action_plan_agent(monkeypatch, client, need, result)

    response = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})

    body = response.json()
    assert response.status_code == 200  # PROVISIONAL is not an HTTP error
    assert [e for e in body["action_plan"]["edges"] if e["relation"] == "requires"] == []
    order = body["dependency_order"]
    assert order["completeness"] == "PROVISIONAL"
    assert order["status"] == "ORDERED"
    assert len(order["limitations"]) == 1
    assert order["limitations"][0]["reason_type"] == "ANY_PREREQUISITE"
    assert set(order["limitations"][0]["course_codes"]) == {"ACCT 209", "ACCT 229"}


def test_action_plan_unresolved_candidate_never_enters_the_plan_and_stays_complete(client, monkeypatch):
    """UNRESOLVED-mode courses land in requires_verification, which
    build_action_plan() never consumes -- confirms the trusted server path
    doesn't leak that evidence into a fake node/edge/limitation."""
    _patch_session(monkeypatch, profile=_full_profile())
    need = _ap_need()
    result = _ap_result(need, unresolved_recs=[_ap_unresolved("CSCE 221", need)])
    _stub_action_plan_agent(monkeypatch, client, need, result)

    response = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})

    body = response.json()
    # the skill_need node itself always exists (build_action_plan creates one
    # per requested need, regardless of whether anything satisfies it yet);
    # only the unresolved candidate's course node must be absent.
    assert [n for n in body["action_plan"]["nodes"] if n["node_type"] == "course"] == []
    assert body["dependency_order"]["completeness"] == "COMPLETE"
    assert body["dependency_order"]["limitations"] == []


def test_action_plan_any_verified_with_missing_unused_alternative_is_complete(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    need = _ap_need()
    evaluation = PrerequisiteEvaluation(
        status=PrerequisiteStatus.ELIGIBLE,
        requirement=PrerequisiteRequirement(mode=PrerequisiteMode.ANY, course_codes=["ACCT 209", "ACCT 229"]),
        satisfied_courses=["ACCT 229"], missing_courses=["ACCT 209"],
    )
    result = _ap_result(need, verified_recs=[_ap_verified("ACCT 210", need, prerequisite_evaluation=evaluation)])
    _stub_action_plan_agent(monkeypatch, client, need, result)

    response = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})

    body = response.json()
    assert body["dependency_order"]["completeness"] == "COMPLETE"
    assert body["dependency_order"]["limitations"] == []
    assert [e for e in body["action_plan"]["edges"] if e["relation"] == "requires"] == []


def test_action_plan_any_verified_with_unknown_unused_alternative_is_complete(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    need = _ap_need()
    evaluation = PrerequisiteEvaluation(
        status=PrerequisiteStatus.ELIGIBLE,
        requirement=PrerequisiteRequirement(mode=PrerequisiteMode.ANY, course_codes=["ACCT 209", "ACCT 229"]),
        satisfied_courses=["ACCT 229"], unknown_courses=["ACCT 209"],
    )
    result = _ap_result(need, verified_recs=[_ap_verified("ACCT 210", need, prerequisite_evaluation=evaluation)])
    _stub_action_plan_agent(monkeypatch, client, need, result)

    response = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})

    body = response.json()
    assert body["dependency_order"]["completeness"] == "COMPLETE"
    assert body["dependency_order"]["limitations"] == []
    assert [e for e in body["action_plan"]["edges"] if e["relation"] == "requires"] == []


def test_action_plan_completed_and_planned_targets_excluded(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    need = _ap_need()
    completed = _ap_verified("CSCE 206", need, student_status=StudentCourseState.COMPLETED)
    planned_course = _ap_verified("CSCE 207", need, student_status=StudentCourseState.PLANNED)
    result = _ap_result(need, verified_recs=[completed, planned_course])
    _stub_action_plan_agent(monkeypatch, client, need, result)

    response = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})

    body = response.json()
    course_nodes = [n for n in body["action_plan"]["nodes"] if n["node_type"] == "course"]
    assert course_nodes == []


def test_action_plan_request_rejects_client_supplied_course_discovery_result(client, monkeypatch):
    """CourseDiscoveryRequest forbids extra fields -- a client cannot smuggle
    a pre-made CourseDiscoveryResult into the trusted planning pipeline."""
    _patch_session(monkeypatch, profile=_full_profile())
    response = _call(
        client, "post", "/api/v2/student/me/action-plan",
        {"target_role": ACTION_PLAN_TARGET_ROLE, "course_discovery_result": {"fabricated": True}},
    )
    assert response.status_code == 422


def test_action_plan_response_round_trips_through_domain_models(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    need = _ap_need()
    evaluation = PrerequisiteEvaluation(
        status=PrerequisiteStatus.INELIGIBLE,
        requirement=PrerequisiteRequirement(mode=PrerequisiteMode.ALL, course_codes=["FINC 351"]),
        missing_courses=["FINC 351"],
    )
    result = _ap_result(need, blocked_recs=[_ap_blocked("FINC 446", need, evaluation)])
    _stub_action_plan_agent(monkeypatch, client, need, result)

    response = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})
    body = response.json()

    plan = UnifiedActionPlan.model_validate(body["action_plan"])
    order = DependencyOrderResult.model_validate(body["dependency_order"])
    assert plan.execution_status == "SUCCESS"
    assert order.status == "ORDERED"


def test_action_plan_uses_the_same_skill_need_ids_course_discovery_used(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    need = _ap_need()
    result = _ap_result(need, verified_recs=[_ap_verified("CSCE 110", need)])
    _stub_action_plan_agent(monkeypatch, client, need, result)

    response = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})

    from GradusIQ_career.action_planning.builder import skill_need_node_id
    node_ids = {n["node_id"] for n in response.json()["action_plan"]["nodes"]}
    assert skill_need_node_id(need.need_id) in node_ids


def test_action_plan_repeated_identical_requests_are_deterministic(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    need = _ap_need()
    evaluation = PrerequisiteEvaluation(
        status=PrerequisiteStatus.INELIGIBLE,
        requirement=PrerequisiteRequirement(mode=PrerequisiteMode.ALL, course_codes=["FINC 351"]),
        missing_courses=["FINC 351"],
    )
    result = _ap_result(need, blocked_recs=[_ap_blocked("FINC 446", need, evaluation)])
    _stub_action_plan_agent(monkeypatch, client, need, result)

    first = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})
    second = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})

    assert first.json()["action_plan"] == second.json()["action_plan"]
    assert first.json()["dependency_order"] == second.json()["dependency_order"]


def test_action_plan_typed_error_is_preserved_when_assembly_fails(client, monkeypatch):
    """Simulates build_action_plan() returning its own typed ERROR envelope
    (e.g. a cycle) at the integration seam -- confirms the route surfaces the
    typed PlanFailure as a handled failure, not a 500, and skips computing
    dependency_order on unusable graph data."""
    _patch_session(monkeypatch, profile=_full_profile())
    need = _ap_need()
    result = _ap_result(need, verified_recs=[_ap_verified("CSCE 110", need)])
    _stub_action_plan_agent(monkeypatch, client, need, result)

    error_plan = UnifiedActionPlan(
        target_role=ACTION_PLAN_TARGET_ROLE, nodes=[], edges=[], conflicts=[],
        execution_status="ERROR",
        failure=PlanFailure(error_class="CycleDetected", safe_message="simulated for this test"),
        summary="Graph assembly aborted.",
    )
    monkeypatch.setattr(api, "build_action_plan", lambda **kwargs: error_plan)

    response = _call(client, "post", "/api/v2/student/me/action-plan", {"target_role": ACTION_PLAN_TARGET_ROLE})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["action_plan"]["execution_status"] == "ERROR"
    assert body["action_plan"]["failure"]["error_class"] == "CycleDetected"
    assert body["dependency_order"] is None


# --- /api/v2/student/me/job-search -----------------------------------------
#
# The feed reads via job_search_feed.fetch_candidate_pool: table().select()
# .eq("is_dfw", True).range(start, end).execute(), paginated. These tests
# fake exactly that chain rather than posting_provider's (different module,
# see job_search_feed.py's own module docstring for why they are separate).

class _FakeJobSearchClient:
    def __init__(self, rows):
        self._rows = rows
        self._eq = {}

    def table(self, name):
        assert name == "job_postings"
        return self

    def select(self, cols):
        assert "raw_payload" not in cols and "description" not in cols
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def range(self, start, end):
        matched = [r for r in self._rows if all(r.get(k) == v for k, v in self._eq.items())]
        self._page = matched[start : end + 1]
        return self

    def execute(self):
        return SimpleNamespace(data=self._page)


def _posting_row(**overrides):
    row = {
        "id": "posting-1",
        "posting_identity": "cluster-1",
        "company": "Acme Corp",
        "title": "Software Engineering Intern",
        "location": "Dallas, TX",
        "url": "https://example.com/jobs/1",
        "posted_date": date.today().isoformat(),
        "fetched_at": "2026-09-30T12:00:00Z",
        "source": "adzuna",
        "is_dfw": True,
    }
    row.update(overrides)
    return row


def test_job_search_returns_cached_postings_for_the_students_own_roles(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(
        api, "build_service_client", lambda: _FakeJobSearchClient([_posting_row()])
    )

    response = _call(client, "get", "/api/v2/student/me/job-search", None)

    assert response.status_code == 200
    body = response.json()
    assert body["coverage"] == "available"
    assert len(body["postings"]) == 1
    posting = body["postings"][0]
    assert posting["employer"] == "Acme Corp"
    assert posting["title"] == "Software Engineering Intern"
    assert posting["locations"] == ["Dallas, TX"]
    assert posting["url"] == "https://example.com/jobs/1"
    assert posting["posted_date"] == date.today().isoformat()
    assert posting["family"] == "Software Engineering Intern"


def test_job_search_reports_no_market_data_for_zero_rows(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "build_service_client", lambda: _FakeJobSearchClient([]))

    response = _call(client, "get", "/api/v2/student/me/job-search", None)

    assert response.status_code == 200
    body = response.json()
    assert body["coverage"] == "no_market_data"
    assert body["postings"] == []


def test_job_search_never_makes_a_live_vendor_call(client, monkeypatch):
    """Pins the quota-safety constraint: the endpoint must read only from the
    Supabase cache via build_service_client(), never call out to Adzuna/
    JSearch directly."""
    _patch_session(monkeypatch, profile=_full_profile())
    calls = []
    monkeypatch.setattr(
        api,
        "build_service_client",
        lambda: calls.append("called") or _FakeJobSearchClient([_posting_row()]),
    )

    response = _call(client, "get", "/api/v2/student/me/job-search", None)

    assert response.status_code == 200
    assert calls == ["called"]


def test_job_search_no_target_roles_and_no_families_param_is_200_not_an_error(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    # _patch_session's profile arg only shapes the legacy /profile response;
    # the canonical profile this route actually reads is the fixed
    # _canonical_profile() _patch_session wires up regardless, so the empty
    # target_roles case has to override that directly.
    no_roles_canonical = _canonical_profile()
    no_roles_canonical.career.target_roles = []
    monkeypatch.setattr(api, "build_student_intelligence_profile", lambda client, sid: no_roles_canonical)
    monkeypatch.setattr(
        api, "build_service_client", lambda: pytest.fail("must not query postings")
    )

    response = _call(client, "get", "/api/v2/student/me/job-search", None)

    assert response.status_code == 200
    body = response.json()
    assert body["coverage"] == "no_target_roles"
    assert body["postings"] == []


def test_job_search_families_param_overrides_the_students_own_roles(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(
        api,
        "build_service_client",
        lambda: _FakeJobSearchClient(
            [_posting_row(id="1", title="Finance Intern"), _posting_row(id="2")]
        ),
    )

    response = _call(
        client, "get", "/api/v2/student/me/job-search?families=Finance+Intern", None
    )

    assert response.status_code == 200
    body = response.json()
    assert [p["title"] for p in body["postings"]] == ["Finance Intern"]


def test_job_search_role_param_is_compatible_with_a_cached_old_bundle(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(
        api,
        "build_service_client",
        lambda: _FakeJobSearchClient(
            [_posting_row(id="1", title="Finance Intern"), _posting_row(id="2")]
        ),
    )

    response = _call(
        client, "get", "/api/v2/student/me/job-search?role=Finance+Intern", None
    )

    assert response.status_code == 200
    body = response.json()
    assert [p["title"] for p in body["postings"]] == ["Finance Intern"]


def test_job_search_days_param_narrows_the_window(client, monkeypatch):
    today = date.today()
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(
        api,
        "build_service_client",
        lambda: _FakeJobSearchClient(
            [
                _posting_row(id="recent", posted_date=today.isoformat()),
                _posting_row(id="old", posted_date=(today - timedelta(days=60)).isoformat()),
            ]
        ),
    )

    response = _call(client, "get", "/api/v2/student/me/job-search?days=7", None)

    assert response.status_code == 200
    body = response.json()
    assert [p["posting_id"] for p in body["postings"]] == ["recent"]


def test_job_search_dedupes_by_posting_identity(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(
        api,
        "build_service_client",
        lambda: _FakeJobSearchClient(
            [
                _posting_row(id="1", posting_identity="c1", location="Dallas, TX"),
                _posting_row(id="2", posting_identity="c1", location="Plano, TX"),
            ]
        ),
    )

    response = _call(client, "get", "/api/v2/student/me/job-search", None)

    body = response.json()
    assert body["total"] == 1
    assert sorted(body["postings"][0]["locations"]) == ["Dallas, TX", "Plano, TX"]


# ── assistant memory notes ───────────────────────────────────────────────────


def test_me_memory_reports_unavailable_before_the_migration(client, monkeypatch):
    _patch_session(monkeypatch)

    def missing(*a, **k):
        raise api.chat_memory.MemoryUnavailable

    monkeypatch.setattr(api.chat_memory, "list_notes", missing)
    response = _call(client, "get", "/api/v2/student/me/memory", None)
    assert response.status_code == 200
    assert response.json() == {"available": False, "notes": [], "max_notes": 20}

    saved = _call(client, "post", "/api/v2/student/me/memory", {"note": "Wants remote roles"})
    assert saved.status_code == 503


def test_me_memory_saves_cleans_dedupes_and_caps(client, monkeypatch):
    _patch_session(monkeypatch)
    store = []
    monkeypatch.setattr(api.chat_memory, "list_notes", lambda client, sid: list(store))

    def add(client, sid, note):
        row = {"id": f"id-{len(store)}", "note": note}
        store.append(row)
        return row

    monkeypatch.setattr(api.chat_memory, "add_note", add)

    first = _call(client, "post", "/api/v2/student/me/memory", {"note": '  "Wants\n remote roles" '})
    assert first.status_code == 200 and first.json()["note"]["note"] == "Wants remote roles"
    again = _call(client, "post", "/api/v2/student/me/memory", {"note": "wants remote ROLES"})
    assert again.status_code == 200 and len(store) == 1

    assert _call(client, "post", "/api/v2/student/me/memory", {"note": "   "}).status_code == 422
    assert _call(client, "post", "/api/v2/student/me/memory", {"note": "x" * 201}).status_code == 422

    store.extend({"id": f"f{i}", "note": f"n{i}"} for i in range(19))
    full = _call(client, "post", "/api/v2/student/me/memory", {"note": "One more"})
    assert full.status_code == 409


def test_me_memory_delete_needs_a_uuid(client, monkeypatch):
    _patch_session(monkeypatch)
    deleted = []
    monkeypatch.setattr(api.chat_memory, "delete_note", lambda client, sid, nid: deleted.append((sid, nid)))
    note_id = "11111111-2222-3333-4444-555555555555"
    assert _call(client, "delete", f"/api/v2/student/me/memory/{note_id}", None).status_code == 200
    assert deleted == [(str(STUDENT_UUID), note_id)]
    assert _call(client, "delete", "/api/v2/student/me/memory/not-a-uuid", None).status_code == 422


def test_me_chat_sends_notes_and_offers_to_remember(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "_gather_chat_context", lambda client, sid, canonical: {})
    monkeypatch.setattr(api.chat_memory, "list_notes", lambda client, sid: [{"note": "Prefers mornings"}])
    fake = FakeAI("Remote roles are common in your field.\nREMEMBER: Aiming for remote roles")
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "I want remote work", "history": []})

    assert response.status_code == 200
    assert response.json()["reply"] == "Remote roles are common in your field."
    assert response.json()["remember"] == "Aiming for remote roles"
    system = fake.calls[0]["messages"][0]["content"]
    assert "Prefers mornings" in system and "<MEMORY>" in system


def test_me_chat_never_offers_to_remember_without_the_table(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "_gather_chat_context", lambda client, sid, canonical: {})

    def missing(*a, **k):
        raise api.chat_memory.MemoryUnavailable

    monkeypatch.setattr(api.chat_memory, "list_notes", missing)
    fake = FakeAI("Noted.\nREMEMBER: Aiming for remote roles")
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "I want remote work", "history": []})

    assert response.json()["reply"] == "Noted."
    assert "remember" not in response.json()
    assert "<MEMORY>" not in fake.calls[0]["messages"][0]["content"]


class ToolCallingAI:
    """Asks for one lookup on the first call, then answers with what it got."""

    def __init__(self, name, arguments, answer="Your exam is on Dec 9."):
        self.name, self.arguments, self.answer = name, arguments, answer
        self.calls = []

    def complete_message_with_metadata(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        if len(self.calls) == 1:
            call = {"id": "call-1", "type": "function",
                    "function": {"name": self.name, "arguments": json.dumps(self.arguments)}}
            return AIMessageResponse(message={"role": "assistant", "content": "", "tool_calls": [call]}, model="fake-model")
        return AIMessageResponse(message={"role": "assistant", "content": self.answer}, model="fake-model")


def test_me_chat_runs_a_lookup_and_names_it(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    events = [
        {"title": "Final exam", "kind": "event", "starts_at": "2026-12-09T15:00:00Z", "likely_exam": True},
        {"title": "Quiz 3", "kind": "assignment", "starts_at": "2026-10-30T23:59:00Z"},
    ]
    monkeypatch.setattr(api.calendar_feed, "load_feed_row", lambda client, sid: {"events": events})
    fake = ToolCallingAI("get_deadlines", {"start_date": "2026-12-01", "end_date": "2026-12-20"})
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "When is my final?", "history": []})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Your exam is on Dec 9."
    assert body["lookups"] == ["your Canvas calendar"]
    first, second = fake.calls
    assert {tool["function"]["name"] for tool in first["extra_body"]["tools"]} >= {"get_deadlines", "get_degree_plan"}
    assert "<LOOKUPS>" in first["messages"][0]["content"]
    tool_message = second["messages"][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "call-1"
    result = json.loads(tool_message["content"])
    assert [event["title"] for event in result["events"]] == ["Final exam"]


def test_me_chat_lookup_failure_still_answers(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())

    def broken(client, sid):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(api.calendar_feed, "load_feed_row", broken)
    fake = ToolCallingAI("get_deadlines", {"start_date": "2026-12-01", "end_date": "2026-12-20"}, "I could not check.")
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "When is my final?", "history": []})

    assert response.status_code == 200
    assert response.json()["reply"] == "I could not check."
    assert json.loads(fake.calls[1]["messages"][-1]["content"]) == {"error": "This lookup is unavailable right now."}


def test_me_chat_rejects_unknown_lookups_and_bad_arguments(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    for name, arguments, expected in [
        ("delete_account", {}, "Unknown lookup 'delete_account'."),
        ("get_deadlines", {"start_date": "2026-12-01"}, "Those arguments do not match this lookup."),
        ("search_courses", {"query": ["CS"]}, "Lookup arguments must be text."),
    ]:
        fake = ToolCallingAI(name, arguments, "ok")
        monkeypatch.setattr(api, "build_client", lambda: fake)
        response = _call(client, "post", "/api/v2/student/me/chat", {"message": "hi", "history": []})
        assert response.status_code == 200
        assert json.loads(fake.calls[1]["messages"][-1]["content"]) == {"error": expected}
        assert "lookups" not in response.json()


def test_demo_chat_offers_no_lookups(client, monkeypatch):
    profile = _full_profile()
    monkeypatch.setattr(api, "load_profile_for_slug", lambda request, slug: profile)
    fake = FakeAI("demo reply")
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = client.post("/api/students/jordanReyes/chat", json={"message": "hi", "history": []})

    assert response.status_code == 200
    assert all("tools" not in (call.get("extra_body") or {}) for call in fake.calls)
    assert "<LOOKUPS>" not in fake.calls[0]["messages"][0]["content"]


def _lookups(canonical=None):
    canonical = canonical or SimpleNamespace(career=SimpleNamespace(target_roles=["Data Analyst"]))
    return api._ChatLookups(request=None, client=object(), student_id=STUDENT_UUID, canonical=canonical)


def test_lookup_degree_plan_shapes_the_schedule(monkeypatch):
    from GradusIQ_career.course_discovery.scheduler import ScheduleResult

    schedule = ScheduleResult(
        student_id=STUDENT_UUID, program_id="p",
        terms=[{"term_key": "2027-Spring", "total_credit_hours": 3.0, "courses": [
            {"course_code": "CS 3353", "credit_hours": 3.0, "requirement_group_id": "g1"}]}],
        unscheduled=[{"requirement_group_id": "g9", "name": "Free electives", "reason": "FREEFORM_MANUAL_REVIEW"}],
    )
    state = SimpleNamespace(
        academic_schedule=schedule,
        base_courses=[SimpleNamespace(requirement_group_id="g1", requirement_group_name="Core CS")],
        academic_selection=SimpleNamespace(decisions=[
            SimpleNamespace(requirement_group_id="g2", requirement_name="Science elective", state="CHOICE_REQUIRED"),
            SimpleNamespace(requirement_group_id="g3", requirement_name="Done", state="LOCKED"),
        ]),
        catalog_by_code={"CS 3353": SimpleNamespace(title="Data Structures")},
    )
    monkeypatch.setattr(api, "_reconstruct_academic_schedule", lambda request: state)
    monkeypatch.setattr(api, "_resolve_decision_term_keys", lambda s: {"g2": "2027-Fall"})
    lookups = _lookups()

    result = json.loads(lookups.run("get_degree_plan", {}))

    assert result == {
        "terms": [{"term": "2027-Spring", "credits": 3.0, "courses": [
            {"course": "CS 3353", "title": "Data Structures", "credits": 3.0, "requirement": "Core CS"}]}],
        "choices_to_make": [{"requirement": "Science elective", "term": "2027-Fall"}],
        "not_placed": [{"requirement": "Free electives", "reason": "FREEFORM_MANUAL_REVIEW"}],
    }
    assert lookups.used == ["get_degree_plan"]


def test_lookup_degree_plan_without_program_data_is_an_error(monkeypatch):
    monkeypatch.setattr(api, "_reconstruct_academic_schedule", lambda request: api._no_program_result())
    lookups = _lookups()

    result = json.loads(lookups.run("get_degree_plan", {}))

    assert "error" in result and lookups.used == []


def test_lookup_course_search_uses_the_home_catalog(monkeypatch):
    from GradusIQ_career.planning.search import CatalogResult

    seen = {}
    monkeypatch.setattr(api, "_home_institution_id", lambda client, sid: "inst-1")

    def fake_search(client, institution_id, query, limit):
        seen.update(institution_id=institution_id, query=query, limit=limit)
        return [CatalogResult(id="1", code="STAT 2331", title="Statistics", department=None,
                              course_level=2000, credit_min=3, credit_max=3)]

    monkeypatch.setattr(api, "search_catalog", fake_search)

    result = json.loads(_lookups().run("search_courses", {"query": "stat"}))

    assert result == {"query": "stat", "results": [{"course": "STAT 2331", "title": "Statistics", "credits": 3}]}
    assert seen == {"institution_id": "inst-1", "query": "stat", "limit": chat_tools.MAX_CATALOG_RESULTS}


def test_lookup_jobs_filters_employer_and_location(monkeypatch):
    seen = {}

    def fake_feed(client, **kwargs):
        seen.update(kwargs)
        return {"total": 2, "facets": {"families": [{"family": "Data Analyst"}]}, "postings": [
            {"title": "Data Intern", "employer": "Acme Corp", "locations": ["Dallas, TX"], "url": "https://a.example/1"},
            {"title": "Data Intern", "employer": "Beta", "locations": ["Dallas, TX"]},
        ]}

    monkeypatch.setattr(api, "build_service_client", lambda: object())
    monkeypatch.setattr(api, "get_job_search_feed", fake_feed)

    result = json.loads(_lookups().run("search_jobs", {"employer": "acme", "location": "Dallas"}))

    assert [p["employer"] for p in result["postings"]] == ["Acme Corp"]
    assert seen["target_role_families"] == ["Data Analyst"] and seen["families"] is None

    empty = json.loads(_lookups().run("search_jobs", {"location": "Tokyo"}))
    assert empty["postings"] == [] and empty["families_available"] == ["Data Analyst"]

    no_roles = _lookups(SimpleNamespace(career=SimpleNamespace(target_roles=[])))
    assert "error" in json.loads(no_roles.run("search_jobs", {}))


def test_lookup_grade_needed_uses_saved_scores(monkeypatch):
    cards = [{"id": "p1", "course_code": "CS 3353", "course_title": "Data Structures", "calculator_ready": True,
              "current_grade": 85.0, "current_letter_grade": "B", "components": []}]
    monkeypatch.setattr(api, "_syllabus_list_items", lambda client, sid: cards)
    monkeypatch.setattr(api.syllabus_service, "get_syllabus_grade_profile",
                        lambda client, profile_id, student_id: {"current_revision": {"id": "r"}})
    monkeypatch.setattr(api.syllabus_store, "get_grade_state", lambda client, profile_id, student_id: {"saved": True})
    monkeypatch.setattr(api.syllabus_read, "grade_state_from_row", lambda row: "SAVED-STATE")
    monkeypatch.setattr(api.syllabus_read, "reconciliation_result_from_row", lambda revision, confirmed: "MODEL")
    seen = {}

    def fake_solve(reconciliation, grade_state, *, target_component, target_letter):
        seen.update(reconciliation=reconciliation, grade_state=grade_state,
                    target_component=target_component, target_letter=target_letter)
        return SimpleNamespace(model_dump=lambda mode: {
            "target_component": "Final Exam", "target_label": "A", "required_score": 91.25,
            "feasible": True, "already_achieved": False, "warnings": []})

    monkeypatch.setattr(api, "solve_required_score", fake_solve)
    lookups = _lookups()

    grades = json.loads(lookups.run("get_course_grades", {}))
    needed = json.loads(lookups.run("solve_grade_needed",
                                    {"course": "data structures", "component": "Final Exam", "target_letter": " A "}))

    assert grades["courses"][0]["course"] == "CS 3353"
    assert needed == {"component": "Final Exam", "target": "A", "feasible": True, "required_score_percent": 91.2}
    assert seen == {"reconciliation": "MODEL", "grade_state": "SAVED-STATE",
                    "target_component": "Final Exam", "target_letter": "A"}
    assert lookups.used == ["get_course_grades", "solve_grade_needed"]
    missing = json.loads(lookups.run("solve_grade_needed", {"course": "BIO", "component": "x", "target_letter": "A"}))
    assert missing == {"error": "No Grade Calculator course matches 'BIO'."}


def _change_lookups(courses=(), terms=(), target_roles=("Data Analyst",)):
    canonical = SimpleNamespace(
        career=SimpleNamespace(target_roles=list(target_roles)),
        academics=SimpleNamespace(courses=list(courses), terms=list(terms)),
    )
    return _lookups(canonical)


def test_propose_add_planned_course_checks_catalog_record_and_term(monkeypatch):
    from datetime import date as real_date

    from GradusIQ_career.planning.search import CatalogResult

    class FixedDate(real_date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 24)

    monkeypatch.setattr(api, "date", FixedDate)
    monkeypatch.setattr(api, "_home_institution_id", lambda client, sid: "inst-1")
    monkeypatch.setattr(api, "list_planned", lambda client, sid: [SimpleNamespace(course_code="MATH 3304")])
    monkeypatch.setattr(api, "search_catalog", lambda client, inst, query, limit: [
        CatalogResult(id="c1", code="CS 3353X", title="Other", department=None, course_level=3000, credit_min=3, credit_max=3),
        CatalogResult(id="c2", code="CS 3353", title="Data Structures", department=None, course_level=3000, credit_min=3, credit_max=3),
    ])
    lookups = _change_lookups(courses=[SimpleNamespace(course_code="CS 1340", status="completed")])

    shown = json.loads(lookups.run("propose_add_planned_course", {"course": "cs 3353", "term": "Spring 2027"}))
    assert shown["card"] == "Add CS 3353 (Data Structures) to your Spring 2027 plan"
    assert lookups.proposals == [{
        "kind": "add_planned_course",
        "summary": "Add CS 3353 (Data Structures) to your Spring 2027 plan",
        "payload": {"course_code": "CS 3353", "title": "Data Structures", "credit_hours": 3,
                    "catalog_course_id": "c2", "year": 2027, "season": "Spring"},
    }]

    for arguments, error in [
        ({"course": "CS 3353", "term": "next year"}, "'next year' is not a term like 'Spring 2027'."),
        ({"course": "CS 3353", "term": "Spring 2026"}, "Spring 2026 is already over."),
        ({"course": "CS 1340", "term": "Spring 2027"}, "CS 1340 is already on their record (completed)."),
        ({"course": "MATH 3304", "term": "Spring 2027"}, "MATH 3304 is already in their plan."),
        ({"course": "CS 9999", "term": "Spring 2027"}, "CS 9999 is not in their school's catalog."),
    ]:
        assert json.loads(lookups.run("propose_add_planned_course", arguments)) == {"error": error}
    assert len(lookups.proposals) == 1
    # Proposals are not lookups, so they never show as "Checked ...".
    assert lookups.used == []


def test_propose_remove_target_role_and_canvas(monkeypatch):
    monkeypatch.setattr(api, "list_planned", lambda client, sid: [
        SimpleNamespace(id="pl-1", course_code="CS 3353", term_id="t1")])
    monkeypatch.setattr(api, "supported_target_roles", lambda: ["Data Analyst", "UX Designer"])
    monkeypatch.setattr(api.calendar_feed, "load_feed_row", lambda client, sid: {"events": []})
    lookups = _change_lookups(terms=[SimpleNamespace(id="t1", label="Spring 2027")])

    lookups.run("propose_remove_planned_course", {"course": "CS 3353"})
    lookups.run("propose_add_target_role", {"role": "ux designer"})
    third = json.loads(lookups.run("propose_refresh_canvas", {}))

    assert [p["summary"] for p in lookups.proposals] == [
        "Remove CS 3353 from your Spring 2027 plan",
        "Add UX Designer to your target roles",
    ]
    assert lookups.proposals[0]["payload"] == {"planned_id": "pl-1"}
    assert lookups.proposals[1]["payload"] == {"target_roles": ["Data Analyst", "UX Designer"]}
    assert "error" in third  # two cards per reply at most

    fresh = _change_lookups()
    assert json.loads(fresh.run("propose_remove_planned_course", {"course": "BIO 1401"}))["error"].startswith(
        "BIO 1401 is not a planned course")
    assert json.loads(fresh.run("propose_add_target_role", {"role": "data analyst"})) == {
        "error": "Data Analyst is already one of their target roles."}
    assert "supported_roles" in json.loads(fresh.run("propose_add_target_role", {"role": "Astronaut"}))
    fresh.run("propose_refresh_canvas", {})
    assert json.loads(fresh.run("propose_refresh_canvas", {}))["status"] == "already shown"
    assert len(fresh.proposals) == 1

    monkeypatch.setattr(api.calendar_feed, "load_feed_row", lambda client, sid: None)
    assert "error" in json.loads(_change_lookups().run("propose_refresh_canvas", {}))


def test_me_chat_returns_proposals_and_the_change_rules(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api.calendar_feed, "load_feed_row", lambda client, sid: {"events": []})
    fake = ToolCallingAI("propose_refresh_canvas", {}, "You can confirm the refresh below.")
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "refresh canvas", "history": []})

    assert response.status_code == 200
    body = response.json()
    assert body["proposals"] == [
        {"id": "p1", "kind": "refresh_canvas", "summary": "Refresh your Canvas calendar now", "payload": {}}
    ]
    assert "lookups" not in body
    assert "<CHANGES>" in fake.calls[0]["messages"][0]["content"]
    assert "propose_refresh_canvas" in {tool["function"]["name"] for tool in fake.calls[0]["extra_body"]["tools"]}
