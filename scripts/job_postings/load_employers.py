#!/usr/bin/env python3
"""Load the DFW employer target list into the employers table.

Source: data/job_postings/dfw_employers_ats.csv -- 44 hand-researched DFW
employers, one example row to skip.

WHAT THIS DOES AND DOES NOT UNBLOCK

It fills the employers table, which is what confirmed_roles needs to start
hardening from inference into evidence.

It does NOT let the ATS fetcher reach any of these employers. That needs
{ats, slug} per employer, and the CSV carries `ats` for one row out of 44
(Match Group, lever) and `slug` for none at all. A slug is the identifier in
the employer's own careers URL and has to be looked up per employer by hand.
So after this load the table says who to target, not who can be fetched, and
the run report says so rather than leaving it to be discovered later.

The `notes` column is mostly hypotheses -- "Enterprise HCM likely -- check for
myworkdayjobs.com" -- which is the research still outstanding, written down.
Loaded verbatim rather than interpreted; a guess about an ATS is not a fact
about one, and the slug lookup is where it gets settled.

ON target_role_families

The CSV's values are mid-career and entry-level occupations ("Financial
analyst; client service associate; risk/compliance"), not the fourteen student
roles in data/role_requirements.json. That is the same mismatch
data/job_postings/role_families.yaml has, and the same cause: both predate the
pivot from the mid-career Career OS concept to students. Stored as given --
rewriting them here would bury a decision that belongs to whoever remaps the
taxonomy.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from errors import JobPostingConfigError  # noqa: E402

DEFAULT_CSV = REPO_ROOT / "data" / "job_postings" / "dfw_employers_ats.csv"
EMPLOYERS_TABLE = "employers"

# Every platform the employers table accepts, which is a wider set than the
# platforms anything can fetch. The real DFW list made the difference concrete:
# 19 of 44 employers are on Workday and exactly one is on any of the original
# five, so restricting this to fetchable platforms would discard the research
# for 43 employers on the way in.
KNOWN_ATS = {
    "greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "workday",
    "icims", "oracle_cloud", "taleo", "successfactors", "avature",
    "eightfold", "ukg", "talent_community", "proprietary",
}

# Which of those an adapter exists for. This is the set that grows when someone
# writes code, and it is what `fetchable()` means.
FETCHABLE_ATS = {
    "greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "workday",
}

# The template row ships in the file so the shape is self-documenting. It says
# so in its own employer cell; matching on the priority column rather than the
# name keeps that from depending on the exact wording.
EXAMPLE_MARKER = "EXAMPLE"


class EmployerCsvError(ValueError):
    """The CSV is not the shape this loader was written for."""


EXPECTED_COLUMNS = {
    "priority", "employer", "sector", "dfw_location", "domain",
    "target_role_families", "ats", "slug", "checked_date", "notes",
}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _split_families(value: str | None) -> list[str]:
    """Semicolon-separated in the source. Commas are inside the values."""
    if not value:
        return []
    return [p.strip() for p in value.split(";") if p.strip()]


def _parse_priority(value: str | None) -> int | None:
    try:
        return int(value) if value and value.strip() else None
    except ValueError:
        return None


def parse_rows(path: Path) -> tuple[list[dict], list[str]]:
    """CSV -> (employer rows, warnings). Warnings never block the load.

    A row is skipped only if it has no employer name, which is the one field
    nothing downstream can work around. Everything else -- no ats, no slug, no
    date -- is the expected state of this file, not an error.
    """
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise EmployerCsvError(f"{path} has no header row")
        missing = EXPECTED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise EmployerCsvError(
                f"{path} is missing expected column(s): {sorted(missing)}. "
                f"Found: {reader.fieldnames}"
            )
        raw = list(reader)

    rows: list[dict] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for i, r in enumerate(raw, start=2):  # header is line 1
        if (r.get("priority") or "").strip().upper() == EXAMPLE_MARKER:
            continue

        name = _clean(r.get("employer"))
        if not name:
            warnings.append(f"line {i}: no employer name, skipped")
            continue

        key = name.casefold()
        if key in seen:
            warnings.append(f"line {i}: duplicate employer {name!r}, skipped")
            continue
        seen.add(key)

        ats = _clean(r.get("ats"))
        if ats:
            ats = ats.lower()
            if ats not in KNOWN_ATS:
                warnings.append(
                    f"line {i}: {name} has ats={ats!r}, which is not one of "
                    f"{sorted(KNOWN_ATS)}. Storing NULL rather than a value the "
                    f"table's check constraint would reject."
                )
                ats = None

        rows.append({
            "name": name,
            "slug": _clean(r.get("slug")),
            "sector": _clean(r.get("sector")),
            "dfw_location": _clean(r.get("dfw_location")),
            "domain": _clean(r.get("domain")),
            "ats_platform": ats,
            "priority": _parse_priority(r.get("priority")),
            "checked_date": _clean(r.get("checked_date")),
            "notes": _clean(r.get("notes")),
            "target_role_families": _split_families(r.get("target_role_families")),
        })

    return rows, warnings


def fetchable(rows: list[dict]) -> list[dict]:
    """Employers an adapter could actually reach.

    Three conditions, not two. A platform and a slug are necessary but not
    sufficient: an employer on iCIMS has both and is still unreachable, because
    no iCIMS adapter exists. And a Workday slug recording only a host with no
    site path cannot be turned into an endpoint at all -- seven of the nineteen
    Workday rows are in that state -- so the slug has to be parseable, not
    merely present.
    """
    out = []
    for r in rows:
        platform, slug = r.get("ats_platform"), r.get("slug")
        if not platform or not slug or platform not in FETCHABLE_ATS:
            continue
        if platform == "workday":
            from workday import parse_workday_slug

            if parse_workday_slug(slug) is None:
                continue
        out.append(r)
    return out


def render_report(rows: list[dict], warnings: list[str], *, dry_run: bool) -> str:
    ready = fetchable(rows)
    with_ats = [r for r in rows if r["ats_platform"]]
    with_slug = [r for r in rows if r["slug"]]

    lines = [
        "",
        "=" * 66,
        f"  employer load -- {'DRY RUN' if dry_run else 'WRITTEN'}",
        "=" * 66,
        f"  employers parsed        {len(rows)}",
        f"  with an ATS named       {len(with_ats)}",
        f"  with a slug             {len(with_slug)}",
        f"  actually fetchable      {len(ready)}",
        "",
    ]
    if len(ready) < len(rows):
        no_platform = [r for r in rows if not r["ats_platform"]]
        no_adapter = [r for r in rows
                      if r["ats_platform"] and r["ats_platform"] not in FETCHABLE_ATS]
        unbuildable = [r for r in rows
                       if r["ats_platform"] in FETCHABLE_ATS and r not in ready]

        lines += [f"  {len(rows) - len(ready)} employer(s) cannot be fetched, for three different reasons:", ""]
        if no_adapter:
            platforms = sorted({r["ats_platform"] for r in no_adapter})
            lines += [
                f"    {len(no_adapter):>2}  no adapter for their platform -- {', '.join(platforms)}.",
                "        Writing one is code, not research.",
            ]
        if unbuildable:
            lines += [
                f"    {len(unbuildable):>2}  on a supported platform but the slug will not build an",
                "        endpoint. Workday rows recording a host with no /site path are",
                "        the whole of this group; the site segment has to be looked up.",
            ]
        if no_platform:
            lines += [f"    {len(no_platform):>2}  platform never confirmed."]
        lines += [
            "",
            "  Loading is still worth doing regardless -- it is what confirmed_roles",
            "  builds on, and it records the research so nobody repeats it.",
            "",
        ]
    if warnings:
        lines.append(f"  {len(warnings)} warning(s):")
        lines += [f"    - {w}" for w in warnings[:10]]
        if len(warnings) > 10:
            lines.append(f"    ... and {len(warnings) - 10} more")
        lines.append("")
    lines.append("=" * 66)
    return "\n".join(lines)


def build_client() -> Any:
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "").strip()
    secret = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    if not url or not secret:
        raise JobPostingConfigError(
            "SUPABASE_URL and SUPABASE_SECRET_KEY are both required to write."
        )
    return create_client(url, secret)


def upsert(client: Any, rows: list[dict]) -> int:
    """Upsert on name.

    confirmed_roles is deliberately absent from the payload: it is written by
    ingest as postings come back, and re-running this loader must not reset
    evidence already collected back to an empty list.
    """
    result = client.table(EMPLOYERS_TABLE).upsert(rows, on_conflict="name").execute()
    return len(result.data or [])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write to Supabase. Without this, parses and reports only. The "
             "employers table does not exist until the staged migration is applied.",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 2

    try:
        rows, warnings = parse_rows(args.csv)
    except EmployerCsvError as exc:
        print(f"CSV error: {exc}", file=sys.stderr)
        return 2

    if not rows:
        print("No employer rows parsed.", file=sys.stderr)
        return 2

    print(render_report(rows, warnings, dry_run=not args.write))

    if args.write:
        try:
            client = build_client()
        except JobPostingConfigError as exc:
            print(f"Config error: {exc}", file=sys.stderr)
            return 2
        written = upsert(client, rows)
        print(f"  upserted {written} employer(s).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
