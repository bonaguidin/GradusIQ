"""Tests for POST /api/v2/student/me/feedback and GradusIQ_career/feedback/report.py.

No network: the route tests replace send_report with a recorder, and the
sender tests run Resend calls through httpx.MockTransport.
"""

from __future__ import annotations

import base64
import json
import tempfile
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from GradusIQ_career import api
from GradusIQ_career.feedback import report as feedback_report

TEST_PROXY_SECRET = "test-proxy-secret"
PROXY_HEADERS = {api.PROXY_SECRET_HEADER: TEST_PROXY_SECRET}

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64

VALID_FORM = {
    "kind": "bug",
    "description": "The Overview page shows a blank card after I upload my transcript.",
    "email": "student@example.edu",
    "name": "Test Student",
    "page": "Overview (/dashboard)",
    "user_agent": "Mozilla/5.0 test",
}


def make_client() -> TestClient:
    config = api.APIConfig(
        proxy_secret=TEST_PROXY_SECRET,
        allowed_origins=(),
        rate_limit_requests=1000,
        rate_limit_window_seconds=60.0,
        max_concurrent_ai_requests=2,
    )
    return TestClient(api.create_app(config), headers=PROXY_HEADERS)


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []

    def fake_send(report, *, api_key, to_address, from_address):
        calls.append(
            {"report": report, "api_key": api_key, "to": to_address, "from": from_address}
        )
        return "msg_123"

    monkeypatch.setattr(api.feedback_report, "send_report", fake_send)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.delenv("GRADUSIQ_REPORT_TO", raising=False)
    monkeypatch.delenv("GRADUSIQ_REPORT_FROM", raising=False)
    return calls


@pytest.fixture
def no_session(monkeypatch):
    def refuse(_token):
        raise AssertionError("no Supabase call expected without a bearer token")

    monkeypatch.setattr(api, "build_client_for_token", refuse)


def fake_session(monkeypatch, *, user_id="user-1", email="owner@tamu.edu"):
    user = SimpleNamespace(id=user_id, email=email)
    client = SimpleNamespace(auth=SimpleNamespace(get_user=lambda _t: SimpleNamespace(user=user)))
    monkeypatch.setattr(api, "build_client_for_token", lambda _t: client)


# ── route ────────────────────────────────────────────────────────────────────


def test_anonymous_report_is_sent_to_team_inbox(sent, no_session):
    response = make_client().post("/api/v2/student/me/feedback", data=VALID_FORM)

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "sent"}
    assert len(sent) == 1
    report = sent[0]["report"]
    assert sent[0]["to"] == "gradus@gradusiq.com"
    assert sent[0]["api_key"] == "re_test_key"
    assert report.kind == "bug"
    assert report.email == "student@example.edu"
    assert report.account_email is None


def test_signed_in_report_carries_the_verified_account(sent, monkeypatch):
    fake_session(monkeypatch)
    response = make_client().post(
        "/api/v2/student/me/feedback",
        data={**VALID_FORM, "email": "typed@example.com"},
        headers={"Authorization": "Bearer token-abc"},
    )

    assert response.status_code == 200, response.text
    report = sent[0]["report"]
    assert report.account_email == "owner@tamu.edu"
    assert report.account_id == "user-1"
    # The typed address is still the one replies go to.
    assert report.email == "typed@example.com"


def test_unverifiable_session_still_sends_as_anonymous(sent, monkeypatch):
    def broken(_token):
        raise RuntimeError("expired")

    monkeypatch.setattr(api, "build_client_for_token", broken)
    response = make_client().post(
        "/api/v2/student/me/feedback",
        data=VALID_FORM,
        headers={"Authorization": "Bearer expired"},
    )
    assert response.status_code == 200
    assert sent[0]["report"].account_email is None


def test_screenshots_are_attached_and_renamed(sent, no_session):
    response = make_client().post(
        "/api/v2/student/me/feedback",
        data=VALID_FORM,
        files=[
            ("screenshots", ("../../etc/passwd.png", PNG, "image/png")),
            ("screenshots", ("photo.jpeg", JPEG, "image/jpeg")),
        ],
    )
    assert response.status_code == 200, response.text
    shots = sent[0]["report"].screenshots
    assert [s.filename for s in shots] == ["screenshot-1.png", "screenshot-2.jpg"]


