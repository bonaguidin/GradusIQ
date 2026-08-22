#!/usr/bin/env python3
"""Fetch the SMU undergraduate course catalog and normalize it to the TAMU shape.

Dry-run is the default: the catalog is fetched and reported on, but nothing is
written under data/catalog/smu/. Use --write to save.

SOURCE. SMU's catalog is a Coursedog-backed Nuxt SPA, not the CourseLeaf HTML
TAMU publishes, so none of the HTML scraping in this directory applies. The SPA
hydrates from a JSON endpoint that is open to anyone sending a catalog.smu.edu
Referer/Origin -- there is no token, cookie or API key involved. That endpoint
is what this script calls.

FIELD DERIVATION. The per-course derivations (course_level, repeatability,
restrictions, ...) are reused from normalize_catalog.py wherever the rule is
institution-agnostic. Three rules are TAMU-specific and are overridden here;
each override says why at its definition:

  * course-code regex -- TAMU is "BIOL 100" (3 digits, space); SMU is
    "ACCT2301" (4 digits, no space) in the `code` field.
  * campuses          -- TAMU's list is Galveston/Qatar.
  * source_url        -- TAMU's per-prefix course-description page.

Rules left alone because they are harmless on SMU data and simply yield empty
values (tccns, cross_listings, ucc_attributes) are noted in build_course().
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

CATALOG_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = CATALOG_ROOT / "smu"

# Import the shared derivations rather than restating them.
sys.path.insert(0, str(CATALOG_ROOT))
import normalize_catalog as nc  # noqa: E402

# ── Source configuration ────────────────────────────────────────────────────
SCHOOL_ID = "southernmethodist_peoplesoft_direct"
CATALOG_ID = "U7Oaufr8kCMqb9TIp0SF"
API_BASE = (
    f"https://app.coursedog.com/api/v1/cm/{SCHOOL_ID}/courses/search/%24filters"
)
CATALOG_SITE = "https://catalog.smu.edu"

# The endpoint answers 401 without these two. It is a referer check, not
# authentication: no token, cookie or key is sent, and the data served is the
# same public catalog the site renders to anonymous visitors.
REQUEST_HEADERS = {
    "content-type": "application/json",
    "accept": "application/json",
    "x-requested-with": "catalog",
    "Referer": f"{CATALOG_SITE}/",
    "Origin": CATALOG_SITE,
    "User-Agent": "GradusIQ-catalog-fetch/1.0 (academic-research)",
}

# The filter the catalog UI itself submits: active, catalog-printable courses.
REQUEST_BODY = {
    "condition": "AND",
    "filters": [
        {
            "id": "kfrDFtKQ",
            "condition": "and",
            "filters": [
                {
                    "id": "status-course",
                    "condition": "field",
                    "name": "status",
                    "inputType": "select",
                    "group": "course",
                    "type": "is",
                    "value": "Active",
                },
                {
                    "id": "catalogPrint-course",
                    "condition": "field",
                    "name": "catalogPrint",
                    "inputType": "boolean",
                    "group": "course",
                    "type": "is",
                    "value": True,
                    "customField": False,
                },
            ],
        }
    ],
}

# Only the fields the target shape needs. The server's default projection is
# 87 fields per course, most of them SIS workflow metadata.
#
# courseGroupId: the internal Coursedog ID the CS-BS degree-requirements
# payload references its required courses by (e.g. "0045691" -> CS 1341),
# confirmed by direct cross-check in the SMU requirement-ID resolution audit.
# It was in every raw record all along; requesting it here is what makes it
# reach build_course() below instead of being silently dropped by the column
# projection. Column-in-storage lands in the same commit; the ID->course-code
# join itself is a separate, later change.
COLUMNS = ",".join(
    [
        "code",
        "subjectCode",
        "courseNumber",
        "name",
        "longName",
        "description",
        "departments",
        "college",
        "career",
        "credits",
        "requisites",
        "status",
        "courseGroupId",
    ]
)

UNDERGRADUATE_CAREER = "Undergraduate"
CATALOG_YEAR = "2026-2027"  # Verified against the rendered catalog.smu.edu page.

# EFFECTIVE DATING -- do not drop this. Coursedog filters courses by an
# effective-date window, and omitting the range makes the server default to
# "today", which is NOT what the catalog site itself shows. Measured directly:
#
#   (no range, ignoreEffectiveDating=false)          -> listLength 6529
#   effectiveDatesRange=2026-08-24,2026-08-24        -> listLength 6665
#   ignoreEffectiveDating=true                       -> listLength 52584
#
# 6665 is the number the site's own "Export all results as CSV" produces, and
# 2026-08-24 is the term start the catalog UI sends. The 136-row difference is
# real catalog content: 241 courses that take effect on the term date and 105
# that lapse before it. The last value, 52584, is every historical version of
# every course, which is not what we want.
EFFECTIVE_DATE = "2026-08-24"

# ── SMU-specific overrides of normalize_catalog rules ───────────────────────

# TAMU: "BIOL 100" -- 3 digits, mandatory space. SMU: "ACCT2301" in `code`,
# but "ACCT 2301" when referenced inside description prose. Accept both.
SMU_CODE_IN_TEXT = re.compile(r"\b([A-Z]{2,5})\s?(\d{4}[A-Z]?)\b")

# TAMU's list is Galveston/Qatar. These are SMU's non-Dallas locations.
SMU_CAMPUSES = ("Taos", "Plano", "Legacy")

# Sentences that belong in `prerequisites` rather than `description`. SMU has
# no separate prerequisite field -- `requisites` is present but empty on every
# record sampled -- so the prose carries it, exactly as TAMU's scraper split
# it out of the description HTML.
REQUISITE_SENTENCE = re.compile(
    r"^\s*(?:pre-?requisite|co-?requisite|prerequisites|corequisites|restricted to|"
    r"restriction|may not be taken)",
    re.IGNORECASE,
)

# Permission/approval phrasing that gates enrollment the same way
# "Restricted to..." does, but doesn't start the sentence the way
# REQUISITE_SENTENCE's patterns do -- e.g. "An opportunity for the advanced
# undergraduate student to undertake independent investigation, design, or
# development. Written permission of the supervising faculty member is
# required before registration." The second sentence is entirely an
# eligibility gate, but "Written" isn't one of REQUISITE_SENTENCE's anchors.
# Confirmed against 48 live SMU rows this missed (prior audit): CS 41xx-49xx
# independent-study sections ("Written permission ... is required before
# registration"), ARHS 4302 ("Instructor permission required."), and the
# ENGR 3390/4390 family ("...guidance from a Dean's Office-approved faculty
# member."). `dean.s` rather than `dean's` because the source text uses a
# curly apostrophe (U+2019), not a straight one.
PERMISSION_PHRASE = re.compile(
    r"permission required|instructor permission|written permission|"
    r"dean.s office[- ]approved",
    re.IGNORECASE,
)


def is_requisite_sentence(sentence: str) -> bool:
    return bool(REQUISITE_SENTENCE.match(sentence) or PERMISSION_PHRASE.search(sentence))

# college string -> directory slug. SMU's `college` arrives as "COX - Cox
# School of Business"; the leading token is the stable part.
# Codes confirmed against the live undergraduate result set, not guessed.
# MOODY never appears here -- Moody is graduate-only, as expected -- and no
# LAW-coded row survives the undergraduate filter either; Law is its own
# career value entirely.
SCHOOL_SLUGS = {
    "COX": "cox",             # Cox School of Business
    "DC": "dedman",           # Dedman College
    "ARTS": "meadows",        # Meadows School of the Arts
    "SEAS": "lyle",           # Lyle School of Engineering
    "DESS": "simmons",        # Simmons School of Education & Human Development
    "THEO": "perkins",        # Perkins School of Theology
    "PROVO": "provost",       # Provost's office: cross-school offerings
    "IC": "international_center",
    "MOODY": "moody",         # graduate-only; kept so a future change is visible
    "LAW": "law",
}


def school_slug(college: Any) -> str:
    if not isinstance(college, str) or not college.strip():
        return "unassigned"
    token = college.split("-")[0].strip().upper()
    if token in SCHOOL_SLUGS:
        return SCHOOL_SLUGS[token]
    slug = re.sub(r"[^a-z0-9]+", "_", college.lower()).strip("_")
    return slug or "unassigned"


def split_description(text: Any) -> tuple[str, str | None]:
    """Return (description, prerequisites) split out of SMU's single prose blob."""
    if not isinstance(text, str) or not text.strip():
        return "", None
    sentences = nc.split_sentences(text)
    body = [s for s in sentences if not is_requisite_sentence(s)]
    reqs = [s for s in sentences if is_requisite_sentence(s)]
    description = " ".join(body).strip()
    # description is NOT NULL downstream. If a course is nothing but its
    # prerequisite/permission sentence(s) -- body is empty because every
    # sentence matched is_requisite_sentence() -- keep the original text as
    # description rather than emitting "".
    #
    # EDGE CASE DECISION: in that same situation, prerequisites is set to
    # None, not reqs. When body still has content, "moving" the requisite
    # sentence(s) out genuinely cleans up description into standalone
    # course-content prose (the common case: an independent-study
    # boilerplate sentence plus a separate permission clause). When body is
    # empty, there is no other content to clean up -- the requisite
    # sentence(s) ARE the whole description, so "moving" them would just
    # duplicate the same text into both fields rather than producing a
    # cleaner description the way it does in the multi-sentence case.
    # Confirmed live: ENGR 3192/3390/3391/3392, whose entire description is
    # one "Dean's Office-approved" sentence -- description alone, unsplit,
    # is the correct output, not a duplicate copy in prerequisites too.
    if not description:
        description = " ".join(" ".join(text.split()).split()).strip()
        return description, None
    return description, (" ".join(reqs).strip() or None)


