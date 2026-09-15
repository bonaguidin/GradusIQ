from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "job_postings"))

import check_integrity  # noqa: E402


def _clean_snapshot() -> check_integrity.Snapshot:
    return check_integrity.Snapshot(
        postings=[
            {
                "id": "p-workday",
                "source": "workday",
                "source_job_id": "JR100",
                "posting_identity": "c-workday",
            },
            {
                "id": "p-adzuna",
                "source": "adzuna",
                "source_job_id": "adz-1",
                "posting_identity": "c-adzuna",
            },
        ],
        clusters=[
            {"id": "c-workday", "canonical_posting_id": "p-workday"},
            {"id": "c-adzuna", "canonical_posting_id": "p-adzuna"},
        ],
        keys=[
            {"key": "ats:workday:acme:JR100", "cluster_id": "c-workday"},
            {"key": "fuzzy:acme:software-engineer:dfw", "cluster_id": "c-adzuna"},
        ],
    )


def _failure_names(snapshot: check_integrity.Snapshot) -> set[str]:
    return {failure.name for failure in check_integrity.evaluate(snapshot).failures}


def test_clean_fixture_passes_all_assertions():
    report = check_integrity.evaluate(_clean_snapshot())

    assert report.ok
    assert report.counts["postings"] == 2
    assert report.counts["clusters"] == 2
    assert report.counts["identity_keys"] == 2


def test_keyless_nonempty_cluster_is_allowed_by_the_dynamic_count_delta():
    snapshot = _clean_snapshot()
    snapshot.postings.append(
        {
            "id": "p-keyless",
            "source": "manual",
            "source_job_id": "manual-1",
            "posting_identity": "c-keyless",
        }
    )
    snapshot.clusters.append({"id": "c-keyless", "canonical_posting_id": "p-keyless"})

    report = check_integrity.evaluate(snapshot)

    assert report.ok
    assert report.counts["cluster_key_delta"] == 1
    assert report.counts["keyless_clusters"] == 1


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    [
        (
            lambda s: s.clusters.append({"id": "c-empty", "canonical_posting_id": "p-workday"}),
            "empty_clusters",
        ),
        (
            lambda s: s.clusters.__setitem__(
                0, {"id": "c-workday", "canonical_posting_id": "p-adzuna"}
            ),
            "canonical_not_member",
        ),
        (
            lambda s: s.clusters.__setitem__(
                0, {"id": "c-workday", "canonical_posting_id": None}
            ),
            "null_canonical",
        ),
        (
            lambda s: s.keys.append({"key": "fuzzy:stale", "cluster_id": "c-missing"}),
            "keys_to_missing_or_empty_clusters",
        ),
        (
            lambda s: s.postings.__setitem__(
                0,
                {
                    "id": "p-workday",
                    "source": "workday",
                    "source_job_id": "JR100",
                    "posting_identity": None,
                },
            ),
            "null_posting_identity",
        ),
        (
            lambda s: s.postings.append(
                {
                    "id": "p-workday-2",
                    "source": "workday",
                    "source_job_id": "JR200",
                    "posting_identity": "c-workday",
                }
            ),
            "clusters_with_multiple_workday_requisition_ids",
        ),
        (
            lambda s: s.keys.append({"key": "fuzzy:extra", "cluster_id": "c-workday"}),
            "cluster_key_count_delta",
        ),
    ],
)
def test_each_assertion_fires_on_a_seeded_violation(mutation, expected_failure):
    snapshot = deepcopy(_clean_snapshot())
    mutation(snapshot)

    assert expected_failure in _failure_names(snapshot)


def test_main_exits_zero_and_prints_counts_on_success(monkeypatch, capsys):
    monkeypatch.setattr(check_integrity, "load_snapshot", lambda: _clean_snapshot())

    assert check_integrity.main([]) == 0

    out = capsys.readouterr().out
    assert "PASS job posting cluster integrity" in out
    assert "postings: 2" in out
    assert "clusters: 2" in out
    assert "identity_keys: 2" in out


def test_main_exits_nonzero_and_prints_bounded_sample_on_violation(monkeypatch, capsys):
    snapshot = _clean_snapshot()
    for index in range(12):
        snapshot.clusters.append({"id": f"c-empty-{index:02}", "canonical_posting_id": "p-workday"})
    monkeypatch.setattr(check_integrity, "load_snapshot", lambda: snapshot)

    assert check_integrity.main([]) == 1

    out = capsys.readouterr().out
    assert "FAIL job posting cluster integrity" in out
    assert "assertion_failed empty_clusters: actual=12 expected=0" in out
    assert "c-empty-09" in out
    assert "c-empty-10" not in out


def test_missing_connection_config_fails_loudly(monkeypatch, capsys):
    monkeypatch.setattr(
        check_integrity,
        "load_snapshot",
        lambda: (_ for _ in ()).throw(check_integrity.IntegrityConfigError("missing database config")),
    )

    assert check_integrity.main([]) == 2

    assert "could not run: missing database config" in capsys.readouterr().err


def test_unreachable_connection_fails_loudly(monkeypatch, capsys):
    monkeypatch.setattr(
        check_integrity,
        "load_snapshot",
        lambda: (_ for _ in ()).throw(OSError("network unreachable")),
    )

    assert check_integrity.main([]) == 2

    assert "could not run: network unreachable" in capsys.readouterr().err
