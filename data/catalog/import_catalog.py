#!/usr/bin/env python3
"""Import normalized catalog JSON into Supabase `course_catalog`.

Dry-run is the default, matching every other script in this directory and
scripts/import_students.py. Use --write to perform the upsert.

WHY NATIVE UPSERT, UNLIKE import_students.py: that script deliberately does an
application-level find-then-write because most of its natural keys had no
backing unique constraint, so `ON CONFLICT` would fail with a missing-constraint
error. That reasoning does not apply here. `course_catalog` carries a real
`unique (institution_id, code)` constraint (20260804155924_course_catalog.sql),
so the native upsert is available and is the correct tool -- the same call
GradusIQ_career/resume/store.py already uses for its child tables. It is also
what makes this script re-runnable: a second run updates in place rather than
duplicating 1,374 rows.

Batching matters at this size. import_students.py writes row-at-a-time, which is
fine for five students; the TAMU catalog is ~1,374 rows, where row-at-a-time
would be ~1,374 round trips.

Connects using SUPABASE_URL / SUPABASE_SECRET_KEY from .env. Never prints a key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

CATALOG_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = CATALOG_ROOT.parents[1]

# Mirrors validate_catalog.py: these hold prose and student fixtures, not
# catalog course arrays.
EXCLUDED_DIRS = {"reference", "students"}

# Institution selector -> the `institutions.name` to resolve it against. The
# name is the lookup key rather than a hardcoded UUID so this script cannot
# drift from the live table, and so a fresh environment with different UUIDs
# still works. See --institution.
INSTITUTION_NAMES = {
    "tamu": "Texas A&M University",
    "smu": "Southern Methodist University",
}

# Which top-level directories of data/catalog/ hold each institution's files.
#
# WHY THIS EXISTS: file discovery used to rglob all of data/catalog/ and lean
# entirely on the provenance guard to reject foreign rows. That was survivable
# while TAMU was the only institution on disk. Once data/catalog/smu/ existed it
# became a hard failure -- a `--institution tamu` run read all 4,623 rows,
# tripped the guard on 3,249 SMU rows, and refused to import TAMU at all.
#
# EVERY institution enumerates its own directories. There is deliberately no
# "everything not claimed by someone else" fallback: under that rule a third
# institution added without an entry here would silently inherit both TAMU's
# college folders and its own, and the provenance guard would then reject the
# whole run with no indication that the cause was a missing map entry. A
# selector with no entry is now a hard, named error instead -- see
# subtrees_for().
#
# TAMU still has no dedicated folder of its own; its college directories sit at
# the root of data/catalog/. Listing them explicitly is what makes that an
# intentional layout rather than an implicit default. Moving them under a
# tamu/ directory is the pending restructure, and would reduce this entry to a
# single name.
INSTITUTION_SUBTREES: dict[str, tuple[str, ...]] = {
    "tamu": (
        "agriculture_life_sciences",
        "architecture",
        "arts_and_sciences",
        "business",
        "education_human_development",
        "engineering",
        "government_public_service",
        "nursing",
        "public_health",
        "veterinary_biomedical_sciences",
    ),
    "smu": ("smu",),
}

# The columns of course_catalog this script populates. The table also has
# `id`, `created_at` and `updated_at`, all of which have database defaults and
# are deliberately not sent.
TARGET_COLUMNS = (
    "institution_id",
    "code",
    "prefix",
    "number",
    "title",
    "description",
    "department",
    "course_level",
    "credit_min",
    "credit_max",
    "prerequisites",
    "catalog_year",
    "source_last_checked",
    "coursedog_group_id",
)

# Fields present in the catalog JSON that course_catalog has no column for, and
# which are therefore dropped on import. Listed explicitly so the omission is a
# recorded decision rather than something silently lost in a dict comprehension:
#
#   ucc_attributes        TAMU University Core Curriculum tags; TAMU-specific
#   satisfies_ucc         the same, on the 84 rows the UCC merge enriched
#   tccns                 Texas Common Course Numbering equivalents
#   cross_listings        codes the course is also listed under
#   campuses              campus availability
#   prerequisite_courses  parsed prereq codes; the table keeps prose only
#   restrictions          parsed restriction phrases, e.g. "Grade of C or better"
#   is_variable_credit    derivable from credit_min != credit_max
#   credit_hours          superseded by credit_min / credit_max
#   source_url            per-row provenance; catalog_year +
#                         source_last_checked are what the table carries
#
# Re-adding any of these is a migration, not a change to this script.
DROPPED_FIELDS = (
    "ucc_attributes",
    "satisfies_ucc",
    "tccns",
    "cross_listings",
    "campuses",
    "prerequisite_courses",
    "restrictions",
    "is_variable_credit",
    "credit_hours",
    "source_url",
)


def stop(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def subtrees_for(selector: str) -> tuple[str, ...]:
    """The directories belonging to `selector`, or exit naming the omission.

    Failing here rather than falling back to "whatever is left over" is the
    point: a missing entry is a configuration mistake, and the run should say
    so plainly instead of importing a plausible-looking wrong set of files.
    """
    subtrees = INSTITUTION_SUBTREES.get(selector)
    if not subtrees:
        stop(
            f"No INSTITUTION_SUBTREES entry for --institution {selector}. "
            f"Add the directories under {CATALOG_ROOT} that hold its catalog "
            f"files before importing it."
        )
    return subtrees


def iter_catalog_files(root: Path, selector: str) -> list[Path]:
    """This institution's catalog JSON files only, in stable order.

    See INSTITUTION_SUBTREES for why discovery is scoped rather than reading
    every file under data/catalog/ and filtering afterwards.
    """
    owned = set(subtrees_for(selector))

    files: list[Path] = []
    for path in root.rglob("*.json"):
        parts = path.relative_to(root).parts
        if EXCLUDED_DIRS.intersection(parts):
            continue
        # Top-level directory only: a file sitting loose at the root of
        # data/catalog/ belongs to no institution and is never imported.
        if len(parts) < 2 or parts[0] not in owned:
            continue
        files.append(path)
    return sorted(files)


def to_row(course: dict[str, Any], institution_id: str) -> dict[str, Any]:
    """Map one normalized catalog record onto course_catalog's columns."""
    return {
        "institution_id": institution_id,
        "code": course.get("code"),
        "prefix": course.get("prefix"),
        "number": course.get("number"),
        "title": course.get("title"),
        "description": course.get("description"),
        "department": course.get("department"),
        # Nullable by design: null for graduate-level courses the normalizer
        # does not map. See the column comment in the migration.
        "course_level": course.get("course_level"),
        "credit_min": course.get("credit_min"),
        "credit_max": course.get("credit_max"),
        # Nullable: null when the source lists no prerequisites.
        "prerequisites": course.get("prerequisites"),
        "catalog_year": course.get("catalog_year"),
        "source_last_checked": course.get("source_last_checked"),
        # Nullable: TAMU (CourseLeaf-sourced) rows never have one; SMU rows
        # have it unless the source record itself omitted courseGroupId.
        "coursedog_group_id": course.get("coursedog_group_id"),
    }