def codes_in(text: Any) -> list[str]:
    if not isinstance(text, str):
        return []
    return nc.unique_preserve_order(
        [f"{prefix} {number}" for prefix, number in SMU_CODE_IN_TEXT.findall(text)]
    )


def smu_campuses(description: Any, prerequisites: Any) -> list[str]:
    text = " ".join(v for v in (description, prerequisites) if isinstance(v, str))
    return [c for c in SMU_CAMPUSES if re.search(rf"\b{re.escape(c)}\b", text, re.I)]


def department_name(record: dict[str, Any]) -> str:
    """Human-readable department, e.g. "Accounting" rather than "ACCT"."""
    departments = record.get("departments")
    if isinstance(departments, list) and departments:
        first = departments[0]
        if isinstance(first, dict):
            for key in ("catalogDisplayName", "displayName", "name", "id"):
                value = first.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        if isinstance(first, str) and first.strip():
            return first.strip()
    college = record.get("college")
    if isinstance(college, str) and college.strip():
        return college.split("-", 1)[-1].strip()
    return str(record.get("subjectCode") or "").strip()


def credit_bounds(record: dict[str, Any]) -> tuple[int | float | None, int | float | None]:
    hours = ((record.get("credits") or {}).get("creditHours") or {})
    lo, hi = hours.get("min"), hours.get("max")
    out: list[int | float | None] = []
    for value in (lo, hi):
        if isinstance(value, bool) or value is None:
            out.append(None)
        elif isinstance(value, (int, float)):
            out.append(int(value) if float(value).is_integer() else value)
        elif isinstance(value, str):
            try:
                out.append(nc.normalize_number(value))
            except ValueError:
                out.append(None)
        else:
            out.append(None)
    return out[0], out[1]


