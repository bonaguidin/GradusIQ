"""Tests for the four transcript routes and the DB-touching modules behind
them: term resolution, catalog matching, storage, the confirm gate, and review.

No network: the OpenRouter client is faked, and Supabase is an in-memory double
that enforces what these paths actually depend on -- per-student row visibility
(RLS), public-read reference tables, the course_records natural key with its
NULLS NOT DISTINCT semantics, and the "unconfirmed only" filter.

Mirrors tests/test_api_v2_resume.py's harness deliberately; the divergences are
the extra reference tables and the (student_id, term_id, course_code) key.
"""

import io
import json

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas

from GradusIQ_career import api
from GradusIQ_career.ai.types import AIResponse
from GradusIQ_career.transcript import store as transcript_store


TEST_PROXY_SECRET = "test-proxy-secret"
PROXY_HEADERS = {api.PROXY_SECRET_HEADER: TEST_PROXY_SECRET}
AUTH = {"Authorization": "Bearer real-session-jwt"}
HEADERS = {**PROXY_HEADERS, **AUTH}

STUDENT_A = "8f14e45f-ceea-467a-9f0e-1c2d3e4f5a6b"
STUDENT_B = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"

TAMU = "75d68331-91d2-47e8-9671-2a3b065955d0"
SMU = "6b180bbf-66d7-4aef-b8c6-2ae534c78e9a"
UNVERIFIED = "00000000-0000-4000-8000-00000000dead"

PDF = "application/pdf"

UPLOAD = "/api/v2/student/me/transcript/upload"
CONFIRM = "/api/v2/student/me/transcript/confirm"
REVIEW = "/api/v2/student/me/transcript/review"

COURSE_KEY = ("student_id", "term_id", "course_code")

TAMU_GRADES = [
    ("A", 4.00, True, True),
    ("B", 3.00, True, True),
    ("C", 2.00, True, True),
    ("D", 1.00, True, True),
    ("F", 0.00, True, True),
    ("W", None, False, False),
    ("I", None, False, False),
]
SMU_GRADES = TAMU_GRADES + [
    ("A-", 3.70, True, True),
    ("B+", 3.30, True, True),
    ("P", None, False, True),
]


# ── fixture transcript file ─────────────────────────────────────────────────


def make_pdf(lines=None) -> bytes:
    lines = lines or [
        "OFFICIAL ACADEMIC TRANSCRIPT",
        "Fall 2023",
        "MATH 251  Engineering Mathematics III  3.000  A",
        "CHEM 107  General Chemistry            4.000  B",
        "Spring 2024",
        "CSCE 121  Introduction to Program Design  4.000  A",
    ]
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    y = letter[1] - 72
    for line in lines:
        c.drawString(72, y, line)
        y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()


def image_only_pdf() -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    c.rect(100, 400, 200, 100, fill=1)
    c.showPage()
    c.save()
    return buf.getvalue()


# ── fake AI ─────────────────────────────────────────────────────────────────


GOOD_PARSE = {
    "status": "ok",
    "courses": [
        {
            "course_code": "MATH 251",
            "title": "Engineering Mathematics III",
            "credit_hours": 3,
            "letter_grade": "A",
            "term_label": "Fall 2023",
            "status": "completed",
        },
        {
            "course_code": "CHEM 107",
            "title": "General Chemistry",
            "credit_hours": 4,
            "letter_grade": "B",
            "term_label": "Fall 2023",
            "status": "completed",
        },
        {
            "course_code": "CSCE 121",
            "title": "Introduction to Program Design",
            "credit_hours": 4,
            "letter_grade": "A",
            "term_label": "Spring 2024",
            "status": "completed",
        },
    ],
    "term_summaries": [
        {"term_label": "Fall 2023", "term_gpa": 3.43, "term_credit_hours": 7},
        {"term_label": "Spring 2024", "term_gpa": 4.0, "term_credit_hours": 4},
    ],
}


class FakeAI:
    def __init__(self, text=None):
        self.text = json.dumps(GOOD_PARSE) if text is None else text
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return AIResponse(text=self.text, raw={"choices": []}, model="fake-parsing-model")


class ExplodingAI:
    def complete(self, **kwargs):
        raise AssertionError("the AI client must not be called on this path")


# ── fake Supabase ───────────────────────────────────────────────────────────

# Tables not scoped to a student: public-read reference data.
REFERENCE_TABLES = {"institutions", "grade_point_map", "course_catalog"}


