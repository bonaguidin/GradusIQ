"""Tests for GET /api/v2/student/me/schedule (GradusIQ_career/api.py).

Mirrors test_api_v2_requirement_satisfaction.py's FakeClient/monkeypatch
convention exactly, reusing its ethan_brooks_tables() as the base and
extending it with the tables this route additionally needs: institutions
(for LocalCatalogRepository institution resolution), students.expected_
graduation, academic_term_dates (for the starting-term horizon), and
course_catalog rows widened with real credit_min/credit_max pulled from
data/catalog/smu/*.json (see the build task's investigation -- all 63
coursedog_group_ids in the shared fixture resolve cleanly against the real
catalog with matching codes).
"""

import json
from datetime import date
from itertools import product
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from GradusIQ_career import api
from GradusIQ_career.course_discovery.models import CareerSkillNeed, EvidenceState, StructuredPrerequisite
from GradusIQ_career.course_discovery.requirement_candidate_ranking import (
    RankedRequirementCandidate,
    RequirementCandidateRanking,
)
from GradusIQ_career.course_discovery.requirement_candidates import (
    AcademicFeasibility,
    CandidateExclusionReason,
    RequirementCandidate,
    RequirementCandidateSet,
    RequirementDecision,
    RequirementDecisionState,
)
from GradusIQ_career.course_discovery.catalog import LocalCatalogRepository
from GradusIQ_career.course_discovery.models import CatalogInstitution
from GradusIQ_career.course_discovery.requirement_satisfaction import evaluate_requirement_tree
from GradusIQ_career.course_discovery.requirement_selection import RequirementSelectionResult
from GradusIQ_career.course_discovery.requirement_selection import LockedSelectionFailureCode
from GradusIQ_career.course_discovery.requirement_selection import structured_candidate_codes
from GradusIQ_career.degree_schedule_choice_service import ChoiceWriteOutcome
from GradusIQ_career.course_discovery.scheduler import ScheduledCourse, ScheduleResult, TermPlan
from GradusIQ_career.degree_schedule_semantics import DegreeScheduleSemanticSnapshot
from GradusIQ_career.planning import term_view as term_view_module
from test_api_v2_me_routes import _canonical_profile
from test_api_v2_requirement_satisfaction import (
    CATALOG_YEAR,
    PROXY_HEADERS,
    SMU_INSTITUTION_ID,
    TEST_PROXY_SECRET,
    FakeClient,
    ethan_brooks_tables,
    make_test_config,
    student_with_no_program_tables,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ethan_brooks_requirement_tree.json"
SCHEDULE_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ethan_brooks_scheduler_input.json"
URL = "/api/v2/student/me/schedule"
OPTIMIZE_URL = "/api/v2/student/me/schedule/career-optimize"
TECHNICAL_ELECTIVES_URL = "/api/v2/student/me/degree-plan/technical-electives"
CHOICES_URL = "/api/v2/student/me/schedule/choices"

# Real credit_min/credit_max per coursedog_group_id, cross-referenced against
# every entry in the shared fixture's catalog_by_gid (63 gids, all resolve
# cleanly, all codes match) directly from data/catalog/smu/*.json.
_REAL_CREDIT_ROWS = json.loads((Path(__file__).parent / "fixtures" / "smu_catalog_credit_rows.json").read_text())

# Six long terms, Fall 2026 (the real upcoming term as of the fixture's
# 2026-08-19 pull date) through Spring 2029 -- matches spec §10.1's "5 terms,
# comfortably inside the 6-term horizon to Spring 2029" worked example.
_SMU_TERM_DATES = [
    {"institution_id": SMU_INSTITUTION_ID, "year": 2026, "season": "Fall", "label": "Fall 2026", "start_date": "2026-08-24", "end_date": "2026-12-12"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2027, "season": "Spring", "label": "Spring 2027", "start_date": "2027-01-19", "end_date": "2027-05-08"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2027, "season": "Fall", "label": "Fall 2027", "start_date": "2027-08-23", "end_date": "2027-12-11"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2028, "season": "Spring", "label": "Spring 2028", "start_date": "2028-01-18", "end_date": "2028-05-06"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2028, "season": "Fall", "label": "Fall 2028", "start_date": "2028-08-21", "end_date": "2028-12-09"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2029, "season": "Spring", "label": "Spring 2029", "start_date": "2029-01-16", "end_date": "2029-05-05"},
]


def _schedule_tables(expected_graduation="Spring 2029"):
    tables, student_id, program_id = ethan_brooks_tables()
    tables["institutions"] = [{"id": SMU_INSTITUTION_ID, "name": "Southern Methodist University"}]
    tables["students"][0]["expected_graduation"] = expected_graduation
    tables["academic_terms"] = []
    tables["academic_term_dates"] = _SMU_TERM_DATES
    tables["course_catalog"] = [
        {"institution_id": SMU_INSTITUTION_ID, "code": row["code"], "coursedog_group_id": row["coursedog_group_id"], "credit_min": row["credit_min"], "credit_max": row["credit_max"]}
        for row in _REAL_CREDIT_ROWS
    ]
    tables["degree_requirement_selections"] = []
    return tables, student_id, program_id


@pytest.fixture
def client():
    return TestClient(api.create_app(make_test_config()), headers=PROXY_HEADERS)


def _patch_client(monkeypatch, tables):
    fake = FakeClient(tables)
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)
    return fake


class _RpcResult:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class FakeScheduleChoiceServiceClient:
    def __init__(self, tables, student_id, program_id):
        self.tables = tables
        self.student_id = student_id
        self.program_id = program_id
        self.student_revision = 1
        self.program_revision = 1
        self.institution_revision = 1
        self.before_cas = None
        self.sync_count = 0
        self.cas_calls = 0

    def rpc(self, name, params):
        if name == "sync_degree_schedule_institution_semantics":
            self.sync_count += 1
            return _RpcResult({
                "status": "UNCHANGED",
                "institution_revision": self.institution_revision,
            })
        if name == "get_degree_schedule_revisions":
            return _RpcResult({
                "student_revision": self.student_revision,
                "program_revision": self.program_revision,
                "institution_revision": self.institution_revision,
            })
        if name != "replace_degree_requirement_selections":
            raise AssertionError(f"unexpected RPC {name}")
        self.cas_calls += 1
        if self.before_cas is not None:
            hook, self.before_cas = self.before_cas, None
            hook(self)
        if (
            params["p_expected_student_revision"] != self.student_revision
            or params["p_expected_program_revision"] != self.program_revision
            or params["p_expected_institution_revision"] != self.institution_revision
        ):
            return _RpcResult({"status": "REVISION_CONFLICT"})
        desired = params["p_selections"]
        current = sorted(
            (
                row["requirement_group_id"], row["candidate_id"], row["course_codes"]
            )
            for row in self.tables["degree_requirement_selections"]
            if row["student_id"] == self.student_id and row["program_id"] == self.program_id
        )
        wanted = sorted(
            (row["requirement_group_id"], row["candidate_id"], row["course_codes"])
            for row in desired
        )
        if current == wanted:
            return _RpcResult({"status": "UNCHANGED"})
        self.tables["degree_requirement_selections"][:] = [
            row for row in self.tables["degree_requirement_selections"]
            if row["student_id"] != self.student_id or row["program_id"] != self.program_id
        ] + [
            {
                "id": f"stored-{index}",
                "student_id": self.student_id,
                "program_id": self.program_id,
                "requirement_group_id": row["requirement_group_id"],
                "candidate_id": row["candidate_id"],
                "course_codes": list(row["course_codes"]),
                "decision_version": params["p_schedule_version"],
                "created_at": "now",
                "updated_at": "now",
            }
            for index, row in enumerate(desired)
        ]
        self.student_revision += 1
        return _RpcResult({"status": "APPLIED"})


def _choice_test_context(client, monkeypatch):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _freeze_today(monkeypatch, date(2026, 8, 19))
    service = FakeScheduleChoiceServiceClient(tables, student_id, program_id)
    monkeypatch.setattr(api, "build_service_client", lambda: service)
    schedule = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    sets = {item["requirement_group_id"]: item for item in schedule["candidate_sets"]}
    choices = [
        (decision, sets[decision["requirement_group_id"]])
        for decision in schedule["decisions"]
        if decision["state"] == "CHOICE_REQUIRED"
    ]
    return tables, service, schedule, choices


def _selection(candidate_set, index=0):
    candidate = candidate_set["feasible_candidates"][index]
    return {
        "requirement_group_id": candidate_set["requirement_group_id"],
        "candidate_id": candidate["candidate_id"],
        "course_codes": candidate["course_codes"],
    }


def _stored_selection(student_id, program_id, selection, suffix="one"):
    return {
        "id": f"stored-{suffix}",
        "student_id": student_id,
        "program_id": program_id,
        **selection,
        "decision_version": "sha256:" + "0" * 64,
        "created_at": "now",
        "updated_at": "now",
    }


def _freeze_today(monkeypatch, frozen):
    """Pin fetch_terms_view's date.today() call so 'upcoming term' resolution
    stays deterministic regardless of when the suite actually runs -- _SMU_TERM_DATES'
    2026-08-19 pull date is a real calendar date, not a moving target, so
    without this the test silently breaks the moment real time crosses
    2026-08-24 (Fall 2026's start_date). Subclassing date and overriding only
    .today() (rather than replacing the date class/constructor wholesale)
    keeps every other date(y, m, d) call in the production code path intact.
    """
    class _FrozenDate(date):
        @classmethod
        def today(cls):
            return frozen

    monkeypatch.setattr(term_view_module, "date", _FrozenDate)


