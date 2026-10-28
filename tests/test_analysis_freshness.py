"""Saved GAP/FIT/SHIFT results report when the profile changed since they ran."""

import copy
import logging

import pytest

from GradusIQ_career import analysis_freshness, api
from tests.test_api_v2_me_routes import FakeAI, _call, _full_profile, _patch_session, client  # noqa: F401


def with_courses(profile, courses):
    profile = copy.deepcopy(profile)
    profile["courses"] = courses
    return profile


COURSE = {"id": "row-1", "term_id": "t1", "course_code": "CS 1341", "title": "Principles",
          "credit_hours": 3, "letter_grade": "B", "status": "completed", "credit_type": "resident",
          "source": "transcript_parse"}


# ── fingerprints ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("feature", ["GAP", "FIT", "SHIFT"])
def test_fingerprint_is_stable_for_the_same_inputs(feature):
    assert analysis_freshness.input_fingerprint(feature, _full_profile()) == \
        analysis_freshness.input_fingerprint(feature.lower(), _full_profile())


def test_unknown_feature_has_no_fingerprint():
    assert analysis_freshness.input_fingerprint("PROFESSOR_COMMENTS", _full_profile()) is None


@pytest.mark.parametrize(
    ("change", "changed_for"),
    [
        (lambda p: p["career"]["skills_self_reported"]["technical"].append("SQL"), {"GAP", "FIT", "SHIFT"}),
        (lambda p: p["career"]["work_experience"].append({"employer": "Beta"}), {"GAP", "FIT"}),
        (lambda p: p["career"].update(geographic_preference="Austin"), {"FIT"}),
        (lambda p: p["career"].update(ai_anxiety_level="high"), {"SHIFT"}),
        (lambda p: p["student"].update(major_current="Math"), {"GAP", "FIT", "SHIFT"}),
        (lambda p: p["student"].update(expected_graduation="2029-05"), {"GAP"}),
        (lambda p: p.update(courses=[{**COURSE, "letter_grade": "A"}]), {"GAP"}),
        # Not an input to any analysis: the name and onboarding progress.
        (lambda p: p["student"].update(name="Renamed", onboarding_stage=4), set()),
    ],
)
def test_only_inputs_a_feature_reads_change_its_fingerprint(change, changed_for):
    before = with_courses(_full_profile(), [COURSE])
    after = copy.deepcopy(before)
    change(after)
    for feature in ("GAP", "FIT", "SHIFT"):
        differs = analysis_freshness.input_fingerprint(feature, before) != \
            analysis_freshness.input_fingerprint(feature, after)
        assert differs == (feature in changed_for), feature


def test_reimported_course_rows_with_new_ids_are_not_a_change():
    before = with_courses(_full_profile(), [COURSE])
    after = with_courses(_full_profile(), [{**COURSE, "id": "row-2", "term_id": "t9", "source": "manual"}])
    assert analysis_freshness.input_fingerprint("GAP", before) == analysis_freshness.input_fingerprint("GAP", after)


def test_for_client_swaps_fingerprint_for_verdict():
    profile = _full_profile()
    saved = analysis_freshness.stamp({"status": "success", "summary": "s"}, "FIT", profile)
    assert analysis_freshness.FINGERPRINT_KEY in saved

    served = analysis_freshness.for_client(saved, "fit", profile)
    assert served == {"status": "success", "summary": "s", "profile_changed": False}

    changed = copy.deepcopy(profile)
    changed["career"]["target_roles"].append("Data Engineer")
    assert analysis_freshness.for_client(saved, "fit", changed)["profile_changed"] is True


def test_results_saved_before_fingerprints_report_nothing():
    served = analysis_freshness.for_client({"status": "success"}, "gap", _full_profile())
    assert served == {"status": "success"}


# ── routes ──────────────────────────────────────────────────────────────────


def test_live_run_saves_a_stamped_result_and_returns_it_unstamped(client, monkeypatch):  # noqa: F811
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    written = []
    monkeypatch.setattr(
        api, "_write_analysis_cache",
        lambda client, sid, feature, role, result: written.append(result),
    )

    response = _call(client, "post", "/api/v2/student/me/analyze/gap", None)

    assert response.status_code == 200
    assert analysis_freshness.FINGERPRINT_KEY not in response.json()
    assert written[0][analysis_freshness.FINGERPRINT_KEY] == \
        analysis_freshness.input_fingerprint("GAP", _full_profile())


def test_live_run_logs_start_and_finish_with_timing(client, monkeypatch, caplog):  # noqa: F811
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())
    monkeypatch.setattr(api, "_write_analysis_cache", lambda *args: True)
    caplog.set_level(logging.INFO, logger="GradusIQ_career.api")

    response = _call(client, "post", "/api/v2/student/me/analyze/gap", None)

    assert response.status_code == 200
    lines = [r.getMessage() for r in caplog.records if r.name == "GradusIQ_career.api"]
    assert any(line.startswith("analysis run started: feature=GAP") for line in lines)
    finished = [line for line in lines if line.startswith("analysis run finished: feature=GAP")]
    assert len(finished) == 1 and "saved=True" in finished[0] and "after=" in finished[0]


def test_failed_run_is_logged(client, monkeypatch, caplog):  # noqa: F811
    _patch_session(monkeypatch, profile=_full_profile())

    def broken_client():
        raise RuntimeError("model down")

    monkeypatch.setattr(api, "build_client", broken_client)
    caplog.set_level(logging.INFO, logger="GradusIQ_career.api")

    response = _call(client, "post", "/api/v2/student/me/analyze/gap", None)

    assert response.status_code == 502
    failed = [r for r in caplog.records if r.getMessage().startswith("analysis run failed: feature=GAP")]
    assert len(failed) == 1 and failed[0].exc_info is not None


def test_cache_write_failure_is_logged_not_raised(caplog):
    class BrokenTable:
        def upsert(self, *args, **kwargs):
            raise RuntimeError("rls")

    class BrokenClient:
        def table(self, name):
            return BrokenTable()

    caplog.set_level(logging.WARNING, logger="GradusIQ_career.api")
    assert api._write_analysis_cache(BrokenClient(), "s1", "GAP", None, {"status": "success"}) is False
    assert any(r.getMessage() == "analysis cache write failed: feature=gap" for r in caplog.records)


@pytest.mark.parametrize("edit_profile", [False, True])
def test_cache_read_reports_profile_changed(client, monkeypatch, edit_profile):  # noqa: F811
    saved = analysis_freshness.stamp({"feature": "GAP", "status": "success", "summary": "old"},
                                     "GAP", _full_profile())
    current = _full_profile()
    if edit_profile:
        current["career"]["projects"].append({"name": "New project"})
    _patch_session(monkeypatch, profile=current)
    monkeypatch.setattr(api, "_read_analysis_cache", lambda client, sid, feature, role: dict(saved))

    response = _call(client, "get", "/api/v2/student/me/analysis-cache/gap", None)

    assert response.status_code == 200
    body = response.json()
    assert body["profile_changed"] is edit_profile
    assert analysis_freshness.FINGERPRINT_KEY not in body
