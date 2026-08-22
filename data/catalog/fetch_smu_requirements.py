#!/usr/bin/env python3
"""Fetch SMU's degree-requirement skeleton for one program (v1: CS-BS only)
and normalize it into the shape import_requirement_groups.py consumes.

Dry-run is the default, matching every other script in this directory. Use
--write to save under data/catalog/smu/.

SOURCE. Same Coursedog "cm" surface as fetch_smu_catalog.py's courses/search
endpoint, but programs/search/$filters instead -- confirmed live this
session, same unauthenticated catalog.smu.edu Referer/Origin pattern, no
token/cookie/key involved.

SCOPE. This script resolves a program to import by (institution, code,
status=Active) rather than by Coursedog's versioned `_id` (e.g.
"CS-BS-2026-05-21") -- that _id embeds an effective-date suffix that changes
whenever SMU republishes the program, while `code` ("CS-BS") and
`programGroupId` ("CS-BS", identical to code on the one record checked this
session) stay stable across that. Hardcoding the _id would silently start
resolving to nothing the next time SMU republishes CS-BS.

It walks only the program's top-level "Requirements for the Major" group
(Coursedog requirementLevel "programRequirements"). CS-BS also publishes 7
specialization-track subplans (requirementLevel "subplan") in the same
payload; those are out of scope for this script by design -- see
planning-docs/degree-planner-spec.md §8 and the build prompt this script was
written from.

REQUISITES SHAPE (confirmed live this session against the CS-BS record,
_id "CS-BS-2026-05-21" as fetched). `requisites.requisitesSimple` is an
array of group objects. The one programRequirements-level group
("Requirements for the Major") has a `rules[]` array; each rule's
`condition` field is one of:

  completedAllOf       all courses in value.values[] required.
  completedAtLeastXOf  choose N of value.values[], N in a sibling
                        `restriction` field.
  freeformText          no structured course criteria at all -- `value` is
                        just a label string ("Complete the following:"),
                        and the entire constraint lives as prose in
                        `notes` (HTML). Confirmed on "Technical Electives"
                        and "Advanced Major Electives" -- both are
                        department+level-threshold, adviser-approved
                        rules with no fixed course set anywhere in the
                        payload.
  allOf / anyOf         compound: no flat `value` at all, instead a
                        `subRules[]` array of further rule objects
                        (recursively any of these five conditions).
                        Confirmed on "Lyle EDGE Curriculum" (allOf) and a
                        lab-science-sequence choice named "Two Courses" in
                        the source (anyOf).

value.values[] entries (for the two enumerated conditions) are
`{value: [coursedogGroupId, ...], logic: "and"|"or"}` -- an "and" pair is a
co-requisite bundle (e.g. lecture+lab) counted as one option, not two
alternatives.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

CATALOG_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = CATALOG_ROOT / "smu"

# ── Source configuration (shared constants with fetch_smu_catalog.py,
#    duplicated rather than imported -- each fetch script in this directory
#    is independently runnable and self-contained, same as
#    fetch_smu_catalog.py itself relative to scrape_approved_subjects.py) ──
SCHOOL_ID = "southernmethodist_peoplesoft_direct"
CATALOG_ID = "U7Oaufr8kCMqb9TIp0SF"
PROGRAMS_API_BASE = (
    f"https://app.coursedog.com/api/v1/cm/{SCHOOL_ID}/programs/search/%24filters"
)
CATALOG_SITE = "https://catalog.smu.edu"

REQUEST_HEADERS = {
    "content-type": "application/json",
    "accept": "application/json",
    "x-requested-with": "catalog",
    "Referer": f"{CATALOG_SITE}/",
    "Origin": CATALOG_SITE,
    "User-Agent": "GradusIQ-catalog-fetch/1.0 (academic-research)",
}

# Matches fetch_smu_catalog.py's EFFECTIVE_DATE -- the term-start date the
# catalog UI itself sends. Confirmed live this session to return the CS-BS
# record; not independently re-measured against the listLength deltas
# fetch_smu_catalog.py documents for the courses endpoint, since programs
# search was only ever run scoped to a single program this session, not the
# full unfiltered set.
EFFECTIVE_DATE = "2026-08-24"

CATALOG_YEAR = "2026-2027"  # Matches fetch_smu_catalog.py's constant.

# v1 target program. A later multi-program version of this script would make
# this a CLI argument list instead of a single default.
DEFAULT_PROGRAM_CODE = "CS-BS"

# requirementLevel value for the group this script imports. "subplan" (the
# specialization tracks) is deliberately not walked -- see module docstring.
TARGET_REQUIREMENT_LEVEL = "programRequirements"

# Coursedog rule `condition` -> our group_type, matching
# requirement_groups.group_type's check constraint
# (supabase/migrations/20260818130000_smu_requirement_skeleton.sql).
CONDITION_TO_GROUP_TYPE = {
    "completedAllOf": "enumerated_all",
    "completedAtLeastXOf": "enumerated_at_least_n",
    # "Choose any one of these" -- structurally identical to
    # completedAtLeastXOf (same value.condition="courses" / value.values[]
    # shape, no extra fields), just without a `restriction` field, since the
    # condition name itself already fixes n_required at 1. Confirmed live:
    # "Advanced/Domain Specific Use/Design of AI", "Leadership and
    # Mentoring", "Experiential Learning" (CS-BS).
    "completedAnyOf": "enumerated_at_least_n",
    # A fixed set of options (lecture+lab pairs, a single course, etc.)
    # where the requirement is satisfied by accumulating minCredits worth
    # of completed options, not by completing every option -- genuinely
    # different satisfaction semantics from completedAllOf's enumerated_all
    # (confirmed the hard way: the requirement-satisfaction engine
    # originally mapped this to enumerated_all too and had to special-case
    # it via a hardcoded coursedog_rule_id allowlist before this group_type
    # existed -- supabase/migrations/20260819160000_requirement_groups_
    # credit_threshold_group_type.sql). Credit hours come directly off the
    # rule (minCredits/maxCredits) rather than a "(N Credit Hours)" name
    # suffix -- see the minCredits handling below. Confirmed live, one
    # occurrence: "Content Area 4, Physics" (CS-BS).
    "completeVariableCoursesAndVariableCredits": "enumerated_credit_threshold",
    "allOf": "compound_all",
    "anyOf": "compound_any",
    "freeformText": "freeform",
}

CREDIT_HOURS_IN_NAME = re.compile(r"\((\d+)(?:-\d+)?\s*Credit Hours?\)", re.IGNORECASE)


def credit_hours_from_name(name: str) -> int | None:
    """Parse the lower bound out of a name like "Technical Electives (9 Credit
    Hours)" or "Lyle EDGE Curriculum (9-13 Credit Hours)". None for names with
    no such suffix (e.g. the "Two Courses" compound rule) -- that is the
    expected, correct result for those, not a parsing failure.
    """
    match = CREDIT_HOURS_IN_NAME.search(name or "")
    return int(match.group(1)) if match else None


def normalize_rule(
    rule: dict[str, Any], parent_coursedog_rule_id: str | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (list of normalized group dicts, list of warnings) for one
    Coursedog rule object, recursing into subRules for compound rules.

    A single rule can produce more than one normalized group: a compound
    rule (allOf/anyOf) yields its own row plus one row per subRule.
    """
    warnings: list[str] = []
    condition = rule.get("condition")
    group_type = CONDITION_TO_GROUP_TYPE.get(condition)
    coursedog_rule_id = rule.get("id")
    name = rule.get("name") or ""

    if group_type is None:
        warnings.append(
            f"unknown rule condition {condition!r} on rule id={coursedog_rule_id!r} "
            f"name={name!r} -- skipping this rule, schema/parser needs a 6th "
            f"group_type to cover it"
        )
        return [], warnings

    base = {
        "coursedog_rule_id": coursedog_rule_id,
        "parent_coursedog_rule_id": parent_coursedog_rule_id,
        "name": name,
        "group_type": group_type,
        "n_required": None,
        "credit_hours_required": credit_hours_from_name(name),
        "notes_html": rule.get("notes") or None,
        "requires_manual_definition": group_type == "freeform",
        "options": [],
    }

    # completeVariableCoursesAndVariableCredits provides credit hours
    # directly on the rule (minCredits/maxCredits) rather than via the
    # "(N Credit Hours)" name suffix credit_hours_from_name() parses.
    # Only minCredits is captured -- credit_hours_required is a single int
    # column (§8.2), not a range, and there's exactly one live example to
    # generalize from (Content Area 4, Physics: minCredits=7, maxCredits=8).
    # maxCredits is intentionally discarded for v1, not an oversight:
    # revisit if the scheduler ever needs to represent a credit range rather
    # than one required value.
    if condition == "completeVariableCoursesAndVariableCredits":
        min_credits = rule.get("minCredits")
        if isinstance(min_credits, int):
            base["credit_hours_required"] = min_credits

    groups = [base]

    if group_type == "enumerated_at_least_n":
        if condition == "completedAnyOf":
            # No `restriction` field on these rules -- the condition name
            # itself fixes n_required at 1, unlike completedAtLeastXOf which
            # carries the count explicitly.
            base["n_required"] = 1
        else:
            restriction = rule.get("restriction")
            if not isinstance(restriction, int) or restriction < 1:
                warnings.append(
                    f"rule id={coursedog_rule_id!r} name={name!r} is "
                    f"completedAtLeastXOf but restriction is {restriction!r} "
                    f"(expected a positive int) -- skipping this rule"
                )
                return [], warnings
            base["n_required"] = restriction

    if group_type in ("enumerated_all", "enumerated_at_least_n", "enumerated_credit_threshold"):
        value = rule.get("value") or {}
        if value.get("condition") != "courses" or not isinstance(
            value.get("values"), list
        ):
            warnings.append(
                f"rule id={coursedog_rule_id!r} name={name!r} has condition "
                f"{condition!r} but value.condition is "
                f"{value.get('condition')!r} (expected 'courses') -- "
                f"skipping this rule"
            )
            return [], warnings
        for index, entry in enumerate(value["values"]):
            course_ids = entry.get("value")
            logic = entry.get("logic")
            if not isinstance(course_ids, list) or logic not in ("and", "or"):
                warnings.append(
                    f"rule id={coursedog_rule_id!r} name={name!r} "
                    f"values[{index}] is malformed ({entry!r}) -- skipping "
                    f"this option, not the whole rule"
                )
                continue
            base["options"].append(
                {
                    "option_index": index,
                    "logic": logic,
                    "coursedog_group_ids": [str(cid) for cid in course_ids],
                }
            )

    if group_type in ("compound_all", "compound_any"):
        sub_rules = rule.get("subRules")
        if not isinstance(sub_rules, list):
            warnings.append(
                f"rule id={coursedog_rule_id!r} name={name!r} has condition "
                f"{condition!r} but subRules is {sub_rules!r} (expected a "
                f"list) -- no children imported for this compound rule"
            )
        else:
            for sub_rule in sub_rules:
                child_groups, child_warnings = normalize_rule(
                    sub_rule, parent_coursedog_rule_id=coursedog_rule_id
                )
                groups.extend(child_groups)
                warnings.extend(child_warnings)

    return groups, warnings


