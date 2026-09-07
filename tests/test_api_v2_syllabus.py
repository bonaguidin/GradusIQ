"""Tests for /api/v2/student/me/syllabus-grade-profiles/*.

No network: OpenRouter is a fake client, Supabase is a small in-memory
double. Mirrors tests/test_api_v2_resume.py's fixture shape.
"""

import copy
import io
import json

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas

from GradusIQ_career import api
from GradusIQ_career.ai.types import AIResponse

TEST_PROXY_SECRET = "test-proxy-secret"
PROXY_HEADERS = {api.PROXY_SECRET_HEADER: TEST_PROXY_SECRET}
AUTH = {"Authorization": "Bearer real-session-jwt"}
HEADERS = {**PROXY_HEADERS, **AUTH}

STUDENT_A = "8f14e45f-ceea-467a-9f0e-1c2d3e4f5a6b"
STUDENT_B = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"

LIST_URL = "/api/v2/student/me/syllabus-grade-profiles"
INGEST_URL = "/api/v2/student/me/syllabus-grade-profiles/ingest"


def profile_url(profile_id: str) -> str:
    return f"{LIST_URL}/{profile_id}"


# --- PDF fixtures (mirrors tests/test_syllabus_parsing.py's builder) ----------------


def _build_pdf(pages: list[list[tuple[str, int, bool]]]) -> bytes:
    buf = io.BytesIO()
    canvas = rl_canvas.Canvas(buf, pagesize=letter)
    for page in pages:
        y = 750
        for text, size, bold in page:
            canvas.setFont("Helvetica-Bold" if bold else "Helvetica", size)
            canvas.drawString(72, y, text)
            y -= size + 10
        canvas.showPage()
    canvas.save()
    return buf.getvalue()


def phys_207_pdf() -> bytes:
    return _build_pdf(
        [
            [("PHYS 207", 10, False), ("Fall 2026", 10, False)],
            [
                ("Grading Policy", 14, True),
                ("Mid-term Exam: 35%", 10, False),
                ("Final Exam: 50%", 10, False),
                ("Lecture Quizzes: 5%", 10, False),
                ("Recitation Quizzes: 10%", 10, False),
                ("Final replaces Midterm when higher.", 10, False),
                ("Grades may be curved upward.", 10, False),
            ],
        ]
    )


def clean_model_pdf() -> bytes:
    return _build_pdf([[("Midterm: 30%", 10, False), ("Final: 40%", 10, False), ("Project: 30%", 10, False)]])


def overlapping_cutoffs_pdf() -> bytes:
    return _build_pdf(
        [
            [
                ("Midterm: 30%", 10, False),
                ("Final: 40%", 10, False),
                ("Project: 30%", 10, False),
                ("A: 91-100", 10, False),
                ("B: 80-90", 10, False),
                ("C: 70-80", 10, False),
            ]
        ]
    )


def unverifiable_thresholds_pdf() -> bytes:
    return _build_pdf(
        [
            [
                ("Midterm: 30%", 10, False),
                ("Final: 40%", 10, False),
                ("Project: 30%", 10, False),
                ("A: at least 90%", 10, False),
                ("B: >= 80% and < 90%", 10, False),
                ("C: >= 70% and < 80%", 10, False),
                ("D: >= 60% and < 70%", 10, False),
                ("F: below 60%", 10, False),
            ]
        ]
    )


def blank_pdf() -> bytes:
    buf = io.BytesIO()
    canvas = rl_canvas.Canvas(buf, pagesize=letter)
    canvas.showPage()
    canvas.save()
    return buf.getvalue()


# --- fake AI -------------------------------------------------------------------------

PHYS_207_MODEL_RESPONSE = {
    "course": {"course_code": "PHYS 207", "term": "Fall 2026"},
    "grading_method": "weighted",
    "categories": [
        {"name": "Mid-term Exam", "weight": 35, "count": None, "evidence": {"page": 2, "text": "Mid-term Exam: 35%", "confidence": 1.0}},
        {"name": "Final Exam", "weight": 50, "count": None, "evidence": {"page": 2, "text": "Final Exam: 50%", "confidence": 1.0}},
        {"name": "Lecture Quizzes", "weight": 5, "count": None, "evidence": {"page": 2, "text": "Lecture Quizzes: 5%", "confidence": 1.0}},
        {"name": "Recitation Quizzes", "weight": 10, "count": None, "evidence": {"page": 2, "text": "Recitation Quizzes: 10%", "confidence": 1.0}},
    ],
    "assessments": [],
    "grade_thresholds": [],
    "rules": [
        {
            "rule_type": "replacement",
            "description": "Final replaces Midterm when higher.",
            "source": "Final Exam",
            "target": "Mid-term Exam",
            "condition": "final_score > midterm_score",
            "evidence": {"page": 2, "text": "Final replaces Midterm when higher.", "confidence": 1.0},
        },
        {
            "rule_type": "curve",
            "description": "Grades may be curved upward.",
            "evidence": {"page": 2, "text": "Grades may be curved upward.", "confidence": 1.0},
        },
    ],
    "warnings": [
        {"type": "possible_curve", "description": "No deterministic curve formula is given."},
    ],
}

CLEAN_MODEL_RESPONSE = {
    "course": {"course_code": "TEST 100"},
    "grading_method": "weighted",
    "categories": [
        {"name": "Midterm", "weight": 30, "count": None, "evidence": {"page": 1, "text": "Midterm: 30%", "confidence": 1.0}},
        {"name": "Final", "weight": 40, "count": None, "evidence": {"page": 1, "text": "Final: 40%", "confidence": 1.0}},
        {"name": "Project", "weight": 30, "count": None, "evidence": {"page": 1, "text": "Project: 30%", "confidence": 1.0}},
    ],
    "assessments": [],
    "grade_thresholds": [],
    "rules": [],
    "warnings": [],
}

