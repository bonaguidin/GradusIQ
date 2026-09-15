"""Guards on .github/workflows/postings-ingest.yml.

The 'Check configuration' step is what stops a half-configured repo from
running the ingest against a real vendor/DB. A missing var in its checklist
means the gate says 'ready' when it is not -- exactly the ADZUNA_APP_KEY bug
this test locks shut.
"""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "postings-ingest.yml"


def _config_step(job: dict) -> dict:
    for step in job["steps"]:
        if step.get("id") == "config":
            return step
    raise AssertionError("no step with id: config")


def test_workflow_parses_and_has_post_ingest_integrity_job():
    wf = yaml.safe_load(WORKFLOW.read_text())
    assert set(wf["jobs"]) == {"ingest", "workday-ingest", "integrity-check"}

    integrity = wf["jobs"]["integrity-check"]
    assert set(integrity["needs"]) == {"ingest", "workday-ingest"}
    assert integrity["if"] == "always()"
    assert not any(step.get("id") == "config" for step in integrity["steps"])
    assert any(
        step.get("run") == "uv run python scripts/job_postings/check_integrity.py"
        for step in integrity["steps"]
    )


def test_adzuna_config_gate_checks_every_var_its_ingest_step_uses():
    wf = yaml.safe_load(WORKFLOW.read_text())
    step = _config_step(wf["jobs"]["ingest"])

    # Every secret the gate is responsible for must appear both in the step env
    # and in an `[ -z "${VAR:-}" ]` check in the script body.
    checked = set(re.findall(r'\[ -z "\$\{(\w+):-\}" \]', step["run"]))
    assert {"ADZUNA_APP_ID", "ADZUNA_APP_KEY", "SUPABASE_URL", "SUPABASE_SECRET_KEY"} <= checked

    ingest_step = next(s for s in wf["jobs"]["ingest"]["steps"] if s.get("name") == "Ingest")
    # Anything the Ingest step needs from secrets must be gate-checked, or a
    # partial config sails past the gate and fails inside the client instead.
    for var in ingest_step["env"]:
        if var.startswith(("ADZUNA_", "SUPABASE_")):
            assert var in checked, f"{var} used by Ingest but not checked by the gate"


def test_workday_config_gate_is_supabase_only():
    wf = yaml.safe_load(WORKFLOW.read_text())
    step = _config_step(wf["jobs"]["workday-ingest"])
    checked = set(re.findall(r'\[ -z "\$\{(\w+):-\}" \]', step["run"]))
    assert checked == {"SUPABASE_URL", "SUPABASE_SECRET_KEY"}