NOT_NULL_COLUMNS = (
    "code",
    "prefix",
    "number",
    "title",
    "description",
    "department",
    "credit_min",
    "credit_max",
    "catalog_year",
    "source_last_checked",
)


def validate_row(row: dict[str, Any], label: str) -> list[str]:
    """Check a mapped row against the table's NOT NULL and CHECK constraints.

    Catching these here turns a mid-batch Postgres error -- which would leave
    an unknown number of earlier batches already applied -- into a complete
    list of problems reported before anything is written.
    """
    problems: list[str] = []

    for column in NOT_NULL_COLUMNS:
        value = row.get(column)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(f"{label}: {column} is null/empty (NOT NULL)")

    credit_min = row.get("credit_min")
    credit_max = row.get("credit_max")
    if isinstance(credit_min, bool) or isinstance(credit_max, bool):
        problems.append(f"{label}: credit_min/credit_max must be integers, got bool")
    elif isinstance(credit_min, int) and isinstance(credit_max, int):
        # course_catalog_credit_range
        if credit_min < 0:
            problems.append(f"{label}: credit_min {credit_min} < 0 (CHECK)")
        if credit_max < credit_min:
            problems.append(
                f"{label}: credit_max {credit_max} < credit_min {credit_min} (CHECK)"
            )
    else:
        problems.append(f"{label}: credit_min/credit_max are not both integers")

    course_level = row.get("course_level")
    if course_level is not None and not isinstance(course_level, int):
        problems.append(f"{label}: course_level must be an integer or null")

    return problems


