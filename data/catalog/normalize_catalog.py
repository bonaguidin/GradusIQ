#!/usr/bin/env python3
"""Normalize existing TAMU catalog JSON files with derived foundation fields.

Dry-run is the default. Use --write to update the source JSON files.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any


CATALOG_ROOT = Path(__file__).resolve().parent
EXCLUDED_DIRS = {"reference", "students"}
DERIVED_FIELDS = [
    "prefix",
    "number",
    "course_level",
    "credit_min",
    "credit_max",
    "is_variable_credit",
    "ucc_attributes",
    "tccns",
    "cross_listings",
    "repeatability",
    "campuses",
    "prerequisite_courses",
    "restrictions",
]
BASE_FIELD_ORDER = [
    "code",
    "title",
    "credit_hours",
    "description",
    "prerequisites",
    "department",
    "satisfies_ucc",
]
COURSE_CODE_RE = re.compile(r"\b([A-Z]{2,5})\s+([0-9]{3}[A-Z]?)\b")
RANGE_CREDITS_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$")
CODE_RE = re.compile(r"^\s*([A-Z]{2,5})\s+([0-9]{3}[A-Z]?)\s*$")


def iter_catalog_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.json"):
        if EXCLUDED_DIRS.intersection(path.relative_to(root).parts):
            continue
        files.append(path)
    return sorted(files)


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        cleaned = " ".join(value.strip().split())
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            unique.append(cleaned)
    return unique


def parse_code(code: Any) -> tuple[str | None, str | None]:
    if not isinstance(code, str):
        return None, None
    match = CODE_RE.match(code)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def derive_course_level(number: str | None) -> int | None:
    if not number or not number[0].isdigit():
        return None
    level = int(number[0]) * 100
    return level if level in {100, 200, 300, 400} else None


def parse_credits(credit_hours: Any) -> tuple[float | int | None, float | int | None, bool]:
    if isinstance(credit_hours, (int, float)) and not isinstance(credit_hours, bool):
        return credit_hours, credit_hours, False
    if isinstance(credit_hours, str):
        range_match = RANGE_CREDITS_RE.match(credit_hours)
        if range_match:
            return normalize_number(range_match.group(1)), normalize_number(range_match.group(2)), True
        try:
            parsed = normalize_number(credit_hours)
            return parsed, parsed, False
        except ValueError:
            return None, None, False
    return None, None, False


def normalize_number(value: str) -> float | int:
    parsed = float(value)
    if parsed.is_integer():
        return int(parsed)
    return parsed


def extract_ucc_attributes(course: dict[str, Any]) -> list[str]:
    value = course.get("satisfies_ucc")
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def extract_tccns(description: Any) -> list[str]:
    if not isinstance(description, str):
        return []
    match = re.match(r"^\s*\(([^)]*)\)", description)
    if not match:
        return []
    return unique_preserve_order(
        [f"{prefix} {number}" for prefix, number in COURSE_CODE_RE.findall(match.group(1))]
    )


def extract_cross_listings(prerequisites: Any) -> list[str]:
    if not isinstance(prerequisites, str):
        return []
    match = re.search(r"Cross Listing:\s*(.*?)(?:\.|$)", prerequisites, flags=re.IGNORECASE)
    if not match:
        return []
    return unique_preserve_order(
        [f"{prefix} {number}" for prefix, number in COURSE_CODE_RE.findall(match.group(1))]
    )


# Abbreviations whose internal period must not always be read as a sentence
# terminator by split_sentences() below -- but only when what immediately
# follows is a lowercase word, the actual signal that this is a same-
# sentence continuation rather than a new sentence. Confirmed live, SMU
# CCPA 5315/5320/5325: "...enrollment in the B.A. in corporate communication
# and public affairs..." was being split right after "B.A.", leaving the
# lowercase continuation as its own bogus "sentence" starting mid-phrase.
#
# Suppressing the split unconditionally after these abbreviations is too
# aggressive, though -- confirmed live against SPAN 3356/4378, where
# "...Hispanic groups in the U.S. Prerequisite: C- or better..." is a real
# sentence boundary (the next sentence starts uppercase, as real sentences
# do); masking "U.S." there unconditionally swallowed a genuine prerequisite
# sentence into the description, a regression this lowercase check exists
# specifically to avoid.
#
# Add to this list only on a confirmed real case, the same way
# PERMISSION_PHRASE in fetch_smu_catalog.py grew from actual audited rows
# rather than a guessed general list.
SENTENCE_ABBREVIATIONS = ("B.A.", "B.S.", "M.A.", "M.S.", "Ph.D.", "U.S.")
_ABBREVIATION_PERIOD_MASK = "\x00"
_FALSE_ABBREVIATION_BOUNDARY = re.compile(
    "(?:" + "|".join(re.escape(a) for a in SENTENCE_ABBREVIATIONS) + r")(?=\s+[a-z])"
)


def split_sentences(text: str) -> list[str]:
    masked = _FALSE_ABBREVIATION_BOUNDARY.sub(
        lambda m: m.group(0).replace(".", _ABBREVIATION_PERIOD_MASK), text
    )
    chunks = re.split(r"(?<=[.!?])\s+", masked)
    return [
        " ".join(chunk.replace(_ABBREVIATION_PERIOD_MASK, ".").strip().split())
        for chunk in chunks
        if chunk.strip()
    ]


def extract_repeatability(description: Any, prerequisites: Any) -> str | None:
    phrases = ("may be repeated", "may be taken", "up to", "for credit")
    text_parts = [value for value in (description, prerequisites) if isinstance(value, str)]
    for text in text_parts:
        for sentence in split_sentences(text):
            lower = sentence.lower()
            if any(phrase in lower for phrase in phrases):
                return sentence
    return None


def extract_campuses(description: Any, prerequisites: Any) -> list[str]:
    text = " ".join(value for value in (description, prerequisites) if isinstance(value, str))
    campuses = []
    for campus in ("Galveston", "Qatar"):
        if re.search(rf"\b{re.escape(campus)}\b", text, flags=re.IGNORECASE):
            campuses.append(campus)
    return campuses


def extract_prerequisite_courses(prerequisites: Any) -> list[str]:
    if not isinstance(prerequisites, str):
        return []
    return unique_preserve_order(
        [f"{prefix} {number}" for prefix, number in COURSE_CODE_RE.findall(prerequisites)]
    )


def extract_restrictions(prerequisites: Any) -> list[str]:
    if not isinstance(prerequisites, str):
        return []

    patterns = [
        r"\b(?:freshman|sophomore|junior|senior)(?:\s+or\s+(?:freshman|sophomore|junior|senior))*\s+classification\b",
        r"\bapproval of (?:the )?department head\b",
        r"\bapproval of (?:the )?instructor\b",
        r"\b[A-Za-z &/-]+ majors only\b",
        r"\bmajors only\b",
        r"\bgrade of C or better\b",
    ]
    matches: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, prerequisites, flags=re.IGNORECASE):
            matches.append(match.group(0).strip(" ;,."))
    return unique_preserve_order(matches)


def derive_fields(course: dict[str, Any]) -> dict[str, Any]:
    prefix, number = parse_code(course.get("code"))
    credit_min, credit_max, is_variable_credit = parse_credits(course.get("credit_hours"))
    return {
        "prefix": prefix,
        "number": number,
        "course_level": derive_course_level(number),
        "credit_min": credit_min,
        "credit_max": credit_max,
        "is_variable_credit": is_variable_credit,
        "ucc_attributes": extract_ucc_attributes(course),
        "tccns": extract_tccns(course.get("description")),
        "cross_listings": extract_cross_listings(course.get("prerequisites")),
        "repeatability": extract_repeatability(course.get("description"), course.get("prerequisites")),
        "campuses": extract_campuses(course.get("description"), course.get("prerequisites")),
        "prerequisite_courses": extract_prerequisite_courses(course.get("prerequisites")),
        "restrictions": extract_restrictions(course.get("prerequisites")),
    }


def ordered_course(course: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    for key in BASE_FIELD_ORDER + DERIVED_FIELDS:
        if key in course:
            ordered[key] = course[key]
    for key in sorted(course):
        if key not in ordered:
            ordered[key] = course[key]
    return ordered


def normalize_course(course: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    normalized = deepcopy(course)
    derived = derive_fields(course)
    changed_fields: list[str] = []
    warnings: list[str] = []

    if derived["prefix"] is None or derived["number"] is None:
        warnings.append(f"unparseable code: {course.get('code')!r}")
    if derived["credit_min"] is None or derived["credit_max"] is None:
        warnings.append(f"unparseable credit_hours for {course.get('code')!r}: {course.get('credit_hours')!r}")

    for key, value in derived.items():
        if key not in normalized or normalized.get(key) != value:
            normalized[key] = value
            changed_fields.append(key)

    return ordered_course(normalized), changed_fields, warnings


def load_courses(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{path} is not a top-level JSON array")
    for index, course in enumerate(data):
        if not isinstance(course, dict):
            raise ValueError(f"{path}[{index}] is not a JSON object")
    return data


def duplicate_codes(courses: list[dict[str, Any]]) -> list[str]:
    counts = Counter(course.get("code") for course in courses if course.get("code"))
    return sorted(str(code) for code, count in counts.items() if count > 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write normalized data back to catalog JSON files")
    args = parser.parse_args()

    files = iter_catalog_files(CATALOG_ROOT)
    field_counts: Counter[str] = Counter()
    parsing_warnings: list[str] = []
    duplicate_warnings: list[str] = []
    total_courses = 0
    files_with_changes = 0

    for path in files:
        courses = load_courses(path)
        total_courses += len(courses)
        normalized_courses: list[dict[str, Any]] = []
        file_changed = False

        for course in courses:
            normalized, changed_fields, warnings = normalize_course(course)
            normalized_courses.append(normalized)
            if changed_fields:
                file_changed = True
                field_counts.update(changed_fields)
            for warning in warnings:
                parsing_warnings.append(f"{path.relative_to(CATALOG_ROOT)}: {warning}")

        duplicates = duplicate_codes(courses)
        for code in duplicates:
            duplicate_warnings.append(f"{path.relative_to(CATALOG_ROOT)}: duplicate code {code}")

        if file_changed:
            files_with_changes += 1
            if args.write:
                with path.open("w", encoding="utf-8") as handle:
                    json.dump(normalized_courses, handle, indent=2, ensure_ascii=False)
                    handle.write("\n")

    mode = "write" if args.write else "dry-run"
    print(f"Mode: {mode}")
    print(f"Total files scanned: {len(files)}")
    print(f"Total courses scanned: {total_courses}")
    print(f"Files with changes: {files_with_changes}")
    print("Fields added or updated:")
    if field_counts:
        for field in DERIVED_FIELDS:
            print(f"  {field}: {field_counts.get(field, 0)}")
    else:
        print("  none")
    print(f"Parsing warnings: {len(parsing_warnings)}")
    for warning in parsing_warnings[:25]:
        print(f"  {warning}")
    if len(parsing_warnings) > 25:
        print(f"  ... {len(parsing_warnings) - 25} more")
    print(f"Duplicate warnings: {len(duplicate_warnings)}")
    for warning in duplicate_warnings[:25]:
        print(f"  {warning}")
    if len(duplicate_warnings) > 25:
        print(f"  ... {len(duplicate_warnings) - 25} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
