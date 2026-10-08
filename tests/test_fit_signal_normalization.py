import json

from GradusIQ_career.ai.runtime import AIRuntime
from GradusIQ_career.features.fit import FitRunner

from tests.test_ai_runtime_fit import QueueClient, canonical_profile
from tests.test_fit_hiring_signal import LEGACY_PROFILE, _no_op_market


def _response_with_role_match(role_match, summary="done"):
    return json.dumps(
        {
            "summary": summary,
            "data": {
                "role_matches": [role_match],
                "overall_fit_summary": "A realistic developing fit.",
            },
        }
    )


def _base_role_match(**overrides):
    role_match = {
        "role": "Computer Engineering Intern",
        "fit_level": "medium",
        "rationale": "Confirmed hardware coursework supports a developing fit.",
        "supporting_signals": ["C"],
        "missing_signals": ["Production experience"],
    }
    role_match.update(overrides)
    return role_match


def test_object_shaped_supporting_signals_are_normalized_to_strings(monkeypatch):
    """Live FIT once returned each supporting_signals entry as an object
    ({"signal": "..."}) instead of the bare string the schema and prompt
    both call for, failing every item in the list and taking the whole run
    down with it. A formatting choice should not fail the run -- the text
    should be pulled out and used.
    """
    _no_op_market(monkeypatch)
    role_match = _base_role_match(
        supporting_signals=[
            {"signal": "C coursework"},
            {"text": "Hardware lab experience"},
            {"unrecognized_key": "Still usable text"},
        ],
    )
    client = QueueClient([_response_with_role_match(role_match)])
    runner = FitRunner(client=client, runtime_factory=lambda c: AIRuntime(c, sleep=lambda _: None))

    result = runner.run_canonical(canonical_profile(), LEGACY_PROFILE)

    assert result["status"] == "success"
    assert result["data"]["role_matches"][0]["supporting_signals"] == [
        "C coursework",
        "Hardware lab experience",
        "Still usable text",
    ]


def test_scalar_items_are_stringified(monkeypatch):
    _no_op_market(monkeypatch)
    role_match = _base_role_match(supporting_signals=["C", 3, True])
    client = QueueClient([_response_with_role_match(role_match)])
    runner = FitRunner(client=client, runtime_factory=lambda c: AIRuntime(c, sleep=lambda _: None))

    result = runner.run_canonical(canonical_profile(), LEGACY_PROFILE)

    assert result["status"] == "success"
    assert result["data"]["role_matches"][0]["supporting_signals"] == ["C", "3", "True"]


def test_empty_supporting_signals_still_fails_after_a_failed_repair(monkeypatch):
    """The original bug: an empty supporting_signals list used to validate
    as a legal "nothing found" result and silently ship a blank "Why this
    fits" section. It must still be rejected -- including after the one
    automatic repair attempt, if the model repeats the same mistake.
    """
    _no_op_market(monkeypatch)
    empty_response = _response_with_role_match(_base_role_match(supporting_signals=[]))
    client = QueueClient([empty_response, empty_response])
    runner = FitRunner(client=client, runtime_factory=lambda c: AIRuntime(c, sleep=lambda _: None))

    result = runner.run_canonical(canonical_profile(), LEGACY_PROFILE)

    assert result["status"] == "failed"
    assert len(client.calls) == 2


def test_dict_items_with_nothing_usable_still_fail_validation(monkeypatch):
    """Normalization only reshapes recognizable text -- it must not invent
    content where none exists."""
    _no_op_market(monkeypatch)
    junk_response = _response_with_role_match(
        _base_role_match(supporting_signals=[{}, {"posting_count": 3}]),
    )
    client = QueueClient([junk_response, junk_response])
    runner = FitRunner(client=client, runtime_factory=lambda c: AIRuntime(c, sleep=lambda _: None))

    result = runner.run_canonical(canonical_profile(), LEGACY_PROFILE)

    assert result["status"] == "failed"
