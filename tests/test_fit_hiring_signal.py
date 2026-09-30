import json

from GradusIQ_career.ai.runtime import AIRuntime
from GradusIQ_career.features.fit import FitRunner, _hiring_signal_by_role, _top_normalized_employers

from tests.test_ai_runtime_fit import QueueClient, canonical_profile


LEGACY_PROFILE = {
    "student": {"major_intended": "Computer Science", "major_current": "Computer Science"},
    "career": {
        "target_roles": ["Computer Engineering Intern"],
        "interests": ["hardware"],
        "skills_self_reported": {"technical": ["C"]},
    },
}


def _model_response(hiring_signal=None, rationale=None, summary="done"):
    role_match = {
        "role": "Computer Engineering Intern",
        "fit_level": "medium",
        "rationale": rationale or "Confirmed hardware coursework supports a developing fit.",
        "supporting_signals": ["C"],
        "missing_signals": ["Production experience"],
    }
    if hiring_signal is not None:
        role_match["hiring_signal"] = hiring_signal
    return json.dumps(
        {
            "summary": summary,
            "data": {
                "role_matches": [role_match],
                "overall_fit_summary": "A realistic developing fit.",
            },
        }
    )


def _no_op_market(monkeypatch):
    monkeypatch.setattr(
        "GradusIQ_career.features.fit.get_market_requirements",
        lambda _roles: {"source": "onet_static", "by_role": {}},
    )
    monkeypatch.setattr(
        "GradusIQ_career.features.fit.get_shift_signals",
        lambda _roles: {"source": "onet_static", "by_role": {}},
    )


# ── _hiring_signal_by_role: top-level unavailable shape ─────────────────────


def test_top_level_unavailable_shape_maps_every_role_to_unavailable_not_keyerror():
    role_postings = {"status": "unavailable", "reason": "Supabase timed out"}
    result = _hiring_signal_by_role(role_postings, ["Role A", "Role B"])
    assert result == {
        "Role A": {"coverage": "unavailable", "employers": [], "posting_count": None},
        "Role B": {"coverage": "unavailable", "employers": [], "posting_count": None},
    }


def test_runner_surfaces_unavailable_hiring_signal_when_posting_client_factory_raises(monkeypatch):
    """End-to-end: a raising posting client must not raise a KeyError building
    hiring_signal -- it must degrade to coverage: "unavailable" for every role,
    same as fit.py's existing role_postings failure handling.
    """
    _no_op_market(monkeypatch)

    def raising_factory():
        raise RuntimeError("Supabase unreachable")

    client = QueueClient([_model_response()])
    runner = FitRunner(
        client=client,
        runtime_factory=lambda c: AIRuntime(c, sleep=lambda _: None),
        posting_client_factory=raising_factory,
    )
    result = runner.run_canonical(canonical_profile(), LEGACY_PROFILE)
    assert result["status"] == "success"
    hiring_signal = result["data"]["role_matches"][0]["hiring_signal"]
    assert hiring_signal == {"coverage": "unavailable", "employers": [], "posting_count": None}


# ── _top_normalized_employers: dedup, cap, order, empty-employer skip ───────


def test_top_normalized_employers_dedupes_by_normalized_key_and_caps_at_three():
    postings = [
        {"employer": "Toyota"},
        {"employer": "toyota"},  # same normalized key as "Toyota" -- dropped
        {"employer": "Comerica"},
        {"employer": None},  # no employer named -- skipped, not fabricated
        {"employer": ""},
        {"employer": "Dell"},
        {"employer": "USAA"},  # beyond the cap of 3
    ]
    employers = _top_normalized_employers(postings)
    assert employers == ["Toyota", "Comerica", "Dell"]


def test_top_normalized_employers_folds_known_alias_variants_into_one_entry():
    """normalize_employer() alone does not merge "Micron" and "Micron
    Technology, Inc." -- they normalize to different keys ("micron" vs
    "micron technology") since normalize_employer() only strips legal-form
    suffixes, not "Technology". _EMPLOYER_DISPLAY_ALIASES covers this known
    case on top of that, so it must not resurface as two entries here.
    """
    postings = [
        {"employer": "Micron"},
        {"employer": "Micron Technology, Inc."},
        {"employer": "Toyota"},
    ]
    employers = _top_normalized_employers(postings)
    assert employers == ["Micron Technology, Inc.", "Toyota"]


def test_top_normalized_employers_empty_when_no_named_employers():
    assert _top_normalized_employers([{"employer": None}, {"employer": ""}]) == []


# ── rationale naming an employer from role_postings: logged, never blocked ──