# A model that genuinely needs student review for a reason unrelated to any
# informational (curve/late-work/makeup) rule: the replacement rule's
# target names a category that does not exist -> unresolved_rule_reference
# (blocking). Built from the PHYS 207 response so every evidence string
# still appears verbatim in phys_207_pdf() (Phase 4 verification). The
# curve rule rides along and, post-reclassification, is non-blocking on its
# own -- so removing just the broken replacement rule reaches ACCEPTED.
REVIEW_REQUIRED_MODEL_RESPONSE = copy.deepcopy(PHYS_207_MODEL_RESPONSE)
REVIEW_REQUIRED_MODEL_RESPONSE["rules"][0]["target"] = "Makeup Exam"

# Otherwise-clean model whose only blocker is an isolated, cleanly-resolvable
# B/C cutoff overlap at 80. Threshold evidence strings appear verbatim in
# overlapping_cutoffs_pdf().
OVERLAPPING_CUTOFFS_MODEL_RESPONSE = copy.deepcopy(CLEAN_MODEL_RESPONSE)
OVERLAPPING_CUTOFFS_MODEL_RESPONSE["grade_thresholds"] = [
    {"letter": "A", "minimum": 91, "maximum": 100, "evidence": {"page": 1, "text": "A: 91-100", "confidence": 1.0}},
    {"letter": "B", "minimum": 80, "maximum": 90, "evidence": {"page": 1, "text": "B: 80-90", "confidence": 1.0}},
    {"letter": "C", "minimum": 70, "maximum": 80, "evidence": {"page": 1, "text": "C: 70-80", "confidence": 1.0}},
]

# Otherwise-clean model whose only blocker is that every A-F threshold's
# verbatim evidence uses ">= / < / at least / below" phrasing the
# deterministic range check cannot parse -> five claim_evidence_consistency_
# unverifiable findings. Evidence strings appear verbatim in
# unverifiable_thresholds_pdf(). Mirrors ECEN 248's real shape.
UNVERIFIABLE_THRESHOLDS_MODEL_RESPONSE = copy.deepcopy(CLEAN_MODEL_RESPONSE)
UNVERIFIABLE_THRESHOLDS_MODEL_RESPONSE["grade_thresholds"] = [
    {"letter": "A", "minimum": 90, "maximum": 100, "evidence": {"page": 1, "text": "A: at least 90%", "confidence": 1.0}},
    {"letter": "B", "minimum": 80, "maximum": 89, "evidence": {"page": 1, "text": "B: >= 80% and < 90%", "confidence": 1.0}},
    {"letter": "C", "minimum": 70, "maximum": 79, "evidence": {"page": 1, "text": "C: >= 70% and < 80%", "confidence": 1.0}},
    {"letter": "D", "minimum": 60, "maximum": 69, "evidence": {"page": 1, "text": "D: >= 60% and < 70%", "confidence": 1.0}},
    {"letter": "F", "minimum": 0, "maximum": 59, "evidence": {"page": 1, "text": "F: below 60%", "confidence": 1.0}},
]


class FakeAI:
    def __init__(self, text=None):
        self.text = json.dumps(PHYS_207_MODEL_RESPONSE) if text is None else text
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return AIResponse(text=self.text, raw={"choices": []}, model="fake-parsing-model")


class ExplodingAI:
    def complete(self, **kwargs):
        raise AssertionError("the AI client must not be called on this path")


# --- fake Supabase ---------------------------------------------------------------------


class FakeDB:
    def __init__(self):
        self.tables = {
            "students": [],
            "syllabus_grade_profiles": [],
            "syllabus_grade_revisions": [],
            "syllabus_grade_states": [],
        }
        self._next = 0

    def new_id(self, prefix):
        self._next += 1
        return f"{prefix}-{self._next:04d}"

    def add_student(self, student_id):
        self.tables["students"].append({"id": student_id, "name": f"Student {student_id[:4]}"})


class _Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, db, table, student_id):
        self.db = db
        self.table_name = table
        self.student_id = student_id
        self.op = None
        self.payload = None
        self.filters = []
        self.null_filters = []
        self._order = None

    def select(self, *a, **k):
        self.op = "select"
        return self

    def insert(self, payload, **k):
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload, **k):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def is_(self, column, value):
        # Only the "<column> IS NULL" form is used (soft-delete filters).
        assert value == "null", f"FakeQuery.is_ only supports 'null', got {value!r}"
        self.null_filters.append(column)
        return self

    def order(self, column, desc=False):
        self._order = (column, desc)
        return self

    def _visible(self):
        rows = self.db.tables[self.table_name]
        if self.table_name == "students":
            return [r for r in rows if r["id"] == self.student_id]
        return [r for r in rows if r.get("student_id") == self.student_id]

    def _matched(self):
        return [
            r
            for r in self._visible()
            if all(r.get(c) == v for c, v in self.filters)
            and all(r.get(c) is None for c in self.null_filters)
        ]

    def execute(self):
        if self.op == "select":
            matched = self._matched()
            if self._order:
                col, desc = self._order
                matched = sorted(matched, key=lambda r: r.get(col) or "", reverse=desc)
            return _Result([dict(r) for r in matched])
        if self.op == "insert":
            row = dict(self.payload)
            row.setdefault("id", self.db.new_id(self.table_name[:4]))
            row.setdefault("created_at", "2026-01-01T00:00:00Z")
            row.setdefault("updated_at", "2026-01-01T00:00:00Z")
            if self.table_name == "syllabus_grade_revisions":
                row.setdefault("corrections", [])
                row.setdefault("confirmed_grade_model", None)
                row.setdefault("confirmed_reconciliation_status", None)
                row.setdefault("confirmed_at", None)
            if self.table_name == "syllabus_grade_profiles":
                row.setdefault("current_revision_id", None)
                row.setdefault("deleted_at", None)
            self.db.tables[self.table_name].append(row)
            return _Result([dict(row)])
        if self.op == "update":
            matched = self._matched()
            for row in matched:
                row.update(self.payload)
            return _Result([dict(r) for r in matched])
        raise AssertionError(f"unsupported op {self.op}")