def build_course(record: dict[str, Any], source_last_checked: str) -> tuple[dict[str, Any], list[str]]:
    """Map one Coursedog record onto the 22-field TAMU catalog shape."""
    warnings: list[str] = []

    prefix = (record.get("subjectCode") or "").strip().upper()
    number = str(record.get("courseNumber") or "").strip()
    if not prefix or not number:
        warnings.append(f"unparseable code: {record.get('code')!r}")
    # Space-separated to match TAMU's "BIOL 100" convention, which is also how
    # SMU's own description prose writes course references.
    code = f"{prefix} {number}".strip()

    title = record.get("longName") or record.get("name") or ""
    description, prerequisites = split_description(record.get("description"))
    credit_min, credit_max = credit_bounds(record)
    if credit_min is None or credit_max is None:
        warnings.append(f"missing creditHours for {code!r}")

    credit_hours: Any
    if credit_min is None or credit_max is None:
        credit_hours = None
    elif credit_min == credit_max:
        credit_hours = credit_min
    else:
        credit_hours = f"{credit_min}-{credit_max}"

    course = {
        "code": code,
        "title": title.strip(),
        "credit_hours": credit_hours,
        "description": description,
        "prerequisites": prerequisites,
        "department": department_name(record),
        "prefix": prefix,
        "number": number,
        # Reused unchanged: SMU's 4-digit numbering also encodes level in the
        # leading digit (2301 -> 200), and 5xxx+ correctly yields null just as
        # TAMU's 6xx/7xx graduate courses do.
        "course_level": nc.derive_course_level(number),
        "credit_min": credit_min,
        "credit_max": credit_max,
        "is_variable_credit": credit_min != credit_max,
        # TAMU-only concepts. Kept for shape parity; empty on SMU by design:
        # ucc_attributes is TAMU's University Core Curriculum, tccns is the
        # Texas Common Course Numbering System (public institutions only), and
        # cross_listings keys off TAMU's "Cross Listing:" phrasing.
        "ucc_attributes": [],
        "tccns": [],
        "cross_listings": [],
        "repeatability": nc.extract_repeatability(description, prerequisites),
        "campuses": smu_campuses(description, prerequisites),
        "prerequisite_courses": codes_in(prerequisites),
        "restrictions": nc.extract_restrictions(prerequisites),
        "source_url": f"{CATALOG_SITE}/departments/{prefix}/courses" if prefix else None,
        "catalog_year": CATALOG_YEAR,
        "source_last_checked": source_last_checked,
        # Coursedog's internal course-group ID, e.g. "0045691". Null only if
        # the source record itself omits it -- not expected in practice, but
        # not assumed either. See the COLUMNS comment above for what this is
        # for.
        "coursedog_group_id": record.get("courseGroupId") or None,
    }
    return course, warnings