def parse_requisites(program: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Walk one program record's requisites.requisitesSimple and return
    (normalized groups, warnings). Only requirementLevel ==
    TARGET_REQUIREMENT_LEVEL entries are walked -- see module docstring.
    """
    warnings: list[str] = []
    requisites = program.get("requisites") or {}
    simple = requisites.get("requisitesSimple")
    if not isinstance(simple, list):
        warnings.append(
            "requisites.requisitesSimple is missing or not a list -- payload "
            "shape has changed since this script was written against a live "
            "sample; nothing parsed"
        )
        return [], warnings

    target_entries = [
        entry
        for entry in simple
        if isinstance(entry, dict) and entry.get("requirementLevel") == TARGET_REQUIREMENT_LEVEL
    ]
    # Narративe/text-only entries (type "Narrative Text") also carry
    # requirementLevel "programRequirements" but have no rules -- confirmed
    # live (one such entry precedes "Requirements for the Major" in CS-BS's
    # payload). Skip those rather than treating an empty rules list as a
    # warning-worthy anomaly.
    rule_bearing = [
        entry for entry in target_entries if isinstance(entry.get("rules"), list) and entry["rules"]
    ]

    if not rule_bearing:
        warnings.append(
            f"no requirementLevel={TARGET_REQUIREMENT_LEVEL!r} entry with a "
            f"non-empty rules[] found -- payload shape has changed since "
            f"this script was written, or this program genuinely has none"
        )
        return [], warnings

    if len(rule_bearing) > 1:
        warnings.append(
            f"{len(rule_bearing)} requirementLevel={TARGET_REQUIREMENT_LEVEL!r} "
            f"entries with rules found (expected exactly 1, "
            f"'Requirements for the Major' on CS-BS) -- importing all of "
            f"them, but confirm this is intended for whatever program was "
            f"just fetched"
        )

    groups: list[dict[str, Any]] = []
    for entry in rule_bearing:
        for rule in entry["rules"]:
            rule_groups, rule_warnings = normalize_rule(rule, parent_coursedog_rule_id=None)
            groups.extend(rule_groups)
            warnings.extend(rule_warnings)

    return groups, warnings


def fetch_program(program_code: str) -> dict[str, Any]:
    """POST to programs/search/$filters for the one Active program matching
    `code`. Raises if the request fails or doesn't return exactly one row.
    """
    url = (
        f"{PROGRAMS_API_BASE}?catalogId={CATALOG_ID}&skip=0&limit=5"
        f"&orderBy=name&ignoreEffectiveDating=false&ignoreTotalCount=false"
        f"&effectiveDatesRange={EFFECTIVE_DATE}%2C{EFFECTIVE_DATE}"
    )
    # No `columns` projection here, unlike fetch_smu_catalog.py's courses
    # call: that projection was measured and confirmed live for the courses
    # endpoint; the equivalent for programs was not independently verified
    # this session (the live check fetched the full default projection, 77
    # fields, and that's what's relied on below). Add a columns param only
    # after confirming it doesn't drop or reshape `requisites`.
    body = {
        "condition": "AND",
        "filters": [
            {
                "id": "kfrDFtKQ",
                "condition": "and",
                "filters": [
                    {
                        "id": "status-program",
                        "condition": "field",
                        "name": "status",
                        "inputType": "select",
                        "group": "program",
                        "type": "is",
                        "value": "Active",
                    },
                    {
                        "id": "code-program",
                        "condition": "field",
                        "name": "code",
                        "inputType": "text",
                        "group": "program",
                        "type": "is",
                        "value": program_code,
                    },
                ],
            }
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=REQUEST_HEADERS,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed host
        status = response.status
        body = response.read()
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Coursedog returned non-JSON response, status={status} -- "
            f"expected a JSON body from {PROGRAMS_API_BASE}, got "
            f"{len(body)} bytes that failed to parse ({exc})"
        ) from exc

    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1:
        raise RuntimeError(
            f"expected exactly 1 Active program with code={program_code!r}, "
            f"got {len(data) if isinstance(data, list) else 'a non-list'} -- "
            f"stopping rather than guessing which record to use"
        )
    return data[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"save normalized JSON under {OUTPUT_ROOT}; without it, fetch and report only",
    )
    parser.add_argument(
        "--program-code",
        default=DEFAULT_PROGRAM_CODE,
        help=f"Coursedog program `code` to fetch (default: {DEFAULT_PROGRAM_CODE})",
    )
    parser.add_argument(
        "--raw-cache",
        type=Path,
        default=None,
        help="path to a raw-response cache; read from it if present, else write it after fetching",
    )
    args = parser.parse_args()

    print(f"Mode: {'write' if args.write else 'dry-run (nothing saved)'}")
    print(f"Program code: {args.program_code}")
    print(f"Source: {PROGRAMS_API_BASE}")
    print()

    from_cache = bool(args.raw_cache and args.raw_cache.exists())
    if from_cache:
        program = json.loads(args.raw_cache.read_text(encoding="utf-8"))
        print(f"Loaded program record from cache {args.raw_cache} (no network call)")
    else:
        try:
            program = fetch_program(args.program_code)
        except urllib.error.HTTPError as exc:
            print(f"ERROR: HTTP {exc.code}: {exc.reason}", file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"ERROR: network failure: {exc.reason}", file=sys.stderr)
            return 1
        if args.raw_cache:
            args.raw_cache.parent.mkdir(parents=True, exist_ok=True)
            args.raw_cache.write_text(json.dumps(program), encoding="utf-8")
            print(f"Raw response cached to {args.raw_cache}")

    print(
        f"\nFetched: {program.get('catalogDisplayName')!r} "
        f"({program.get('code')}, id={program.get('_id')})"
    )

    groups, warnings = parse_requisites(program)

    print(f"\nGroups parsed: {len(groups)}")
    by_type = Counter(g["group_type"] for g in groups)
    for group_type in sorted(by_type):
        print(f"  {group_type:<22} {by_type[group_type]:>3}")

    print(f"\nWarnings: {len(warnings)}")
    for warning in warnings:
        print(f"  {warning}")

    output = {
        "program": {
            "coursedog_program_id": program.get("_id"),
            "program_group_id": program.get("programGroupId"),
            "code": program.get("code"),
            "name": program.get("catalogDisplayName"),
            "degree_designation": program.get("degreeDesignation"),
        },
        "catalog_year": CATALOG_YEAR,
        "groups": groups,
    }

    if not args.write:
        print(f"\nDRY RUN — nothing written. Re-run with --write to save under {OUTPUT_ROOT}.")
        return 0

    if warnings:
        print(
            "\nERROR: refusing to write with unresolved warnings above -- fix "
            "the parser or the target program before writing.",
            file=sys.stderr,
        )
        return 1

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_ROOT / f"requirements_{args.program_code.lower()}.json"
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"\nWrote {out_path.relative_to(CATALOG_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