def test_rationale_naming_an_employer_is_logged_not_blocked(monkeypatch, caplog):
    """rationale is supposed to leave employer/count citation to hiring_signal
    and the "Who's hiring" bullet -- if the model names an employer in
    rationale anyway, that must be logged for observability but must not
    fail the run or alter the returned data.
    """
    _no_op_market(monkeypatch)
    # Uses the alias's canonical form -- _employer_names_by_role (which this
    # check compares rationale against) now returns "Micron Technology,
    # Inc." for this posting's raw "Micron" company field, via the same
    # _EMPLOYER_DISPLAY_ALIASES _top_normalized_employers uses. A rationale
    # saying just "Micron" would no longer match; see the alias's own
    # comment for why that tradeoff was accepted.
    rationale = "Micron Technology, Inc. actively recruits for this role, which supports a developing fit."
    client = QueueClient([_model_response(rationale=rationale)])
    runner = FitRunner(
        client=client,
        runtime_factory=lambda c: AIRuntime(c, sleep=lambda _: None),
        posting_client_factory=_RoleAvailableClient,
    )
    with caplog.at_level("INFO", logger="GradusIQ_career.features.fit"):
        result = runner.run_canonical(canonical_profile(), LEGACY_PROFILE)

    assert result["status"] == "success"
    assert result["data"]["role_matches"][0]["rationale"] == rationale
    messages = [r.message for r in caplog.records if r.name == "GradusIQ_career.features.fit"]
    assert any("fit_rationale_employer_mention" in m and "Micron Technology, Inc." in m for m in messages)


def test_rationale_not_naming_an_employer_logs_nothing(monkeypatch, caplog):
    _no_op_market(monkeypatch)
    client = QueueClient([_model_response()])  # default rationale names no employer
    runner = FitRunner(
        client=client,
        runtime_factory=lambda c: AIRuntime(c, sleep=lambda _: None),
        posting_client_factory=_RoleAvailableClient,
    )
    with caplog.at_level("INFO", logger="GradusIQ_career.features.fit"):
        result = runner.run_canonical(canonical_profile(), LEGACY_PROFILE)

    assert result["status"] == "success"
    messages = [r.message for r in caplog.records if r.name == "GradusIQ_career.features.fit"]
    assert not any("fit_rationale_employer_mention" in m for m in messages)


# ── Server truth always wins over the model's own attempt ───────────────────


def test_model_fabricated_hiring_signal_is_overwritten_with_server_truth(monkeypatch):
    _no_op_market(monkeypatch)

    def posting_client_factory():
        return _RoleAvailableClient()

    fabricated = {"coverage": "available", "employers": ["Not A Real Employer"], "posting_count": 999}
    client = QueueClient([_model_response(hiring_signal=fabricated)])
    runner = FitRunner(
        client=client,
        runtime_factory=lambda c: AIRuntime(c, sleep=lambda _: None),
        posting_client_factory=posting_client_factory,
    )
    result = runner.run_canonical(canonical_profile(), LEGACY_PROFILE)
    assert result["status"] == "success"
    hiring_signal = result["data"]["role_matches"][0]["hiring_signal"]
    assert hiring_signal == {
        "coverage": "available",
        "employers": ["Micron Technology, Inc."],
        "posting_count": 1,
    }
    assert hiring_signal != fabricated


def test_role_name_mismatch_falls_back_to_unavailable(monkeypatch):
    """If the model paraphrases the role name, the server-truth lookup misses
    -- it must fall back to "unavailable" rather than leaving the model's
    unverified hiring_signal in place.
    """
    _no_op_market(monkeypatch)
    client = QueueClient(
        [
            json.dumps(
                {
                    "summary": "done",
                    "data": {
                        "role_matches": [
                            {
                                "role": "Computer Engineer Intern",  # paraphrased, no trailing "ing"
                                "fit_level": "medium",
                                "rationale": "Confirmed hardware coursework.",
                                "supporting_signals": ["C"],
                                "missing_signals": [],
                                "hiring_signal": {
                                    "coverage": "available",
                                    "employers": ["Micron"],
                                    "posting_count": 1,
                                },
                            }
                        ],
                        "overall_fit_summary": "A realistic developing fit.",
                    },
                }
            )
        ]
    )
    runner = FitRunner(
        client=client,
        runtime_factory=lambda c: AIRuntime(c, sleep=lambda _: None),
        posting_client_factory=_RoleAvailableClient,
    )
    result = runner.run_canonical(canonical_profile(), LEGACY_PROFILE)
    assert result["status"] == "success"
    hiring_signal = result["data"]["role_matches"][0]["hiring_signal"]
    assert hiring_signal == {"coverage": "unavailable", "employers": [], "posting_count": None}


class _RoleAvailableClient:
    """Fake Supabase client returning one Micron posting for the one target role."""

    def table(self, _name):
        return self

    def select(self, _columns):
        return self

    def eq(self, _column, _value):
        return self

    def neq(self, _column, _value):
        return self

    def execute(self):
        return _Response(
            [
                {
                    "id": "posting-1",
                    "posting_identity": "cluster-1",
                    "company": "Micron",
                    "title": "Computer Engineering Intern",
                    "location": "Allen, TX",
                    "url": "https://example.com/posting-1",
                    "posted_date": "2026-09-01",
                    "fetched_at": "2026-09-02T00:00:00Z",
                    "source": "adzuna",
                    "target_role": "Computer Engineering Intern",
                    "is_dfw": True,
                }
            ]
        )


class _Response:
    def __init__(self, data):
        self.data = data