class FakeDB:
    def __init__(self):
        self.tables = {
            "students": [],
            "student_institutions": [],
            "institutions": [],
            "grade_point_map": [],
            "course_catalog": [],
            "academic_terms": [],
            "course_records": [],
        }
        self._next = 0

    def new_id(self, prefix):
        self._next += 1
        return f"{prefix}-{self._next:04d}"

    def add_student(self, student_id, institution_id=TAMU):
        self.tables["students"].append({"id": student_id, "name": f"Student {student_id[:4]}"})
        self.tables["student_institutions"].append(
            {
                "id": self.new_id("si"),
                "student_id": student_id,
                "institution_id": institution_id,
                "relationship": "home",
            }
        )

    def add_institution(self, institution_id, name, *, verified, grades):
        self.tables["institutions"].append(
            {
                "id": institution_id,
                "name": name,
                "grade_scale_verified": verified,
                "uses_plus_minus": institution_id != TAMU,
            }
        )
        for letter_, points, gpa, credit in grades:
            self.tables["grade_point_map"].append(
                {
                    "id": self.new_id("gpm"),
                    "institution_id": institution_id,
                    "letter": letter_,
                    "points": points,
                    "counts_toward_gpa": gpa,
                    "counts_toward_credit": credit,
                }
            )

    def add_catalog(self, institution_id, *codes):
        for code in codes:
            prefix, number = code.split(" ", 1)
            self.tables["course_catalog"].append(
                {
                    "id": self.new_id("cat"),
                    "institution_id": institution_id,
                    "code": code,
                    "prefix": prefix,
                    "number": number,
                    "title": f"{code} Title",
                }
            )

    def rows_for(self, table, student_id):
        return [r for r in self.tables[table] if r.get("student_id") == student_id]


class FakeQuery:
    def __init__(self, db, table, student_id):
        self.db = db
        self.table_name = table
        self.student_id = student_id
        self.op = None
        self.payload = None
        self.filters = []
        self.on_conflict = None
        self.ignore_duplicates = False

    def select(self, *a, **k):
        self.op = "select"
        return self

    def insert(self, json, **k):
        self.op = "insert"
        self.payload = json
        return self

    def upsert(self, json, *, ignore_duplicates=False, on_conflict="", **k):
        self.op = "upsert"
        self.payload = json
        self.ignore_duplicates = ignore_duplicates
        self.on_conflict = on_conflict
        return self

    def update(self, json, **k):
        self.op = "update"
        self.payload = json
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def is_(self, column, value):
        self.filters.append(("is", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, list(values)))
        return self

    def _matches(self, row):
        for kind, column, value in self.filters:
            if kind == "eq" and row.get(column) != value:
                return False
            if kind == "is":
                wanted = None if value in (None, "null") else value
                if row.get(column) is not wanted:
                    return False
            if kind == "in" and row.get(column) not in value:
                return False
        return True

    def _visible(self):
        """RLS: student tables are narrowed; reference tables are public-read."""
        rows = self.db.tables[self.table_name]
        if self.table_name in REFERENCE_TABLES:
            return rows
        if self.table_name == "students":
            return [r for r in rows if r["id"] == self.student_id]
        return [r for r in rows if r.get("student_id") == self.student_id]

    def execute(self):
        if self.op == "select":
            return _Result([dict(r) for r in self._visible() if self._matches(r)])

        if self.op == "insert":
            row = dict(self.payload)
            row.setdefault("id", self.db.new_id(self.table_name[:4]))
            self.db.tables[self.table_name].append(row)
            return _Result([dict(row)])

        if self.op == "upsert":
            columns = tuple(c.strip() for c in (self.on_conflict or "").split(",") if c.strip())
            assert columns == COURSE_KEY, (
                f"on_conflict {columns} does not match the live natural key "
                f"{COURSE_KEY} -- Postgres would raise 42P10"
            )
            row = dict(self.payload)
            # NULLS NOT DISTINCT: None compares equal to None, matching the
            # live course_records_student_term_course_key index.
            key = tuple(row.get(c) for c in columns)
            for existing in self.db.tables[self.table_name]:
                if tuple(existing.get(c) for c in columns) == key:
                    assert self.ignore_duplicates, "expected ignore_duplicates=True"
                    return _Result([])
            row.setdefault("id", self.db.new_id(self.table_name[:4]))
            self.db.tables[self.table_name].append(row)
            return _Result([dict(row)])

        if self.op == "update":
            updated = []
            for row in self._visible():
                if self._matches(row):
                    row.update(self.payload)
                    updated.append(dict(row))
            return _Result(updated)

        raise AssertionError(f"unsupported op {self.op}")


class _Result:
    def __init__(self, data):
        self.data = data


class _Postgrest:
    def __init__(self):
        self.tokens = []

    def auth(self, token):
        self.tokens.append(token)


class FakeSupabase:
    def __init__(self, db, student_id):
        self.db = db
        self.student_id = student_id
        self.postgrest = _Postgrest()

    def table(self, name):
        return FakeQuery(self.db, name, self.student_id)