def chunked(rows: list[dict[str, Any]], size: int):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def resolve_institution(client: Client, selector: str) -> tuple[str, str, str | None]:
    """Return (institution_id, name, catalog_base_url) for the selector, or exit."""
    name = INSTITUTION_NAMES[selector]
    rows = (
        client.table("institutions")
        .select("id,name,catalog_base_url")
        .eq("name", name)
        .execute()
        .data
    )
    if not rows:
        stop(f"No institutions row named {name!r}. Cannot resolve --institution {selector}.")
    if len(rows) > 1:
        stop(f"Ambiguous: {len(rows)} institutions rows named {name!r}.")
    return rows[0]["id"], rows[0]["name"], rows[0].get("catalog_base_url")


def verify_rls_read(publishable_key: str, url: str, institution_id: str) -> None:
    """Read back a sample through the publishable key, as import_students.py does.

    course_catalog carries a public-read policy (course_catalog_read_public,
    to anon + authenticated). This confirms that policy is actually in force
    for the rows just written, rather than assuming it from the migration.
    """
    anon_client: Client = create_client(url, publishable_key)
    sample = (
        anon_client.table("course_catalog")
        .select("code,title,credit_min,credit_max")
        .eq("institution_id", institution_id)
        .limit(5)
        .execute()
        .data
    )
    print("\n-- RLS read-back (publishable key) --")
    if not sample:
        print("  WARNING: publishable-key read returned no rows.")
        print("  Expected the public-read policy to expose them. Investigate before relying")
        print("  on a browser-side catalog search.")
        return
    print(f"  publishable-key SELECT returned {len(sample)} row(s):")
    for row in sample:
        credits = (
            str(row["credit_min"])
            if row["credit_min"] == row["credit_max"]
            else f"{row['credit_min']}-{row['credit_max']}"
        )
        print(f"    {row['code']:<12} {row['title'][:52]:<52} {credits} cr")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="perform the upsert; without this the script only reports what it would do",
    )
    parser.add_argument(
        "--institution",
        choices=sorted(INSTITUTION_NAMES),
        default="tamu",
        help="which institution the local catalog JSON belongs to (default: tamu)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="rows per upsert request (default: 500)",
    )
    args = parser.parse_args()

    if args.batch_size < 1:
        stop("--batch-size must be at least 1.")

    load_dotenv(PROJECT_ROOT / ".env")
    url = os.environ.get("SUPABASE_URL")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY")
    publishable_key = os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    if not url or not secret_key:
        stop("SUPABASE_URL and/or SUPABASE_SECRET_KEY are not set in .env.")

    print(f"mode: {'WRITE' if args.write else 'DRY RUN (no writes)'}")
    print(f"institution selector: {args.institution}")

    client: Client = create_client(url, secret_key)
    institution_id, institution_name, catalog_base_url = resolve_institution(
        client, args.institution
    )
    print(f"resolved institution: {institution_name} ({institution_id})")
    print(f"catalog_base_url:     {catalog_base_url or '(not set)'}")

    # PROVENANCE GUARD. data/catalog/ has no per-institution subtree -- every
    # file under it is TAMU data today -- so --institution alone would happily
    # stamp 1,374 TAMU courses with SMU's institution_id and upsert them. That
    # is silent, plausible-looking corruption of institution-wide reference
    # data, so the selector is not trusted on its own: each row's source_url
    # must sit under the selected institution's catalog_base_url.
    #
    # This is why source_url is read even though it is dropped before writing,
    # and why an institution with no catalog_base_url (SMU today) cannot be
    # imported for at all rather than defaulting to something permissive.
    if not catalog_base_url:
        stop(
            f"{institution_name} has no catalog_base_url in the institutions table, so the "
            f"local catalog JSON cannot be confirmed to belong to it. Refusing to import. "
            f"Set institutions.catalog_base_url first."
        )

    # ── Load and map ────────────────────────────────────────────────────────
    files = iter_catalog_files(CATALOG_ROOT, args.institution)
    if not files:
        stop(
            f"No catalog JSON files found for --institution {args.institution} "
            f"under {CATALOG_ROOT}."
        )

    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    per_file: list[tuple[str, int]] = []
    dropped_seen: Counter[str] = Counter()
    origin_by_code: dict[str, list[str]] = defaultdict(list)
    mismatched_source: list[str] = []

    for path in files:
        rel = path.relative_to(CATALOG_ROOT)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{rel}: invalid JSON ({exc})")
            continue
        if not isinstance(data, list):
            problems.append(f"{rel}: top-level value is not an array")
            continue

        for index, course in enumerate(data):
            if not isinstance(course, dict):
                problems.append(f"{rel}[{index}]: record is not an object")
                continue
            for field in DROPPED_FIELDS:
                if field in course:
                    dropped_seen[field] += 1

            source_url = course.get("source_url")
            if not isinstance(source_url, str) or not source_url.startswith(catalog_base_url):
                mismatched_source.append(
                    f"{rel} {course.get('code') or f'[{index}]'}: source_url "
                    f"{source_url!r} is not under {catalog_base_url!r}"
                )
            row = to_row(course, institution_id)
            label = f"{rel} {course.get('code') or f'[{index}]'}"
            problems.extend(validate_row(row, label))
            rows.append(row)
            if row.get("code"):
                origin_by_code[row["code"]].append(str(rel))

        per_file.append((str(rel), len(data)))

    # ── Duplicate detection on the upsert key ───────────────────────────────
    # A duplicate code within one payload is not a constraint violation the
    # database would reject cleanly -- Postgres refuses an ON CONFLICT upsert
    # whose payload touches the same key twice ("cannot affect row a second
    # time"), so this must be caught here.
    duplicates = {
        code: origins for code, origins in origin_by_code.items() if len(origins) > 1
    }

    # ── Report ──────────────────────────────────────────────────────────────
    print(f"\n-- Source files ({len(files)}) --")
    for rel, count in per_file:
        print(f"  {rel:<58} {count:>5}")
    print(f"  {'TOTAL':<58} {len(rows):>5}")

    print("\n-- Dropped fields (present in JSON, no column in course_catalog) --")
    for field in DROPPED_FIELDS:
        print(f"  {field:<22} present on {dropped_seen.get(field, 0):>5} row(s)")

    print("\n-- Validation --")
    if problems:
        print(f"  {len(problems)} problem(s):")
        for problem in problems[:50]:
            print(f"    {problem}")
        if len(problems) > 50:
            print(f"    ... and {len(problems) - 50} more")
    else:
        print("  0 problems: every row satisfies the NOT NULL and CHECK constraints.")

    print("\n-- Duplicate codes on the upsert key (institution_id, code) --")
    if duplicates:
        print(f"  {len(duplicates)} duplicated code(s):")
        for code, origins in sorted(duplicates.items())[:20]:
            print(f"    {code} x{len(origins)} -> {', '.join(origins)}")
    else:
        print("  0 duplicates.")

    print(f"\n-- Provenance guard (source_url under {catalog_base_url}) --")
    if mismatched_source:
        print(f"  {len(mismatched_source)} row(s) do NOT belong to {institution_name}:")
        for line in mismatched_source[:10]:
            print(f"    {line}")
        if len(mismatched_source) > 10:
            print(f"    ... and {len(mismatched_source) - 10} more")
    else:
        print(f"  0 mismatches: all {len(rows)} row(s) trace to {institution_name}'s catalog.")

    existing = (
        client.table("course_catalog")
        .select("id", count="exact")
        .eq("institution_id", institution_id)
        .execute()
    )
    existing_count = existing.count or 0
    batches = (len(rows) + args.batch_size - 1) // args.batch_size
    print("\n-- Plan --")
    print(f"  rows already in course_catalog for this institution: {existing_count}")
    print(f"  rows to upsert:                                      {len(rows)}")
    print(f"  batch size:                                          {args.batch_size}")
    print(f"  requests:                                            {batches}")
    print(f"  on_conflict:                                         institution_id,code")

    if problems or duplicates or mismatched_source:
        stop("Refusing to proceed: fix the problems above first. Nothing was written.")

    if not args.write:
        print("\nDRY RUN — no writes were performed. Re-run with --write to apply.")
        return 0

    # ── Write ───────────────────────────────────────────────────────────────
    written = 0
    for number, batch in enumerate(chunked(rows, args.batch_size), start=1):
        client.table("course_catalog").upsert(
            batch, on_conflict="institution_id,code"
        ).execute()
        written += len(batch)
        print(f"  batch {number}/{batches}: {len(batch)} row(s) upserted ({written}/{len(rows)})")

    after = (
        client.table("course_catalog")
        .select("id", count="exact")
        .eq("institution_id", institution_id)
        .execute()
    )
    print(f"\n  course_catalog now holds {after.count or 0} row(s) for {institution_name}.")

    if publishable_key:
        verify_rls_read(publishable_key, url, institution_id)
    else:
        print("\n  SUPABASE_PUBLISHABLE_KEY not set — skipping RLS read-back verification.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
