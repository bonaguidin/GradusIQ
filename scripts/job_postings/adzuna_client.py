#!/usr/bin/env python3
"""Thin diagnostic wrapper around Adzuna's job-search endpoint.

SCRATCH / DIAGNOSTIC ONLY -- not wired into GradusIQ_career. This exists to
answer "does Adzuna have volume for role X in market Y" cheaply, ahead of any
real fetch-scheduler build.

CREDENTIALS: ADZUNA_APP_ID + ADZUNA_APP_KEY, loaded via python-dotenv from
.env exactly once at CLI entry (see main()), matching scripts/import_students.py
and scripts/fetch_smu_term_dates.py. AdzunaClient itself never calls
load_dotenv() -- constructing it assumes the environment is already populated,
same division of responsibility as OpenRouterClient/TavilyClient (the env
lookup happens in __init__, dotenv loading is the caller's job). A missing or
blank credential raises JobPostingConfigError immediately: job-posting data
is not optional-with-fallback the way a missing TAVILY_API_KEY is (that path
degrades to a warning and an empty tool result -- see role_research_agent.py's
_tavily_client). There is no equivalent silent-degrade path here.

DRY RUN IS THE DEFAULT. Every call to search() without live=True only builds
and prints the exact request (URL, params, app_key masked) and returns None
without touching the network. Both vendors' free tiers are small and already
partially spent this session -- see the module docstring context in the task
this script was built for. Pass live=True (CLI: --live) to actually send it.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from errors import JobPostingConfigError, JobPostingRequestError  # noqa: E402

ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs"

# Per-call timeout, matching the ~15s explicit-timeout convention confirmed in
# role_research_agent.py's Tavily client (_TAVILY_TIMEOUT_SECONDS) and
# test.py's own ad-hoc Adzuna probe this session -- no implicit requests
# default.
DEFAULT_TIMEOUT_SECONDS = 15.0

_MASK = "***"


class AdzunaClient:
    def __init__(
        self,
        app_id: str | None = None,
        app_key: str | None = None,
        *,
        base_url: str = ADZUNA_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: Any = requests,
    ) -> None:
        self.app_id = app_id if app_id is not None else os.getenv("ADZUNA_APP_ID")
        self.app_key = app_key if app_key is not None else os.getenv("ADZUNA_APP_KEY")
        if not self.app_id or not self.app_id.strip():
            raise JobPostingConfigError("ADZUNA_APP_ID is required for Adzuna calls.")
        if not self.app_key or not self.app_key.strip():
            raise JobPostingConfigError("ADZUNA_APP_KEY is required for Adzuna calls.")
        self.base_url = base_url
        self.timeout = timeout
        self.session = session

    def build_request(
        self,
        *,
        what: str,
        where: str,
        distance: int = 30,
        results_per_page: int = 5,
        page: int = 1,
        job_type: str | None = None,
        country: str = "us",
    ) -> tuple[str, dict[str, Any]]:
        """Returns (url, params) without sending anything."""
        url = f"{self.base_url}/{country}/search/{page}"
        params: dict[str, Any] = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "what": what,
            "where": where,
            "distance": distance,
            "results_per_page": results_per_page,
            "content-type": "application/json",
        }
        if job_type:
            params["job_type"] = job_type
        return url, params

    def masked_params(self, params: dict[str, Any]) -> dict[str, Any]:
        masked = dict(params)
        if "app_id" in masked:
            masked["app_id"] = _MASK
        if "app_key" in masked:
            masked["app_key"] = _MASK
        return masked

    def search(
        self,
        *,
        what: str,
        where: str,
        distance: int = 30,
        results_per_page: int = 5,
        page: int = 1,
        job_type: str | None = None,
        country: str = "us",
        live: bool = False,
    ) -> dict[str, Any] | None:
        """Dry-run by default: prints the request and returns None.

        Pass live=True to actually send it. results_per_page defaults to 5,
        not Adzuna's own default of 10+ -- keep it capped at the smallest
        value that still answers "how many results / what do the titles look
        like" per the task's call-minimization constraint.
        """
        url, params = self.build_request(
            what=what,
            where=where,
            distance=distance,
            results_per_page=results_per_page,
            page=page,
            job_type=job_type,
            country=country,
        )
        if not live:
            print("[DRY RUN] Adzuna request (not sent):")
            print(f"  GET {url}")
            print(f"  params: {self.masked_params(params)}")
            return None

        endpoint = f"/{country}/search/{page}"  # path only -- never the query string
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            # requests' own str(exc) embeds the full request URL, which for
            # this API includes app_id/app_key as query params -- confirmed
            # live when a transient 503 put both in a printed traceback. Never
            # interpolate `exc` itself (not even via `from exc`, which keeps
            # the original exception, URL and all, reachable from the new
            # one's __cause__ and printed by the default traceback handler) --
            # only its type, the HTTP status if one was received, and the
            # endpoint PATH built above, with no query string.
            status = exc.response.status_code if exc.response is not None else None
            transient = isinstance(exc, (requests.ConnectionError, requests.Timeout)) or (
                status == 429 or (status is not None and 500 <= status < 600)
            )
            status_label = str(status) if status is not None else "no response"
            raise JobPostingRequestError(
                f"Adzuna request failed: {type(exc).__name__} (status={status_label}) at {endpoint}",
                transient=transient,
            ) from None

        # A 200 with a non-JSON body (Adzuna maintenance page, CDN error) must
        # surface as a caught JobPostingRequestError -- otherwise the raw
        # decode error propagates past ingest.py's per-role handler and aborts
        # the whole run mid-loop. Not transient: a bad body this minute is a
        # vendor-side problem, not a blip to retry inside the same run.
        try:
            return response.json()
        except ValueError as exc:  # includes requests' JSONDecodeError
            raise JobPostingRequestError(
                f"Adzuna returned a non-JSON body: {type(exc).__name__} "
                f"(HTTP {response.status_code}) at {endpoint}",
                transient=False,
            ) from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--what", required=True, help="Search keyword(s), e.g. 'embedded systems'")
    parser.add_argument("--where", default="Dallas", help="Location, e.g. 'Dallas'")
    parser.add_argument("--distance", type=int, default=30)
    parser.add_argument("--results-per-page", type=int, default=5)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--job-type", default=None, help="e.g. 'placement student'")
    parser.add_argument("--country", default="us")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually send the request. Without this flag, only prints the request and exits.",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")

    try:
        client = AdzunaClient()
    except JobPostingConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        result = client.search(
            what=args.what,
            where=args.where,
            distance=args.distance,
            results_per_page=args.results_per_page,
            page=args.page,
            job_type=args.job_type,
            country=args.country,
            live=args.live,
        )
    except JobPostingRequestError as exc:
        print(f"Request error (transient={exc.transient}): {exc}", file=sys.stderr)
        sys.exit(1)

    if result is not None:
        print(f"count: {result.get('count')}")
        titles = [r.get("title") for r in result.get("results", [])]
        print(f"sample titles: {titles}")


if __name__ == "__main__":
    main()
