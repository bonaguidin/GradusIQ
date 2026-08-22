#!/usr/bin/env python3
"""Turn the employer list's empty slug column into a fill-in-the-blank task.

A slug is the identifier in an employer's own careers URL, and it is the one
thing standing between the 44-row DFW employer list and the ATS fetcher. The
list has slugs for none of them.

Two modes, dry run as always:

  (default)  Writes a worksheet -- every employer, its domain, plausible slug
             candidates, and the exact URL to check for each ATS. Nothing is
             fetched. This is a checklist a person works through.

  --live     Probes the candidate URLs against the five ATS JSON feeds and
             fills in whatever answers. Zero-auth public endpoints, the same
             feeds powering each employer's own careers page, but it is still
             other people's infrastructure -- sequential, delayed, and capped.

WHY A WRONG SLUG IS WORSE THAN A MISSING ONE

A missing slug means an employer is not fetched, which shows up as an obvious
zero. A slug pointing at the wrong company means real postings get filed under
the wrong employer, which looks exactly like data. So --live records what it
actually saw -- the posting count and a sample title -- rather than just
writing a slug and declaring victory. Someone still eyeballs the sample.

Recruitee is the sharp edge: its slug is the hostname, so a wrong guess is a
DNS failure rather than a 404, and DNS failures are slower and noisier than
404s. It is probed last for that reason.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

DEFAULT_CSV = REPO_ROOT / "data" / "job_postings" / "dfw_employers_ats.csv"
DEFAULT_WORKSHEET = REPO_ROOT / "data" / "job_postings" / "slug_worksheet.md"

USER_AGENT = "GradusIQ-research/0.1 (labor market research; slug verification)"
TIMEOUT_SECONDS = 15
DELAY_BETWEEN_REQUESTS = 1.0


@dataclass(frozen=True)
class AtsProbe:
    """One ATS: where a human looks, and where the script looks."""

    name: str
    careers_url: Callable[[str], str]
    api_url: Callable[[str], str]
    count: Callable[[Any], int]
    titles: Callable[[Any], list[str]]


def _g(payload: Any) -> list:
    return payload.get("jobs", []) if isinstance(payload, dict) else []


ATS_PROBES: tuple[AtsProbe, ...] = (
    AtsProbe(
        "greenhouse",
        lambda s: f"https://boards.greenhouse.io/{s}",
        lambda s: f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs",
        lambda p: len(_g(p)),
        lambda p: [j.get("title", "") for j in _g(p)[:3]],
    ),
    AtsProbe(
        "lever",
        lambda s: f"https://jobs.lever.co/{s}",
        lambda s: f"https://api.lever.co/v0/postings/{s}?mode=json",
        lambda p: len(p) if isinstance(p, list) else 0,
        lambda p: [j.get("text", "") for j in p[:3]] if isinstance(p, list) else [],
    ),
    AtsProbe(
        "ashby",
        lambda s: f"https://jobs.ashbyhq.com/{s}",
        lambda s: f"https://api.ashbyhq.com/posting-api/job-board/{s}",
        lambda p: len(p.get("jobs", [])) if isinstance(p, dict) else 0,
        lambda p: [j.get("title", "") for j in p.get("jobs", [])[:3]] if isinstance(p, dict) else [],
    ),
    AtsProbe(
        "smartrecruiters",
        lambda s: f"https://careers.smartrecruiters.com/{s}",
        lambda s: f"https://api.smartrecruiters.com/v1/companies/{s}/postings",
        lambda p: p.get("totalFound", 0) if isinstance(p, dict) else 0,
        lambda p: [j.get("name", "") for j in p.get("content", [])[:3]] if isinstance(p, dict) else [],
    ),
    # Last on purpose -- see the module docstring.
    AtsProbe(
        "recruitee",
        lambda s: f"https://{s}.recruitee.com",
        lambda s: f"https://{s}.recruitee.com/api/offers/",
        lambda p: len(p.get("offers", [])) if isinstance(p, dict) else 0,
        lambda p: [j.get("title", "") for j in p.get("offers", [])[:3]] if isinstance(p, dict) else [],
    ),
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_LEGAL = re.compile(r"\b(inc|llc|corp|corporation|ltd|limited|co|plc|group|holdings)\b", re.I)


def candidate_slugs(employer: str, domain: str | None) -> list[str]:
    """Plausible slugs, most likely first.

    The domain root is first because it is right far more often than anything
    derived from the display name -- an employer picks one identifier and
    tends to reuse it.
    """
    out: list[str] = []

    def add(value: str) -> None:
        v = value.strip("-")
        if v and v not in out:
            out.append(v)

    if domain:
        root = domain.strip().lower().split("/")[0]
        root = root[4:] if root.startswith("www.") else root
        add(root.split(".")[0])

    # The FULL name comes before the suffix-stripped one, and that ordering is
    # load-bearing. Match Group's real Lever slug is "matchgroup"; stripping
    # "Group" as though it were a legal suffix yields "match" and never finds
    # the board. Words like Group and Holdings are part of the trading name,
    # and the identifier an employer registers usually keeps them.
    lowered = employer.lower()
    add(_NON_ALNUM.sub("", lowered))
    add(_NON_ALNUM.sub("-", lowered).strip("-"))

    stripped = _LEGAL.sub(" ", lowered)
    add(_NON_ALNUM.sub("", stripped))
    add(_NON_ALNUM.sub("-", stripped).strip("-"))

    first = _NON_ALNUM.sub("-", stripped).strip("-").split("-")[0]
    if len(first) > 3:
        add(first)

    return out


@dataclass
class ProbeResult:
    employer: str
    ats: str | None = None
    slug: str | None = None
    count: int = 0
    sample: list[str] = field(default_factory=list)
    attempts: int = 0


def _fetch(url: str) -> Any | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            json.JSONDecodeError, OSError):
        # A miss is the expected outcome for most probes -- a wrong slug is a
        # 404, and for Recruitee a DNS failure. Neither is exceptional here.
        return None


def probe_employer(employer: str, domain: str | None, *, max_attempts: int,
                   delay: float = DELAY_BETWEEN_REQUESTS) -> ProbeResult:
    """Try each candidate against each ATS until something answers."""
    result = ProbeResult(employer=employer)
    for slug in candidate_slugs(employer, domain):
        for probe in ATS_PROBES:
            if result.attempts >= max_attempts:
                return result
            result.attempts += 1
            payload = _fetch(probe.api_url(slug))
            time.sleep(delay)
            if payload is None:
                continue
            count = probe.count(payload)
            if count > 0:
                result.ats = probe.name
                result.slug = slug
                result.count = count
                result.sample = [t for t in probe.titles(payload) if t]
                return result
    return result


def render_worksheet(rows: list[dict]) -> str:
    """The fill-in-the-blank checklist."""
    lines = [
        "# Slug worksheet — DFW employer list",
        "",
        "The ATS fetcher needs `{ats, slug}` per employer. The employer list has",
        f"slugs for none of its {len(rows)}. This is that gap as a checklist.",
        "",
        "**The slug is the identifier in the employer's own careers URL.** Open the",
        "employer's careers page, look at where it redirects, and read it off:",
        "",
        "| ATS | Careers URL shape | Slug is |",
        "|---|---|---|",
        "| greenhouse | `boards.greenhouse.io/<slug>` | the path segment |",
        "| lever | `jobs.lever.co/<slug>` | the path segment |",
        "| ashby | `jobs.ashbyhq.com/<slug>` | the path segment |",
        "| smartrecruiters | `careers.smartrecruiters.com/<slug>` | the path segment — **PascalCase, case-sensitive** |",
        "| recruitee | `<slug>.recruitee.com` | the **subdomain** |",
        "",
        "Many of these employers will be on none of the five — enterprise HCM",
        "platforms like Workday are common at this size, and the `notes` column",
        "already flags several. Write `none` rather than leaving a row ambiguous,",
        "so nobody researches it twice.",
        "",
        "**A wrong slug is worse than a blank one.** A blank means an employer is not",
        "fetched, which reads as an obvious zero. A slug pointing at the wrong company",
        "files real postings under the wrong employer, which reads as data. Confirm the",
        "board you land on actually belongs to the employer before writing it down.",
        "",
        "Filling this in is the input to `dfw_employers_ats.csv`'s `ats` and `slug`",
        "columns. `resolve_slugs.py --live` can attempt the same job automatically.",
        "",
    ]

    by_priority: dict[Any, list[dict]] = {}
    for r in rows:
        by_priority.setdefault(r.get("priority"), []).append(r)

    for priority in sorted(by_priority, key=lambda p: (p is None, p)):
        group = by_priority[priority]
        lines += [f"## Priority {priority if priority is not None else '(unset)'} — {len(group)} employers", ""]
        for r in group:
            cands = candidate_slugs(r["name"], r.get("domain"))
            known = f"  _already recorded: `{r['ats_platform']}`_" if r.get("ats_platform") else ""
            lines += [
                f"### {r['name']}",
                f"- domain: `{r.get('domain') or '—'}`{known}",
                f"- candidate slugs: {', '.join(f'`{c}`' for c in cands) or '—'}",
                "- check: "
                + " · ".join(f"[{p.name}]({p.careers_url(cands[0])})" for p in ATS_PROBES)
                if cands else "- check: (no candidate to build a URL from)",
            ]
            if r.get("notes"):
                lines.append(f"- notes: {r['notes']}")
            lines += ["- **ats:** `____________`   **slug:** `____________`", ""]

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out", type=Path, default=DEFAULT_WORKSHEET)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Probe the ATS feeds instead of only writing the worksheet.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only process the first N employers. Use this before committing to all 44.",
    )
    parser.add_argument(
        "--max-attempts", type=int, default=10,
        help="Cap on requests per employer (candidates x platforms). Default 10.",
    )
    parser.add_argument("--delay", type=float, default=DELAY_BETWEEN_REQUESTS)
    args = parser.parse_args()

    sys.path.insert(0, str(HERE))
    from load_employers import parse_rows  # noqa: E402

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 2

    rows, _ = parse_rows(args.csv)
    if args.limit:
        rows = rows[: args.limit]

    if not args.live:
        args.out.write_text(render_worksheet(rows), encoding="utf-8")
        pending = [r for r in rows if not (r.get("ats_platform") and r.get("slug"))]
        print(f"Worksheet written: {args.out}")
        print(f"  {len(rows)} employers, {len(pending)} still needing a slug.")
        print(f"  Nothing was fetched. Re-run with --live to probe automatically.")
        return 0

    print(f"Probing {len(rows)} employer(s), up to {args.max_attempts} requests each, "
          f"{args.delay}s apart. Ctrl-C is safe.\n")
    found: list[ProbeResult] = []
    for i, r in enumerate(rows, 1):
        res = probe_employer(r["name"], r.get("domain"),
                             max_attempts=args.max_attempts, delay=args.delay)
        if res.ats:
            found.append(res)
            print(f"  [{i}/{len(rows)}] {r['name']}: {res.ats}/{res.slug} "
                  f"-- {res.count} postings")
            for t in res.sample:
                print(f"        sample: {t[:70]}")
        else:
            print(f"  [{i}/{len(rows)}] {r['name']}: no board found "
                  f"({res.attempts} tried)")

    print(f"\n{len(found)} of {len(rows)} resolved.")
    if found:
        print("\nPaste into dfw_employers_ats.csv (ats, slug) -- but read the sample")
        print("titles first and confirm each board really is that employer's:\n")
        for res in found:
            print(f"  {res.employer},{res.ats},{res.slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