def test_honeypot_reports_success_and_sends_nothing(sent, no_session):
    response = make_client().post(
        "/api/v2/student/me/feedback", data={**VALID_FORM, "website": "http://spam.example"}
    )
    assert response.status_code == 200
    assert sent == []


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"kind": "complaint"}, "bug or feature"),
        ({"description": "broken"}, "more detail"),
        ({"email": "not-an-email"}, "email address"),
        ({"email": "a@b.co\r\nBcc: x@y.z"}, "email address"),
    ],
)
def test_invalid_fields_are_rejected(sent, no_session, overrides, message):
    response = make_client().post("/api/v2/student/me/feedback", data={**VALID_FORM, **overrides})
    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert sent == []


def test_non_image_screenshot_is_rejected(sent, no_session):
    response = make_client().post(
        "/api/v2/student/me/feedback",
        data=VALID_FORM,
        files=[("screenshots", ("shot.png", b"<svg onload=alert(1)>", "image/png"))],
    )
    assert response.status_code == 422
    assert "PNG, JPEG or WebP" in response.json()["detail"]
    assert sent == []


def test_too_many_screenshots_is_rejected(sent, no_session):
    files = [("screenshots", (f"s{i}.png", PNG, "image/png")) for i in range(4)]
    response = make_client().post("/api/v2/student/me/feedback", data=VALID_FORM, files=files)
    assert response.status_code == 422
    assert sent == []


def test_too_many_screenshots_are_rejected_without_reading_any(sent, no_session, monkeypatch):
    # Starlette only writes uploads while parsing; the handler is the sole
    # reader, so any read() means a file was buffered before the count check.
    reads: list[int] = []
    original = tempfile.SpooledTemporaryFile.read

    def spy(self, *args):
        reads.append(1)
        return original(self, *args)

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "read", spy)
    files = [("screenshots", (f"s{i}.png", PNG, "image/png")) for i in range(feedback_report.MAX_SCREENSHOTS + 3)]
    response = make_client().post("/api/v2/student/me/feedback", data=VALID_FORM, files=files)

    assert response.status_code == 422
    assert str(feedback_report.MAX_SCREENSHOTS) in response.json()["detail"]
    assert reads == []
    assert sent == []


def test_body_over_the_cap_is_413_before_parsing(sent, no_session):
    body = b"x" * (api.MAX_FEEDBACK_BODY_BYTES + 1)
    response = make_client().post(
        "/api/v2/student/me/feedback",
        content=body,
        headers={"Content-Type": "multipart/form-data; boundary=zzz"},
    )
    assert response.status_code == 413
    assert sent == []


