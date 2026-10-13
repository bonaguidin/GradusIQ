"""Canvas calendar feed: URL validation (the SSRF guard), iCal parsing,
windowing, and the /api/v2/student/me/canvas-calendar routes.

The sample feed mirrors what Canvas emits: assignment UIDs of the form
event-assignment-<id>, "Title [Course]" summaries, all-day due dates as
VALUE=DATE, timed ones in UTC, and folded long lines.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from GradusIQ_career import api
from GradusIQ_career.canvas import calendar_feed as cf


TEST_PROXY_SECRET = "test-proxy-secret"
PROXY_HEADERS = {api.PROXY_SECRET_HEADER: TEST_PROXY_SECRET}
AUTH = {"Authorization": "Bearer real-session-jwt"}
STUDENT = "stu-1"
INSTITUTION = "inst-1"
TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"
FEED_URL = f"https://canvas.tamu.edu/feeds/calendars/user_{TOKEN}.ics"
NOW = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def sample_ics(now: datetime = NOW) -> str:
    soon = now + timedelta(days=2)
    later = now + timedelta(days=9)
    far = now + timedelta(days=200)
    past = now - timedelta(days=30)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Instructure//Canvas//EN",
        "BEGIN:VEVENT",
        "UID:event-assignment-1001",
        f"DTSTART:{_stamp(soon)}",
        f"DTEND:{_stamp(soon)}",
        "SUMMARY:Homework 4 [MATH 151-501: Engineering Mathematics I]",
        "URL:https://canvas.tamu.edu/courses/55/assignments/1001",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:event-calendar-event-2002",
        f"DTSTART:{_stamp(later)}",
        f"DTEND:{_stamp(later + timedelta(hours=2))}",
        # Folded across two lines, with an escaped comma.
        "SUMMARY:Midterm Exam 2\\, Chapters 4-6 [CHEM 107: General Chemistry for",
        "  Engineers]",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:event-assignment-1003",
        f"DTSTART;VALUE=DATE:{(now + timedelta(days=5)).strftime('%Y%m%d')}",
        "SUMMARY:Final Project Proposal [ENGR 102]",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:event-assignment-1004",
        f"DTSTART:{_stamp(past)}",
        "SUMMARY:Old quiz [MATH 151-501: Engineering Mathematics I]",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:event-assignment-1005",
        f"DTSTART:{_stamp(far)}",
        "SUMMARY:Next year [MATH 152]",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:event-broken",
        "SUMMARY:No start date",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


# ── URL validation ───────────────────────────────────────────────────────────


def test_accepts_institution_host_and_normalizes_webcal():
    assert cf.validate_feed_url(FEED_URL, "canvas.tamu.edu") == FEED_URL
    webcal = FEED_URL.replace("https://", "webcal://")
    assert cf.validate_feed_url(f"  {webcal}  ", "canvas.tamu.edu") == FEED_URL


def test_accepts_instructure_subdomain_without_institution_host():
    url = f"https://smu.instructure.com/feeds/calendars/user_{TOKEN}.ics"
    assert cf.validate_feed_url(url, None) == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        f"http://canvas.tamu.edu/feeds/calendars/user_{TOKEN}.ics",
        f"https://evil.example/feeds/calendars/user_{TOKEN}.ics",
        f"https://canvas.tamu.edu.evil.example/feeds/calendars/user_{TOKEN}.ics",
        f"https://instructure.com/feeds/calendars/user_{TOKEN}.ics",
        f"https://169.254.169.254/feeds/calendars/user_{TOKEN}.ics",
        f"https://user:pw@canvas.tamu.edu/feeds/calendars/user_{TOKEN}.ics",
        f"https://canvas.tamu.edu:8443/feeds/calendars/user_{TOKEN}.ics",
        "https://canvas.tamu.edu/calendar",
        f"https://canvas.tamu.edu/feeds/calendars/user_{TOKEN}.ics?x=1",
        "https://canvas.tamu.edu/feeds/calendars/user_short.ics",
        f"https://canvas.tamu.edu/api/v1/users/self?f=/feeds/calendars/user_{TOKEN}.ics",
    ],
)
def test_rejects_anything_but_a_canvas_feed(url):
    with pytest.raises(cf.FeedUrlError):
        cf.validate_feed_url(url, "canvas.tamu.edu")


# ── parsing ─────────────────────────────────────────────────────────────────


def test_parse_ics_reads_canvas_shapes():
    events = {e.uid: e for e in cf.parse_ics(sample_ics())}
    assert "event-broken" not in events

    hw = events["event-assignment-1001"]
    assert hw.title == "Homework 4"
    assert hw.course_label == "MATH 151-501: Engineering Mathematics I"
    assert hw.kind == "assignment"
    assert hw.all_day is False
    assert hw.starts_at.endswith("Z")
    assert hw.likely_exam is False
    assert hw.url == "https://canvas.tamu.edu/courses/55/assignments/1001"

    exam = events["event-calendar-event-2002"]
    assert exam.title == "Midterm Exam 2, Chapters 4-6"
    assert exam.course_label == "CHEM 107: General Chemistry for Engineers"
    assert exam.kind == "event"
    assert exam.likely_exam is True

    proposal = events["event-assignment-1003"]
    assert proposal.all_day is True
    assert len(proposal.starts_at) == 10
    assert proposal.likely_exam is False


def test_tzid_times_are_converted_to_utc():
    text = "\n".join([
        "BEGIN:VCALENDAR",
        "BEGIN:VEVENT",
        "UID:x",
        "DTSTART;TZID=America/Chicago:20261020T090000",
        "SUMMARY:Lab",
        "END:VEVENT",
        "END:VCALENDAR",
    ])
    (event,) = cf.parse_ics(text)
    assert event.starts_at == "2026-10-20T14:00:00Z"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Exam 1", True),
        ("Midterm", True),
        ("Quiz 3", True),
        ("Final Exam", True),
        ("Final", True),
        ("Unit test review", True),
        ("Final Project", False),
        ("Final paper draft", False),
        ("Homework 2", False),
        ("Contest entry", False),
    ],
)
def test_looks_like_exam(title, expected):
    assert cf.looks_like_exam(title) is expected


def test_keep_for_storage_and_upcoming_windows():
    stored = cf.keep_for_storage(cf.parse_ics(sample_ics()), NOW)
    uids = [e["uid"] for e in stored]
    assert "event-assignment-1004" not in uids  # 30 days ago
    assert "event-assignment-1005" not in uids  # 200 days out
    assert uids == ["event-assignment-1001", "event-assignment-1003", "event-calendar-event-2002"]

    later = NOW + timedelta(days=3)
    assert [e["uid"] for e in cf.upcoming(stored, later)] == [
        "event-assignment-1003",
        "event-calendar-event-2002",
    ]


def test_staleness_backs_off_after_a_failed_sync():
    synced = (NOW - timedelta(days=1)).isoformat()
    assert cf.is_stale({"synced_at": synced}, NOW)
    assert not cf.is_stale({"synced_at": (NOW - timedelta(hours=1)).isoformat()}, NOW)
    failed_recently = {"synced_at": synced, "last_error": "x", "updated_at": (NOW - timedelta(minutes=5)).isoformat()}
    assert not cf.is_stale(failed_recently, NOW)
    failed_long_ago = dict(failed_recently, updated_at=(NOW - timedelta(hours=2)).isoformat())
    assert cf.is_stale(failed_long_ago, NOW)


def test_sync_rejects_non_calendar_body():
    with pytest.raises(cf.FeedFetchError):
        cf.sync(FEED_URL, "canvas.tamu.edu", NOW, fetcher=lambda url, host: "<html>login</html>")


# ── fetching ────────────────────────────────────────────────────────────────


def test_fetch_follows_same_host_redirect_but_not_foreign_one():
    def handler(request):
        if request.url.path.endswith("hop.ics"):
            return httpx.Response(302, headers={"location": "https://evil.example/x.ics"})
        if "user_" in request.url.path and request.url.host == "canvas.tamu.edu":
            return httpx.Response(302, headers={"location": "https://tamu.instructure.com/feeds/calendars/final.ics"})
        if request.url.host == "tamu.instructure.com":
            return httpx.Response(200, text="BEGIN:VCALENDAR\nEND:VCALENDAR")
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    assert cf.fetch_feed(FEED_URL, "canvas.tamu.edu", transport=transport).startswith("BEGIN:VCALENDAR")

    with pytest.raises(cf.FeedFetchError, match="unexpected"):
        cf.fetch_feed("https://canvas.tamu.edu/feeds/calendars/hop.ics", "canvas.tamu.edu", transport=transport)


def test_fetch_maps_not_found_to_reset_message():
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    with pytest.raises(cf.FeedFetchError, match="reset"):
        cf.fetch_feed(FEED_URL, "canvas.tamu.edu", transport=transport)


# ── routes ──────────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table):
        self.table = table
        self.filters = []
        self.op = "select"
        self.payload = None
        self.on_conflict = ""

    def select(self, *_a, **_k):
        return self

    def upsert(self, payload, *, on_conflict="", **_k):
        self.op, self.payload, self.on_conflict = "upsert", payload, on_conflict
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def _matches(self, row):
        return all(row.get(c) == v for c, v in self.filters)

    def execute(self):
        rows = self.table
        if self.op == "select":
            return FakeResponse([dict(r) for r in rows if self._matches(r)])
        if self.op == "upsert":
            for row in rows:
                if row.get(self.on_conflict) == self.payload.get(self.on_conflict):
                    row.update(self.payload)
                    return FakeResponse([dict(row)])
            rows.append(dict(self.payload))
            return FakeResponse([dict(self.payload)])
        if self.op == "update":
            hit = [r for r in rows if self._matches(r)]
            for r in hit:
                r.update(self.payload)
            return FakeResponse([dict(r) for r in hit])
        if self.op == "delete":
            hit = [r for r in rows if self._matches(r)]
            for r in hit:
                rows.remove(r)
            return FakeResponse(hit)
        raise AssertionError(self.op)


class FakeClient:
    def __init__(self, feeds=None):
        self.tables = {
            "students": [{"id": STUDENT}],
            "student_institutions": [
                {"student_id": STUDENT, "institution_id": INSTITUTION, "relationship": "home"}
            ],
            "institutions": [{"id": INSTITUTION, "canvas_host": "canvas.tamu.edu"}],
            "canvas_calendar_feeds": list(feeds or []),
        }

    def table(self, name):
        return FakeQuery(self.tables.setdefault(name, []))


@pytest.fixture
def client():
    config = api.APIConfig(
        proxy_secret=TEST_PROXY_SECRET,
        allowed_origins=("https://frontend.example",),
        rate_limit_requests=100,
        rate_limit_window_seconds=60.0,
        max_concurrent_ai_requests=2,
    )
    return TestClient(api.create_app(config), headers=PROXY_HEADERS)


@pytest.fixture
def feed_body(monkeypatch):
    calls = []

    def fake_fetch(url, host):
        calls.append(url)
        return sample_ics(datetime.now(timezone.utc))

    monkeypatch.setattr(cf, "fetch_feed", fake_fetch)
    return calls


def test_get_not_connected(client, monkeypatch):
    monkeypatch.setattr(api, "build_client_for_token", lambda token: FakeClient())
    resp = client.get("/api/v2/student/me/canvas-calendar", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"connected": False, "canvas_host": "canvas.tamu.edu", "events": []}


def test_put_saves_and_never_echoes_url(client, monkeypatch, feed_body):
    fake = FakeClient()
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)

    resp = client.put("/api/v2/student/me/canvas-calendar", headers=AUTH, json={"feed_url": FEED_URL})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connected"] is True
    assert TOKEN not in resp.text
    assert [e["uid"] for e in body["events"]] == [
        "event-assignment-1001",
        "event-assignment-1003",
        "event-calendar-event-2002",
    ]
    (row,) = fake.tables["canvas_calendar_feeds"]
    assert row["feed_url"] == FEED_URL and row["student_id"] == STUDENT


def test_put_rejects_foreign_url_without_fetching(client, monkeypatch, feed_body):
    fake = FakeClient()
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)
    resp = client.put(
        "/api/v2/student/me/canvas-calendar",
        headers=AUTH,
        json={"feed_url": "https://evil.example/feeds/calendars/user_" + TOKEN + ".ics"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "invalid_feed_url"
    assert feed_body == []
    assert fake.tables["canvas_calendar_feeds"] == []


def test_stale_get_refresh_failure_keeps_cached_events(client, monkeypatch):
    now = datetime.now(timezone.utc)
    cached = cf.keep_for_storage(cf.parse_ics(sample_ics(now)), now)
    fake = FakeClient(feeds=[{
        "student_id": STUDENT,
        "feed_url": FEED_URL,
        "feed_host": "canvas.tamu.edu",
        "events": cached,
        "synced_at": (now - timedelta(days=1)).isoformat(),
        "last_error": None,
    }])
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)

    def broken(url, host):
        raise cf.FeedFetchError("Couldn't reach Canvas. Try again shortly.")

    monkeypatch.setattr(cf, "fetch_feed", broken)

    resp = client.get("/api/v2/student/me/canvas-calendar", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_error"] == "Couldn't reach Canvas. Try again shortly."
    assert len(body["events"]) == 3
    assert fake.tables["canvas_calendar_feeds"][0]["last_error"] == body["last_error"]


def test_delete_disconnects(client, monkeypatch):
    fake = FakeClient(feeds=[{"student_id": STUDENT, "feed_url": FEED_URL, "events": []}])
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)
    resp = client.delete("/api/v2/student/me/canvas-calendar", headers=AUTH)
    assert resp.status_code == 200
    assert fake.tables["canvas_calendar_feeds"] == []
