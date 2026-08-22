#!/usr/bin/env python3
"""Workday adapter -- the sixth source, and the one that reaches the DFW list.

WHY THIS EXISTS

The five original adapters were built for indie ATS platforms. The real DFW
employer list is not on them: of 44 researched employers, exactly ONE (Match
Group, Lever) is reachable by all five combined. Nineteen are on Workday, and
thirteen employers have confirmed live posting counts totalling 6,092 -- forty
times the entire existing corpus of 153. One adapter here is worth more than
the five that came before it.

THE ENDPOINT

Workday's career sites are backed by a public JSON API with no key:

    POST https://<host>/wday/cxs/<tenant>/<site>/jobs
    {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}

POST rather than GET, which is why it could not be bolted onto the existing
GET-shaped adapters. Two host layouts appear in the wild and both are in the
employer list:

    att.wd1.myworkdayjobs.com/ATTGeneral
      -> host att.wd1.myworkdayjobs.com, tenant att, site ATTGeneral

    wd12.myworkdaysite.com/recruiting/parklandhospital/Parkland_Careers
      -> host wd12.myworkdaysite.com, tenant parklandhospital,
         site Parkland_Careers

RESPONSE SHAPE IS VERIFIED, UNLIKE normalize.py's VENDOR MAPS

Confirmed against a live response from Atmos Energy on 2026-08-19: the
envelope carries {facets, jobPostings, total, userAuthenticated}, `total` was
44 exactly as the slug research recorded, and each posting carries title,
externalPath, locationsText, postedOn and bulletFields. A full paged fetch
then returned all 44. So the field names here are observed rather than
assumed. `--probe` re-checks it for one request if that ever stops holding.

Required fields are still fatal rather than silently null, for the same reason
as everywhere else in this package: a posting with no URL cannot be
exact-matched or spot-checked, and nothing downstream would look wrong.

Two things the live response settled that documentation would not have:

  - `bulletFields[0]` is the requisition number ('JR13846'), and it makes a
    better source_job_id than the externalPath tail, which embeds the job
    title and therefore changes when someone edits it.
  - `postedOn` is relative prose ('Posted Today'), never a timestamp.

WHAT A MISSING SITE PATH MEANS

Seven of the nineteen Workday employers were recorded with a host but no site
segment, and none of those has a live posting count either -- the two go
together, because the URL cannot be built without the site. Those rows are
incomplete rather than merely unconfirmed, and parse_workday_slug returns None
for them rather than guessing a default like "careers" that would 404 or,
worse, land on some other tenant's board. Twelve are usable today.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from errors import JobPostingConfigError, JobPostingRequestError  # noqa: E402

USER_AGENT = "GradusIQ-ATS-Puller/0.1 (labor market research)"
TIMEOUT_SECONDS = 20.0
PAGE_SIZE = 20
DELAY_BETWEEN_PAGES = 1.0
MAX_PAGES = 25  # 500 postings per employer; Michaels alone reports 2,000

SOURCE = "workday"

_MYWORKDAYSITE = re.compile(r"^(?P<host>wd\d+\.myworkdaysite\.com)/recruiting/(?P<tenant>[^/]+)/(?P<site>[^/?#]+)")
_MYWORKDAYJOBS = re.compile(r"^(?P<tenant>[^./]+)\.(?P<hostrest>wd\d+\.myworkdayjobs\.com)/(?P<site>[^/?#]+)")


@dataclass(frozen=True)
class WorkdayBoard:
    host: str
    tenant: str
    site: str

    @property
    def jobs_url(self) -> str:
        return f"https://{self.host}/wday/cxs/{self.tenant}/{self.site}/jobs"

    @property
    def careers_url(self) -> str:
        return f"https://{self.host}/{self.site}"


def parse_workday_slug(slug: str | None) -> WorkdayBoard | None:
    """Slug string -> board, or None when it cannot be built.

    Returning None for a host with no site path is deliberate. Defaulting to
    something like "careers" would either 404 or, worse, succeed against a
    different site on the same tenant and file real postings under the wrong
    board.
    """
    if not slug or not slug.strip():
        return None
    s = re.sub(r"^https?://", "", slug.strip()).strip("/")
    s = s.split("?")[0]

    m = _MYWORKDAYSITE.match(s)
    if m:
        return WorkdayBoard(m.group("host"), m.group("tenant"), m.group("site"))

    m = _MYWORKDAYJOBS.match(s)
    if m:
        host = f"{m.group('tenant')}.{m.group('hostrest')}"
        return WorkdayBoard(host, m.group("tenant"), m.group("site"))

    return None


def _post(url: str, body: dict, *, timeout: float = TIMEOUT_SECONDS) -> Any:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        transient = exc.code == 429 or 500 <= exc.code < 600
        raise JobPostingRequestError(
            f"Workday returned HTTP {exc.code} for {url}", transient=transient
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise JobPostingRequestError(f"Workday request failed: {exc}", transient=True) from exc
    except json.JSONDecodeError as exc:
        raise JobPostingRequestError(
            f"Workday returned non-JSON from {url}: {exc}", transient=False
        ) from exc


def fetch_page(board: WorkdayBoard, *, offset: int = 0, limit: int = PAGE_SIZE) -> dict:
    return _post(board.jobs_url, {
        "appliedFacets": {},
        "limit": limit,
        "offset": offset,
        "searchText": "",
    })


def total_from(payload: dict) -> int:
    return int(payload.get("total") or 0) if isinstance(payload, dict) else 0


def listings_from(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    return payload.get("jobPostings") or []


def normalize_listing(listing: dict, board: WorkdayBoard, employer: str) -> dict:
    """One Workday posting -> the shared row shape.

    externalPath is a site-relative path ("/job/Dallas/Analyst_R-12345"), so
    the absolute URL has to be rebuilt from the board. That URL is what dedup
    and spot-checking both depend on, which is why its absence is fatal.
    """
    external_path = listing.get("externalPath")
    title = listing.get("title")
    if not external_path or not title:
        raise ValueError(
            f"Workday listing for {employer} missing "
            f"{'externalPath' if not external_path else 'title'}. "
            f"Keys present: {sorted(listing)}. The response shape in workday.py "
            f"is unverified against live data -- this is what a wrong one looks like."
        )

    return {
        "source": SOURCE,
        "source_job_id": _job_id(listing, external_path),
        "title": title,
        "company": employer,
        "location": listing.get("locationsText"),
        "url": f"https://{board.host}{external_path}",
        "posted_date": parse_posted_on(listing.get("postedOn")),
        "salary_min": None,
        "salary_max": None,
        "raw_payload": listing,
    }


def _job_id(listing: dict, external_path: str) -> str:
    """Prefer the requisition number over the URL slug.

    A live response gives bulletFields ['JR13846'] alongside externalPath
    '/job/Texas---Dallas/Sr-Applications-Developer_JR13846'. The path embeds
    the job title, so an employer editing the title changes the path, the
    upsert key forks, and one posting becomes two rows. The requisition number
    does not move.
    """
    bullets = listing.get("bulletFields")
    if isinstance(bullets, list) and bullets and isinstance(bullets[0], str) and bullets[0].strip():
        return bullets[0].strip()
    return external_path.rstrip("/").split("/")[-1]


_RELATIVE_DAYS = re.compile(r"posted\s+(\d+)\+?\s+days?\s+ago", re.IGNORECASE)


def parse_posted_on(posted_on: str | None) -> str | None:
    """Workday's relative string -> an ISO date, or None.

    A live response returns 'Posted Today', not a timestamp. Approximate is
    still worth having: posted_date would otherwise be null for every one of
    the nineteen Workday employers, and freshness is the whole point of the
    column.

    Anything not confidently understood returns None rather than a guess --
    "Posted 30+ Days Ago" is a floor, not a date, and treating it as exact
    would make old postings look precisely dated.
    """
    if not posted_on or not isinstance(posted_on, str):
        return None
    text = posted_on.strip().lower()
    if "today" in text:
        return date.today().isoformat()
    if "yesterday" in text:
        return (date.today() - timedelta(days=1)).isoformat()
    if "+" in text:
        return None
    m = _RELATIVE_DAYS.search(text)
    if m:
        return (date.today() - timedelta(days=int(m.group(1)))).isoformat()
    return None


def fetch_board(
    board: WorkdayBoard,
    employer: str,
    *,
    live: bool = False,
    max_pages: int = MAX_PAGES,
    delay: float = DELAY_BETWEEN_PAGES,
) -> tuple[list[dict], list[str]]:
    """Page through one board. Dry run prints the request and fetches nothing."""
    if not live:
        print(f"[DRY RUN] Workday request (not sent):")
        print(f"  POST {board.jobs_url}")
        print(f"  body: {{'appliedFacets': {{}}, 'limit': {PAGE_SIZE}, 'offset': 0, 'searchText': ''}}")
        return [], []

    rows: list[dict] = []
    errors: list[str] = []
    offset = 0
    total = None

    for _ in range(max_pages):
        payload = fetch_page(board, offset=offset)
        if total is None:
            total = total_from(payload)
        listings = listings_from(payload)
        if not listings:
            break
        for listing in listings:
            try:
                rows.append(normalize_listing(listing, board, employer))
            except ValueError as exc:
                errors.append(str(exc))
        offset += len(listings)
        if total and offset >= total:
            break
        time.sleep(delay)

    return rows, errors


def describe_shape(payload: dict, board: WorkdayBoard) -> str:
    lines = [f"{board.jobs_url}", f"  top-level keys: {sorted(payload) if isinstance(payload, dict) else type(payload).__name__}"]
    lines.append(f"  total: {total_from(payload)}")
    listings = listings_from(payload)
    lines.append(f"  jobPostings: {len(listings)}")
    if listings:
        first = listings[0]
        lines.append(f"  first listing keys: {sorted(first)}")
        for field in ("title", "externalPath", "locationsText", "postedOn", "bulletFields"):
            value = first.get(field)
            lines.append(f"    {field:<16} {repr(value)[:70] if value is not None else 'None  <-- MISSING'}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--slug", help="e.g. atmosenergy.wd108.myworkdayjobs.com/External_Career_Site")
    parser.add_argument("--employer", default="(unnamed)")
    parser.add_argument("--live", action="store_true", help="Actually send the request.")
    parser.add_argument("--probe", action="store_true",
                        help="Fetch one page and print the response shape against what this expects.")
    parser.add_argument("--list-boards", action="store_true",
                        help="Show which employers in the CSV have a usable Workday board.")
    args = parser.parse_args()

    if args.list_boards:
        import csv
        path = REPO_ROOT / "data" / "job_postings" / "dfw_employers_ats.csv"
        usable = unusable = 0
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("ats") != "workday":
                    continue
                board = parse_workday_slug(r.get("slug"))
                if board:
                    usable += 1
                    print(f"  OK       {r['employer'][:32]:<34} {board.tenant}/{board.site}")
                else:
                    unusable += 1
                    print(f"  NO SITE  {r['employer'][:32]:<34} {r.get('slug')}")
        print(f"\n{usable} usable, {unusable} missing a site path.")
        return 0

    if not args.slug:
        print("--slug is required (or use --list-boards).", file=sys.stderr)
        return 2

    board = parse_workday_slug(args.slug)
    if board is None:
        print(f"Could not parse a Workday board from {args.slug!r}.", file=sys.stderr)
        print("Expected <tenant>.wdN.myworkdayjobs.com/<site> or "
              "wdN.myworkdaysite.com/recruiting/<tenant>/<site>.", file=sys.stderr)
        return 2

    if args.probe:
        try:
            payload = fetch_page(board, limit=5)
        except JobPostingRequestError as exc:
            print(f"Request error (transient={exc.transient}): {exc}", file=sys.stderr)
            return 1
        print(describe_shape(payload, board))
        return 0

    try:
        rows, errors = fetch_board(board, args.employer, live=args.live)
    except JobPostingRequestError as exc:
        print(f"Request error (transient={exc.transient}): {exc}", file=sys.stderr)
        return 1

    if args.live:
        print(f"{len(rows)} posting(s) normalized from {board.tenant}/{board.site}.")
        for r in rows[:5]:
            print(f"   {r['title'][:60]:<62} {r['location'] or ''}")
        if errors:
            print(f"\n{len(errors)} listing(s) failed to normalize:")
            for e in errors[:3]:
                print(f"   - {e[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
