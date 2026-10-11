"""Unit tests for the scratch job-posting diagnostic clients
(scripts/job_postings/). Mirrors the FakeClient + monkeypatch mock-injection
style already used in tests/test_role_research_agent.py -- no cassette
library, no real network calls.
"""

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "job_postings"))

import adzuna_client  # noqa: E402
import jsearch_client  # noqa: E402
from errors import JobPostingConfigError, JobPostingRequestError  # noqa: E402


class FakeHTTPResponse:
    def __init__(self, payload, status_code=200, *, json_exc=None, text=""):
        self.payload = payload
        self.status_code = status_code
        self._json_exc = json_exc
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self.payload


class FakeSession:
    """Records every .get() call so tests can assert on what was (or was
    not) sent, matching SequencedHTTPSession's .calls list convention."""

    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, "kwargs": kwargs})
        if self._exc is not None:
            raise self._exc
        return self._response


# ---------------------------------------------------------------- Adzuna


def test_adzuna_missing_app_id_raises_config_error(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    with pytest.raises(JobPostingConfigError):
        adzuna_client.AdzunaClient(app_key="key-only")


def test_adzuna_missing_app_key_raises_config_error(monkeypatch):
    # GradusIQ_career/api.py's load_dotenv() (imported transitively by
    # earlier-collected test modules) puts .env's real ADZUNA_APP_KEY into
    # this process's environment before this test ever runs -- same
    # class of leak tests/conftest.py's _no_live_role_research_by_default
    # already documents for OPENROUTER_API_KEY/TAVILY_API_KEY.
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    with pytest.raises(JobPostingConfigError):
        adzuna_client.AdzunaClient(app_id="id-only")


def test_adzuna_dry_run_by_default_sends_nothing(capsys):
    session = FakeSession()
    client = adzuna_client.AdzunaClient(app_id="id", app_key="secret-key", session=session)

    result = client.search(what="embedded systems", where="Dallas")

    assert result is None
    assert session.calls == []
    captured = capsys.readouterr()
    assert "DRY RUN" in captured.out
    assert "secret-key" not in captured.out


def test_adzuna_live_call_sends_request_and_returns_json():
    session = FakeSession(response=FakeHTTPResponse({"count": 23, "results": []}))
    client = adzuna_client.AdzunaClient(app_id="id", app_key="secret-key", session=session)

    result = client.search(what="clinical volunteer", where="Dallas", live=True)

    assert result == {"count": 23, "results": []}
    assert len(session.calls) == 1
    assert session.calls[0]["kwargs"]["params"]["app_key"] == "secret-key"


def test_adzuna_results_per_page_defaults_small():
    client = adzuna_client.AdzunaClient(app_id="id", app_key="secret-key")
    _url, params = client.build_request(what="x", where="Dallas")
    assert params["results_per_page"] == 5


@pytest.mark.parametrize(
    "status_code,expected_transient",
    [(429, True), (503, True), (404, False), (401, False)],
)
def test_adzuna_live_call_classifies_transient_vs_permanent(status_code, expected_transient):
    session = FakeSession(response=FakeHTTPResponse({}, status_code=status_code))
    client = adzuna_client.AdzunaClient(app_id="id", app_key="secret-key", session=session)

    with pytest.raises(JobPostingRequestError) as exc_info:
        client.search(what="x", where="Dallas", live=True)

    assert exc_info.value.transient is expected_transient


def test_adzuna_connection_error_is_transient():
    session = FakeSession(exc=requests.ConnectionError("boom"))
    client = adzuna_client.AdzunaClient(app_id="id", app_key="secret-key", session=session)

    with pytest.raises(JobPostingRequestError) as exc_info:
        client.search(what="x", where="Dallas", live=True)

    assert exc_info.value.transient is True


def test_adzuna_200_with_non_json_body_raises_caught_error_not_a_raw_decode():
    """A maintenance page / CDN error returned as HTTP 200 must come back as a
    JobPostingRequestError so ingest.py's per-role handler catches it -- not a
    raw ValueError that escapes and aborts the whole nightly loop."""
    bad = FakeHTTPResponse(
        None, status_code=200,
        json_exc=requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0),
    )
    session = FakeSession(response=bad)
    client = adzuna_client.AdzunaClient(app_id="id", app_key="secret-key", session=session)

    with pytest.raises(JobPostingRequestError) as exc_info:
        client.search(what="x", where="Dallas", live=True)

    assert exc_info.value.transient is False
    assert "non-JSON body" in str(exc_info.value)
    assert "HTTP 200" in str(exc_info.value)


# ------------------------------------------------- Credential redaction
#
# A transient 503 during a live diagnostic run put the full request URL --
# including app_id and app_key, since Adzuna takes them as query params --
# into a printed traceback. requests' own exceptions embed that URL in
# their str(): HTTPError via response.url (set from the request that was
# actually sent), ConnectionError via urllib3's retry message. These pin
# that neither leaks through JobPostingRequestError's message, and that
# `from None` severs the chain so the original exception (URL and all) is
# not reachable from the raised one's __cause__/__context__ either.


def _real_response_with_credential_bearing_url(status_code: int) -> requests.Response:
    """A genuine requests.Response (not the simplified FakeHTTPResponse
    stand-in above) so response.raise_for_status() -- the exact call
    AdzunaClient.search() makes -- builds its message the same way it did
    for the real 503 that leaked: "503 Server Error: ... for url: ...",
    with the full query string including app_id/app_key."""
    response = requests.Response()
    response.status_code = status_code
    response.reason = "Service Temporarily Unavailable"
    response.url = (
        "https://api.adzuna.com/v1/api/jobs/us/search/1"
        "?app_id=SECRETAPPID&app_key=SECRETAPPKEY&what=software+engineer+intern"
    )
    return response