def test_schedule_reconstruction_captures_one_date_and_never_rechecks_clock(
    client, monkeypatch
):
    tables, _, _ = _schedule_tables()
    _patch_client(monkeypatch, tables)
    captured = []

    def capture_once():
        captured.append(date(2026, 8, 19))
        return captured[-1]

    class _ClockMustNotBeRead(date):
        @classmethod
        def today(cls):
            raise AssertionError("downstream Degree Schedule code reread the wall clock")

    monkeypatch.setattr(api, "capture_reconstruction_date", capture_once)
    monkeypatch.setattr(term_view_module, "date", _ClockMustNotBeRead)

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})

    assert response.status_code == 200
    assert captured == [date(2026, 8, 19)]


def test_explicit_dates_across_term_boundary_change_schedule_version(client, monkeypatch):
    tables, _, _ = _schedule_tables()
    _patch_client(monkeypatch, tables)
    monkeypatch.setattr(api, "capture_reconstruction_date", lambda: date(2026, 8, 23))
    before = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    monkeypatch.setattr(api, "capture_reconstruction_date", lambda: date(2026, 8, 24))
    after = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()

    assert before["terms"][0]["term_key"] == "2026-Fall"
    assert after["terms"][0]["term_key"] == "2027-Spring"
    assert before["schedule_version"] != after["schedule_version"]


def test_put_schedule_choices_applies_and_returns_selection_aware_version(client, monkeypatch):
    tables, service, schedule, choices = _choice_test_context(client, monkeypatch)
    desired = _selection(choices[0][1])
    response = client.put(
        CHOICES_URL,
        json={"schedule_version": schedule["schedule_version"], "selections": [desired]},
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPLIED"
    assert body["selections"] == [desired]
    assert body["schedule_version"] != schedule["schedule_version"]
    assert service.cas_calls == 1
    assert tables["degree_requirement_selections"][0]["candidate_id"] == desired["candidate_id"]
    refreshed = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert refreshed["schedule_version"] == body["schedule_version"]
    locked = next(
        decision for decision in refreshed["decisions"]
        if decision["requirement_group_id"] == desired["requirement_group_id"]
    )
    assert locked["state"] == "LOCKED"
    assert locked["selected_candidate_id"] == desired["candidate_id"]
    assert refreshed["selection_state"] == {
        "status": "APPLIED", "selections": [desired], "failure": None,
    }
    scheduled_codes = {
        course["course_code"]
        for term in refreshed["terms"]
        for course in term["courses"]
    }
    assert set(desired["course_codes"]) <= scheduled_codes


def test_put_multi_course_choice_persists_one_atomic_row(client, monkeypatch):
    tables, _, schedule, choices = _choice_test_context(client, monkeypatch)
    candidate_set = next(
        candidate_set for _, candidate_set in choices
        if any(len(item["course_codes"]) > 1 for item in candidate_set["feasible_candidates"])
    )
    candidate = next(
        item for item in candidate_set["feasible_candidates"]
        if len(item["course_codes"]) > 1
    )
    desired = {
        "requirement_group_id": candidate_set["requirement_group_id"],
        "candidate_id": candidate["candidate_id"],
        "course_codes": candidate["course_codes"],
    }
    response = client.put(
        CHOICES_URL,
        json={"schedule_version": schedule["schedule_version"], "selections": [desired]},
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200
    assert len(tables["degree_requirement_selections"]) == 1
    assert tables["degree_requirement_selections"][0]["course_codes"] == candidate["course_codes"]
    refreshed = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    decision = next(
        item for item in refreshed["decisions"]
        if item["requirement_group_id"] == desired["requirement_group_id"]
    )
    assert decision["state"] == "LOCKED"
    scheduled = {
        course["course_code"] for term in refreshed["terms"] for course in term["courses"]
    }
    assert set(candidate["course_codes"]) <= scheduled


def test_put_accepts_a_globally_compatible_multi_requirement_complete_set(client, monkeypatch):
    tables, _, schedule, choices = _choice_test_context(client, monkeypatch)
    left, right = choices[0][1], choices[1][1]
    response = None
    submitted = None
    for left_candidate, right_candidate in product(
        left["feasible_candidates"], right["feasible_candidates"]
    ):
        desired = [
            {
                "requirement_group_id": left["requirement_group_id"],
                "candidate_id": left_candidate["candidate_id"],
                "course_codes": left_candidate["course_codes"],
            },
            {
                "requirement_group_id": right["requirement_group_id"],
                "candidate_id": right_candidate["candidate_id"],
                "course_codes": right_candidate["course_codes"],
            },
        ]
        response = client.put(
            CHOICES_URL,
            json={"schedule_version": schedule["schedule_version"], "selections": desired},
            headers={"Authorization": "Bearer good-token"},
        )
        if response.status_code == 200:
            submitted = desired
            break
        assert response.json()["detail"]["code"] == "LOCK_INCOMPATIBLE"
    assert response is not None and response.status_code == 200
    assert submitted is not None
    assert len(tables["degree_requirement_selections"]) == 2
    refreshed = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert refreshed["selection_state"]["status"] == "APPLIED"
    assert {
        item["requirement_group_id"] for item in refreshed["selection_state"]["selections"]
    } == {item["requirement_group_id"] for item in submitted}


def test_put_replaces_complete_set_and_empty_set_removes_all(client, monkeypatch):
    tables, _, schedule, choices = _choice_test_context(client, monkeypatch)
    first_set = choices[0][1]
    first = _selection(first_set, 0)
    applied = client.put(
        CHOICES_URL,
        json={"schedule_version": schedule["schedule_version"], "selections": [first]},
        headers={"Authorization": "Bearer good-token"},
    ).json()
    replacement = _selection(first_set, 1)
    replaced = client.put(
        CHOICES_URL,
        json={"schedule_version": applied["schedule_version"], "selections": [replacement]},
        headers={"Authorization": "Bearer good-token"},
    ).json()
    removed = client.put(
        CHOICES_URL,
        json={"schedule_version": replaced["schedule_version"], "selections": []},
        headers={"Authorization": "Bearer good-token"},
    )

    assert replaced["status"] == "APPLIED"
    assert len(tables["degree_requirement_selections"]) == 0
    assert removed.status_code == 200
    assert removed.json()["status"] == "APPLIED"
    assert removed.json()["selections"] == []


def test_refresh_change_and_clear_persisted_choice_lifecycle(client, monkeypatch):
    _, _, initial, choices = _choice_test_context(client, monkeypatch)
    first = _selection(choices[0][1], 0)
    second = _selection(choices[0][1], 1)

    applied = client.put(
        CHOICES_URL,
        json={"schedule_version": initial["schedule_version"], "selections": [first]},
        headers={"Authorization": "Bearer good-token"},
    ).json()
    refreshed = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert refreshed["schedule_version"] == applied["schedule_version"]
    assert refreshed["selection_state"]["status"] == "APPLIED"
    assert next(
        item for item in refreshed["decisions"]
        if item["requirement_group_id"] == first["requirement_group_id"]
    )["selected_candidate_id"] == first["candidate_id"]

    changed = client.put(
        CHOICES_URL,
        json={"schedule_version": refreshed["schedule_version"], "selections": [second]},
        headers={"Authorization": "Bearer good-token"},
    )
    assert changed.status_code == 200
    changed_get = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert changed_get["schedule_version"] == changed.json()["schedule_version"]
    changed_decision = next(
        item for item in changed_get["decisions"]
        if item["requirement_group_id"] == second["requirement_group_id"]
    )
    assert changed_decision["state"] == "LOCKED"
    assert changed_decision["selected_candidate_id"] == second["candidate_id"]

    cleared = client.put(
        CHOICES_URL,
        json={"schedule_version": changed_get["schedule_version"], "selections": []},
        headers={"Authorization": "Bearer good-token"},
    )
    assert cleared.status_code == 200
    cleared_get = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert cleared_get["selection_state"] == {
        "status": "NONE", "selections": [], "failure": None,
    }
    assert next(
        item for item in cleared_get["decisions"]
        if item["requirement_group_id"] == first["requirement_group_id"]
    )["state"] == "CHOICE_REQUIRED"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("candidate_removed", "LOCK_CANDIDATE_NOT_FOUND"),
        ("path_changed", "LOCK_PATH_MISMATCH"),
        ("choice_no_longer_required", "LOCK_CHOICE_NO_LONGER_REQUIRED"),
    ],
)
def test_stale_persisted_choice_falls_back_and_can_be_cleared(
    client, monkeypatch, mutation, expected_code
):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _freeze_today(monkeypatch, date(2026, 8, 19))
    service = FakeScheduleChoiceServiceClient(tables, student_id, program_id)
    monkeypatch.setattr(api, "build_service_client", lambda: service)
    if mutation == "choice_no_longer_required":
        # No group in this fixture auto-resolves to a sole feasible
        # candidate on its own data (StructuredPrerequisite.restrictions no
        # longer excludes a candidate purely for informational text -- see
        # test_ethan_brooks_returns_full_schedule_result). A student-
        # excluded group's decision is EXCLUDED, which is also
        # != CHOICE_REQUIRED -- the same "this decision no longer needs the
        # student's stale choice" shape _validate_locks gates on.
        seed = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
        excluded_group_id = next(
            item for item in seed["decisions"] if item["state"] == "CHOICE_REQUIRED"
        )["requirement_group_id"]
        tables["degree_requirement_exclusions"] = [{
            "student_id": student_id, "program_id": program_id,
            "requirement_group_id": excluded_group_id,
        }]
    unlocked = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    if mutation == "choice_no_longer_required":
        decision = next(item for item in unlocked["decisions"] if item["state"] == "EXCLUDED")
    else:
        decision = next(item for item in unlocked["decisions"] if item["state"] == "CHOICE_REQUIRED")
    candidate_set = next(
        item for item in unlocked["candidate_sets"]
        if item["requirement_group_id"] == decision["requirement_group_id"]
    )
    selection = _selection(candidate_set)
    if mutation == "candidate_removed":
        selection["candidate_id"] = "reqcand_removed"
    elif mutation == "path_changed":
        selection["course_codes"] = ["STALE 9999"]
    tables["degree_requirement_selections"] = [
        _stored_selection(student_id, program_id, selection)
    ]

    stale = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert stale["selection_state"]["status"] == "RESELECTION_REQUIRED"
    assert stale["selection_state"]["failure"]["code"] == expected_code
    assert stale["decisions"] == unlocked["decisions"]
    assert stale["terms"] == unlocked["terms"]
    repeated = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert repeated["schedule_version"] == stale["schedule_version"]

    cleared = client.put(
        CHOICES_URL,
        json={"schedule_version": stale["schedule_version"], "selections": []},
        headers={"Authorization": "Bearer good-token"},
    )
    assert cleared.status_code == 200
    assert client.get(URL, headers={"Authorization": "Bearer good-token"}).json()[
        "selection_state"
    ]["status"] == "NONE"