# ── wiring ──────────────────────────────────────────────────────────────────


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
def db():
    store = FakeDB()
    store.add_institution(TAMU, "Texas A&M University", verified=True, grades=TAMU_GRADES)
    store.add_institution(SMU, "Southern Methodist University", verified=True, grades=SMU_GRADES)
    # A third institution standing in for any scale that has NOT been verified.
    # Deliberately not SMU: SMU's scale was verified on 2026-07-28 (migration
    # 20260728035418) and is seeded true, so using it here would test the seed
    # rather than the gate.
    store.add_institution(
        UNVERIFIED, "Unverified State College", verified=False, grades=TAMU_GRADES
    )
    store.add_catalog(TAMU, "MATH 251", "CHEM 107", "CSCE 121")
    store.add_student(STUDENT_A, TAMU)
    store.add_student(STUDENT_B, TAMU)
    return store


@pytest.fixture
def client():
    return TestClient(api.create_app(make_test_config()), headers=PROXY_HEADERS)


def patch_session(monkeypatch, db, student_id=STUDENT_A):
    monkeypatch.setattr(api, "build_client_for_token", lambda token: FakeSupabase(db, student_id))


def upload(client, content=None, filename="transcript.pdf", content_type=PDF, headers=None):
    return client.post(
        UPLOAD,
        headers=HEADERS if headers is None else headers,
        files={"file": (filename, make_pdf() if content is None else content, content_type)},
    )


def fake_client(db, student_id=STUDENT_A):
    return FakeSupabase(db, student_id)


# ── 1. happy path ───────────────────────────────────────────────────────────