def test_live_503_does_not_leak_credentials_into_the_raised_error():
    # FakeSession returns this response from .get(); AdzunaClient.search()
    # then calls the REAL response.raise_for_status() on it, exactly as it
    # does against a real Adzuna response -- not a hand-built exception.
    response = _real_response_with_credential_bearing_url(503)
    session = FakeSession(response=response)
    client = adzuna_client.AdzunaClient(app_id="SECRETAPPID", app_key="SECRETAPPKEY", session=session)

    with pytest.raises(JobPostingRequestError) as exc_info:
        client.search(what="software engineer intern", where="Dallas", live=True)

    message = str(exc_info.value)
    assert "SECRETAPPID" not in message
    assert "SECRETAPPKEY" not in message
    assert "api.adzuna.com" not in message
    assert exc_info.value.transient is True
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True  # from None -- never auto-printed


def test_live_connection_error_does_not_leak_credentials_into_the_raised_error():
    # urllib3's own retry-exhausted message embeds the full path + query
    # string it was trying to reach, including the credentials.
    underlying = requests.ConnectionError(
        "HTTPSConnectionPool(host='api.adzuna.com', port=443): Max retries "
        "exceeded with url: /v1/api/jobs/us/search/1?app_id=SECRETAPPID&"
        "app_key=SECRETAPPKEY&what=software+engineer+intern"
    )
    session = FakeSession(exc=underlying)
    client = adzuna_client.AdzunaClient(app_id="SECRETAPPID", app_key="SECRETAPPKEY", session=session)

    with pytest.raises(JobPostingRequestError) as exc_info:
        client.search(what="software engineer intern", where="Dallas", live=True)

    message = str(exc_info.value)
    assert "SECRETAPPID" not in message
    assert "SECRETAPPKEY" not in message
    assert exc_info.value.transient is True
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True  # from None -- never auto-printed


def test_full_traceback_text_does_not_contain_credentials():
    """The exact failure mode: a caller that prints traceback.format_exc()
    (or lets an uncaught exception print one) must not see the credentials
    either -- not just str(exc) in isolation."""
    import traceback

    response = _real_response_with_credential_bearing_url(503)
    session = FakeSession(response=response)
    client = adzuna_client.AdzunaClient(app_id="SECRETAPPID", app_key="SECRETAPPKEY", session=session)

    try:
        client.search(what="software engineer intern", where="Dallas", live=True)
    except JobPostingRequestError:
        rendered = traceback.format_exc()
    else:
        pytest.fail("expected JobPostingRequestError")

    assert "SECRETAPPID" not in rendered
    assert "SECRETAPPKEY" not in rendered


# ---------------------------------------------------------------- JSearch


def test_jsearch_missing_base_url_raises_config_error(monkeypatch):
    # Same .env-via-load_dotenv() leak as test_adzuna_missing_app_key_raises_
    # config_error above -- JSEARCH_BASE_URL is real in .env.
    monkeypatch.delenv("JSEARCH_BASE_URL", raising=False)
    with pytest.raises(JobPostingConfigError):
        jsearch_client.JSearchClient(api_key="key-only")


def test_jsearch_missing_api_key_raises_config_error(monkeypatch):
    # Same leak; the client reads JSEARCH_RAPIDAPI_KEY (see
    # jsearch_client.py:85), which .env also sets for real.
    monkeypatch.delenv("JSEARCH_RAPIDAPI_KEY", raising=False)
    with pytest.raises(JobPostingConfigError):
        jsearch_client.JSearchClient(base_url="https://api.openwebninja.com")


def test_jsearch_dry_run_by_default_sends_nothing_and_masks_key(capsys):
    session = FakeSession()
    client = jsearch_client.JSearchClient(
        base_url="https://api.openwebninja.com", api_key="ak_secretvalue", session=session
    )

    result = client.search(query="clinical volunteer", location="Dallas, TX")

    assert result is None
    assert session.calls == []
    captured = capsys.readouterr()
    assert "DRY RUN" in captured.out
    assert "ak_secretvalue" not in captured.out


def test_jsearch_live_call_sends_auth_header():
    payload = {"data": [{"job_title": "Clinical Research Volunteer", "job_publisher": "LinkedIn"}]}
    session = FakeSession(response=FakeHTTPResponse(payload))
    client = jsearch_client.JSearchClient(
        base_url="https://api.openwebninja.com", api_key="ak_secretvalue", session=session
    )

    result = client.search(query="clinical volunteer", live=True)

    assert result == payload
    assert len(session.calls) == 1
    assert session.calls[0]["kwargs"]["headers"][client.auth_header] == "ak_secretvalue"


def test_jsearch_200_with_non_json_body_raises_caught_error():
    bad = FakeHTTPResponse(
        None, status_code=200, text="<html>maintenance</html>",
        json_exc=requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0),
    )
    session = FakeSession(response=bad)
    client = jsearch_client.JSearchClient(
        base_url="https://api.openwebninja.com", api_key="ak_secretvalue", session=session
    )

    with pytest.raises(JobPostingRequestError) as exc_info:
        client.search(query="x", live=True)

    assert exc_info.value.transient is False
    assert "non-JSON body (HTTP 200)" in str(exc_info.value)


def test_find_source_field_prefers_job_publisher():
    item = {"job_title": "x", "job_publisher": "LinkedIn", "source": "other"}
    assert jsearch_client.find_source_field(item) == ("job_publisher", "LinkedIn")


def test_find_source_field_returns_none_when_absent():
    assert jsearch_client.find_source_field({"job_title": "x"}) is None