def test_excluded_persisted_choice_requires_reselection(client, monkeypatch):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _freeze_today(monkeypatch, date(2026, 8, 19))
    unlocked = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    candidate_set = next(item for item in unlocked["candidate_sets"] if item["excluded_candidates"])
    candidate = candidate_set["excluded_candidates"][0]
    selection = {
        "requirement_group_id": candidate_set["requirement_group_id"],
        "candidate_id": candidate["candidate_id"],
        "course_codes": candidate["course_codes"],
    }
    tables["degree_requirement_selections"] = [
        _stored_selection(student_id, program_id, selection)
    ]
    stale = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert stale["selection_state"]["status"] == "RESELECTION_REQUIRED"
    assert stale["selection_state"]["failure"]["code"] == "LOCK_CANDIDATE_EXCLUDED"
    assert stale["selection_state"]["failure"]["exclusion_reasons"]


def test_stale_persisted_choice_can_be_replaced_directly(client, monkeypatch):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _freeze_today(monkeypatch, date(2026, 8, 19))
    service = FakeScheduleChoiceServiceClient(tables, student_id, program_id)
    monkeypatch.setattr(api, "build_service_client", lambda: service)
    unlocked = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    candidate_set = next(
        item for item in unlocked["candidate_sets"]
        if len(item["feasible_candidates"]) > 1
    )
    valid = _selection(candidate_set, 1)
    stale_selection = {**_selection(candidate_set, 0), "candidate_id": "reqcand_removed"}
    tables["degree_requirement_selections"] = [
        _stored_selection(student_id, program_id, stale_selection)
    ]
    stale = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert stale["selection_state"]["status"] == "RESELECTION_REQUIRED"

    replaced = client.put(
        CHOICES_URL,
        json={"schedule_version": stale["schedule_version"], "selections": [valid]},
        headers={"Authorization": "Bearer good-token"},
    )
    assert replaced.status_code == 200
    refreshed = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert refreshed["selection_state"]["status"] == "APPLIED"
    decision = next(
        item for item in refreshed["decisions"]
        if item["requirement_group_id"] == valid["requirement_group_id"]
    )
    assert decision["state"] == "LOCKED"
    assert decision["selected_candidate_id"] == valid["candidate_id"]


def test_old_program_selection_is_inactive_and_retained(client, monkeypatch):
    tables, student_id, _ = _schedule_tables()
    old = {
        "requirement_group_id": "99999999-9999-4999-8999-999999999999",
        "candidate_id": "reqcand_old",
        "course_codes": ["OLD 1000"],
    }
    tables["degree_requirement_selections"] = [
        _stored_selection(student_id, "20000000-0000-0000-0000-000000000099", old)
    ]
    _patch_client(monkeypatch, tables)
    _freeze_today(monkeypatch, date(2026, 8, 19))
    response = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert response["selection_state"]["status"] == "NONE"
    assert len(tables["degree_requirement_selections"]) == 1


def test_put_same_current_set_is_unchanged_without_revision_advance(client, monkeypatch):
    tables, service, schedule, choices = _choice_test_context(client, monkeypatch)
    desired = _selection(choices[0][1])
    applied = client.put(
        CHOICES_URL,
        json={"schedule_version": schedule["schedule_version"], "selections": [desired]},
        headers={"Authorization": "Bearer good-token"},
    ).json()
    revision = service.student_revision
    repeated = client.put(
        CHOICES_URL,
        json={"schedule_version": applied["schedule_version"], "selections": [desired]},
        headers={"Authorization": "Bearer good-token"},
    )

    assert repeated.status_code == 200
    assert repeated.json()["status"] == "UNCHANGED"
    assert service.student_revision == revision


def test_two_tab_selection_only_stale_token_is_schedule_version_conflict(client, monkeypatch):
    tables, service, schedule, choices = _choice_test_context(client, monkeypatch)
    first = _selection(choices[0][1], 0)
    second = _selection(choices[0][1], 1)
    tab_a = client.put(
        CHOICES_URL,
        json={"schedule_version": schedule["schedule_version"], "selections": [first]},
        headers={"Authorization": "Bearer good-token"},
    )
    cas_calls = service.cas_calls
    tab_b = client.put(
        CHOICES_URL,
        json={"schedule_version": schedule["schedule_version"], "selections": [second]},
        headers={"Authorization": "Bearer good-token"},
    )

    assert tab_a.status_code == 200
    assert tab_b.status_code == 409
    assert tab_b.json()["detail"]["code"] == "SCHEDULE_VERSION_CONFLICT"
    assert service.cas_calls == cas_calls