# ── Fetch ───────────────────────────────────────────────────────────────────


def fetch_page(skip: int, limit: int) -> dict[str, Any]:
    url = (
        f"{API_BASE}?catalogId={CATALOG_ID}&skip={skip}&limit={limit}"
        f"&orderBy=code&ignoreEffectiveDating=false&ignoreTotalCount=false"
        f"&effectiveDatesRange={EFFECTIVE_DATE}%2C{EFFECTIVE_DATE}"
        f"&columns={COLUMNS.replace(',', '%2C')}"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(REQUEST_BODY).encode("utf-8"),
        headers=REQUEST_HEADERS,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed host
        return json.loads(response.read().decode("utf-8"))


def records_of(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.values())
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"save normalized JSON under {OUTPUT_ROOT}; without it, fetch and report only",
    )
    parser.add_argument("--page-size", type=int, default=250, help="records per request (default: 250)")
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        # This is a bulk JSON API returning 250 records per call, so the whole
        # catalog is ~27 requests; 1s keeps the run polite and brief.
        help="seconds between requests (default: 1.0)",
    )
    parser.add_argument(
        "--all-careers",
        action="store_true",
        help="keep every career level instead of undergraduate only",
    )
    parser.add_argument(
        "--raw-cache",
        type=Path,
        default=None,
        # Re-running the mapping should not mean re-hitting SMU's API 27 times.
        help="path to a raw-response cache; read from it if present, else write it after fetching",
    )
    args = parser.parse_args()

    if args.page_size < 1:
        print("ERROR: --page-size must be at least 1", file=sys.stderr)
        return 1

    source_last_checked = date.today().isoformat()
    print(f"Mode: {'write' if args.write else 'dry-run (nothing saved)'}")
    print(f"Source: {API_BASE}")
    print(f"Page size: {args.page_size}   delay: {args.delay}s")
    print(f"source_last_checked: {source_last_checked}")
    print()

    # ── Paginate ────────────────────────────────────────────────────────────
    raw: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    duplicate_ids = 0
    skip = 0
    list_length: int | None = None
    page = 0

    from_cache = bool(args.raw_cache and args.raw_cache.exists())
    if from_cache:
        cached = json.loads(args.raw_cache.read_text(encoding="utf-8"))
        raw = cached["records"]
        list_length = cached.get("listLength")
        print(f"Loaded {len(raw)} record(s) from cache {args.raw_cache} (no network calls)")
        print(f"listLength recorded at fetch time: {list_length}")

    while not from_cache:
        page += 1
        try:
            payload = fetch_page(skip, args.page_size)
        except urllib.error.HTTPError as exc:
            print(f"ERROR: HTTP {exc.code} at skip={skip}: {exc.reason}", file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"ERROR: network failure at skip={skip}: {exc.reason}", file=sys.stderr)
            return 1

        if list_length is None:
            list_length = payload.get("listLength")
            print(f"listLength reported by API: {list_length}")

        batch = records_of(payload)
        if not batch:
            print(f"  page {page}: 0 records — stopping")
            break

        for record in batch:
            key = str(record.get("_id") or record.get("id") or record.get("code"))
            if key in seen_ids:
                duplicate_ids += 1
                continue
            seen_ids.add(key)
            raw.append(record)

        print(f"  page {page}: skip={skip} got {len(batch)} (running total {len(raw)})")
        skip += args.page_size
        if list_length is not None and skip >= list_length:
            break
        time.sleep(args.delay)

    print(f"\nRetrieved {len(raw)} unique records ({duplicate_ids} duplicate id(s) skipped)")

    if args.raw_cache and not from_cache:
        args.raw_cache.parent.mkdir(parents=True, exist_ok=True)
        args.raw_cache.write_text(
            json.dumps({"listLength": list_length, "records": raw}), encoding="utf-8"
        )
        print(f"Raw responses cached to {args.raw_cache}")

    # ── Career split ────────────────────────────────────────────────────────
    careers = Counter(r.get("career") for r in raw)
    print("\nRecords by career:")
    for career, count in careers.most_common():
        print(f"  {str(career):<32} {count:>5}")

    if args.all_careers:
        kept = raw
    else:
        kept = [r for r in raw if r.get("career") == UNDERGRADUATE_CAREER]
    excluded = len(raw) - len(kept)
    print(f"\nUndergraduate: {len(kept)}   excluded (non-undergraduate): {excluded}")

    # ── Map ─────────────────────────────────────────────────────────────────
    #
    # EMPTY DESCRIPTIONS ARE DROPPED, NOT BACKFILLED. A small number of SMU
    # courses (internships, directed research, project courses) are published
    # with no description at all. course_catalog.description is NOT NULL, and
    # substituting the title would fabricate catalog text that SMU does not
    # publish. Excluding them keeps the local files a faithful subset of the
    # source; the dropped codes are listed in the run output.
    by_school: dict[str, list[dict[str, Any]]] = defaultdict(list)
    warnings: list[str] = []
    dropped_empty_description: list[str] = []
    for record in kept:
        course, course_warnings = build_course(record, source_last_checked)
        if not (course.get("description") or "").strip():
            dropped_empty_description.append(course.get("code") or str(record.get("code")))
            continue
        warnings.extend(course_warnings)
        by_school[school_slug(record.get("college"))].append(course)

    print(f"\nDropped for empty description (not backfilled): {len(dropped_empty_description)}")
    for code in sorted(dropped_empty_description):
        print(f"  {code}")

    for courses in by_school.values():
        courses.sort(key=lambda c: (c["prefix"], c["number"]))

    print("\nUndergraduate courses by school:")
    total = 0
    for slug in sorted(by_school):
        print(f"  {slug:<24} {len(by_school[slug]):>5}")
        total += len(by_school[slug])
    print(f"  {'TOTAL':<24} {total:>5}")

    # ── Field-population report ─────────────────────────────────────────────
    all_courses = [c for courses in by_school.values() for c in courses]
    print("\nField population:")
    for field in (
        "code", "title", "description", "department", "prefix", "number",
        "credit_min", "credit_max", "course_level", "prerequisites",
        "prerequisite_courses", "restrictions", "repeatability", "campuses",
        "source_url",
    ):
        filled = sum(
            1
            for c in all_courses
            if c.get(field) not in (None, "", [], {})
        )
        print(f"  {field:<22} {filled:>5}/{len(all_courses)}")

    duplicates = [
        code for code, n in Counter(c["code"] for c in all_courses).items() if n > 1
    ]
    print(f"\nDuplicate codes across all schools: {len(duplicates)}")
    for code in sorted(duplicates)[:15]:
        print(f"  {code}")

    print(f"\nWarnings: {len(warnings)}")
    for warning in warnings[:25]:
        print(f"  {warning}")
    if len(warnings) > 25:
        print(f"  ... {len(warnings) - 25} more")

    if not args.write:
        print(f"\nDRY RUN — nothing written. Re-run with --write to save under {OUTPUT_ROOT}.")
        return 0

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"\nWriting to {OUTPUT_ROOT}:")
    for slug in sorted(by_school):
        path = OUTPUT_ROOT / f"{slug}.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(by_school[slug], handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"  {path.relative_to(CATALOG_ROOT)}  {len(by_school[slug])} course(s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
