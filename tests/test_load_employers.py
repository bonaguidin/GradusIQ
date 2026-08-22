"""Tests for the DFW employer list loader.

Reads the real CSV where it exists, since the point of most of these is that
the file's actual state -- 44 employers, almost no ATS data, no slugs at all --
is what the loader has to report honestly rather than paper over.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "job_postings"))

from load_employers import (  # noqa: E402
    EmployerCsvError,
    fetchable,
    parse_rows,
    render_report,
)

CSV = REPO_ROOT / "data" / "job_postings" / "dfw_employers_ats.csv"

HEADER = ("priority,employer,sector,dfw_location,domain,"
          "target_role_families,ats,slug,checked_date,notes\n")


def write_csv(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "employers.csv"
    p.write_text(HEADER + body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Shape and parsing
# ---------------------------------------------------------------------------

def test_missing_columns_are_fatal(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("employer,sector\nAcme,Tech\n", encoding="utf-8")
    with pytest.raises(EmployerCsvError, match="missing expected column"):
        parse_rows(p)


def test_example_row_is_skipped(tmp_path):
    p = write_csv(tmp_path,
        "EXAMPLE,EXAMPLE CO — delete this row,S,Plano,e.com,Marketing,greenhouse,ex,2026-08-17,note\n"
        "1,Acme,Finance,Dallas,acme.com,Financial analyst,,,,\n")
    rows, _ = parse_rows(p)
    assert [r["name"] for r in rows] == ["Acme"]


def test_role_families_split_on_semicolon_not_comma(tmp_path):
    """The values contain commas ('risk/compliance, junior') so the delimiter
    has to be the semicolon the source actually uses."""
    p = write_csv(tmp_path,
        '1,Acme,Finance,Dallas,acme.com,"Financial analyst; client service associate; risk/compliance",,,,\n')
    rows, _ = parse_rows(p)
    assert rows[0]["target_role_families"] == [
        "Financial analyst", "client service associate", "risk/compliance",
    ]


def test_blank_fields_become_none_not_empty_string(tmp_path):
    """An empty CSV cell is absent data. Writing '' would make a NOT NULL-ish
    value out of nothing and defeat the 'has a slug?' check."""
    p = write_csv(tmp_path, "1,Acme,Finance,Dallas,acme.com,Analyst,,,,\n")
    rows, _ = parse_rows(p)
    assert rows[0]["slug"] is None
    assert rows[0]["ats_platform"] is None
    assert rows[0]["checked_date"] is None


def test_unknown_ats_is_nulled_with_a_warning(tmp_path):
    """The table's check constraint would reject it, so storing it would fail
    the whole load for one bad cell.

    'brassring' rather than 'workday' -- this test originally used the latter,
    which stopped being unknown the moment the platform vocabulary widened.
    """
    p = write_csv(tmp_path, "1,Acme,Finance,Dallas,acme.com,Analyst,brassring,acme,,\n")
    rows, warnings = parse_rows(p)
    assert rows[0]["ats_platform"] is None
    assert any("brassring" in w for w in warnings)


def test_a_widened_platform_is_kept(tmp_path):
    """Workday and the other enterprise platforms are valid values now. They
    are not fetchable by every adapter, but that is a different question and
    fetchable() answers it."""
    p = write_csv(tmp_path, "1,Acme,Finance,Dallas,acme.com,Analyst,workday,acme.wd1.myworkdayjobs.com/External,,\n")
    rows, warnings = parse_rows(p)
    assert rows[0]["ats_platform"] == "workday"
    assert not warnings


def test_known_ats_is_lowercased(tmp_path):
    p = write_csv(tmp_path, "1,Acme,Finance,Dallas,acme.com,Analyst,Greenhouse,acme,,\n")
    rows, _ = parse_rows(p)
    assert rows[0]["ats_platform"] == "greenhouse"


def test_row_without_a_name_is_skipped(tmp_path):
    p = write_csv(tmp_path, "1,,Finance,Dallas,acme.com,Analyst,,,,\n")
    rows, warnings = parse_rows(p)
    assert rows == []
    assert any("no employer name" in w for w in warnings)


def test_duplicate_employer_is_skipped_case_insensitively(tmp_path):
    p = write_csv(tmp_path,
        "1,Acme,Finance,Dallas,acme.com,Analyst,,,,\n"
        "2,ACME,Finance,Plano,acme.com,Analyst,,,,\n")
    rows, warnings = parse_rows(p)
    assert len(rows) == 1
    assert any("duplicate" in w for w in warnings)


def test_priority_parses_and_survives_junk(tmp_path):
    p = write_csv(tmp_path,
        "3,Acme,Finance,Dallas,acme.com,Analyst,,,,\n"
        "high,Beta,Finance,Dallas,beta.com,Analyst,,,,\n")
    rows, _ = parse_rows(p)
    assert rows[0]["priority"] == 3
    assert rows[1]["priority"] is None


# ---------------------------------------------------------------------------
# Fetchability -- the thing the report must not overstate
# ---------------------------------------------------------------------------

def test_fetchable_requires_both_ats_and_slug(tmp_path):
    p = write_csv(tmp_path,
        "1,BothMissing,F,Dallas,a.com,Analyst,,,,\n"
        "1,AtsOnly,F,Dallas,b.com,Analyst,lever,,,\n"
        "1,SlugOnly,F,Dallas,c.com,Analyst,,someslug,,\n"
        "1,Complete,F,Dallas,d.com,Analyst,lever,goodslug,,\n")
    rows, _ = parse_rows(p)
    assert [r["name"] for r in fetchable(rows)] == ["Complete"]


def test_report_says_plainly_when_nothing_is_fetchable(tmp_path):
    p = write_csv(tmp_path, "1,Acme,Finance,Dallas,acme.com,Analyst,lever,,,\n")
    rows, warnings = parse_rows(p)
    out = render_report(rows, warnings, dry_run=True)
    assert "actually fetchable      0" in out
    assert "cannot be fetched" in out


def test_report_separates_the_three_reasons_something_is_unfetchable(tmp_path):
    """One count hides three different problems, and they need different
    people: an adapter is code, a site path is research, and an unconfirmed
    platform is neither until someone looks."""
    p = write_csv(tmp_path,
        "1,NoAdapter,F,Dallas,a.com,Analyst,icims,careers-a.icims.com,,\n"
        "1,NoSitePath,F,Dallas,b.com,Analyst,workday,b.wd1.myworkdayjobs.com,,\n"
        "1,Unconfirmed,F,Dallas,c.com,Analyst,,something,,\n"
        "1,Good,F,Dallas,d.com,Analyst,workday,d.wd1.myworkdayjobs.com/External,,\n")
    rows, warnings = parse_rows(p)
    out = render_report(rows, warnings, dry_run=True)
    assert "actually fetchable      1" in out
    assert "no adapter for their platform" in out and "icims" in out
    assert "will not build an" in out
    assert "platform never confirmed" in out


# ---------------------------------------------------------------------------
# The real file
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CSV.exists(), reason="employer CSV not in the repo")
def test_real_csv_parses_to_44_employers():
    rows, warnings = parse_rows(CSV)
    assert len(rows) == 44, f"expected 44 real employers, got {len(rows)}"
    assert not warnings, f"unexpected warnings: {warnings}"


@pytest.mark.skipif(not CSV.exists(), reason="employer CSV not in the repo")
def test_real_csv_state_after_the_slug_pass():
    """Pins where the research actually landed.

    The previous version of this test asserted zero slugs and zero fetchable
    employers, and it failed the moment the completed worksheet was merged --
    which is what it was written to do. This is its replacement.

    The shape of the answer is the finding: 44 employers researched, 43 of them
    on platforms the original five adapters cannot touch. Workday is why that
    is not fatal.
    """
    rows, _ = parse_rows(CSV)
    assert len(rows) == 44
    assert sum(1 for r in rows if r["slug"]) == 44, "every employer got a slug"

    platforms = {}
    for r in rows:
        platforms[r["ats_platform"]] = platforms.get(r["ats_platform"], 0) + 1
    assert platforms.get("workday") == 19
    assert platforms.get("lever") == 1

    # Match Group on Lever, plus the twelve Workday boards whose slug carries a
    # site path. The other seven Workday rows are hosts without a site and
    # cannot be built into an endpoint.
    assert len(fetchable(rows)) == 13


@pytest.mark.skipif(not CSV.exists(), reason="employer CSV not in the repo")
def test_platforms_without_an_adapter_are_not_called_fetchable():
    """An iCIMS employer has both a platform and a slug and is still
    unreachable, because no iCIMS adapter exists."""
    rows, _ = parse_rows(CSV)
    reachable = {r["ats_platform"] for r in fetchable(rows)}
    assert reachable <= {"workday", "lever"}
    assert "icims" not in reachable and "taleo" not in reachable


@pytest.mark.skipif(not CSV.exists(), reason="employer CSV not in the repo")
def test_real_csv_every_employer_has_a_domain():
    """The domain is what a slug lookup starts from, so its absence would make
    an employer unresearchable rather than merely unfetched."""
    rows, _ = parse_rows(CSV)
    assert [r["name"] for r in rows if not r["domain"]] == []