def test_upload_parses_matches_and_stores_a_multi_term_transcript(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    fake = FakeAI()
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = upload(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["written"] == {"course_records": {"inserted": 3, "skipped_duplicate": 0}}
    assert body["terms"]["created"] == 2
    assert body["rejected"] == []

    rows = db.rows_for("course_records", STUDENT_A)
    assert len(rows) == 3
    assert {r["course_code"] for r in rows} == {"MATH 251", "CHEM 107", "CSCE 121"}
    for row in rows:
        assert row["source"] == "transcript_parse"
        assert row["confirmed_at"] is None
        assert row["credit_type"] == "resident"
        assert row["institution_id"] == TAMU

    # temperature=0 reached the model.
    assert fake.calls[0]["temperature"] == 0


def test_stored_rows_carry_correct_counts_flags(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())

    upload(client)

    rows = {r["course_code"]: r for r in db.rows_for("course_records", STUDENT_A)}
    assert rows["MATH 251"]["counts_toward_gpa"] is True
    assert rows["MATH 251"]["counts_toward_credit"] is True


def test_credit_hours_are_stored_at_two_decimal_scale(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())

    upload(client)

    rows = db.rows_for("course_records", STUDENT_A)
    assert {r["credit_hours"] for r in rows} == {"3.00", "4.00"}


# ── 2. term resolution ──────────────────────────────────────────────────────


def test_terms_are_created_in_chronological_order_despite_page_order(db):
    """Transcripts print terms out of order; sequence must follow time."""
    client = fake_client(db)
    labels = ["Spring 2024", "Fall 2023", "Summer 2024", "Fall 2022"]

    from GradusIQ_career.transcript.terms import resolve_terms

    resolution = resolve_terms(client, STUDENT_A, TAMU, labels)

    assert resolution.errors == {}
    assert resolution.created == 4
    rows = sorted(db.rows_for("academic_terms", STUDENT_A), key=lambda r: r["sequence"])
    assert [(r["season"], r["year"]) for r in rows] == [
        ("Fall", 2022),
        ("Fall", 2023),
        ("Spring", 2024),
        ("Summer", 2024),
    ]
    assert [r["sequence"] for r in rows] == [0, 1, 2, 3]


def test_existing_terms_are_reused_not_duplicated(db):
    from GradusIQ_career.transcript.terms import resolve_terms

    client = fake_client(db)
    first = resolve_terms(client, STUDENT_A, TAMU, ["Fall 2023", "Spring 2024"])
    second = resolve_terms(client, STUDENT_A, TAMU, ["Fall 2023", "Spring 2024"])

    assert first.term_id_by_label == second.term_id_by_label
    assert first.created == 2 and first.reused == 0
    assert second.created == 0 and second.reused == 2
    assert len(db.rows_for("academic_terms", STUDENT_A)) == 2


def test_differently_spelled_labels_collapse_onto_one_term(db):
    """'Fall 2023' and 'FALL 2023' are one term, not two."""
    from GradusIQ_career.transcript.terms import resolve_terms

    client = fake_client(db)
    resolution = resolve_terms(
        client, STUDENT_A, TAMU, ["Fall 2023", "FALL 2023", "Fall Semester 2023"]
    )

    assert len(set(resolution.term_id_by_label.values())) == 1
    assert len(db.rows_for("academic_terms", STUDENT_A)) == 1


def test_a_second_upload_appends_sequence_without_renumbering(db):
    from GradusIQ_career.transcript.terms import resolve_terms

    client = fake_client(db)
    resolve_terms(client, STUDENT_A, TAMU, ["Fall 2023"])
    resolve_terms(client, STUDENT_A, TAMU, ["Spring 2024"])

    rows = {r["label"]: r for r in db.rows_for("academic_terms", STUDENT_A)}
    assert rows["Fall 2023"]["sequence"] == 0
    assert rows["Spring 2024"]["sequence"] == 1
    # Sequence is unique per student -- the live constraint.
    sequences = [r["sequence"] for r in db.rows_for("academic_terms", STUDENT_A)]
    assert len(sequences) == len(set(sequences))


def test_unresolvable_term_is_reported_and_its_courses_get_a_null_term(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    parse = json.loads(json.dumps(GOOD_PARSE))
    parse["courses"][0]["term_label"] = "Term Five"
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(json.dumps(parse)))

    response = upload(client)

    body = response.json()
    assert "Term Five" in body["terms"]["unresolved"]
    row = next(r for r in db.rows_for("course_records", STUDENT_A) if r["course_code"] == "MATH 251")
    assert row["term_id"] is None, "must not be filed under a guessed semester"


def test_two_null_term_rows_with_the_same_code_collide(client, db, monkeypatch):
    """NULLS NOT DISTINCT: the second is a skipped duplicate, not a second row."""
    patch_session(monkeypatch, db)
    parse = {
        "status": "ok",
        "courses": [
            {"course_code": "MATH 251", "title": "A", "credit_hours": 3,
             "letter_grade": "A", "term_label": None, "status": "completed"},
            {"course_code": "MATH 251", "title": "B", "credit_hours": 3,
             "letter_grade": "B", "term_label": None, "status": "completed"},
        ],
    }
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(json.dumps(parse)))

    body = upload(client).json()

    assert body["written"]["course_records"] == {"inserted": 1, "skipped_duplicate": 1}
    assert len(db.rows_for("course_records", STUDENT_A)) == 1


# ── 3. catalog matching ─────────────────────────────────────────────────────


def test_catalog_hit_sets_catalog_course_id(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())

    body = upload(client).json()

    assert body["catalog"]["matched"] == 3
    assert body["catalog"]["unmatched"] == 0
    for row in db.rows_for("course_records", STUDENT_A):
        assert row["catalog_course_id"] is not None


def test_catalog_miss_leaves_null_and_keeps_free_text(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    parse = json.loads(json.dumps(GOOD_PARSE))
    parse["courses"] = [
        {"course_code": "ARTS 999", "title": "Underwater Basket Weaving",
         "credit_hours": 3, "letter_grade": "A", "term_label": "Fall 2023",
         "status": "completed"}
    ]
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(json.dumps(parse)))

    body = upload(client).json()

    assert body["catalog"]["matched"] == 0
    assert body["catalog"]["unmatched"] == 1
    assert "ARTS 999" in body["catalog"]["misses"]

    row = db.rows_for("course_records", STUDENT_A)[0]
    assert row["catalog_course_id"] is None
    assert row["course_code"] == "ARTS 999"
    assert row["title"] == "Underwater Basket Weaving"


def test_unnormalized_code_still_matches_the_catalog(client, db, monkeypatch):
    """'math251' on the page must find catalog 'MATH 251'."""
    patch_session(monkeypatch, db)
    parse = {
        "status": "ok",
        "courses": [
            {"course_code": "math251", "title": "T", "credit_hours": 3,
             "letter_grade": "A", "term_label": "Fall 2023", "status": "completed"}
        ],
    }
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(json.dumps(parse)))

    body = upload(client).json()

    assert body["catalog"]["matched"] == 1


def test_catalog_is_scoped_per_institution(db):
    """SMU has no rows in this catalog, so a TAMU code must not match for SMU."""
    from GradusIQ_career.transcript.catalog import lookup_catalog_ids

    client = fake_client(db)
    assert lookup_catalog_ids(client, TAMU, ["MATH 251"]) != {}
    assert lookup_catalog_ids(client, SMU, ["MATH 251"]) == {}


def test_catalog_misses_are_logged_with_the_raw_string(client, db, monkeypatch, caplog):
    patch_session(monkeypatch, db)
    parse = {
        "status": "ok",
        "courses": [
            {"course_code": "arts-999", "title": "T", "credit_hours": 3,
             "letter_grade": "A", "term_label": "Fall 2023", "status": "completed"}
        ],
    }
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(json.dumps(parse)))

    with caplog.at_level("INFO", logger="GradusIQ_career.transcript.catalog"):
        upload(client)

    assert any("arts-999" in r.getMessage() for r in caplog.records), (
        "the RAW string must be logged for Tier 2 analysis"
    )