class FakeSupabase:
    def __init__(self, db, student_id):
        self.db = db
        self.student_id = student_id

    def table(self, name):
        return FakeQuery(self.db, name, self.student_id)


# --- wiring --------------------------------------------------------------------------


def make_test_config(**overrides):
    values = {
        "proxy_secret": TEST_PROXY_SECRET,
        "allowed_origins": ("https://frontend.example",),
        "rate_limit_requests": 200,
        "rate_limit_window_seconds": 60.0,
        "max_concurrent_ai_requests": 2,
    }
    values.update(overrides)
    return api.APIConfig(**values)


@pytest.fixture
def db():
    store = FakeDB()
    store.add_student(STUDENT_A)
    store.add_student(STUDENT_B)
    return store


@pytest.fixture
def client():
    return TestClient(api.create_app(make_test_config()), headers=PROXY_HEADERS)


def patch_session(monkeypatch, db, student_id=STUDENT_A):
    monkeypatch.setattr(api, "build_client_for_token", lambda token: FakeSupabase(db, student_id))


def ingest(client, *, pdf_bytes=None, ai_text=None, filename="syllabus.pdf", course_code="PHYS 207", term="Fall 2026"):
    return client.post(
        INGEST_URL,
        headers=HEADERS,
        files={"file": (filename, pdf_bytes or phys_207_pdf(), "application/pdf")},
        data={"institution": "tamu", "course_code": course_code, "term": term},
    )


# --- list / read ------------------------------------------------------------------------