def test_streamed_body_over_the_cap_is_413_without_content_length(sent, no_session):
    def chunks():
        chunk = b"x" * 65536
        for _ in range(api.MAX_FEEDBACK_BODY_BYTES // len(chunk) + 2):
            yield chunk

    response = make_client().post(
        "/api/v2/student/me/feedback",
        content=chunks(),
        headers={"Content-Type": "multipart/form-data; boundary=zzz"},
    )
    assert response.status_code == 413
    assert sent == []


def test_cap_applies_only_to_the_feedback_route(sent, no_session):
    # A normal report just under the cap still goes through.
    files = [("screenshots", ("a.png", PNG + b"\x00" * 1_000_000, "image/png"))]
    response = make_client().post("/api/v2/student/me/feedback", data=VALID_FORM, files=files)
    assert response.status_code == 200, response.text


def test_oversized_screenshot_is_rejected(sent, no_session):
    big = PNG + b"\x00" * feedback_report.MAX_SCREENSHOT_BYTES
    response = make_client().post(
        "/api/v2/student/me/feedback",
        data=VALID_FORM,
        files=[("screenshots", ("big.png", big, "image/png"))],
    )
    assert response.status_code == 422
    assert sent == []


def test_anonymous_reports_share_one_rate_limit(sent, no_session):
    client = make_client()
    limit = api.FEEDBACK_ANONYMOUS_LIMIT[0]
    for _ in range(limit):
        assert client.post("/api/v2/student/me/feedback", data=VALID_FORM).status_code == 200
    response = client.post("/api/v2/student/me/feedback", data=VALID_FORM)
    assert response.status_code == 429
    assert len(sent) == limit


def test_signed_in_rate_limit_is_per_account(sent, monkeypatch):
    client = make_client()
    limit = api.FEEDBACK_ACCOUNT_LIMIT[0]
    fake_session(monkeypatch, user_id="user-1")
    for _ in range(limit):
        assert client.post(
            "/api/v2/student/me/feedback", data=VALID_FORM, headers={"Authorization": "Bearer a"}
        ).status_code == 200
    assert client.post(
        "/api/v2/student/me/feedback", data=VALID_FORM, headers={"Authorization": "Bearer a"}
    ).status_code == 429

    fake_session(monkeypatch, user_id="user-2")
    assert client.post(
        "/api/v2/student/me/feedback", data=VALID_FORM, headers={"Authorization": "Bearer b"}
    ).status_code == 200


def test_missing_api_key_is_a_clear_503(monkeypatch, no_session):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    response = make_client().post("/api/v2/student/me/feedback", data=VALID_FORM)
    assert response.status_code == 503
    assert "gradus@gradusiq.com" in response.json()["detail"]


def test_delivery_failure_is_a_502(monkeypatch, no_session):
    def failing(*_args, **_kwargs):
        raise feedback_report.ReportDeliveryError("Email service returned 403: domain not verified")

    monkeypatch.setattr(api.feedback_report, "send_report", failing)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    response = make_client().post("/api/v2/student/me/feedback", data=VALID_FORM)
    assert response.status_code == 502
    assert "domain" not in response.json()["detail"]


def test_requires_proxy_secret(sent, no_session):
    config = api.APIConfig(
        proxy_secret=TEST_PROXY_SECRET,
        allowed_origins=(),
        rate_limit_requests=1000,
        rate_limit_window_seconds=60.0,
        max_concurrent_ai_requests=2,
    )
    response = TestClient(api.create_app(config)).post("/api/v2/student/me/feedback", data=VALID_FORM)
    assert response.status_code == 401
    assert sent == []


def test_report_address_env_overrides(sent, no_session, monkeypatch):
    monkeypatch.setenv("GRADUSIQ_REPORT_TO", "qa@gradusiq.com")
    monkeypatch.setenv("GRADUSIQ_REPORT_FROM", "Reports <bugs@gradusiq.com>")
    make_client().post("/api/v2/student/me/feedback", data=VALID_FORM)
    assert sent[0]["to"] == "qa@gradusiq.com"
    assert sent[0]["from"] == "Reports <bugs@gradusiq.com>"


# ── email sender ─────────────────────────────────────────────────────────────


def _report(**overrides) -> feedback_report.Report:
    values = dict(
        kind="feature",
        description="Please add a dark mode.\nIt would help at night.",
        name="Sam",
        email="sam@example.com",
        page="Career",
        user_agent="UA",
        screenshots=(feedback_report.Screenshot("screenshot-1.webp", "image/webp", WEBP),),
    )
    values.update(overrides)
    return feedback_report.Report(**values)


def test_send_report_posts_plain_text_with_reply_to_and_attachments():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "abc"})

    message_id = feedback_report.send_report(
        _report(), api_key="re_key", transport=httpx.MockTransport(handler)
    )

    body = captured["body"]
    assert message_id == "abc"
    assert captured["auth"] == "Bearer re_key"
    assert body["to"] == ["gradus@gradusiq.com"]
    assert body["reply_to"] == "sam@example.com"
    assert body["subject"] == "[GradusIQ Feature request] Please add a dark mode."
    assert "html" not in body
    assert "Please add a dark mode." in body["text"]
    assert "Not signed in" in body["text"]
    assert body["attachments"] == [
        {"filename": "screenshot-1.webp", "content": base64.b64encode(WEBP).decode()}
    ]


def test_send_report_raises_on_provider_error():
    transport = httpx.MockTransport(lambda _r: httpx.Response(403, json={"message": "nope"}))
    with pytest.raises(feedback_report.ReportDeliveryError):
        feedback_report.send_report(_report(), api_key="re_key", transport=transport)


def test_send_report_requires_a_key():
    with pytest.raises(feedback_report.ReportNotConfiguredError):
        feedback_report.send_report(_report(), api_key="")


def test_long_subject_is_trimmed():
    body = feedback_report.build_email(
        _report(description="x" * 200), to_address="t@x.com", from_address="f@x.com"
    )
    assert len(body["subject"]) < 110
    assert body["subject"].endswith("...")


def test_keyed_rate_limiter_window_slides():
    now = [0.0]
    limiter = feedback_report.KeyedRateLimiter(limit=2, window_seconds=10.0, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")
    now[0] = 10.5
    assert limiter.allow("a")