# ── 4. reject-not-repair reaches the response ───────────────────────────────


def test_malformed_rows_are_rejected_and_reported_not_stored(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    parse = {
        "status": "ok",
        "courses": [
            {"course_code": "MATH 251", "title": "Good", "credit_hours": 3,
             "letter_grade": "A", "term_label": "Fall 2023", "status": "completed"},
            {"course_code": "CHEM 107", "title": "Bad hours", "credit_hours": "three",
             "letter_grade": "A", "term_label": "Fall 2023", "status": "completed"},
            {"course_code": "CSCE 121", "title": "Bad grade", "credit_hours": 4,
             "letter_grade": "B+", "term_label": "Fall 2023", "status": "completed"},
        ],
    }
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(json.dumps(parse)))

    body = upload(client).json()

    assert body["written"]["course_records"]["inserted"] == 1
    reasons = {r["reason"] for r in body["rejected"]}
    assert reasons == {"uncoercible_credit_hours", "unmapped_letter_grade"}

    stored = db.rows_for("course_records", STUDENT_A)
    assert [r["course_code"] for r in stored] == ["MATH 251"]
    assert all(r["credit_hours"] != "0.00" for r in stored), "nothing was defaulted"


# ── 5. MAX_PROMPT_CHARS hard fail ───────────────────────────────────────────


def test_over_length_transcript_is_rejected_with_413_and_no_model_call(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: ExplodingAI())

    # A PDF whose extracted text exceeds MAX_PROMPT_CHARS.
    lines = [f"CSCE {i:04d}  A Long Course Title For Padding Purposes  3.000  A" for i in range(1400)]
    huge = make_pdf(lines)

    response = upload(client, content=huge)

    assert response.status_code == 413, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "transcript_too_long"
    assert "truncat" in detail["message"].lower()
    assert db.rows_for("course_records", STUDENT_A) == []


# ── 6. extraction short-circuit ─────────────────────────────────────────────


def test_scanned_pdf_short_circuits_before_the_model(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: ExplodingAI())

    response = upload(client, content=image_only_pdf())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["extraction_status"] == "empty"
    assert "scanned" in detail["message"].lower()


def test_unsupported_type_short_circuits_before_the_model(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: ExplodingAI())

    response = upload(client, content=b"plain text", content_type="text/plain")

    assert response.status_code == 415


# ── 7. the confirm gate ─────────────────────────────────────────────────────


def _seed_unconfirmed_course(db, student_id, institution_id):
    db.tables["course_records"].append(
        {
            "id": db.new_id("cr"),
            "student_id": student_id,
            "institution_id": institution_id,
            "term_id": None,
            "course_code": "MATH 251",
            "title": "T",
            "credit_hours": "3.00",
            "letter_grade": "A",
            "credit_type": "resident",
            "counts_toward_credit": True,
            "counts_toward_gpa": True,
            "status": "completed",
            "source": "transcript_parse",
            "catalog_course_id": None,
            "confirmed_at": None,
        }
    )