def test_list_profiles_empty(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    response = client.get(LIST_URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"syllabus_grade_profiles": []}


def test_list_profiles_does_not_call_ai(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: ExplodingAI())
    response = client.get(LIST_URL, headers=HEADERS)
    assert response.status_code == 200


def test_read_owned_profile(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    created = ingest(client).json()
    response = client.get(profile_url(created["id"]), headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert "student_id" not in response.json()


def test_cannot_read_another_students_profile(client, db, monkeypatch):
    patch_session(monkeypatch, db, student_id=STUDENT_A)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    created = ingest(client).json()

    patch_session(monkeypatch, db, student_id=STUDENT_B)
    response = client.get(profile_url(created["id"]), headers=HEADERS)
    assert response.status_code == 404


def test_read_nonexistent_profile_404(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    response = client.get(profile_url("nonexistent-id"), headers=HEADERS)
    assert response.status_code == 404


# --- soft delete ---------------------------------------------------------------------


def test_soft_deleted_profile_disappears_from_list(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    created = ingest(client).json()
    profile_id = created["id"]

    assert [p["id"] for p in client.get(LIST_URL, headers=HEADERS).json()["syllabus_grade_profiles"]] == [profile_id]

    delete_response = client.delete(profile_url(profile_id), headers=HEADERS)
    assert delete_response.status_code == 200
    assert delete_response.json() == {"removed": profile_id}

    # Gone from the list; the underlying rows (revision history, grade state)
    # are untouched -- this is a soft delete, not a cascade.
    assert client.get(LIST_URL, headers=HEADERS).json() == {"syllabus_grade_profiles": []}
    assert len(db.tables["syllabus_grade_revisions"]) == 1
    profile_row = db.tables["syllabus_grade_profiles"][0]
    assert profile_row["deleted_at"] is not None

    # A re-upload of the same course does not resurface or reuse the
    # soft-deleted profile.
    recreated = ingest(client).json()
    assert recreated["id"] != profile_id
    assert recreated["possible_duplicate_profiles"] == []


def test_cannot_soft_delete_another_students_profile(client, db, monkeypatch):
    patch_session(monkeypatch, db, student_id=STUDENT_A)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    created = ingest(client).json()
    profile_id = created["id"]

    patch_session(monkeypatch, db, student_id=STUDENT_B)
    response = client.delete(profile_url(profile_id), headers=HEADERS)
    assert response.status_code == 404

    # Student A's profile is untouched and still listed for them.
    patch_session(monkeypatch, db, student_id=STUDENT_A)
    assert db.tables["syllabus_grade_profiles"][0]["deleted_at"] is None
    assert [p["id"] for p in client.get(LIST_URL, headers=HEADERS).json()["syllabus_grade_profiles"]] == [profile_id]


def test_soft_delete_nonexistent_profile_404(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    response = client.delete(profile_url("nonexistent-id"), headers=HEADERS)
    assert response.status_code == 404


def test_soft_deleted_profile_404s_on_direct_access(client, db, monkeypatch):
    """Removing a profile hides it everywhere, not just from the list: the
    detail read and every mutating/compute route resolve it through the
    same get_profile lookup, which now excludes soft-deleted rows.
    """
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    created = ingest(client).json()
    profile_id = created["id"]

    assert client.delete(profile_url(profile_id), headers=HEADERS).status_code == 200

    assert client.get(profile_url(profile_id), headers=HEADERS).status_code == 404
    assert client.post(f"{profile_url(profile_id)}/confirm", headers=HEADERS).status_code == 404
    assert client.post(f"{profile_url(profile_id)}/calculate", headers=HEADERS, json={}).status_code == 404
    assert client.post(
        f"{profile_url(profile_id)}/corrections",
        headers=HEADERS,
        json={"corrections": [{"target_type": "rule", "operation": "remove_rule", "rule_index": 1}]},
    ).status_code == 404
    assert client.put(
        f"{profile_url(profile_id)}/grade-state",
        headers=HEADERS,
        json={"category_scores": [{"category_name": "Mid-term Exam", "actual_score": 88}]},
    ).status_code == 404
    assert client.post(
        f"{profile_url(profile_id)}/solve-target",
        headers=HEADERS,
        json={"target_component": "Final Exam", "target_grade": 90},
    ).status_code == 404


def test_cross_student_mutation_and_calculation_paths_404(client, db, monkeypatch):
    """Student B must not be able to touch Student A's syllabus profile via
    any mutating/compute route -- not just GET. Each of these resolves
    profile_id through a student-scoped lookup (student_id from the
    session, never the request body), so a cross-student profile_id must
    404 exactly like a nonexistent one, never leak a 403 (which would
    confirm the row exists) or succeed.
    """
    patch_session(monkeypatch, db, student_id=STUDENT_A)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    created = ingest(client).json()
    profile_id = created["id"]

    patch_session(monkeypatch, db, student_id=STUDENT_B)

    corrections_response = client.post(
        f"{profile_url(profile_id)}/corrections",
        headers=HEADERS,
        json={"corrections": [{"target_type": "rule", "operation": "remove_rule", "rule_index": 1}]},
    )
    assert corrections_response.status_code == 404

    confirm_response = client.post(f"{profile_url(profile_id)}/confirm", headers=HEADERS)
    assert confirm_response.status_code == 404

    grade_state_response = client.put(
        f"{profile_url(profile_id)}/grade-state",
        headers=HEADERS,
        json={"category_scores": [{"category_name": "Mid-term Exam", "actual_score": 99}]},
    )
    assert grade_state_response.status_code == 404

    calculate_response = client.post(f"{profile_url(profile_id)}/calculate", headers=HEADERS, json={})
    assert calculate_response.status_code == 404

    solve_response = client.post(
        f"{profile_url(profile_id)}/solve-target",
        headers=HEADERS,
        json={"target_component": "Final Exam", "target_grade": 80},
    )
    assert solve_response.status_code == 404

    # Confirm Student A's profile was genuinely untouched by the rejected
    # cross-student attempts.
    patch_session(monkeypatch, db, student_id=STUDENT_A)
    still_a = client.get(profile_url(profile_id), headers=HEADERS).json()
    assert still_a["review_state"] == "needs_review"
    assert still_a["grade_state"] is None


# --- ingestion -------------------------------------------------------------------------


def test_valid_pdf_ingestion_review_required(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(text=json.dumps(REVIEW_REQUIRED_MODEL_RESPONSE)))
    response = ingest(client)
    assert response.status_code == 200
    body = response.json()
    assert body["reconciliation"]["status"] == "needs_student_review"
    assert body["calculator_ready"] is False
    assert body["extracted_grade_model"]["categories"][0]["name"] == "Mid-term Exam"


def test_curve_syllabus_reaches_calculator_ready_without_correction(client, db, monkeypatch):
    # A correctly-extracted curve is informational, not a blocker
    # (syllabus-review redesign §2C / §5): ingest lands ACCEPTED and the
    # student confirms without removing the curve.
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    created = ingest(client).json()
    assert created["reconciliation"]["status"] == "accepted"
    assert created["calculator_ready"] is False

    confirmed = client.post(f"{profile_url(created['id'])}/confirm", headers=HEADERS)
    assert confirmed.status_code == 200
    assert confirmed.json()["calculator_ready"] is True
    assert any(r["rule_type"] == "curve" for r in confirmed.json()["extracted_grade_model"]["rules"])
    assert any(r["rule_type"] == "curve" for r in confirmed.json()["confirmed_grade_model"]["rules"])


def test_valid_pdf_ingestion_persists(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    ingest(client)
    assert len(db.tables["syllabus_grade_profiles"]) == 1
    assert len(db.tables["syllabus_grade_revisions"]) == 1


def test_invalid_pdf_rejected(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    response = ingest(client, pdf_bytes=b"not a pdf at all")
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "invalid_pdf"


def test_no_text_pdf_rejected(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    response = ingest(client, pdf_bytes=blank_pdf())
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "no_extractable_text"


def test_non_pdf_content_type_rejected(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    response = client.post(
        INGEST_URL,
        headers=HEADERS,
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={},
    )
    assert response.status_code == 415


def test_extraction_failure_mapped_to_502(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(text="not valid json {{{"))
    response = ingest(client)
    assert response.status_code == 502
    assert response.json()["detail"]["error"] == "extraction_failed"
    # nothing persisted on failure
    assert db.tables["syllabus_grade_revisions"] == []


def test_duplicate_course_signal(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    first = ingest(client).json()
    second = ingest(client, pdf_bytes=phys_207_pdf()).json()
    assert first["id"] != second["id"]
    duplicate_ids = {p["id"] for p in second["possible_duplicate_profiles"]}
    assert first["id"] in duplicate_ids


# --- corrections / confirmation ---------------------------------------------------------


def test_correction_and_confirm_reaches_calculator_ready(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(text=json.dumps(REVIEW_REQUIRED_MODEL_RESPONSE)))
    created = ingest(client).json()
    assert created["reconciliation"]["status"] == "needs_student_review"

    # Remove only the broken replacement rule (index 0); the curve rule
    # (index 1) stays and is non-blocking on its own.
    corrected = client.post(
        f"{profile_url(created['id'])}/corrections",
        headers=HEADERS,
        json={"corrections": [{"target_type": "rule", "operation": "remove_rule", "rule_index": 0}]},
    )
    assert corrected.status_code == 200
    assert corrected.json()["confirmed_reconciliation"]["status"] == "accepted"
    # the ORIGINAL extraction's reconciliation is untouched by the correction
    assert corrected.json()["reconciliation"]["status"] == "needs_student_review"

    confirm_before = client.post(f"{profile_url(created['id'])}/calculate", headers=HEADERS, json={})
    assert confirm_before.status_code == 409

    confirmed = client.post(f"{profile_url(created['id'])}/confirm", headers=HEADERS)
    assert confirmed.status_code == 200
    assert confirmed.json()["calculator_ready"] is True
    # original extracted (broken) rule preserved; gone from the confirmed model
    assert any(r["target"] == "Makeup Exam" for r in confirmed.json()["extracted_grade_model"]["rules"])
    confirmed_rules = confirmed.json()["confirmed_grade_model"]["rules"]
    assert not any(r["target"] == "Makeup Exam" for r in confirmed_rules)
    # the informational curve rule is retained -- it never needed removing
    assert any(r["rule_type"] == "curve" for r in confirmed_rules)


def test_invalid_correction_rejected(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    created = ingest(client).json()
    response = client.post(
        f"{profile_url(created['id'])}/corrections",
        headers=HEADERS,
        json={"corrections": [{"target_type": "category", "operation": "set_weight", "category_name": "Nonexistent", "value": 5}]},
    )
    assert response.status_code == 422


def test_cutoff_overlap_resolution_appears_and_confirming_it_unblocks_calculator_ready(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(text=json.dumps(OVERLAPPING_CUTOFFS_MODEL_RESPONSE)))
    created = ingest(
        client, pdf_bytes=overlapping_cutoffs_pdf(), course_code="TEST 100", term="Spring 2027"
    ).json()

    # the resolution proposal is on the detail response, and the overlap
    # still blocks until the student confirms it
    assert created["reconciliation"]["status"] == "needs_student_review"
    assert created["calculator_ready"] is False
    resolution = created["cutoff_overlap_resolution"]
    assert resolution["unresolved"] == []
    assert [(r["winner"], r["loser"], r["boundary"]) for r in resolution["resolved"]] == [("B", "C", 80.0)]
    assert created["clarifying_answers"] == {}

    corrected = client.post(
        f"{profile_url(created['id'])}/corrections",
        headers=HEADERS,
        json={"corrections": [{"target_type": "threshold", "operation": "resolve_cutoff_overlap", "threshold_letter": "C"}]},
    ).json()
    assert corrected["confirmed_reconciliation"]["status"] == "accepted"
    assert corrected["clarifying_answers"] == {
        "cutoff_overlap:B,C": {"answer": "confirm_default", "boundary": 80.0, "winner": "B", "loser": "C"}
    }
    # thresholds untouched -- the resolution proposal is unchanged
    assert corrected["cutoff_overlap_resolution"]["resolved"][0]["loser"] == "C"
    c_threshold = next(t for t in corrected["confirmed_grade_model"]["grade_thresholds"] if t["letter"] == "C")
    assert (c_threshold["minimum"], c_threshold["maximum"]) == (70, 80)

    confirmed = client.post(f"{profile_url(created['id'])}/confirm", headers=HEADERS)
    assert confirmed.status_code == 200
    assert confirmed.json()["calculator_ready"] is True


def test_confirming_threshold_value_claims_re_reconciles_and_unblocks_calculator_ready(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(
        api, "build_client", lambda: FakeAI(text=json.dumps(UNVERIFIABLE_THRESHOLDS_MODEL_RESPONSE))
    )
    created = ingest(
        client, pdf_bytes=unverifiable_thresholds_pdf(), course_code="ECEN 248", term="Fall 2026"
    ).json()

    assert created["reconciliation"]["status"] == "needs_student_review"
    assert created["calculator_ready"] is False
    assert sorted(
        f["field"]
        for f in created["reconciliation"]["findings"]
        if f["code"] == "claim_evidence_consistency_unverifiable"
    ) == ["threshold:A", "threshold:B", "threshold:C", "threshold:D", "threshold:F"]

    corrected = client.post(
        f"{profile_url(created['id'])}/corrections",
        headers=HEADERS,
        json={
            "corrections": [
                {"target_type": "threshold", "operation": "confirm_threshold_value", "threshold_letter": letter}
                for letter in ("A", "B", "C", "D", "F")
            ]
        },
    ).json()

    # confirmed_reconciliation is a real re-run of the corrected model, not
    # the stale original-extraction findings: every claim_evidence finding
    # is gone and the status is accepted.
    assert corrected["confirmed_reconciliation"]["status"] == "accepted"
    assert not any(
        f["code"].startswith("claim_evidence")
        for f in corrected["confirmed_reconciliation"]["findings"]
    )
    assert corrected["clarifying_answers"] == {
        f"claim_evidence:threshold:{letter}": {"answer": "confirm_value", "letter": letter}
        for letter in ("a", "b", "c", "d", "f")
    }
    # the ORIGINAL extraction's reconciliation is untouched
    assert corrected["reconciliation"]["status"] == "needs_student_review"
    # thresholds and their verbatim evidence are unchanged
    a_threshold = next(t for t in corrected["confirmed_grade_model"]["grade_thresholds"] if t["letter"] == "A")
    assert (a_threshold["minimum"], a_threshold["maximum"], a_threshold["evidence"]["text"]) == (
        90,
        100,
        "A: at least 90%",
    )

    confirmed = client.post(f"{profile_url(created['id'])}/confirm", headers=HEADERS)
    assert confirmed.status_code == 200
    assert confirmed.json()["calculator_ready"] is True


def test_confirming_only_some_threshold_value_claims_still_blocks(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(
        api, "build_client", lambda: FakeAI(text=json.dumps(UNVERIFIABLE_THRESHOLDS_MODEL_RESPONSE))
    )
    created = ingest(
        client, pdf_bytes=unverifiable_thresholds_pdf(), course_code="ECEN 248", term="Fall 2026"
    ).json()

    corrected = client.post(
        f"{profile_url(created['id'])}/corrections",
        headers=HEADERS,
        json={
            "corrections": [
                {"target_type": "threshold", "operation": "confirm_threshold_value", "threshold_letter": letter}
                for letter in ("A", "B", "C")
            ]
        },
    ).json()
    assert corrected["confirmed_reconciliation"]["status"] == "needs_student_review"
    assert sorted(
        f["field"]
        for f in corrected["confirmed_reconciliation"]["findings"]
        if f["code"] == "claim_evidence_consistency_unverifiable"
    ) == ["threshold:D", "threshold:F"]
    assert client.post(f"{profile_url(created['id'])}/confirm", headers=HEADERS).status_code == 409


def test_confirm_threshold_value_for_a_clean_threshold_is_a_tolerated_no_op(client, db, monkeypatch):
    # A (91-100) verifies clean against its evidence -- no finding to
    # suppress. Affirming it is inert, so the correction is accepted as a
    # no-op rather than 422'd: the unified cutoff table auto-appends
    # confirm_threshold_value after every in-place edit and must not have
    # the whole atomic batch rejected for a letter that needed no affirming.
    patch_session(monkeypatch, db)
    monkeypatch.setattr(
        api, "build_client", lambda: FakeAI(text=json.dumps(OVERLAPPING_CUTOFFS_MODEL_RESPONSE))
    )
    created = ingest(
        client, pdf_bytes=overlapping_cutoffs_pdf(), course_code="TEST 100", term="Spring 2027"
    ).json()
    response = client.post(
        f"{profile_url(created['id'])}/corrections",
        headers=HEADERS,
        json={
            "corrections": [
                {"target_type": "threshold", "operation": "confirm_threshold_value", "threshold_letter": "A"}
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    # inert: the threshold is untouched and the B/C overlap still blocks
    assert body["confirmed_grade_model"]["grade_thresholds"][0] == {
        "letter": "A", "minimum": 91, "maximum": 100,
        "evidence": {"page": 1, "text": "A: 91-100", "confidence": 1.0},
    }
    assert body["confirmed_reconciliation"]["status"] == "needs_student_review"


def test_confirm_without_correction_when_accepted(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(text=json.dumps(CLEAN_MODEL_RESPONSE)))
    created = ingest(client, pdf_bytes=clean_model_pdf(), course_code="TEST 100", term="Spring 2027").json()
    assert created["reconciliation"]["status"] == "accepted"
    confirmed = client.post(f"{profile_url(created['id'])}/confirm", headers=HEADERS)
    assert confirmed.status_code == 200
    assert confirmed.json()["calculator_ready"] is True


def test_confirm_when_not_accepted_returns_409(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(text=json.dumps(REVIEW_REQUIRED_MODEL_RESPONSE)))
    created = ingest(client).json()
    response = client.post(f"{profile_url(created['id'])}/confirm", headers=HEADERS)
    assert response.status_code == 409


# --- grade state -------------------------------------------------------------------------


def _confirmed_phys_profile(client, db, monkeypatch):
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    created = ingest(client).json()
    client.post(
        f"{profile_url(created['id'])}/corrections",
        headers=HEADERS,
        json={
            "corrections": [
                {"target_type": "rule", "operation": "remove_rule", "rule_index": 1},
                {"target_type": "warning", "operation": "dismiss_warning", "warning_index": 0},
            ]
        },
    )
    client.post(f"{profile_url(created['id'])}/confirm", headers=HEADERS)
    return created["id"]


def test_grade_state_round_trip(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _confirmed_phys_profile(client, db, monkeypatch)

    response = client.put(
        f"{profile_url(profile_id)}/grade-state",
        headers=HEADERS,
        json={"category_scores": [{"category_name": "Mid-term Exam", "actual_score": 78}]},
    )
    assert response.status_code == 200
    assert response.json()["revision"] == 1

    updated = client.put(
        f"{profile_url(profile_id)}/grade-state",
        headers=HEADERS,
        json={"category_scores": [{"category_name": "Mid-term Exam", "actual_score": 80}], "expected_revision": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2


def test_stale_grade_state_revision_returns_409(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _confirmed_phys_profile(client, db, monkeypatch)
    client.put(
        f"{profile_url(profile_id)}/grade-state",
        headers=HEADERS,
        json={"category_scores": [{"category_name": "Mid-term Exam", "actual_score": 78}]},
    )
    stale = client.put(
        f"{profile_url(profile_id)}/grade-state",
        headers=HEADERS,
        json={"category_scores": [{"category_name": "Mid-term Exam", "actual_score": 90}], "expected_revision": 1},
    )
    assert stale.status_code == 200  # first stale attempt at revision=1 while stored=1 succeeds
    conflict = client.put(
        f"{profile_url(profile_id)}/grade-state",
        headers=HEADERS,
        json={"category_scores": [{"category_name": "Mid-term Exam", "actual_score": 95}], "expected_revision": 1},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error"] == "stale_revision"


# --- calculate / solve-target -----------------------------------------------------------


def test_calculate_before_confirm_returns_409(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    created = ingest(client).json()
    response = client.post(f"{profile_url(created['id'])}/calculate", headers=HEADERS, json={})
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "not_calculator_ready"


def test_calculate_phys_207_current_grade(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _confirmed_phys_profile(client, db, monkeypatch)

    response = client.post(
        f"{profile_url(profile_id)}/calculate",
        headers=HEADERS,
        json={
            "category_scores": [
                {"category_name": "Mid-term Exam", "actual_score": 78},
                {"category_name": "Lecture Quizzes", "actual_score": 92},
                {"category_name": "Recitation Quizzes", "actual_score": 88},
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["current_grade"] == 81.4
    assert body["completed_weight"] == 50.0
    assert body["projected_grade"] is None


def test_calculate_hypothetical_does_not_persist(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _confirmed_phys_profile(client, db, monkeypatch)
    client.put(
        f"{profile_url(profile_id)}/grade-state",
        headers=HEADERS,
        json={
            "category_scores": [
                {"category_name": "Mid-term Exam", "actual_score": 78},
                {"category_name": "Lecture Quizzes", "actual_score": 92},
                {"category_name": "Recitation Quizzes", "actual_score": 88},
            ]
        },
    )
    response = client.post(
        f"{profile_url(profile_id)}/calculate",
        headers=HEADERS,
        json={
            "category_scores": [
                {"category_name": "Mid-term Exam", "actual_score": 78},
                {"category_name": "Lecture Quizzes", "actual_score": 92},
                {"category_name": "Recitation Quizzes", "actual_score": 88},
                {"category_name": "Final Exam", "projected_score": 88},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["projected_grade"] is not None
    # persisted grade-state row is untouched by the transient calculate call
    saved = client.get(profile_url(profile_id), headers=HEADERS).json()
    final_saved = [c for c in saved["grade_state"]["category_scores"] if c["category_name"] == "Final Exam"]
    assert final_saved == []


def test_solve_target_b_and_a(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _confirmed_phys_profile(client, db, monkeypatch)
    state = {
        "category_scores": [
            {"category_name": "Mid-term Exam", "actual_score": 78},
            {"category_name": "Lecture Quizzes", "actual_score": 92},
            {"category_name": "Recitation Quizzes", "actual_score": 88},
        ]
    }
    b = client.post(
        f"{profile_url(profile_id)}/solve-target",
        headers=HEADERS,
        json={**state, "target_component": "Final Exam", "target_grade": 80},
    )
    assert b.status_code == 200
    assert abs(b.json()["required_score"] - 78.35) < 0.01

    a = client.post(
        f"{profile_url(profile_id)}/solve-target",
        headers=HEADERS,
        json={**state, "target_component": "Final Exam", "target_grade": 90},
    )
    assert a.status_code == 200
    assert abs(a.json()["required_score"] - 90.12) < 0.01


# --- list-card payload: letter grade + trimmed per-component breakdown ------------------


def _ready_scaled_profile(client, db, monkeypatch):
    """A calculator_ready profile whose confirmed model carries a usable A-F
    grade scale (so current_letter_grade classifies) over three weighted
    categories -- Midterm 30, Final 40, Project 30. Mirrors the confirm flow
    in test_confirming_threshold_value_claims_re_reconciles_and_unblocks_
    calculator_ready.
    """
    monkeypatch.setattr(
        api, "build_client", lambda: FakeAI(text=json.dumps(UNVERIFIABLE_THRESHOLDS_MODEL_RESPONSE))
    )
    created = ingest(
        client, pdf_bytes=unverifiable_thresholds_pdf(), course_code="ECEN 248", term="Fall 2026"
    ).json()
    client.post(
        f"{profile_url(created['id'])}/corrections",
        headers=HEADERS,
        json={
            "corrections": [
                {"target_type": "threshold", "operation": "confirm_threshold_value", "threshold_letter": letter}
                for letter in ("A", "B", "C", "D", "F")
            ]
        },
    )
    confirmed = client.post(f"{profile_url(created['id'])}/confirm", headers=HEADERS)
    assert confirmed.json()["calculator_ready"] is True
    return created["id"]


def _list_summary(client, profile_id):
    body = client.get(LIST_URL, headers=HEADERS).json()
    return next(p for p in body["syllabus_grade_profiles"] if p["id"] == profile_id)


def test_list_card_payload_has_letter_grade_and_trimmed_components(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _ready_scaled_profile(client, db, monkeypatch)
    client.put(
        f"{profile_url(profile_id)}/grade-state",
        headers=HEADERS,
        json={
            "category_scores": [
                {"category_name": "Midterm", "actual_score": 90},
                {"category_name": "Final", "actual_score": 85},
                {"category_name": "Project", "actual_score": 100},
            ]
        },
    )

    summary = _list_summary(client, profile_id)

    # 90*0.30 + 85*0.40 + 100*0.30 = 91.0 -> "A" on the confirmed A-F scale
    assert summary["current_grade"] == 91.0
    assert summary["current_letter_grade"] == "A"

    assert {c["name"] for c in summary["components"]} == {"Midterm", "Final", "Project"}
    midterm = next(c for c in summary["components"] if c["name"] == "Midterm")
    assert midterm == {
        "name": "Midterm",
        "source_type": "category",
        "weight_percent": 30.0,
        "effective_score": 90.0,
        "status": "completed",
    }


def test_list_card_component_carries_only_the_five_named_fields(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _ready_scaled_profile(client, db, monkeypatch)
    client.put(
        f"{profile_url(profile_id)}/grade-state",
        headers=HEADERS,
        json={"category_scores": [{"category_name": "Midterm", "actual_score": 88}]},
    )

    components = _list_summary(client, profile_id)["components"]
    assert components
    for component in components:
        assert set(component) == {"name", "source_type", "weight_percent", "effective_score", "status"}
    # explicitly none of the fuller CalculationComponent fields leak through
    for dropped in ("original_score", "contribution", "earned_points", "possible_points"):
        assert all(dropped not in component for component in components)


def test_list_card_component_distinguishes_ungraded_from_a_scored_zero(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _ready_scaled_profile(client, db, monkeypatch)
    client.put(
        f"{profile_url(profile_id)}/grade-state",
        headers=HEADERS,
        json={"category_scores": [{"category_name": "Midterm", "actual_score": 0}]},
    )

    by_name = {c["name"]: c for c in _list_summary(client, profile_id)["components"]}

    # Midterm was explicitly entered as 0 -- a real scored zero
    assert by_name["Midterm"]["effective_score"] == 0.0
    assert by_name["Midterm"]["status"] == "completed"

    # Final / Project were never entered -- ungraded, an empty ring segment
    for ungraded in ("Final", "Project"):
        assert by_name[ungraded]["effective_score"] is None
        assert by_name[ungraded]["status"] is None


def test_list_card_payload_null_and_empty_when_not_calculator_ready(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(text=json.dumps(REVIEW_REQUIRED_MODEL_RESPONSE)))
    created = ingest(client).json()
    assert created["calculator_ready"] is False

    summary = _list_summary(client, created["id"])
    assert summary["calculator_ready"] is False
    assert summary["current_grade"] is None
    assert summary["current_letter_grade"] is None
    assert summary["components"] == []


def test_list_card_payload_empty_for_ready_profile_with_no_saved_grades(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _ready_scaled_profile(client, db, monkeypatch)

    # no grade-state PUT: a ready course the student hasn't scored yet must
    # render as an empty ring, never an error
    summary = _list_summary(client, profile_id)
    assert summary["calculator_ready"] is True
    assert summary["current_grade"] is None
    assert summary["current_letter_grade"] is None
    assert summary["components"] == []


# --- list-card course title: dug out of the grade-model JSONB, defensively -------------


def _only_revision(db):
    rows = db.tables["syllabus_grade_revisions"]
    assert len(rows) == 1
    return rows[0]


def test_list_card_course_title_present(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _confirmed_phys_profile(client, db, monkeypatch)
    rev = _only_revision(db)
    rev["confirmed_grade_model"] = {
        **rev["confirmed_grade_model"],
        "course": {
            "course_code": "PHYS 207",
            "course_title": "Electricity and Magnetism",
            "section": None,
            "term": "Fall 2026",
            "instructor": None,
        },
    }

    assert _list_summary(client, profile_id)["course_title"] == "Electricity and Magnetism"


def test_list_card_course_title_course_key_absent_does_not_raise(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _confirmed_phys_profile(client, db, monkeypatch)
    rev = _only_revision(db)
    # a malformed extraction with no 'course' block at all, on both models
    rev["confirmed_grade_model"] = {"grading_method": "weighted", "categories": []}
    rev["extracted_grade_model"] = {"grading_method": "weighted", "categories": []}

    response = client.get(LIST_URL, headers=HEADERS)
    assert response.status_code == 200
    summary = next(p for p in response.json()["syllabus_grade_profiles"] if p["id"] == profile_id)
    assert summary["course_title"] is None


def test_list_card_course_title_null_stays_null(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _confirmed_phys_profile(client, db, monkeypatch)
    rev = _only_revision(db)
    rev["confirmed_grade_model"] = {**rev["confirmed_grade_model"], "course": {"course_code": "PHYS 207", "course_title": None}}
    rev["extracted_grade_model"] = {**rev["extracted_grade_model"], "course": {"course_code": "PHYS 207", "course_title": None}}

    assert _list_summary(client, profile_id)["course_title"] is None


def test_list_card_course_title_no_revision_does_not_raise(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    profile_id = _confirmed_phys_profile(client, db, monkeypatch)
    # profile with no current revision at all
    profile = next(p for p in db.tables["syllabus_grade_profiles"] if p["id"] == profile_id)
    profile["current_revision_id"] = None
    db.tables["syllabus_grade_revisions"].clear()

    response = client.get(LIST_URL, headers=HEADERS)
    assert response.status_code == 200
    summary = next(p for p in response.json()["syllabus_grade_profiles"] if p["id"] == profile_id)
    assert summary["course_title"] is None
    assert summary["calculator_ready"] is False
