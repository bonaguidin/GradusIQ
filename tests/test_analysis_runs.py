"""Background GAP/FIT/SHIFT runs: start returns at once, status reports the outcome."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from GradusIQ_career import analysis_runs, api
from tests.test_api_v2_me_routes import (  # noqa: F401
    PROXY_HEADERS,
    FakeAI,
    _call,
    _full_profile,
    _patch_session,
    client,
    make_test_config,
)

RUNS = "/api/v2/student/me/analysis-runs/gap"


def _wait_until_finished(client, timeout=5.0):  # noqa: F811
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = _call(client, "get", RUNS, None).json()
        if body["state"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError("run did not finish")


# ── registry ────────────────────────────────────────────────────────────────


def test_registry_runs_work_and_keeps_the_result():
    registry = analysis_runs.AnalysisRunRegistry()
    run, started = registry.start("s1", "gap", lambda: {"status": "success"}, lambda exc: (502, "x"))
    run.thread.join(1)

    assert started is True
    assert registry.get("s1", "gap").to_client(time.monotonic())["result"] == {"status": "success"}


def test_registry_joins_a_run_that_is_still_going():
    registry = analysis_runs.AnalysisRunRegistry()
    release = threading.Event()
    first, _ = registry.start("s1", "gap", lambda: release.wait(1) and {"n": 1}, lambda exc: (502, "x"))

    second, started = registry.start("s1", "gap", lambda: pytest.fail("must not run twice"), lambda exc: (502, "x"))
    release.set()
    first.thread.join(1)

    assert started is False and second is first


def test_registry_reports_a_failure_with_the_mapped_status():
    registry = analysis_runs.AnalysisRunRegistry()

    def boom():
        raise RuntimeError("model down")

    run, _ = registry.start("s1", "fit", boom, lambda exc: (502, f"mapped {type(exc).__name__}"))
    run.thread.join(1)

    assert run.to_client(time.monotonic()) == {
        "state": "failed", "elapsed_seconds": pytest.approx(0, abs=1), "status_code": 502,
        "detail": "mapped RuntimeError",
    }


def test_registry_forgets_finished_runs_after_a_while():
    now = [1000.0]
    registry = analysis_runs.AnalysisRunRegistry(clock=lambda: now[0])
    run, _ = registry.start("s1", "gap", lambda: {}, lambda exc: (502, "x"))
    run.thread.join(1)

    now[0] += analysis_runs.KEEP_FINISHED_SECONDS + 1

    assert registry.get("s1", "gap") is None


# ── routes ──────────────────────────────────────────────────────────────────


def test_start_returns_at_once_and_status_gives_the_saved_result(client, monkeypatch):  # noqa: F811
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    written = []
    monkeypatch.setattr(api, "_write_analysis_cache", lambda *args: written.append(args[2]) or True)

    started = _call(client, "post", RUNS, None)
    finished = _wait_until_finished(client)

    assert started.status_code == 200 and started.json()["state"] in {"running", "done"}
    assert finished["state"] == "done"
    assert "LIVE-RESULT" in str(finished["result"])
    assert written == ["GAP"]
    # The capacity slot was given back: both slots can be taken again.
    gate = client.app.state.ai_concurrency
    gate.acquire()
    gate.acquire()


def test_failed_run_reports_the_error_and_frees_the_slot(client, monkeypatch):  # noqa: F811
    _patch_session(monkeypatch, profile=_full_profile())

    def broken_client():
        raise RuntimeError("model down")

    monkeypatch.setattr(api, "build_client", broken_client)

    _call(client, "post", RUNS, None)
    finished = _wait_until_finished(client)

    assert finished["state"] == "failed"
    assert finished["status_code"] == 502
    assert finished["detail"] == "Analysis service is unavailable."
    client.app.state.ai_concurrency.acquire()
    client.app.state.ai_concurrency.acquire()


def test_start_while_busy_is_429(client, monkeypatch):  # noqa: F811
    _patch_session(monkeypatch, profile=_full_profile())
    gate = client.app.state.ai_concurrency
    gate.acquire()
    gate.acquire()

    response = _call(client, "post", RUNS, None)

    assert response.status_code == 429
    assert _call(client, "get", RUNS, None).json() == {"state": "none"}


def test_status_without_a_run_is_none(client, monkeypatch):  # noqa: F811
    _patch_session(monkeypatch, profile=_full_profile())

    assert _call(client, "get", RUNS, None).json() == {"state": "none"}


def test_unknown_feature_is_404(client, monkeypatch):  # noqa: F811
    _patch_session(monkeypatch, profile=_full_profile())

    assert _call(client, "post", "/api/v2/student/me/analysis-runs/chat", None).status_code == 404
    assert _call(client, "get", "/api/v2/student/me/analysis-runs/chat", None).status_code == 404


def test_status_reads_do_not_use_up_the_rate_limit(monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    limited = TestClient(api.create_app(make_test_config(rate_limit_requests=1)), headers=PROXY_HEADERS)

    statuses = [_call(limited, "get", RUNS, None).status_code for _ in range(5)]

    assert statuses == [200] * 5
    # The one rate-limited request is still available to start a run.
    assert _call(limited, "get", "/api/v2/student/me/profile", None).status_code != 429
