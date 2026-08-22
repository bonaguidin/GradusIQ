"""Execute the requirement_groups.rule_source migration against an isolated
PostgreSQL 17 cluster.

Same harness pattern as test_student_institutions_catalog_year_migration.py
and test_resume_reconciliation_migration.py: no application code reads or
writes this column yet, so there is nothing to unit-test at the Python
level -- the thing worth verifying is that the DDL applies cleanly against a
schema shaped like the real requirement_groups table, that the new check
constraint and default behave correctly, and that RLS/grants are unchanged,
which is exactly what that precedent test already does for a different
migration.
"""

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "tests/sql/requirement_groups_rule_source_base.sql"
MIGRATION = ROOT / "supabase/migrations/20260819150000_requirement_groups_rule_source.sql"
ASSERTIONS = ROOT / "tests/sql/requirement_groups_rule_source_assertions.sql"
PG_BIN = Path("/opt/homebrew/opt/postgresql@17/bin")


def _run(args, **kwargs):
    result = subprocess.run(args, text=True, capture_output=True, **kwargs)
    if result.returncode:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(map(str, args))}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.skipif(not (PG_BIN / "initdb").exists(), reason="PostgreSQL 17 is unavailable")
def test_requirement_groups_rule_source_migration(tmp_path):
    data = tmp_path / "pgdata"
    port = _free_port()
    env = {**os.environ, "PGHOST": "127.0.0.1", "PGPORT": str(port), "PGDATABASE": "postgres"}
    _run([str(PG_BIN / "initdb"), "-D", str(data), "--auth=trust", "--no-locale"])
    try:
        _run(
            [
                str(PG_BIN / "pg_ctl"), "-D", str(data),
                "-l", str(tmp_path / "postgres.log"),
                "-o", f"-p {port} -k /tmp", "-w", "-t", "15", "start",
            ]
        )
        for sql in (BASE, MIGRATION):
            _run([str(PG_BIN / "psql"), "-v", "ON_ERROR_STOP=1", "-f", str(sql)], env=env)
        _seed(env)
        _run([str(PG_BIN / "psql"), "-f", str(ASSERTIONS)], env=env)
    finally:
        if data.exists():
            subprocess.run(
                [str(PG_BIN / "pg_ctl"), "-D", str(data), "-m", "immediate", "stop"],
                check=False,
                capture_output=True,
            )
            shutil.rmtree(data, ignore_errors=True)


def _seed(env):
    sql = r"""
insert into institutions(id, name) values
('90000000-0000-0000-0000-000000000000', 'Southern Methodist University');
insert into programs(id, institution_id, coursedog_program_id, program_group_id, code, name, catalog_year) values
('90000000-0000-0000-0000-000000000010', '90000000-0000-0000-0000-000000000000',
 'CS-BS-2026-05-21', 'CS-BS', 'CS-BS', 'Computer Science, B.S.', '2026-2027');
"""
    _run([str(PG_BIN / "psql"), "-v", "ON_ERROR_STOP=1", "-c", sql], env=env)
