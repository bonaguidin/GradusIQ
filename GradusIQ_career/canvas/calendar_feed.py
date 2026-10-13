"""Canvas calendar feed: one pasted URL in, upcoming due dates and exams out.

WHY A CALENDAR FEED AND NOT THE CANVAS API
------------------------------------------
Every Canvas user has a private iCal URL (Calendar -> "Calendar Feed") that
Canvas offers for subscribing from Google, Apple or Outlook calendars. Reading
it needs no developer key, no admin approval and no access token, which is why
it can ship before any school approves a GradusIQ integration. It carries
assignment due dates and calendar events across all of the student's courses.
It does NOT carry grades, scores or professor comments -- those need the API.

SECURITY
--------
The feed URL is a bearer secret: anyone holding it can read that calendar.
It is stored only in the student's own RLS-protected row, never logged, and
never returned to the browser after it is saved.

The server fetches whatever URL a student pastes, so validate_feed_url is the
SSRF guard: https only, the exact Canvas feed path shape, and a host that is
either the student's institution's canvas_host or an instructure.com
subdomain. Redirects are followed manually and every hop is re-validated, so
a redirect cannot walk the fetch onto an internal address.

EXAM DETECTION IS A HEURISTIC
-----------------------------
Canvas has no "this is an exam" flag in the feed. looks_like_exam matches
words like exam/midterm/quiz in the title and is surfaced to students as
"likely exam", never as a fact.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from ..transcript.store_helpers import rows_of


TABLE = "canvas_calendar_feeds"

FEED_PATH_RE = re.compile(r"^/feeds/calendars/user_[A-Za-z0-9-]{16,}\.ics$")
INSTRUCTURE_SUFFIX = ".instructure.com"

FETCH_TIMEOUT_SECONDS = 15.0
MAX_FEED_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3

# A cached snapshot older than this is refreshed on the next read. Due dates
# move rarely enough that a few hours is fine, and it keeps a dashboard load
# from hitting Canvas every time.
STALE_AFTER = timedelta(hours=6)
RETRY_AFTER_FAILURE = timedelta(minutes=30)

# What is kept from a sync. The feed spans the whole term and earlier terms;
# only the near past (so "due yesterday" is still visible) and the rest of a
# term ahead are useful here, and the cap bounds the jsonb row.
KEEP_PAST = timedelta(days=2)
KEEP_FUTURE = timedelta(days=150)
MAX_STORED_EVENTS = 500

# How far ahead the dashboard list looks.
UPCOMING_WINDOW = timedelta(days=21)


class FeedUrlError(ValueError):
    """The pasted URL is not a Canvas calendar feed we will fetch."""


class FeedFetchError(RuntimeError):
    """Canvas could not be reached or did not return a calendar."""


# ── URL validation ───────────────────────────────────────────────────────────


def allowed_host(host: str, canvas_host: str | None) -> bool:
    host = host.lower()
    if canvas_host and host == canvas_host.lower():
        return True
    return host.endswith(INSTRUCTURE_SUFFIX)


def validate_feed_url(raw: str, canvas_host: str | None) -> str:
    """The normalized https feed URL, or FeedUrlError with a student-facing message."""
    text = (raw or "").strip()
    if not text:
        raise FeedUrlError("Paste the Calendar Feed link from Canvas.")
    if text.lower().startswith("webcal://"):
        text = "https://" + text[len("webcal://"):]

    parts = urlsplit(text)
    if parts.scheme.lower() != "https":
        raise FeedUrlError("That link should start with https://.")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise FeedUrlError("That doesn't look like a Canvas Calendar Feed link.")
    host = (parts.hostname or "").lower()
    if not host or not allowed_host(host, canvas_host):
        expected = canvas_host or "your school's Canvas site"
        raise FeedUrlError(f"That link isn't from {expected}. Copy the Calendar Feed link from Canvas.")
    if parts.query or not FEED_PATH_RE.match(parts.path):
        raise FeedUrlError(
            "That doesn't look like a Canvas Calendar Feed link. It should end in .ics."
        )
    return urlunsplit(("https", host, parts.path, "", ""))


# ── fetching ────────────────────────────────────────────────────────────────


def fetch_feed(
    url: str,
    canvas_host: str | None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Fetch the feed body. Redirects are followed by hand and re-validated."""
    current = url
    with httpx.Client(
        follow_redirects=False,
        timeout=FETCH_TIMEOUT_SECONDS,
        transport=transport,
        headers={"Accept": "text/calendar", "User-Agent": "GradusIQ calendar sync"},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location", "")
                        target = urlsplit(str(response.url.join(location)))
                        if target.scheme != "https" or not allowed_host(target.hostname or "", canvas_host):
                            raise FeedFetchError("Canvas redirected somewhere unexpected.")
                        current = urlunsplit(target)
                        continue
                    if response.status_code in (401, 403, 404):
                        raise FeedFetchError(
                            "Canvas didn't accept that link. It may have been reset; copy it again from Canvas."
                        )
                    if response.status_code != 200:
                        raise FeedFetchError(f"Canvas returned an error ({response.status_code}). Try again shortly.")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_FEED_BYTES:
                            raise FeedFetchError("That calendar is too large to import.")
                    return body.decode("utf-8", errors="replace")
            except httpx.HTTPError as exc:
                raise FeedFetchError("Couldn't reach Canvas. Try again shortly.") from exc
    raise FeedFetchError("Canvas redirected too many times.")


# ── iCal parsing ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CalendarEvent:
    uid: str
    title: str
    course_label: str | None
    kind: str  # 'assignment' | 'event'
    # Timed events: an aware UTC ISO datetime. All-day events: a bare
    # YYYY-MM-DD date, because an all-day due date has no time zone and
    # converting it would shift it a day for half the country.
    starts_at: str
    ends_at: str | None
    all_day: bool
    likely_exam: bool
    url: str | None

    def to_dict(self) -> dict:
        return asdict(self)


_SUMMARY_COURSE_RE = re.compile(r"^(?P<title>.*?)\s*\[(?P<course>[^\[\]]+)\]\s*$")
_EXAM_RE = re.compile(r"\b(exams?|midterms?|quiz(?:zes)?|tests?)\b", re.IGNORECASE)
_FINAL_RE = re.compile(
    r"\bfinal\b(?!\s+(?:project|paper|report|presentation|essay|draft|portfolio|submission))",
    re.IGNORECASE,
)


def looks_like_exam(title: str) -> bool:
    return bool(_EXAM_RE.search(title) or _FINAL_RE.search(title))


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_property(line: str) -> tuple[str, dict[str, str], str] | None:
    if ":" not in line:
        return None
    head, value = line.split(":", 1)
    name, *raw_params = head.split(";")
    params = {}
    for param in raw_params:
        if "=" in param:
            key, val = param.split("=", 1)
            params[key.upper()] = val.strip('"')
    return name.upper(), params, value


def _parse_when(value: str, params: Mapping[str, str]) -> tuple[datetime | date, bool] | None:
    value = value.strip()
    try:
        if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
            return datetime.strptime(value, "%Y%m%d").date(), True
        if value.endswith("Z"):
            parsed = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return parsed, False
        naive = datetime.strptime(value, "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    tz: Any = timezone.utc
    if "TZID" in params:
        try:
            tz = ZoneInfo(params["TZID"])
        except (ZoneInfoNotFoundError, ValueError):
            tz = timezone.utc
    return naive.replace(tzinfo=tz).astimezone(timezone.utc), False


def _iso(when: datetime | date) -> str:
    if isinstance(when, datetime):
        return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return when.isoformat()


def parse_ics(text: str) -> list[CalendarEvent]:
    """Every VEVENT with a summary and a start, in feed order. Never raises."""
    events: list[CalendarEvent] = []
    current: dict[str, tuple[dict[str, str], str]] | None = None
    for line in _unfold(text):
        stripped = line.strip()
        if stripped.upper() == "BEGIN:VEVENT":
            current = {}
            continue
        if stripped.upper() == "END:VEVENT":
            if current is not None:
                event = _build_event(current)
                if event is not None:
                    events.append(event)
            current = None
            continue
        if current is None:
            continue
        prop = _split_property(line)
        if prop is not None:
            name, params, value = prop
            current.setdefault(name, (params, value))
    return events


def _build_event(props: Mapping[str, tuple[dict[str, str], str]]) -> CalendarEvent | None:
    if "SUMMARY" not in props or "DTSTART" not in props:
        return None
    summary = _unescape(props["SUMMARY"][1]).strip()
    start = _parse_when(props["DTSTART"][1], props["DTSTART"][0])
    if not summary or start is None:
        return None
    end = _parse_when(props["DTEND"][1], props["DTEND"][0]) if "DTEND" in props else None

    match = _SUMMARY_COURSE_RE.match(summary)
    title, course = (match["title"].strip(), match["course"].strip()) if match else (summary, None)
    uid = props.get("UID", ({}, ""))[1].strip() or f"{summary}|{props['DTSTART'][1]}"
    url = props.get("URL", ({}, ""))[1].strip() or None

    return CalendarEvent(
        uid=uid,
        title=title or summary,
        course_label=course,
        kind="assignment" if "assignment" in uid.lower() else "event",
        starts_at=_iso(start[0]),
        ends_at=_iso(end[0]) if end else None,
        all_day=start[1],
        likely_exam=looks_like_exam(title or summary),
        url=url if url and url.startswith("https://") else None,
    )


# ── windowing ───────────────────────────────────────────────────────────────


def _start_day(event: Mapping[str, Any]) -> date:
    value = str(event["starts_at"])
    if event.get("all_day"):
        return date.fromisoformat(value[:10])
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _sort_key(event: Mapping[str, Any]) -> str:
    value = str(event["starts_at"])
    # All-day items sort to the end of their day: "due today" with no time
    # reads as "by end of day".
    return value + "T23:59:59Z" if event.get("all_day") else value


def keep_for_storage(events: list[CalendarEvent], now: datetime) -> list[dict]:
    lo, hi = (now - KEEP_PAST).date(), (now + KEEP_FUTURE).date()
    kept = [e.to_dict() for e in events if lo <= _start_day(e.to_dict()) <= hi]
    seen: set[str] = set()
    unique = []
    for event in sorted(kept, key=_sort_key):
        if event["uid"] in seen:
            continue
        seen.add(event["uid"])
        unique.append(event)
    return unique[:MAX_STORED_EVENTS]


def upcoming(events: list[Mapping[str, Any]], now: datetime) -> list[dict]:
    """Stored events from today (UTC) through the upcoming window, in order."""
    lo, hi = now.date(), (now + UPCOMING_WINDOW).date()
    out = []
    for event in events:
        try:
            day = _start_day(event)
        except (KeyError, ValueError):
            continue
        if not lo <= day <= hi:
            continue
        if not event.get("all_day"):
            try:
                if datetime.fromisoformat(str(event["starts_at"]).replace("Z", "+00:00")) < now:
                    continue
            except ValueError:
                continue
        out.append(dict(event))
    return sorted(out, key=_sort_key)


# ── storage ─────────────────────────────────────────────────────────────────


def load_feed_row(client, student_id: str) -> dict | None:
    rows = rows_of(client.table(TABLE).select("*").eq("student_id", student_id).execute())
    return rows[0] if rows else None


def save_feed_row(client, student_id: str, *, feed_url: str, host: str, events: list[dict], now: datetime) -> dict:
    payload = {
        "student_id": student_id,
        "feed_url": feed_url,
        "feed_host": host,
        "events": events,
        "synced_at": now.isoformat(),
        "last_error": None,
        "updated_at": now.isoformat(),
    }
    rows = rows_of(client.table(TABLE).upsert(payload, on_conflict="student_id").execute())
    return rows[0] if rows else payload


def record_sync(client, student_id: str, *, events: list[dict] | None, error: str | None, now: datetime) -> None:
    patch: dict[str, Any] = {"last_error": error, "updated_at": now.isoformat()}
    if events is not None:
        patch["events"] = events
        patch["synced_at"] = now.isoformat()
    client.table(TABLE).update(patch).eq("student_id", student_id).execute()


def delete_feed_row(client, student_id: str) -> None:
    client.table(TABLE).delete().eq("student_id", student_id).execute()


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_stale(row: Mapping[str, Any], now: datetime) -> bool:
    """Due for an automatic re-sync on read.

    After a failed sync, wait RETRY_AFTER_FAILURE before trying again on
    reads: an unreachable Canvas would otherwise hold every dashboard load
    for the full fetch timeout. An explicit refresh ignores this.
    """
    if row.get("last_error"):
        attempted = _parse_ts(row.get("updated_at"))
        if attempted is not None and now - attempted < RETRY_AFTER_FAILURE:
            return False
    synced_at = _parse_ts(row.get("synced_at"))
    return synced_at is None or now - synced_at > STALE_AFTER


def sync(
    url: str,
    canvas_host: str | None,
    now: datetime,
    *,
    fetcher: Callable[[str, str | None], str] | None = None,
) -> list[dict]:
    """Fetch and parse; FeedFetchError if the body isn't a calendar at all."""
    body = (fetcher or fetch_feed)(url, canvas_host)
    if "BEGIN:VCALENDAR" not in body[:2048].upper():
        raise FeedFetchError("That link didn't return a calendar. Copy the Calendar Feed link from Canvas again.")
    return keep_for_storage(parse_ics(body), now)
