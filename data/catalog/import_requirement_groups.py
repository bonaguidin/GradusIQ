#!/usr/bin/env python3
"""Import a normalized requirement-skeleton JSON (from
fetch_smu_requirements.py) into Supabase: programs, requirement_groups,
requirement_group_options, requirement_group_option_courses.

Dry-run is the default, matching fetch_smu_requirements.py and
import_catalog.py. Use --write to perform the writes.

WHY DELETE-THEN-INSERT FOR OPTIONS/COURSES, UNLIKE import_catalog.py'S
NATIVE UPSERT: requirement_group_options and requirement_group_option_courses
have no natural key stable enough to upsert on. option_index is only a
position in the source's value.values[] array -- if SMU reorders that array
on a future republish, upserting on (requirement_group_id, option_index)
would silently reattach the wrong course list to an existing option_index
rather than detecting the change. requirement_groups itself DOES upsert
natively, on (program_id, coursedog_rule_id), because that pair is a real
stable identity from the source, the same reasoning course_catalog's
(institution_id, code) upsert key relies on.

Connects using SUPABASE_URL / SUPABASE_SECRET_KEY from .env, same as
import_catalog.py. Never prints a key.

ATOMICITY GUARANTEE -- READ BEFORE RELYING ON THIS SCRIPT'S FAILURE BEHAVIOR:
the write phase is NOT wrapped in a database transaction -- the Supabase
Python client issues each table operation (programs upsert, requirement_groups
upsert, per-child parent_group_id updates, options delete, options insert,
courses insert) as its own separate PostgREST request, and PostgREST does not
expose a way to group unrelated requests into one transaction from this
client. If the process dies mid-run (network failure, killed process, etc.),
the database can be left in a transient state where some requirement_groups
have their options deleted but not yet reinserted.

What IS guaranteed: **idempotent, safe to blindly rerun from scratch.** Every
write this script performs is fully determined by (a) the input JSON file and
(b) the current live course_catalog contents -- nothing here is incremental
or accumulates across runs. requirement_groups upserts on its real stable key
(program_id, coursedog_rule_id); options+courses are deleted and fully
rebuilt per enumerated group on every run, not merged with whatever was
already there. So re-running this exact script against the exact same input
file after a crash -- with no manual cleanup -- always converges to the same
correct end state, whether the prior run crashed before writing anything, mid-
way through, or completed successfully. This is a "safe to retry" guarantee,
NOT an atomicity guarantee: a reader querying the database in the window
between a crash and the next successful rerun can observe a requirement group
with zero options, and that is expected, not a bug to fix here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

CATALOG_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = CATALOG_ROOT.parents[1]

VALID_GROUP_TYPES = (
    "enumerated_all",
    "enumerated_at_least_n",
    "compound_all",
    "compound_any",
    "freeform",
    "enumerated_credit_threshold",
)
# Group types that carry options (requirement_group_options +
# requirement_group_option_courses) rather than children --
# enumerated_credit_threshold uses the identical value.values[] shape as
# enumerated_all (see fetch_smu_requirements.py's CONDITION_TO_GROUP_TYPE
# comment for completeVariableCoursesAndVariableCredits), it just differs
# in how the satisfaction engine reads those options, not in ingestion.
ENUMERATED_GROUP_TYPES = ("enumerated_all", "enumerated_at_least_n", "enumerated_credit_threshold")

# v1 is SMU-only -- see fetch_smu_requirements.py and spec §6 step 4. Not a
# general multi-institution selector the way import_catalog.py's
# --institution is; extend this the same way if a second institution's
# requirement skeleton is ever imported.
INSTITUTION_NAME = "Southern Methodist University"


def stop(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


# ── Pure mapping/validation functions (no network, no Supabase client) ─────


def to_program_row(program: dict[str, Any], institution_id: str, catalog_year: str) -> dict[str, Any]:
    return {
        "institution_id": institution_id,
        "coursedog_program_id": program.get("coursedog_program_id"),
        "program_group_id": program.get("program_group_id"),
        "code": program.get("code"),
        "name": program.get("name"),
        "degree_designation": program.get("degree_designation"),
        "catalog_year": catalog_year,
    }


PROGRAM_NOT_NULL_COLUMNS = (
    "coursedog_program_id",
    "program_group_id",
    "code",
    "name",
    "catalog_year",
)


def validate_program_row(row: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for column in PROGRAM_NOT_NULL_COLUMNS:
        value = row.get(column)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(f"program: {column} is null/empty (NOT NULL)")
    return problems


def to_requirement_group_row(
    group: dict[str, Any], program_id: str, catalog_year: str
) -> dict[str, Any]:
    """Map one normalized group dict (from fetch_smu_requirements.py's output)
    onto requirement_groups' columns. parent_group_id is NOT resolved here --
    the caller does a second pass once every group in the same import has a
    real id, since a child can reference a parent that hasn't been inserted
    yet within the same batch.
    """
    return {
        "program_id": program_id,
        "catalog_year": catalog_year,
        "coursedog_rule_id": group.get("coursedog_rule_id"),
        "name": group.get("name"),
        "group_type": group.get("group_type"),
        "n_required": group.get("n_required"),
        "credit_hours_required": group.get("credit_hours_required"),
        "notes_html": group.get("notes_html"),
        "requires_manual_definition": bool(group.get("requires_manual_definition", False)),
    }


def validate_requirement_group_row(row: dict[str, Any], label: str) -> list[str]:
    """Mirrors requirement_groups' NOT NULL and CHECK constraints
    (20260818130000_smu_requirement_skeleton.sql), so a bad row is caught
    here rather than as a mid-batch Postgres error.
    """
    problems: list[str] = []

    for column in ("coursedog_rule_id", "name", "group_type", "catalog_year"):
        value = row.get(column)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(f"{label}: {column} is null/empty (NOT NULL)")

    group_type = row.get("group_type")
    if group_type is not None and group_type not in VALID_GROUP_TYPES:
        problems.append(
            f"{label}: group_type {group_type!r} not one of {VALID_GROUP_TYPES}"
        )

    n_required = row.get("n_required")
    if group_type == "enumerated_at_least_n":
        if not isinstance(n_required, int) or isinstance(n_required, bool) or n_required < 1:
            problems.append(
                f"{label}: group_type is enumerated_at_least_n but n_required "
                f"is {n_required!r} (must be a positive int)"
            )
    elif n_required is not None:
        problems.append(
            f"{label}: group_type is {group_type!r} but n_required is "
            f"{n_required!r} (must be null unless enumerated_at_least_n)"
        )

    credit_hours = row.get("credit_hours_required")
    if credit_hours is not None and (
        isinstance(credit_hours, bool) or not isinstance(credit_hours, int) or credit_hours < 0
    ):
        problems.append(
            f"{label}: credit_hours_required must be a non-negative int or "
            f"null, got {credit_hours!r}"
        )

    return problems


def build_option_rows(
    group: dict[str, Any], resolved_ids: set[str]
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    """For one enumerated group, return (option rows without
    requirement_group_id yet, parallel list of that option's course rows
    without requirement_group_option_id yet). `resolved_ids` is the set of
    coursedog_group_id values known to course_catalog (for this
    institution) -- anything not in it becomes an unresolved_course_ref row
    instead of failing the import, per spec §8.3's already-decided
    "unresolved course IDs" item.
    """
    option_rows: list[dict[str, Any]] = []
    course_rows_by_option: list[list[dict[str, Any]]] = []

    for option in group.get("options", []):
        option_rows.append(
            {
                "option_index": option.get("option_index"),
                "logic": option.get("logic"),
            }
        )
        course_rows: list[dict[str, Any]] = []
        for coursedog_group_id in option.get("coursedog_group_ids", []):
            if coursedog_group_id in resolved_ids:
                course_rows.append(
                    {"coursedog_group_id": coursedog_group_id, "unresolved_course_ref": None}
                )
            else:
                course_rows.append(
                    {"coursedog_group_id": None, "unresolved_course_ref": coursedog_group_id}
                )
        course_rows_by_option.append(course_rows)

    return option_rows, course_rows_by_option


def validate_option_row(row: dict[str, Any], label: str) -> list[str]:
    problems: list[str] = []
    option_index = row.get("option_index")
    if not isinstance(option_index, int) or isinstance(option_index, bool) or option_index < 0:
        problems.append(f"{label}: option_index must be a non-negative int, got {option_index!r}")
    if row.get("logic") not in ("and", "or"):
        problems.append(f"{label}: logic must be 'and' or 'or', got {row.get('logic')!r}")
    return problems


# ── Supabase-touching functions ─────────────────────────────────────────────


def resolve_institution(client: Client) -> str:
    rows = (
        client.table("institutions")
        .select("id,name")
        .eq("name", INSTITUTION_NAME)
        .execute()
        .data
    )
    if not rows:
        stop(f"No institutions row named {INSTITUTION_NAME!r}.")
    if len(rows) > 1:
        stop(f"Ambiguous: {len(rows)} institutions rows named {INSTITUTION_NAME!r}.")
    return rows[0]["id"]


def fetch_resolved_coursedog_group_ids(client: Client, institution_id: str) -> set[str]:
    """All coursedog_group_id values course_catalog already has for this
    institution. Paginated: course_catalog is thousands of rows, and
    PostgREST default-limits a single select.
    """
    resolved: set[str] = set()
    page_size = 1000
    offset = 0
    while True:
        rows = (
            client.table("course_catalog")
            .select("coursedog_group_id")
            .eq("institution_id", institution_id)
            .not_.is_("coursedog_group_id", "null")
            .range(offset, offset + page_size - 1)
            .execute()
            .data
        )
        if not rows:
            break
        resolved.update(row["coursedog_group_id"] for row in rows if row.get("coursedog_group_id"))
        if len(rows) < page_size:
            break
        offset += page_size
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        type=Path,
        help="path to a normalized JSON file from fetch_smu_requirements.py --write",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="perform the writes; without this the script only reports what it would do",
    )
    args = parser.parse_args()

    if not args.input.exists():
        stop(f"{args.input} does not exist. Run fetch_smu_requirements.py --write first.")

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    program = payload.get("program") or {}
    catalog_year = payload.get("catalog_year")
    groups = payload.get("groups") or []

    print(f"mode: {'WRITE' if args.write else 'DRY RUN (no writes)'}")
    print(f"input: {args.input}")
    print(f"program: {program.get('name')} ({program.get('code')})")
    print(f"catalog_year: {catalog_year}")
    print(f"groups in file: {len(groups)}")

    # ── Validate before touching the network ───────────────────────────────
    problems: list[str] = []

    program_row_template = to_program_row(program, institution_id="<pending>", catalog_year=catalog_year)
    problems.extend(validate_program_row(program_row_template))

    known_rule_ids = {g.get("coursedog_rule_id") for g in groups}
    for group in groups:
        label = f"group {group.get('coursedog_rule_id')} ({group.get('name')})"
        row = to_requirement_group_row(group, program_id="<pending>", catalog_year=catalog_year)
        problems.extend(validate_requirement_group_row(row, label))

        parent_id = group.get("parent_coursedog_rule_id")
        if parent_id is not None and parent_id not in known_rule_ids:
            problems.append(
                f"{label}: parent_coursedog_rule_id {parent_id!r} is not "
                f"among this file's own groups -- orphaned reference"
            )

        if group.get("group_type") in ENUMERATED_GROUP_TYPES:
            for option in group.get("options", []):
                option_label = f"{label} option {option.get('option_index')}"
                problems.extend(
                    validate_option_row(
                        {"option_index": option.get("option_index"), "logic": option.get("logic")},
                        option_label,
                    )
                )
                if not option.get("coursedog_group_ids"):
                    problems.append(f"{option_label}: no coursedog_group_ids")
        elif group.get("options"):
            problems.append(
                f"{label}: group_type {group.get('group_type')!r} should carry "
                f"no options, but {len(group['options'])} present"
            )

    print("\n-- Validation --")
    if problems:
        print(f"  {len(problems)} problem(s):")
        for problem in problems[:50]:
            print(f"    {problem}")
        if len(problems) > 50:
            print(f"    ... and {len(problems) - 50} more")
        stop("Refusing to proceed: fix the problems above first. Nothing was written.")
    else:
        print("  0 problems.")

    if not args.write:
        print("\nDRY RUN — no writes were performed. Re-run with --write to apply.")
        return 0

    # ── Write ───────────────────────────────────────────────────────────────
    load_dotenv(PROJECT_ROOT / ".env")
    url = os.environ.get("SUPABASE_URL")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not secret_key:
        stop("SUPABASE_URL and/or SUPABASE_SECRET_KEY are not set in .env.")

    client: Client = create_client(url, secret_key)
    try:
        _write(client, program, catalog_year, groups)
    except Exception:
        print(
            "\nERROR: write phase failed partway through -- see traceback below. "
            "This script's writes are idempotent (see module docstring's "
            "ATOMICITY GUARANTEE section): re-running it against this same "
            "input file, with no manual cleanup, is safe and will converge "
            "to the correct end state.",
            file=sys.stderr,
        )
        raise
    return 0


def _write(
    client: Client, program: dict[str, Any], catalog_year: str, groups: list[dict[str, Any]]
) -> None:
    institution_id = resolve_institution(client)
    print(f"\nresolved institution: {INSTITUTION_NAME} ({institution_id})")

    program_row = to_program_row(program, institution_id=institution_id, catalog_year=catalog_year)
    program_result = (
        client.table("programs")
        .upsert(program_row, on_conflict="institution_id,coursedog_program_id")
        .execute()
    )
    if not program_result.data:
        stop(
            f"programs upsert for {program_row['code']!r} returned no rows -- "
            f"cannot proceed without a program_id to attach requirement_groups to."
        )
    program_id = program_result.data[0]["id"]
    print(f"program upserted: {program_id}")

    resolved_coursedog_ids = fetch_resolved_coursedog_group_ids(client, institution_id)
    print(f"course_catalog coursedog_group_id values known for SMU: {len(resolved_coursedog_ids)}")

    # Phase 1: upsert every requirement_groups row with parent_group_id left
    # null, so a child's parent always already has a real id by phase 2 --
    # order within this phase doesn't matter.
    group_rows = [
        to_requirement_group_row(group, program_id=program_id, catalog_year=catalog_year)
        for group in groups
    ]
    result = (
        client.table("requirement_groups")
        .upsert(group_rows, on_conflict="program_id,coursedog_rule_id")
        .execute()
    )
    id_by_rule_id = {row["coursedog_rule_id"]: row["id"] for row in result.data}
    print(f"requirement_groups upserted: {len(id_by_rule_id)}")

    # Phase 2: set parent_group_id on every child.
    unresolved_refs = 0
    parent_updates = 0
    for group in groups:
        parent_rule_id = group.get("parent_coursedog_rule_id")
        if parent_rule_id is None:
            continue
        child_id = id_by_rule_id[group["coursedog_rule_id"]]
        parent_id = id_by_rule_id[parent_rule_id]
        client.table("requirement_groups").update({"parent_group_id": parent_id}).eq(
            "id", child_id
        ).execute()
        parent_updates += 1
    print(f"parent_group_id set on {parent_updates} row(s)")

    # Options + courses: delete-then-insert per group (see module docstring
    # for why this isn't a native upsert).
    enumerated_group_ids = [
        id_by_rule_id[g["coursedog_rule_id"]]
        for g in groups
        if g.get("group_type") in ENUMERATED_GROUP_TYPES
    ]
    if enumerated_group_ids:
        client.table("requirement_group_options").delete().in_(
            "requirement_group_id", enumerated_group_ids
        ).execute()

    options_written = 0
    courses_written = 0
    for group in groups:
        if group.get("group_type") not in ENUMERATED_GROUP_TYPES:
            continue
        group_id = id_by_rule_id[group["coursedog_rule_id"]]
        option_rows, course_rows_by_option = build_option_rows(group, resolved_coursedog_ids)
        for option_row in option_rows:
            option_row["requirement_group_id"] = group_id
        inserted_options = (
            client.table("requirement_group_options").insert(option_rows).execute().data
            if option_rows
            else []
        )
        options_written += len(inserted_options)

        all_course_rows: list[dict[str, Any]] = []
        for option_result, course_rows in zip(inserted_options, course_rows_by_option):
            for course_row in course_rows:
                course_row = dict(course_row)
                course_row["requirement_group_option_id"] = option_result["id"]
                if course_row["unresolved_course_ref"] is not None:
                    unresolved_refs += 1
                all_course_rows.append(course_row)
        if all_course_rows:
            client.table("requirement_group_option_courses").insert(all_course_rows).execute()
            courses_written += len(all_course_rows)

    print(f"requirement_group_options written: {options_written}")
    print(f"requirement_group_option_courses written: {courses_written} "
          f"({unresolved_refs} unresolved_course_ref, flagged not failed)")


if __name__ == "__main__":
    raise SystemExit(main())