def test_confirm_succeeds_for_a_verified_institution(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    _seed_unconfirmed_course(db, STUDENT_A, TAMU)

    response = client.post(CONFIRM, headers=HEADERS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["confirmed"] == 1
    assert db.rows_for("course_records", STUDENT_A)[0]["confirmed_at"] is not None


def test_confirm_succeeds_for_smu(client, db, monkeypatch):
    """SMU's scale WAS verified (migration 20260728035418), so it is not gated."""
    db.add_student("smu-student", SMU)
    monkeypatch.setattr(
        api, "build_client_for_token", lambda token: FakeSupabase(db, "smu-student")
    )
    _seed_unconfirmed_course(db, "smu-student", SMU)

    response = client.post(CONFIRM, headers=HEADERS)

    assert response.status_code == 200, response.text
    assert response.json()["confirmed"] == 1


def test_confirm_is_blocked_for_an_unverified_institution(client, db, monkeypatch):
    db.add_student("unv-student", UNVERIFIED)
    monkeypatch.setattr(
        api, "build_client_for_token", lambda token: FakeSupabase(db, "unv-student")
    )
    _seed_unconfirmed_course(db, "unv-student", UNVERIFIED)

    response = client.post(CONFIRM, headers=HEADERS)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "grade_scale_unverified"
    assert "Unverified State College" in detail["message"]
    assert "verification is pending" in detail["message"]

    # Nothing was written -- the gate blocks, it does not partially confirm.
    assert db.rows_for("course_records", "unv-student")[0]["confirmed_at"] is None


def test_gate_does_not_block_upload_parse_or_review(client, db, monkeypatch):
    """The gate is at CONFIRM only. Everything before it stays open."""
    db.add_student("unv-student", UNVERIFIED)
    db.add_catalog(UNVERIFIED, "MATH 251")
    monkeypatch.setattr(
        api, "build_client_for_token", lambda token: FakeSupabase(db, "unv-student")
    )
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())

    assert upload(client).status_code == 200, "upload must not be gated"
    assert client.get(REVIEW, headers=HEADERS).status_code == 200, "review must not be gated"
    assert db.rows_for("course_records", "unv-student"), "rows must still be stored"


def test_unknown_institution_is_treated_as_unverified(db):
    client_ = fake_client(db)
    blocked = transcript_store.unverified_institutions(client_, ["not-a-real-institution"])

    assert len(blocked) == 1


def test_confirm_never_backdates_an_existing_confirmation(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    _seed_unconfirmed_course(db, STUDENT_A, TAMU)
    client.post(CONFIRM, headers=HEADERS)
    first = db.rows_for("course_records", STUDENT_A)[0]["confirmed_at"]

    second_response = client.post(CONFIRM, headers=HEADERS)

    assert second_response.json()["confirmed"] == 0
    assert db.rows_for("course_records", STUDENT_A)[0]["confirmed_at"] == first


def test_confirm_does_not_touch_another_students_rows(client, db, monkeypatch):
    patch_session(monkeypatch, db, STUDENT_A)
    _seed_unconfirmed_course(db, STUDENT_A, TAMU)
    _seed_unconfirmed_course(db, STUDENT_B, TAMU)

    client.post(CONFIRM, headers=HEADERS)

    assert db.rows_for("course_records", STUDENT_B)[0]["confirmed_at"] is None


# ── 8. review flow ──────────────────────────────────────────────────────────


def test_review_lists_unconfirmed_rows_and_flags_catalog_gaps(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    _seed_unconfirmed_course(db, STUDENT_A, TAMU)
    db.tables["academic_terms"].append(
        {
            "id": "term-fall-2025",
            "student_id": STUDENT_A,
            "institution_id": TAMU,
            "label": "Fall 2025",
            "year": 2025,
            "season": "fall",
            "sequence": 1,
        }
    )
    db.tables["course_records"][0]["term_id"] = "term-fall-2025"

    response = client.get(REVIEW, headers=HEADERS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["course_records"]) == 1
    row = body["course_records"][0]
    assert row["course_code"] == "MATH 251"
    assert row["needs_catalog_review"] is True
    assert body["pending_catalog_review"] == 1
    assert body["terms"][0]["label"] == "Fall 2025"
    assert body["institutions"] == [{"id": TAMU, "name": "Texas A&M University"}]
    # System columns must never be projected.
    assert "student_id" not in row
    assert "confirmed_at" not in row


def test_review_excludes_confirmed_rows(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    _seed_unconfirmed_course(db, STUDENT_A, TAMU)
    db.tables["course_records"][0]["confirmed_at"] = "2026-08-09T00:00:00Z"

    body = client.get(REVIEW, headers=HEADERS).json()

    assert body["course_records"] == []


def test_review_edit_updates_a_field(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    _seed_unconfirmed_course(db, STUDENT_A, TAMU)
    row_id = db.rows_for("course_records", STUDENT_A)[0]["id"]

    response = client.patch(
        f"{REVIEW}/{row_id}", headers=HEADERS, json={"title": "Corrected Title"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Corrected Title"


def test_review_edit_recomputes_counts_flags(client, db, monkeypatch):
    """counts_* are derived; editing the grade must move them."""
    patch_session(monkeypatch, db)
    _seed_unconfirmed_course(db, STUDENT_A, TAMU)
    row_id = db.rows_for("course_records", STUDENT_A)[0]["id"]

    response = client.patch(f"{REVIEW}/{row_id}", headers=HEADERS, json={"letter_grade": "W"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts_toward_gpa"] is False
    assert body["counts_toward_credit"] is False


def test_review_edit_rejects_uncoercible_credit_hours(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    _seed_unconfirmed_course(db, STUDENT_A, TAMU)
    row_id = db.rows_for("course_records", STUDENT_A)[0]["id"]

    response = client.patch(
        f"{REVIEW}/{row_id}", headers=HEADERS, json={"credit_hours": "three"}
    )

    assert response.status_code == 422
    assert "credit_hours" in response.json()["detail"]


def test_review_edit_silently_drops_system_managed_fields(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    _seed_unconfirmed_course(db, STUDENT_A, TAMU)
    row_id = db.rows_for("course_records", STUDENT_A)[0]["id"]

    response = client.patch(
        f"{REVIEW}/{row_id}",
        headers=HEADERS,
        json={"title": "New", "confirmed_at": "2020-01-01T00:00:00Z", "student_id": STUDENT_B},
    )

    assert response.status_code == 200
    row = db.rows_for("course_records", STUDENT_A)[0]
    assert row["confirmed_at"] is None, "confirmed_at must not be writable here"
    assert row["student_id"] == STUDENT_A


def test_review_edit_with_no_editable_fields_is_422(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    _seed_unconfirmed_course(db, STUDENT_A, TAMU)
    row_id = db.rows_for("course_records", STUDENT_A)[0]["id"]

    response = client.patch(f"{REVIEW}/{row_id}", headers=HEADERS, json={"nonsense": 1})

    assert response.status_code == 422


def test_review_edit_of_a_confirmed_row_is_409(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    _seed_unconfirmed_course(db, STUDENT_A, TAMU)
    row = db.rows_for("course_records", STUDENT_A)[0]
    row["confirmed_at"] = "2026-08-09T00:00:00Z"

    response = client.patch(f"{REVIEW}/{row['id']}", headers=HEADERS, json={"title": "X"})

    assert response.status_code == 409


def test_review_edit_of_another_students_row_is_404(client, db, monkeypatch):
    patch_session(monkeypatch, db, STUDENT_A)
    _seed_unconfirmed_course(db, STUDENT_B, TAMU)
    other_id = db.rows_for("course_records", STUDENT_B)[0]["id"]

    response = client.patch(f"{REVIEW}/{other_id}", headers=HEADERS, json={"title": "X"})

    assert response.status_code == 404, "must not reveal that the row exists"


def test_review_edit_of_unknown_row_is_404(client, db, monkeypatch):
    patch_session(monkeypatch, db)

    response = client.patch(f"{REVIEW}/nope-0001", headers=HEADERS, json={"title": "X"})

    assert response.status_code == 404


# ── 9. cross-check surfaces in the response ─────────────────────────────────


def test_cross_check_is_reported_and_does_not_block(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    parse = json.loads(json.dumps(GOOD_PARSE))
    # Printed totals claim a course that the parsed rows do not contain.
    parse["term_summaries"][0]["term_credit_hours"] = 99
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(json.dumps(parse)))

    response = upload(client)

    assert response.status_code == 200, "a mismatch must never block the upload"
    body = response.json()
    assert body["cross_check"]["ok"] is False
    assert body["written"]["course_records"]["inserted"] == 3, "rows still stored"
    assert any(m["field"] == "term_credit_hours" for m in body["cross_check"]["mismatches"])


def test_cross_check_passes_on_a_consistent_transcript(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())

    body = upload(client).json()

    assert body["cross_check"]["ok"] is True


# ── 10. non-ok parse statuses ───────────────────────────────────────────────


@pytest.mark.parametrize("status", ["not_a_transcript", "unparseable"])
def test_non_ok_parse_writes_nothing(client, db, monkeypatch, status):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(
        api, "build_client", lambda: FakeAI(json.dumps({"status": status, "courses": []}))
    )

    body = upload(client).json()

    assert body["status"] == status
    assert body["written"] is None
    assert db.rows_for("course_records", STUDENT_A) == []


def test_contract_violation_returns_parse_failed_not_500(client, db, monkeypatch):
    patch_session(monkeypatch, db)
    monkeypatch.setattr(api, "build_client", lambda: FakeAI(json.dumps({"courses": []})))

    response = upload(client)

    assert response.status_code == 200
    assert response.json()["status"] == "parse_failed"
    assert db.rows_for("course_records", STUDENT_A) == []


# ── 11. auth / plumbing ─────────────────────────────────────────────────────


def test_upload_requires_the_proxy_secret(db, monkeypatch):
    patch_session(monkeypatch, db)
    # A bare client: the shared `client` fixture sets PROXY_HEADERS as default
    # headers on every request, which per-request headers cannot remove.
    bare = TestClient(api.create_app(make_test_config()))

    response = bare.post(
        UPLOAD, headers=AUTH, files={"file": ("t.pdf", make_pdf(), PDF)}
    )

    assert response.status_code in (401, 403)


def test_student_without_a_home_institution_gets_409(client, db, monkeypatch):
    db.tables["students"].append({"id": "orphan", "name": "Orphan"})
    monkeypatch.setattr(api, "build_client_for_token", lambda token: FakeSupabase(db, "orphan"))
    monkeypatch.setattr(api, "build_client", lambda: ExplodingAI())

    response = upload(client)

    assert response.status_code == 409
    assert "home institution" in response.json()["detail"].lower()


# ── 12. institution-specific grading schema ─────────────────────────────────
# GET /me/grading-schema is the single canonical source the current-grade and
# final-grade selectors (and, at compute time, resolve_grade/academics/gpa.py)
# must agree on -- see GradusIQ_career/planning/lifecycle.py's edit/finalize
# routes. These tests pin the exact TAMU vocabulary against a regression to a
# hard-coded generic plus/minus list, and confirm SMU's own scale stays
# independent rather than being flattened to match TAMU's.

GRADING_SCHEMA = "/api/v2/student/me/grading-schema"


def test_grading_schema_tamu_is_exactly_five_gpa_letters_plus_w_and_i(client, db, monkeypatch):
    patch_session(monkeypatch, db, STUDENT_A)  # STUDENT_A's home institution is TAMU

    response = client.get(GRADING_SCHEMA, headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["institution_id"] == TAMU
    assert body["uses_plus_minus"] is False
    assert [g["letter"] for g in body["grades"]] == ["A", "B", "C", "D", "F", "I", "W"]


def test_grading_schema_tamu_gpa_bearing_points_are_4_3_2_1_0(client, db, monkeypatch):
    patch_session(monkeypatch, db, STUDENT_A)

    response = client.get(GRADING_SCHEMA, headers=HEADERS)

    gpa_bearing = {
        g["letter"]: g["points"] for g in response.json()["grades"] if g["counts_toward_gpa"]
    }
    assert gpa_bearing == {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}
    non_gpa = {g["letter"] for g in response.json()["grades"] if not g["counts_toward_gpa"]}
    assert non_gpa == {"W", "I"}


def test_grading_schema_tamu_never_exposes_plus_minus_letters(client, db, monkeypatch):
    patch_session(monkeypatch, db, STUDENT_A)

    response = client.get(GRADING_SCHEMA, headers=HEADERS)

    letters = {g["letter"] for g in response.json()["grades"]}
    for bad in ("A-", "B+", "B-", "C+", "C-", "D+", "D-", "A+"):
        assert bad not in letters


def test_grading_schema_smu_keeps_its_own_independent_plus_minus_scale(client, db, monkeypatch):
    smu_student = "smu-student-0001"
    db.add_student(smu_student, SMU)
    monkeypatch.setattr(api, "build_client_for_token", lambda token: FakeSupabase(db, smu_student))

    response = client.get(GRADING_SCHEMA, headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["institution_id"] == SMU
    assert body["uses_plus_minus"] is True
    letters = {g["letter"] for g in body["grades"]}
    # SMU's scale, not TAMU's -- plus/minus letters and P are present, and
    # this must hold independently of whatever TAMU's own schema looks like.
    assert {"A", "A-", "B+", "B", "F", "P"} <= letters


def test_grading_schema_requires_a_home_institution(client, db, monkeypatch):
    db.tables["students"].append({"id": "orphan-grades", "name": "Orphan"})
    monkeypatch.setattr(
        api, "build_client_for_token", lambda token: FakeSupabase(db, "orphan-grades")
    )

    response = client.get(GRADING_SCHEMA, headers=HEADERS)

    assert response.status_code == 409


# ── 13. cross-listing map for the add-time duplicate check ─────────────────
# GET /me/catalog/cross-listings backs CourseSearchAdd's cross-listing-aware
# duplicate check. Deliberately backed by LocalCatalogRepository (the
# in-process JSON catalog, which carries a real cross_listings field) rather
# than the course_catalog table db.add_catalog() seeds -- that Supabase table
# has no cross_listings column at all, which is exactly why this route reads
# from a different source than /me/catalog/search does.

CROSS_LISTINGS = "/api/v2/student/me/catalog/cross-listings"


def test_cross_listings_returns_the_real_catalog_pair_for_tamu(client, db, monkeypatch):
    patch_session(monkeypatch, db, STUDENT_A)  # STUDENT_A's home institution is TAMU

    response = client.get(CROSS_LISTINGS, headers=HEADERS)

    assert response.status_code == 200
    mapping = response.json()["cross_listings"]
    assert mapping["CSCE 222"] == ["ECEN 222"]
    assert mapping["ECEN 222"] == ["CSCE 222"]
    # A code with no cross-listing carries no entry at all, not an empty list.
    assert "CSCE 121" not in mapping


def test_cross_listings_is_scoped_per_institution(client, db, monkeypatch):
    smu_student = "smu-student-0002"
    db.add_student(smu_student, SMU)
    monkeypatch.setattr(api, "build_client_for_token", lambda token: FakeSupabase(db, smu_student))

    response = client.get(CROSS_LISTINGS, headers=HEADERS)

    assert response.status_code == 200
    # SMU's own catalog, not TAMU's -- the TAMU-only CSCE/ECEN pair must not
    # leak into an SMU student's response.
    assert "CSCE 222" not in response.json()["cross_listings"]


def test_cross_listings_requires_a_home_institution(client, db, monkeypatch):
    db.tables["students"].append({"id": "orphan-cross-listings", "name": "Orphan"})
    monkeypatch.setattr(
        api, "build_client_for_token", lambda token: FakeSupabase(db, "orphan-cross-listings")
    )

    response = client.get(CROSS_LISTINGS, headers=HEADERS)

    assert response.status_code == 409