@pytest.mark.parametrize("revision_name", [
    "student_revision", "program_revision", "institution_revision",
])
def test_put_revision_races_are_academic_revision_conflicts(
    client, monkeypatch, revision_name
):
    tables, service, schedule, choices = _choice_test_context(client, monkeypatch)
    service.before_cas = lambda current: setattr(
        current, revision_name, getattr(current, revision_name) + 1
    )
    response = client.put(
        CHOICES_URL,
        json={
            "schedule_version": schedule["schedule_version"],
            "selections": [_selection(choices[0][1])],
        },
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ACADEMIC_REVISION_CONFLICT"
    assert tables["degree_requirement_selections"] == []


def test_put_semantic_resynchronization_race_fails_closed(client, monkeypatch):
    tables, service, schedule, choices = _choice_test_context(client, monkeypatch)
    original_rpc = service.rpc

    def rpc(name, params):
        result = original_rpc(name, params)
        if name == "sync_degree_schedule_institution_semantics" and service.sync_count == 2:
            service.institution_revision += 1
        return result

    service.rpc = rpc
    response = client.put(
        CHOICES_URL,
        json={
            "schedule_version": schedule["schedule_version"],
            "selections": [_selection(choices[0][1])],
        },
        headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ACADEMIC_REVISION_CONFLICT"
    assert tables["degree_requirement_selections"] == []


def test_put_rejects_unknown_candidate_and_path_mismatch_without_rpc(client, monkeypatch):
    _, service, schedule, choices = _choice_test_context(client, monkeypatch)
    valid = _selection(choices[0][1])
    unknown = {**valid, "candidate_id": "reqcand_missing"}
    response = client.put(
        CHOICES_URL,
        json={"schedule_version": schedule["schedule_version"], "selections": [unknown]},
        headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LOCK_CANDIDATE_NOT_FOUND"
    assert service.cas_calls == 0

    mismatch = {**valid, "course_codes": ["WRONG 9999"]}
    response = client.put(
        CHOICES_URL,
        json={"schedule_version": schedule["schedule_version"], "selections": [mismatch]},
        headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LOCK_PATH_MISMATCH"
    assert service.cas_calls == 0


def test_put_rejects_unknown_requirement_and_excluded_candidate(client, monkeypatch):
    _, service, schedule, _ = _choice_test_context(client, monkeypatch)
    unknown = client.put(
        CHOICES_URL,
        json={
            "schedule_version": schedule["schedule_version"],
            "selections": [{
                "requirement_group_id": "99999999-9999-4999-8999-999999999999",
                "candidate_id": "reqcand_missing",
                "course_codes": ["CS 9999"],
            }],
        },
        headers={"Authorization": "Bearer good-token"},
    )
    assert unknown.status_code == 409
    assert unknown.json()["detail"]["code"] == "LOCK_REQUIREMENT_NOT_FOUND"

    candidate_set = next(
        item for item in schedule["candidate_sets"] if item["excluded_candidates"]
    )
    excluded_candidate = candidate_set["excluded_candidates"][0]
    excluded = client.put(
        CHOICES_URL,
        json={
            "schedule_version": schedule["schedule_version"],
            "selections": [{
                "requirement_group_id": candidate_set["requirement_group_id"],
                "candidate_id": excluded_candidate["candidate_id"],
                "course_codes": excluded_candidate["course_codes"],
            }],
        },
        headers={"Authorization": "Bearer good-token"},
    )
    assert excluded.status_code == 409
    assert excluded.json()["detail"]["code"] == "LOCK_CANDIDATE_EXCLUDED"
    assert excluded.json()["detail"]["exclusion_reasons"]
    assert service.cas_calls == 0


def test_put_rejects_date_boundary_stale_version(client, monkeypatch):
    _, service, schedule, choices = _choice_test_context(client, monkeypatch)
    monkeypatch.setattr(api, "capture_reconstruction_date", lambda: date(2026, 8, 24))
    response = client.put(
        CHOICES_URL,
        json={
            "schedule_version": schedule["schedule_version"],
            "selections": [_selection(choices[0][1])],
        },
        headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SCHEDULE_VERSION_CONFLICT"
    assert service.cas_calls == 0


def test_put_maps_incompatible_complete_set_without_persistence(client, monkeypatch):
    tables, service, schedule, choices = _choice_test_context(client, monkeypatch)
    monkeypatch.setattr(
        api,
        "write_degree_schedule_choices",
        lambda **kwargs: ChoiceWriteOutcome(
            conflict=LockedSelectionFailureCode.INCOMPATIBLE
        ),
    )
    response = client.put(
        CHOICES_URL,
        json={
            "schedule_version": schedule["schedule_version"],
            "selections": [_selection(choices[0][1])],
        },
        headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LOCK_INCOMPATIBLE"
    assert tables["degree_requirement_selections"] == []
    assert service.cas_calls == 0


def test_put_schedule_choices_is_model_free(client, monkeypatch):
    _, _, schedule, choices = _choice_test_context(client, monkeypatch)
    monkeypatch.setattr(
        api, "build_client",
        lambda: (_ for _ in ()).throw(AssertionError("model provider called")),
    )
    response = client.put(
        CHOICES_URL,
        json={
            "schedule_version": schedule["schedule_version"],
            "selections": [_selection(choices[0][1])],
        },
        headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 200


def test_put_choice_no_longer_required_and_structural_errors(client, monkeypatch):
    # No group in this Ethan Brooks fixture auto-resolves to a sole
    # feasible candidate on its own data any more (StructuredPrerequisite.
    # restrictions no longer excludes a candidate purely for informational
    # text -- see test_ethan_brooks_returns_full_schedule_result), so this
    # test can't reuse _choice_test_context's baseline to find an
    # AUTO_SELECTED decision. A student-excluded group's decision is
    # EXCLUDED instead, which is also != CHOICE_REQUIRED -- the same
    # "stale lock on a decision that no longer needs the student's choice"
    # shape _validate_locks gates on.
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _freeze_today(monkeypatch, date(2026, 8, 19))
    service = FakeScheduleChoiceServiceClient(tables, student_id, program_id)
    monkeypatch.setattr(api, "build_service_client", lambda: service)
    seed = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    excluded_group_id = next(
        item for item in seed["decisions"] if item["state"] == "CHOICE_REQUIRED"
    )["requirement_group_id"]
    tables["degree_requirement_exclusions"] = [{
        "student_id": student_id, "program_id": program_id,
        "requirement_group_id": excluded_group_id,
    }]
    schedule = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    auto_decision = next(item for item in schedule["decisions"] if item["state"] == "EXCLUDED")
    candidate_set = next(
        item for item in schedule["candidate_sets"]
        if item["requirement_group_id"] == auto_decision["requirement_group_id"]
    )
    response = client.put(
        CHOICES_URL,
        json={
            "schedule_version": schedule["schedule_version"],
            "selections": [_selection(candidate_set)],
        },
        headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LOCK_CHOICE_NO_LONGER_REQUIRED"
    assert service.cas_calls == 0

    invalid = client.put(
        CHOICES_URL,
        json={
            "schedule_version": "bad",
            "selections": [{
                "requirement_group_id": "not-a-uuid",
                "candidate_id": " ", "course_codes": [],
            }],
        },
        headers={"Authorization": "Bearer good-token"},
    )
    assert invalid.status_code == 422
    duplicate = _selection(candidate_set)
    duplicate_response = client.put(
        CHOICES_URL,
        json={
            "schedule_version": schedule["schedule_version"],
            "selections": [duplicate, duplicate],
        },
        headers={"Authorization": "Bearer good-token"},
    )
    assert duplicate_response.status_code == 422


def test_put_requires_authentication_and_accepts_no_identity_spoof_fields(client):
    unauthorized = client.put(
        CHOICES_URL,
        json={"schedule_version": "sha256:" + "a" * 64, "selections": []},
    )
    spoofed = client.put(
        CHOICES_URL,
        json={
            "schedule_version": "sha256:" + "a" * 64,
            "selections": [],
            "student_id": "10000000-0000-0000-0000-000000000099",
        },
        headers={"Authorization": "Bearer good-token"},
    )
    assert unauthorized.status_code == 401
    assert spoofed.status_code == 422


# 1. Ethan Brooks -- 200, full ScheduleResult including only sole-feasible
#    structured choices while preserving the response contract.
def test_ethan_brooks_returns_full_schedule_result(client, monkeypatch):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _freeze_today(monkeypatch, date(2026, 8, 19))

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()

    assert body["student_id"] == student_id
    assert body["program_id"] == program_id
    assert body["status"] == "SCHEDULED"
    assert body["failure"] is None
    assert body["schedule_version"].startswith("sha256:")
    assert len(body["schedule_version"]) == 71

    decisions = {item["requirement_name"]: item for item in body["decisions"]}
    candidate_sets = {item["requirement_name"]: item for item in body["candidate_sets"]}
    # Engineering Leadership no longer collapses to a single auto-picked
    # candidate. CS 5312's "Prerequisites: Junior standing" -- and every
    # other candidate's non-course prerequisite text in this set -- is
    # StructuredPrerequisite.restrictions, which is informational by its own
    # model contract ("classification... campus notes, and similar...
    # not enforced by the scheduler", models.py:261-269) and must not
    # exclude a candidate. With that no longer gating, 6 combinations of
    # {CEE 2302, CEE 3302, CS 3377, OREM 3308} are genuinely feasible, so
    # the student has a real choice instead of one silently auto-selected
    # because its siblings carried an unenforced restriction note.
    leadership_decision = decisions["Engineering Leadership (6 Credit Hours)"]
    assert leadership_decision["state"] == "CHOICE_REQUIRED"
    assert leadership_decision["selected_candidate_id"] is None
    assert len(candidate_sets["Engineering Leadership (6 Credit Hours)"]["feasible_candidates"]) == 6
    assert len(candidate_sets["Engineering Leadership (6 Credit Hours)"]["excluded_candidates"]) == 2
    assert all(
        candidate["exclusion_reasons"] == ["UNRESOLVED_COURSE"]
        for candidate in candidate_sets["Engineering Leadership (6 Credit Hours)"]["excluded_candidates"]
    )

    statistics_decision = decisions["Statistical Methods"]
    assert statistics_decision["state"] == "CHOICE_REQUIRED"
    assert statistics_decision["selected_candidate_id"] is None
    assert len(candidate_sets["Statistical Methods"]["feasible_candidates"]) == 3
    assert candidate_sets["Statistical Methods"]["excluded_candidates"] == []
    statistical_candidate = candidate_sets["Statistical Methods"]["feasible_candidates"][0]
    assert statistical_candidate["candidate_id"] == "reqcand_76e7fbe959765b5b"
    assert statistical_candidate["candidate_courses"] == [{
        "course_code": "CS 4340",
        "title": "Statistical Methods for Engineers and Applied Scientists",
        "credits": 3.0,
    }]

    two_courses_decision = decisions["Two Courses"]
    assert two_courses_decision["state"] == "CHOICE_REQUIRED"
    assert two_courses_decision["selected_candidate_id"] is None
    assert len(candidate_sets["Two Courses"]["feasible_candidates"]) == 13
    assert len(candidate_sets["Two Courses"]["excluded_candidates"]) == 3
    assert any(
        len(candidate["course_codes"]) == 4
        for candidate in candidate_sets["Two Courses"]["feasible_candidates"]
    )
    # CHEM 1303's "C- or higher in CHEM 1302 ... or a passing grade on the
    # Chemistry Placement Exam" mixes a real course code with an
    # unverifiable alternative path -- exactly the CS-1341-style shape
    # StructuredPrerequisite.needs_review's own contract describes
    # (models.py:270-280). It genuinely may hide an unresolved course
    # dependency, so it stays excluded even under the narrowed gate.
    needs_review_candidate = next(
        candidate for candidate in candidate_sets["Two Courses"]["excluded_candidates"]
        if set(candidate["course_codes"]) == {"CHEM 1113", "CHEM 1114", "CHEM 1303", "CHEM 1304"}
    )
    assert needs_review_candidate["exclusion_reasons"] == ["PREREQUISITE_NEEDS_REVIEW"]
    leadership_candidate = next(
        candidate for candidate in candidate_sets["Engineering Leadership (6 Credit Hours)"]["feasible_candidates"]
        if set(candidate["course_codes"]) == {"CEE 2302", "CS 3377"}
    )
    assert leadership_candidate["candidate_courses"] == [
        {"course_code": "CEE 2302", "title": "Authentic Leadership", "credits": 3.0},
        {"course_code": "CS 3377", "title": "Ethical Issues in Computing", "credits": 3.0},
    ]
    assert leadership_candidate["additional_credits"] == 6.0

    # Engineering Leadership now joins the unscheduled list too: with no
    # structured group AUTO_SELECTED, nothing beyond the base no-choice
    # courses is merged into the deterministic schedule.
    assert {u["name"] for u in body["unscheduled"]} == {
        "Advanced/Domain Specific Use/Design of AI",
        "Experiential Learning (1-3 Credit Hours)",
        "Statistical Methods",
        "Two Courses",
        "Engineering Leadership (6 Credit Hours)",
        "Technical Electives (9 Credit Hours)",
        "Advanced Major Electives (3-5 Credit Hours)",
    }
    assert len(body["unscheduled"]) == 7

    scheduled_codes = {course["course_code"] for term in body["terms"] for course in term["courses"]}
    schedule_fixture = json.loads(SCHEDULE_FIXTURE_PATH.read_text())
    expected_codes = {row["course_code"] for row in schedule_fixture["courses"]}
    assert scheduled_codes == expected_codes
    assert len(scheduled_codes) == 13
    assert not ({"CEE 2302", "CS 3377"} & scheduled_codes)
    assert not ({"CS 4340", "STAT 4340", "OREM 3340"} & scheduled_codes)

    # Structured selection consumes the existing slack without extending
    # the corrected four-term plan.
    assert len(body["terms"]) == 4
    assert body["terms"][0]["term_key"] == "2026-Fall"
    placement = {
        course["course_code"]: index
        for index, term in enumerate(body["terms"])
        for course in term["courses"]
    }
    assert placement["CS 2341"] < placement["CS 3353"]
    assert placement["CS 2353"] < placement["CS 3353"]
    for term in body["terms"]:
        assert term["total_credit_hours"] <= 15.0

    repeated = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert repeated.status_code == 200
    assert repeated.json() == body


def test_ethan_technical_elective_pool_is_read_only_and_catalog_grounded(client, monkeypatch):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    before = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()

    response = client.get(TECHNICAL_ELECTIVES_URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == student_id
    assert body["program_id"] == program_id
    assert body["catalog_year"] == CATALOG_YEAR
    assert body["requirement_name"] == "Technical Electives (9 Credit Hours)"
    assert body["credits_required"] == 9
    assert body["review_required"] is True
    assert body["institution"] == "smu"
    assert body["candidates"]
    assert all(item["course_code"].startswith("CS ") for item in body["candidates"])
    assert all(int(item["course_code"].split()[1]) >= 3000 for item in body["candidates"])
    assert all(item["credit_max"] > 0 for item in body["candidates"])
    assert len(body["limitations"]) == 3
    # technical_elective_candidates.py's own restriction/needs_review gate
    # (unrelated to select_structured_requirements' gate fixed above) is
    # unchanged, so those counts hold. excluded_already_used and
    # candidate_count shift by one: Engineering Leadership no longer
    # AUTO_SELECTs {CEE 2302, CS 3377}, so CS 3377 (CS 3000+) is no longer
    # claimed by another requirement and is a genuine technical-elective
    # candidate again.
    assert body["stats"] == {
        "catalog_courses_considered": 3249,
        "cs_3000_plus_courses": 87,
        "excluded_already_used": 7,
        "excluded_zero_credit": 1,
        "excluded_restriction_or_review": 46,
        "candidate_count": 33,
    }
    # SMU matches exactly one freeform group -- the new multi-group support
    # for TAMU must not surface a phantom "also satisfies" entry for SMU.
    assert body["also_satisfies_requirement_groups"] == []

    after = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    assert after == before
    # CEE 2302/CS 3377 are no longer merged into the deterministic schedule
    # (Engineering Leadership is CHOICE_REQUIRED, not AUTO_SELECTED) --
    # 15 courses/39 credits drops to the 13 base no-choice courses/33 credits.
    assert sum(len(term["courses"]) for term in after["terms"]) == 13
    assert sum(term["total_credit_hours"] for term in after["terms"]) == 33
    assert len(after["terms"]) == 4
    assert len(after["unscheduled"]) == 7


def test_technical_elective_endpoint_is_model_free(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("candidate GET must not build a model"))
    monkeypatch.setattr(
        api, "rank_requirement_candidates",
        lambda *args, **kwargs: pytest.fail("candidate GET must not invoke ranking"),
    )
    response = client.get(TECHNICAL_ELECTIVES_URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    # 33, not 32: see test_ethan_technical_elective_pool_is_read_only_and_
    # catalog_grounded -- Engineering Leadership no longer AUTO_SELECTs
    # CS 3377, so it's free to appear as a technical-elective candidate too.
    assert response.json()["stats"]["candidate_count"] == 33


def test_missing_technical_elective_requirement_skips_safely(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables()
    tables["requirement_groups"] = [
        row for row in tables["requirement_groups"]
        if row.get("coursedog_rule_id") != "AjzAZTn4"
    ]
    _patch_client(monkeypatch, tables)
    response = client.get(TECHNICAL_ELECTIVES_URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"


def test_get_schedule_is_strictly_model_and_optimization_free(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("GET must not build a model client"))
    monkeypatch.setattr(
        api, "rank_requirement_candidates",
        lambda *args, **kwargs: pytest.fail("GET must not rank candidates"),
    )
    client.app.state.career_optimization = type("Forbidden", (), {
        "run": lambda *args, **kwargs: pytest.fail("GET must not touch optimization cache")
    })()
    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    assert len(response.json()["terms"]) == 4


def test_schedule_payload_serializes_tamu_choice_and_zero_feasible_evidence():
    def candidate(candidate_id, requirement_id, code, feasibility, reason=None, unresolved_code=None):
        return RequirementCandidate(
            candidate_id=candidate_id,
            requirement_group_id=requirement_id,
            requirement_name=requirement_id,
            course_codes=[code] if code else [],
            unresolved_course_codes=[unresolved_code] if unresolved_code else [],
            existing_contribution=0,
            additional_course_count=1 if code else 0,
            additional_credits=3 if code else None,
            academic_feasibility=feasibility,
            completion_term_index=0 if feasibility == AcademicFeasibility.FEASIBLE else None,
            exclusion_reasons=[reason] if reason else [],
        )

    candidate_sets = [
        RequirementCandidateSet(
            requirement_group_id="tamu-or", requirement_name="tamu-or",
            feasible_candidates=[
                candidate("engl-103", "tamu-or", "ENGL 103", AcademicFeasibility.FEASIBLE),
                candidate("engl-104", "tamu-or", "ENGL 104", AcademicFeasibility.FEASIBLE),
            ],
        ),
        RequirementCandidateSet(
            requirement_group_id="unknown", requirement_name="unknown",
            excluded_candidates=[candidate(
                "unknown-999", "unknown", None, AcademicFeasibility.EXCLUDED,
                CandidateExclusionReason.UNRESOLVED_COURSE, "UNKNOWN 999",
            )],
        ),
        RequirementCandidateSet(
            requirement_group_id="restricted", requirement_name="restricted",
            excluded_candidates=[candidate(
                "restricted-a", "restricted", "A", AcademicFeasibility.EXCLUDED,
                CandidateExclusionReason.RESTRICTION_REQUIRES_REVIEW,
            )],
        ),
        RequirementCandidateSet(
            requirement_group_id="cross-listed", requirement_name="cross-listed",
            feasible_candidates=[candidate(
                "engr-217", "cross-listed", "ENGR 217", AcademicFeasibility.FEASIBLE,
            )],
        ),
    ]
    decisions = [
        RequirementDecision(
            requirement_group_id="tamu-or", requirement_name="tamu-or",
            state=RequirementDecisionState.CHOICE_REQUIRED,
            feasible_candidate_ids=["engl-103", "engl-104"],
        ),
        RequirementDecision(
            requirement_group_id="unknown", requirement_name="unknown",
            state=RequirementDecisionState.DATA_UNRESOLVED,
            excluded_candidate_ids=["unknown-999"],
        ),
        RequirementDecision(
            requirement_group_id="restricted", requirement_name="restricted",
            state=RequirementDecisionState.ADVISER_REVIEW,
            excluded_candidate_ids=["restricted-a"],
        ),
        RequirementDecision(
            requirement_group_id="cross-listed", requirement_name="cross-listed",
            state=RequirementDecisionState.AUTO_SELECTED,
            feasible_candidate_ids=["engr-217"], selected_candidate_id="engr-217",
        ),
    ]
    state = SimpleNamespace(
        student_id="s", program_id="p", starting_year=2026,
        starting_season="Fall", max_terms=4,
        academic_schedule=ScheduleResult(student_id="s", program_id="p"),
        academic_selection=RequirementSelectionResult(
            candidate_sets=candidate_sets, decisions=decisions,
        ),
        catalog_by_code={
            "ENGL 103": SimpleNamespace(title="Introduction to Rhetoric", credit_min=3),
            "ENGL 104": SimpleNamespace(title="Composition and Rhetoric", credit_min=3),
            "A": SimpleNamespace(title="Restricted Course", credit_min=3),
            "ENGR 217": SimpleNamespace(title="Experimental Physics and Engineering Lab", credit_min=2),
        },
        raw=SimpleNamespace(
            groups=[], options=[], option_courses=[], course_records=[],
            catalog_credit_by_code={"ENGL 103": 3, "ENGL 104": 3, "A": 3, "ENGR 217": 2},
        ),
        prerequisites={
            code: StructuredPrerequisite()
            for code in ("ENGL 103", "ENGL 104", "A", "ENGR 217")
        },
        semantic_snapshot=DegreeScheduleSemanticSnapshot(
            planner_contract_version="1",
            local_catalog_fingerprint="sha256:" + "a" * 64,
            reconstruction_date=date(2026, 8, 19),
        ),
        active_selections=(),
    )

    payload = api._degree_schedule_payload(state)
    assert payload["schedule_version"].startswith("sha256:")

    assert [item["state"] for item in payload["decisions"]] == [
        "CHOICE_REQUIRED", "DATA_UNRESOLVED", "ADVISER_REVIEW", "AUTO_SELECTED",
    ]
    assert [item["course_codes"] for item in payload["candidate_sets"][0]["feasible_candidates"]] == [
        ["ENGL 103"], ["ENGL 104"],
    ]
    assert [item["candidate_courses"] for item in payload["candidate_sets"][0]["feasible_candidates"]] == [
        [{"course_code": "ENGL 103", "title": "Introduction to Rhetoric", "credits": 3.0}],
        [{"course_code": "ENGL 104", "title": "Composition and Rhetoric", "credits": 3.0}],
    ]
    assert payload["candidate_sets"][1]["excluded_candidates"][0]["exclusion_reasons"] == [
        "UNRESOLVED_COURSE"
    ]
    assert payload["candidate_sets"][1]["excluded_candidates"][0]["candidate_courses"] == [{
        "course_code": "UNKNOWN 999", "title": None, "credits": None,
    }]
    assert payload["candidate_sets"][2]["excluded_candidates"][0]["exclusion_reasons"] == [
        "RESTRICTION_REQUIRES_REVIEW"
    ]
    assert payload["candidate_sets"][3]["feasible_candidates"][0]["course_codes"] == ["ENGR 217"]
    assert payload["candidate_sets"][3]["feasible_candidates"][0]["candidate_courses"] == [{
        "course_code": "ENGR 217",
        "title": "Experimental Physics and Engineering Lab",
        "credits": 2.0,
    }]
    json.dumps(payload)


def test_schedule_payload_enriches_candidate_courses_under_a_deeply_nested_tamu_leaf():
    """Regression for the audit finding: on TAMU Computer Engineering the
    course-bearing requirement groups sit three levels deep (compound_all
    year -> compound_all season -> enumerated_all leaf). _build_academic_
    schedule_state seeds its display-enrichment catalog off
    structured_candidate_codes(); when that walk stopped at roots + direct
    children it returned nothing for such a program, so every decision
    option's courses (CSCE 221 / ECEN 214 / ECEN 303 / MATH 308) rendered
    with title=None and credits=None even though the local catalog has full
    data for all of them. This drives the real requirements tree shape and
    the real LocalCatalogRepository through the same relevant_codes ->
    catalog_by_code -> _degree_schedule_payload chain api.py uses.
    """
    def _group(rule_id, group_type, *, parent=None, n=None):
        return {
            "id": rule_id, "coursedog_rule_id": rule_id, "parent_group_id": parent,
            "name": rule_id, "group_type": group_type, "n_required": n,
            "credit_hours_required": None, "notes_html": None,
            "requires_manual_definition": False,
        }

    def _option(option_id, group_id, index, logic="and"):
        return {"id": option_id, "requirement_group_id": group_id, "option_index": index, "logic": logic}

    def _course(option_id, code):
        return {
            "requirement_group_option_id": option_id,
            "coursedog_group_id": None, "unresolved_course_ref": None, "course_code": code,
        }

    leaf = "Second Year — Spring — Required Courses"
    raw_groups = [
        _group("Second Year", "compound_all"),
        _group("Second Year — Spring", "compound_all", parent="Second Year"),
        _group(leaf, "enumerated_all", parent="Second Year — Spring"),
    ]
    options = [
        _option("o-0", leaf, 0), _option("o-1", leaf, 1), _option("o-2", leaf, 2, "or"),
        _option("o-3", leaf, 3),
    ]
    option_courses = [
        _course("o-0", "CSCE 221"), _course("o-1", "ECEN 214"),
        _course("o-2", "ECEN 303"), _course("o-2", "STAT 211"), _course("o-3", "MATH 308"),
    ]
    targets = ["CSCE 221", "ECEN 214", "ECEN 303", "MATH 308"]
    raw_catalog_by_code = {c: [c] for c in ("CSCE 221", "ECEN 214", "ECEN 303", "STAT 211", "MATH 308")}

    evaluated = evaluate_requirement_tree(
        raw_groups, options, option_courses, [], {}, raw_catalog_by_code
    )

    # Exactly api.py:_build_academic_schedule_state -> relevant_codes -> catalog_by_code.
    repo = LocalCatalogRepository()
    candidate_codes = structured_candidate_codes(
        evaluated, raw_groups, options, option_courses, {}, raw_catalog_by_code
    )
    assert set(targets).issubset(candidate_codes)
    catalog_by_code = {
        code: record
        for code in sorted(candidate_codes)
        if (record := repo.get(CatalogInstitution.TAMU, code)) is not None
    }

    def _cand(candidate_id, codes):
        return RequirementCandidate(
            candidate_id=candidate_id, requirement_group_id=leaf, requirement_name=leaf,
            course_codes=codes,
            existing_contribution=0, additional_course_count=len(codes), additional_credits=14,
            academic_feasibility=AcademicFeasibility.FEASIBLE, completion_term_index=0,
        )

    # The `or` option (ECEN 303 / STAT 211) is what makes this a real choice.
    candidate_sets = [
        RequirementCandidateSet(
            requirement_group_id=leaf, requirement_name=leaf,
            feasible_candidates=[
                _cand("cand-a", targets),
                _cand("cand-b", ["CSCE 221", "ECEN 214", "STAT 211", "MATH 308"]),
            ],
        ),
    ]
    decisions = [RequirementDecision(
        requirement_group_id=leaf, requirement_name=leaf,
        state=RequirementDecisionState.CHOICE_REQUIRED,
        feasible_candidate_ids=["cand-a", "cand-b"],
    )]
    state = SimpleNamespace(
        student_id="s", program_id="p", starting_year=2026, starting_season="Fall", max_terms=4,
        academic_schedule=ScheduleResult(student_id="s", program_id="p"),
        academic_selection=RequirementSelectionResult(
            candidate_sets=candidate_sets, decisions=decisions,
        ),
        catalog_by_code=catalog_by_code,
        raw=SimpleNamespace(
            groups=[], options=[], option_courses=[], course_records=[],
            catalog_credit_by_code={c: float(catalog_by_code[c].credit_min) for c in targets},
        ),
        prerequisites={code: StructuredPrerequisite() for code in targets},
        semantic_snapshot=DegreeScheduleSemanticSnapshot(
            planner_contract_version="1",
            local_catalog_fingerprint="sha256:" + "a" * 64,
            reconstruction_date=date(2026, 8, 19),
        ),
        active_selections=(),
    )

    payload = api._degree_schedule_payload(state)
    enriched = payload["candidate_sets"][0]["feasible_candidates"][0]["candidate_courses"]
    assert enriched == [
        {"course_code": "CSCE 221", "title": "Data Structures and Algorithms", "credits": 4.0},
        {"course_code": "ECEN 214", "title": "Electrical Circuit Theory", "credits": 4.0},
        {"course_code": "ECEN 303", "title": "Random Signals and Systems", "credits": 3.0},
        {"course_code": "MATH 308", "title": "Differential Equations", "credits": 3.0},
    ]
    # No entry silently degraded to the "code not in catalog" shape.
    assert all(item["title"] is not None and item["credits"] for item in enriched)
    json.dumps(payload)


def test_schedule_payload_resolves_decision_term_keys_per_state():
    """Phase 3: each decision carries the term card it should render on.

    LOCKED -> the term its course actually landed in; CHOICE_REQUIRED ->
    min(completion_term_index) over feasible candidates, mapped through the
    scheduler's own Fall<->Spring cadence; EXCLUDED -> the excluded
    candidate's completion_term_index (None when it never joined a feasible
    combination); AUTO_SELECTED / ADVISER_REVIEW / DATA_UNRESOLVED -> None.
    """

    def feasible(candidate_id, requirement_id, code, term_index):
        return RequirementCandidate(
            candidate_id=candidate_id, requirement_group_id=requirement_id,
            requirement_name=requirement_id, course_codes=[code],
            existing_contribution=0, additional_course_count=1, additional_credits=3,
            academic_feasibility=AcademicFeasibility.FEASIBLE,
            completion_term_index=term_index,
        )

    def excluded(candidate_id, requirement_id, code, reason):
        return RequirementCandidate(
            candidate_id=candidate_id, requirement_group_id=requirement_id,
            requirement_name=requirement_id, course_codes=[code],
            existing_contribution=0, additional_course_count=1, additional_credits=3,
            academic_feasibility=AcademicFeasibility.EXCLUDED,
            completion_term_index=None, exclusion_reasons=[reason],
        )

    candidate_sets = [
        RequirementCandidateSet(
            requirement_group_id="locked", requirement_name="American History",
            feasible_candidates=[
                feasible("hist-1301", "locked", "HIST 1301", 0),
                feasible("hist-1302", "locked", "HIST 1302", 1),
            ],
        ),
        RequirementCandidateSet(
            requirement_group_id="choice", requirement_name="Statistical Methods",
            feasible_candidates=[
                feasible("stat-early", "choice", "STAT 3011", 1),
                feasible("stat-late", "choice", "STAT 4011", 3),
            ],
        ),
        RequirementCandidateSet(
            requirement_group_id="excluded", requirement_name="Technical Elective",
            feasible_candidates=[feasible("tech-1", "excluded", "CSCE 4901", 2)],
        ),
        RequirementCandidateSet(
            requirement_group_id="excluded-noterm", requirement_name="Mystery Elective",
            excluded_candidates=[excluded(
                "myst-1", "excluded-noterm", "MYST 1000",
                CandidateExclusionReason.UNSCHEDULABLE,
            )],
        ),
        RequirementCandidateSet(
            requirement_group_id="review", requirement_name="Restricted Elective",
            excluded_candidates=[excluded(
                "rev-1", "review", "REV 1000",
                CandidateExclusionReason.RESTRICTION_REQUIRES_REVIEW,
            )],
        ),
    ]
    decisions = [
        RequirementDecision(
            requirement_group_id="locked", requirement_name="American History",
            state=RequirementDecisionState.LOCKED,
            feasible_candidate_ids=["hist-1301", "hist-1302"],
            selected_candidate_id="hist-1301",
        ),
        RequirementDecision(
            requirement_group_id="choice", requirement_name="Statistical Methods",
            state=RequirementDecisionState.CHOICE_REQUIRED,
            feasible_candidate_ids=["stat-early", "stat-late"],
        ),
        RequirementDecision(
            requirement_group_id="excluded", requirement_name="Technical Elective",
            state=RequirementDecisionState.EXCLUDED,
            excluded_candidate_ids=["tech-1"],
        ),
        RequirementDecision(
            requirement_group_id="excluded-noterm", requirement_name="Mystery Elective",
            state=RequirementDecisionState.EXCLUDED,
            excluded_candidate_ids=["myst-1"],
        ),
        RequirementDecision(
            requirement_group_id="review", requirement_name="Restricted Elective",
            state=RequirementDecisionState.ADVISER_REVIEW,
            excluded_candidate_ids=["rev-1"],
        ),
    ]
    schedule = ScheduleResult(
        student_id="s", program_id="p",
        terms=[
            TermPlan(
                term_key="2026-Fall", total_credit_hours=3,
                courses=[ScheduledCourse(
                    course_code="HIST 1301", credit_hours=3, requirement_group_id="locked",
                )],
            ),
            TermPlan(term_key="2027-Spring", total_credit_hours=0, courses=[]),
        ],
    )
    state = SimpleNamespace(
        student_id="s", program_id="p", starting_year=2026, starting_season="Fall",
        max_terms=8, academic_schedule=schedule,
        academic_selection=RequirementSelectionResult(
            candidate_sets=candidate_sets, decisions=decisions,
        ),
        catalog_by_code={}, raw=SimpleNamespace(
            groups=[], options=[], option_courses=[], course_records=[],
            catalog_credit_by_code={},
        ),
        prerequisites={},
        semantic_snapshot=DegreeScheduleSemanticSnapshot(
            planner_contract_version="1",
            local_catalog_fingerprint="sha256:" + "a" * 64,
            reconstruction_date=date(2026, 8, 19),
        ),
        active_selections=(),
    )

    payload = api._degree_schedule_payload(state)
    resolved = {item["requirement_group_id"]: item["resolved_term_key"] for item in payload["decisions"]}

    # LOCKED joins to the term HIST 1301 actually landed in.
    assert resolved["locked"] == "2026-Fall"
    # CHOICE_REQUIRED -> min index 1 from start (2026-Fall) -> one long term on.
    assert resolved["choice"] == "2027-Spring"
    # EXCLUDED -> the excluded candidate's index 2 -> two long terms on.
    assert resolved["excluded"] == "2027-Fall"
    # EXCLUDED with no resolvable index stays None (frontend drops it).
    assert resolved["excluded-noterm"] is None
    # ADVISER_REVIEW / DATA_UNRESOLVED carry no term signal.
    assert resolved["review"] is None
    json.dumps(payload)


def _trusted_need():
    return CareerSkillNeed(
        skill="Software design", category="skills",
        target_role="Software Engineering Intern", importance="required",
        evidence_state=EvidenceState.VERIFIED_LOCAL,
        evidence_source="O*NET trusted", confidence=.9,
    )


def _fake_valid_ranker(_client, candidate_set, **_kwargs):
    return RequirementCandidateRanking(
        requirement_group_id=candidate_set.requirement_group_id,
        ranked_candidates=[
            RankedRequirementCandidate(
                candidate_id=candidate.candidate_id, rank=index,
                ranking_reason="Synthetic test preference.",
                skill_alignment_explanation="Synthetic trusted-need alignment.",
            )
            for index, candidate in enumerate(reversed(candidate_set.feasible_candidates), 1)
        ],
    )


def _patch_career_context(monkeypatch, *, roles=("Software Engineering Intern",), confirmed=True):
    profile = _canonical_profile()
    profile.career.confirmed = confirmed
    profile.career.target_roles = list(roles)
    monkeypatch.setattr(api, "build_student_intelligence_profile", lambda client, student_id: profile)
    monkeypatch.setattr(api, "derive_career_skill_needs", lambda profile, role: [_trusted_need()])


def test_career_optimize_returns_typed_preview_and_cache_hit(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _patch_career_context(monkeypatch)
    monkeypatch.setattr(api, "build_client", lambda: object())
    calls = []
    monkeypatch.setattr(
        api, "rank_requirement_candidates",
        lambda *args, **kwargs: calls.append(args[1].requirement_group_id) or _fake_valid_ranker(*args, **kwargs),
    )
    first = client.post(
        OPTIMIZE_URL, json={"target_role": "Software Engineering Intern"},
        headers={"Authorization": "Bearer good-token"},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["feature"] == "CAREER_OPTIMIZED_SCHEDULE"
    assert body["status"] == "OPTIMIZED"
    assert body["selection_basis"] == "CAREER_RANKED"
    assert body["cache_status"] == "MISS"
    assert body["fingerprint"] and body["ranking_prompt_version"] == "1"
    assert len(body["academic_schedule"]["terms"]) == 4
    assert len(body["optimized_schedule"]["terms"]) == 4
    # Engineering Leadership joins the unscheduled/ranked set too: it no
    # longer AUTO_SELECTs a sole feasible candidate (see
    # test_ethan_brooks_returns_full_schedule_result), so it now also needs
    # a ranking call like the other 4 structured groups.
    assert len(body["academic_schedule"]["unscheduled"]) == 7
    assert len(body["optimized_schedule"]["unscheduled"]) == 2
    assert len(body["requirement_rankings"]) == len(calls) == 5
    initial_calls = len(calls)

    second = client.post(
        OPTIMIZE_URL, json={}, headers={"Authorization": "Bearer good-token"},
    )
    assert second.status_code == 200
    assert second.json()["cache_status"] == "HIT"
    assert len(calls) == initial_calls


def test_career_optimize_honors_persisted_lock_over_provider_preference(
    client, monkeypatch
):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _patch_career_context(monkeypatch)
    monkeypatch.setattr(api, "build_client", lambda: object())
    calls = []
    monkeypatch.setattr(
        api, "rank_requirement_candidates",
        lambda *args, **kwargs: calls.append(args[1].requirement_group_id)
        or _fake_valid_ranker(*args, **kwargs),
    )
    baseline = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    statistical = next(
        item for item in baseline["candidate_sets"]
        if item["requirement_name"] == "Statistical Methods"
    )
    locked = _selection(statistical, 0)
    provider_preferred = statistical["feasible_candidates"][-1]
    tables["degree_requirement_selections"] = [
        _stored_selection(student_id, program_id, locked)
    ]

    response = client.post(
        OPTIMIZE_URL, json={"target_role": "Software Engineering Intern"},
        headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 200
    body = response.json()
    optimized_codes = {
        course["course_code"]
        for term in body["optimized_schedule"]["terms"]
        for course in term["courses"]
    }
    assert set(locked["course_codes"]) <= optimized_codes
    assert not set(provider_preferred["course_codes"]) <= optimized_codes
    assert locked["requirement_group_id"] not in calls
    # 4, not 3: Statistical Methods is locked (excluded from ranking) and
    # Engineering Leadership now also needs a ranking call -- it no longer
    # AUTO_SELECTs a sole feasible candidate (see
    # test_ethan_brooks_returns_full_schedule_result) -- so the remaining
    # 4 of 5 structured groups (AI, Experiential Learning, Two Courses,
    # Engineering Leadership) are ranked, not 3.
    assert len(body["requirement_rankings"]) == len(calls) == 4

    forced = client.post(
        OPTIMIZE_URL, json={"force_refresh": True},
        headers={"Authorization": "Bearer good-token"},
    )
    assert forced.status_code == 200
    assert forced.json()["cache_status"] == "BYPASSED"
    forced_codes = {
        course["course_code"]
        for term in forced.json()["optimized_schedule"]["terms"]
        for course in term["courses"]
    }
    assert set(locked["course_codes"]) <= forced_codes


def test_career_optimize_preserves_atomic_multi_course_lock_without_writes(
    client, monkeypatch
):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _patch_career_context(monkeypatch)
    monkeypatch.setattr(api, "build_client", lambda: object())
    monkeypatch.setattr(api, "rank_requirement_candidates", _fake_valid_ranker)
    baseline = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    candidate_set = next(
        item for item in baseline["candidate_sets"]
        if any(len(candidate["course_codes"]) > 1 for candidate in item["feasible_candidates"])
    )
    candidate = next(
        item for item in candidate_set["feasible_candidates"]
        if len(item["course_codes"]) > 1
    )
    locked = {
        "requirement_group_id": candidate_set["requirement_group_id"],
        "candidate_id": candidate["candidate_id"],
        "course_codes": candidate["course_codes"],
    }
    tables["degree_requirement_selections"] = [
        _stored_selection(student_id, program_id, locked)
    ]
    before_selections = json.loads(json.dumps(tables["degree_requirement_selections"]))
    before_planned = json.loads(json.dumps(tables.get("planned_courses", [])))

    response = client.post(
        OPTIMIZE_URL, json={}, headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 200
    optimized_codes = {
        course["course_code"]
        for term in response.json()["optimized_schedule"]["terms"]
        for course in term["courses"]
    }
    assert set(candidate["course_codes"]) <= optimized_codes
    assert tables["degree_requirement_selections"] == before_selections
    assert tables.get("planned_courses", []) == before_planned


def test_career_optimization_cache_changes_with_selection_add_change_and_clear(
    client, monkeypatch
):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _patch_career_context(monkeypatch)
    monkeypatch.setattr(api, "build_client", lambda: object())
    calls = []
    monkeypatch.setattr(
        api, "rank_requirement_candidates",
        lambda *args, **kwargs: calls.append(args[1].requirement_group_id)
        or _fake_valid_ranker(*args, **kwargs),
    )
    baseline = client.get(URL, headers={"Authorization": "Bearer good-token"}).json()
    candidate_set = next(
        item for item in baseline["candidate_sets"]
        if item["requirement_name"] == "Statistical Methods"
    )
    first, second = _selection(candidate_set, 0), _selection(candidate_set, 1)

    unlocked = client.post(
        OPTIMIZE_URL, json={}, headers={"Authorization": "Bearer good-token"},
    ).json()
    tables["degree_requirement_selections"] = [
        _stored_selection(student_id, program_id, first)
    ]
    locked_first = client.post(
        OPTIMIZE_URL, json={}, headers={"Authorization": "Bearer good-token"},
    ).json()
    tables["degree_requirement_selections"] = [
        _stored_selection(student_id, program_id, second)
    ]
    locked_second = client.post(
        OPTIMIZE_URL, json={"force_refresh": False},
        headers={"Authorization": "Bearer good-token"},
    ).json()
    tables["degree_requirement_selections"] = []
    cleared = client.post(
        OPTIMIZE_URL, json={}, headers={"Authorization": "Bearer good-token"},
    ).json()

    assert len({
        unlocked["fingerprint"], locked_first["fingerprint"],
        locked_second["fingerprint"], cleared["fingerprint"],
    }) == 3
    assert locked_first["fingerprint"] != locked_second["fingerprint"]
    assert locked_second["cache_status"] == "MISS"
    # Clearing restores the exact unlocked semantic identity, so its safe
    # prior unlocked result is reusable.
    assert cleared["fingerprint"] == unlocked["fingerprint"]
    assert cleared["cache_status"] == "HIT"


def test_career_optimize_blocks_stale_selection_before_model_or_cache(
    client, monkeypatch
):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    tables["degree_requirement_selections"] = [
        _stored_selection(student_id, program_id, {
            "requirement_group_id": tables["requirement_groups"][0]["id"],
            "candidate_id": "reqcand_removed",
            "course_codes": ["STALE 9999"],
        })
    ]
    monkeypatch.setattr(
        api, "get_model_for_role",
        lambda *_: pytest.fail("stale selection must fail before model resolution"),
    )
    monkeypatch.setattr(
        api, "build_student_intelligence_profile",
        lambda *_: pytest.fail("stale selection must fail before career profile work"),
    )
    monkeypatch.setattr(
        api, "build_client",
        lambda: pytest.fail("stale selection must fail before provider work"),
    )
    response = client.post(
        OPTIMIZE_URL, json={}, headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESELECTION_REQUIRED"
    assert response.json()["detail"]["selection_failure"]["code"].startswith("LOCK_")


def test_career_optimize_force_refresh_and_full_failure_preserve_ethan_baseline(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _patch_career_context(monkeypatch)
    monkeypatch.setattr(api, "build_client", lambda: object())
    monkeypatch.setattr(api, "rank_requirement_candidates", lambda *args, **kwargs: None)
    response = client.post(
        OPTIMIZE_URL, json={"force_refresh": True},
        headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FALLBACK"
    assert body["selection_basis"] == "ACADEMIC_DEFAULT"
    assert body["cache_status"] == "BYPASSED"
    assert body["optimized_schedule"] == body["academic_schedule"]
    schedule = body["academic_schedule"]
    courses = [course for term in schedule["terms"] for course in term["courses"]]
    # 13 courses/33 credits/7 unscheduled, not 15/39/6: no structured group
    # is AUTO_SELECTED any more (see test_ethan_brooks_returns_full_schedule_
    # result), so only the base no-choice courses populate the baseline
    # academic schedule and Engineering Leadership joins unscheduled too.
    assert len(courses) == 13
    assert sum(course["credit_hours"] for course in courses) == 33
    assert len(schedule["terms"]) == 4
    assert len(schedule["unscheduled"]) == 7


@pytest.mark.parametrize("roles,body,summary_fragment", [
    ((), {}, "Confirm a target role"),
    (("Software Engineering Intern", "Data Scientist Intern"), {}, "Choose which"),
    (("Software Engineering Intern",), {"target_role": "NVIDIA Robotics Engineer"}, "not confirmed"),
])
def test_career_optimize_handles_missing_ambiguous_and_unconfirmed_roles_safely(
    client, monkeypatch, roles, body, summary_fragment
):
    tables, _student_id, _program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)
    _patch_career_context(monkeypatch, roles=roles)
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("skipped must not build a model"))
    response = client.post(
        OPTIMIZE_URL, json=body, headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SKIPPED"
    assert summary_fragment in response.json()["summary"]


@pytest.mark.parametrize("injection", [
    {"candidate_ids": ["fake"]}, {"course_codes": ["CS 9999"]},
    {"requirement_ids": ["fake"]}, {"student_id": "someone-else"},
])
def test_career_optimize_rejects_client_academic_authority(client, injection):
    response = client.post(
        OPTIMIZE_URL, json=injection, headers={"Authorization": "Bearer good-token"},
    )
    assert response.status_code == 422


# 2. No program data (every real student except Ethan Brooks) -> 200, skipped.
def test_no_program_data_returns_200_skipped(client, monkeypatch):
    _patch_client(monkeypatch, student_with_no_program_tables())

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "SCHEDULE"
    assert body["status"] == "skipped"


# 3. Program data present but no expected_graduation on record -> 200, skipped.
def test_no_expected_graduation_returns_200_skipped(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables(expected_graduation=None)
    _patch_client(monkeypatch, tables)

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "SCHEDULE"
    assert body["status"] == "skipped"
    assert body["missing_fields"][0]["path"] == "students.expected_graduation"


class _MissingRelationError(Exception):
    """Shaped like a PostgREST schema-cache miss for a table that isn't there."""

    def __init__(self):
        super().__init__(
            "{'message': \"Could not find the table "
            "'public.degree_requirement_exclusions' in the schema cache\", "
            "'code': 'PGRST205'}"
        )
        self.code = "PGRST205"
        self.message = (
            "Could not find the table 'public.degree_requirement_exclusions' "
            "in the schema cache"
        )


class _ExclusionsTableMissingClient(FakeClient):
    """FakeClient that raises on any query against degree_requirement_exclusions,
    reproducing the state of a database the exclusions migration hasn't reached."""

    def table(self, name):
        if name == "degree_requirement_exclusions":
            class _Raising:
                def select(self, *a, **k):
                    return self

                def eq(self, *a, **k):
                    return self

                def execute(self):
                    raise _MissingRelationError()

            return _Raising()
        return super().table(name)


def test_load_requirement_exclusion_group_ids_degrades_when_table_missing():
    from GradusIQ_career.planning.requirement_exclusions import (
        load_requirement_exclusion_group_ids,
    )

    client = _ExclusionsTableMissingClient({})
    assert load_requirement_exclusion_group_ids(client, "stu", "prog") == ()


def test_load_requirement_exclusion_group_ids_reraises_unrelated_error():
    from GradusIQ_career.planning.requirement_exclusions import (
        load_requirement_exclusion_group_ids,
    )

    class _AuthError(Exception):
        pass

    class _AuthFailingClient(FakeClient):
        def table(self, name):
            class _Raising:
                def select(self, *a, **k):
                    return self

                def eq(self, *a, **k):
                    return self

                def execute(self):
                    raise _AuthError("JWT expired")

            return _Raising()

    with pytest.raises(_AuthError):
        load_requirement_exclusion_group_ids(_AuthFailingClient({}), "stu", "prog")


# Defense-in-depth: the exclusions migration can be written, tested, and
# shipped in code while its schema dependency stays unapplied (this exact
# failure mode took every schedule route to a 502 on 2026-09-02). A missing
# degree_requirement_exclusions relation must degrade to "no exclusions", not
# propagate an uncaught error out of _reconstruct_academic_schedule.
def test_missing_exclusions_table_still_returns_200_schedule(client, monkeypatch):
    tables, student_id, _program_id = _schedule_tables()
    fake = _ExclusionsTableMissingClient(tables)
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)
    _freeze_today(monkeypatch, date(2026, 8, 19))

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SCHEDULED"
    assert body["student_id"] == student_id
    # active_exclusions treated as empty -> nothing set aside in the payload
    assert body["exclusion_state"]["excluded_group_ids"] == []


# 4. Over-constrained: an expected_graduation in the immediate past relative
#    to the starting term forces max_terms down to 0 against a non-empty
#    course list -- schedule_courses()'s own over-constrained detection
#    fires, and the route returns 200 with the ERROR payload intact, not a
#    4xx/5xx.
def test_over_constrained_returns_200_with_error_payload(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables(expected_graduation="Fall 2025")
    _patch_client(monkeypatch, tables)

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "ERROR"
    assert body["terms"] == []
    assert body["unscheduled"] == []
    assert body["failure"] is not None
    assert body["failure"]["error_class"]
