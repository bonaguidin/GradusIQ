"""Bug and feature reports: validated in, one plain-text email out.

WHY THE BACKEND SENDS IT
------------------------
The browser never talks to the email provider. The Resend API key lives only
in this service's environment (RESEND_API_KEY), so nothing in the shipped
frontend bundle can be lifted and used to send mail as gradusiq.com.

WHY PLAIN TEXT
--------------
Every field in a report is typed by whoever opened the form, signed in or not.
The email is sent as `text` only, so nothing a reporter writes can render as
HTML in the team inbox. The reporter's address goes in `reply_to`, which is a
JSON field in the Resend request, never a raw header, so CR/LF in it cannot
inject headers; validate_email rejects them anyway.

SPAM AND ABUSE
--------------
* `website` is a honeypot: the form hides it from people, so a non-empty
  value means a bot filled every field. The caller reports success and sends
  nothing, so the bot learns nothing.
* KeyedRateLimiter caps reports per verified account, and puts every
  unverified caller (demo visitors, expired sessions) in one shared bucket.
  It is process-local like SlidingWindowRateLimiter in api.py, which is
  fine for the same reason: the service runs exactly one worker.
* Screenshots are capped by count and size and must really be PNG, JPEG or
  WebP (checked by magic bytes, not by the declared Content-Type). The
  frontend shrinks images before upload so a report stays well under
  Vercel's 4.5 MB request body limit; the caps here are the backstop.
"""

from __future__ import annotations

import base64
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Literal

import httpx

RESEND_ENDPOINT = "https://api.resend.com/emails"
DEFAULT_REPORT_TO = "gradus@gradusiq.com"
DEFAULT_REPORT_FROM = "GradusIQ Reports <reports@gradusiq.com>"

ReportKind = Literal["bug", "feature"]
REPORT_KINDS: tuple[str, ...] = ("bug", "feature")

MAX_SCREENSHOTS = 3
MAX_SCREENSHOT_BYTES = 1_500_000
MAX_TOTAL_SCREENSHOT_BYTES = 3_500_000
MIN_DESCRIPTION_CHARS = 10
MAX_DESCRIPTION_CHARS = 5000
MAX_NAME_CHARS = 120
MAX_EMAIL_CHARS = 254
MAX_CONTEXT_CHARS = 300

# Deliberately loose: one @, no whitespace, a dot in the domain. The point is
# catching typos, not proving deliverability.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ReportValidationError(ValueError):
    """The submitted report is unusable; the message is safe to show."""


class ReportDeliveryError(RuntimeError):
    """The email provider refused or could not be reached."""


class ReportNotConfiguredError(RuntimeError):
    """RESEND_API_KEY is not set, so reports cannot be sent."""


@dataclass(frozen=True)
class Screenshot:
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class Report:
    kind: ReportKind
    description: str
    name: str | None
    email: str
    page: str | None
    user_agent: str | None
    screenshots: tuple[Screenshot, ...] = ()
    # Set only when the caller's Supabase session was verified server side.
    account_email: str | None = None
    account_id: str | None = None


def _clean_line(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = _CONTROL_CHARS.sub("", value).replace("\r", " ").replace("\n", " ").strip()
    return cleaned[:limit] or None


def validate_kind(value: str) -> ReportKind:
    if value not in REPORT_KINDS:
        raise ReportValidationError("Choose bug or feature request.")
    return value  # type: ignore[return-value]


def validate_description(value: str) -> str:
    cleaned = _CONTROL_CHARS.sub("", value or "").strip()
    if len(cleaned) < MIN_DESCRIPTION_CHARS:
        raise ReportValidationError(
            f"Add a little more detail (at least {MIN_DESCRIPTION_CHARS} characters)."
        )
    if len(cleaned) > MAX_DESCRIPTION_CHARS:
        raise ReportValidationError(
            f"Keep the description under {MAX_DESCRIPTION_CHARS} characters."
        )
    return cleaned


def validate_email(value: str) -> str:
    cleaned = (value or "").strip()
    if (
        not cleaned
        or len(cleaned) > MAX_EMAIL_CHARS
        or "\r" in cleaned
        or "\n" in cleaned
        or not _EMAIL_PATTERN.match(cleaned)
    ):
        raise ReportValidationError("Enter an email address we can reply to.")
    return cleaned


def validate_name(value: str | None) -> str | None:
    return _clean_line(value, MAX_NAME_CHARS)


def validate_context(value: str | None) -> str | None:
    return _clean_line(value, MAX_CONTEXT_CHARS)


def _sniff_image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def validate_screenshots(files: list[tuple[str | None, bytes]]) -> tuple[Screenshot, ...]:
    """`files` is (original filename, bytes) per upload, in order.

    Original filenames are not trusted or forwarded; each attachment is
    renamed screenshot-N.<ext> from its sniffed type.
    """
    if len(files) > MAX_SCREENSHOTS:
        raise ReportValidationError(f"Attach at most {MAX_SCREENSHOTS} screenshots.")
    total = 0
    screenshots: list[Screenshot] = []
    for index, (_name, data) in enumerate(files, start=1):
        if not data:
            continue
        if len(data) > MAX_SCREENSHOT_BYTES:
            raise ReportValidationError("Each screenshot must be under 1.5 MB.")
        total += len(data)
        if total > MAX_TOTAL_SCREENSHOT_BYTES:
            raise ReportValidationError("Screenshots must total under 3.5 MB.")
        content_type = _sniff_image_type(data)
        if content_type is None:
            raise ReportValidationError("Screenshots must be PNG, JPEG or WebP images.")
        screenshots.append(
            Screenshot(
                filename=f"screenshot-{index}.{_EXTENSIONS[content_type]}",
                content_type=content_type,
                data=data,
            )
        )
    return tuple(screenshots)


def _summary_line(description: str) -> str:
    first_line = description.strip().splitlines()[0] if description.strip() else ""
    first_line = first_line.strip()
    return first_line if len(first_line) <= 70 else first_line[:67].rstrip() + "..."


def build_email(report: Report, *, to_address: str, from_address: str) -> dict:
    """The Resend request body for one report."""
    label = "Bug report" if report.kind == "bug" else "Feature request"
    subject = f"[GradusIQ {label}] {_summary_line(report.description)}"

    if report.account_email:
        account_line = f"{report.account_email} (verified session, user {report.account_id})"
    else:
        account_line = "Not signed in, or session could not be verified"

    lines = [
        f"{label} from {report.name or 'no name given'} <{report.email}>",
        "",
        "Description",
        "-----------",
        report.description,
        "",
        "Context",
        "-------",
        f"Signed-in account: {account_line}",
        f"Page: {report.page or 'not provided'}",
        f"Browser: {report.user_agent or 'not provided'}",
        f"Screenshots attached: {len(report.screenshots)}",
        "",
        "Reply to this email to answer the reporter directly.",
    ]

    body: dict = {
        "from": from_address,
        "to": [to_address],
        "subject": subject,
        "text": "\n".join(lines),
        "reply_to": report.email,
    }
    if report.screenshots:
        body["attachments"] = [
            {
                "filename": shot.filename,
                "content": base64.b64encode(shot.data).decode("ascii"),
            }
            for shot in report.screenshots
        ]
    return body


def send_report(
    report: Report,
    *,
    api_key: str,
    to_address: str = DEFAULT_REPORT_TO,
    from_address: str = DEFAULT_REPORT_FROM,
    transport: httpx.BaseTransport | None = None,
) -> str | None:
    """Send through Resend. Returns Resend's message id when it gives one."""
    if not api_key:
        raise ReportNotConfiguredError("RESEND_API_KEY is not set.")
    payload = build_email(report, to_address=to_address, from_address=from_address)
    try:
        with httpx.Client(timeout=15.0, transport=transport) as client:
            response = client.post(
                RESEND_ENDPOINT,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.HTTPError as exc:
        raise ReportDeliveryError("Could not reach the email service.") from exc
    if response.status_code >= 400:
        # Resend's error body names the problem (unverified domain, bad key)
        # without echoing the key; keep it for the server log only.
        raise ReportDeliveryError(
            f"Email service returned {response.status_code}: {response.text[:300]}"
        )
    try:
        return response.json().get("id")
    except ValueError:
        return None


@dataclass
class KeyedRateLimiter:
    """Sliding window per key. Process-local; see the module docstring."""

    limit: int
    window_seconds: float
    max_keys: int = 5000
    clock: Callable[[], float] = time.monotonic
    _hits: dict[str, deque] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, key: str) -> bool:
        now = self.clock()
        cutoff = now - self.window_seconds
        with self._lock:
            if len(self._hits) >= self.max_keys and key not in self._hits:
                self._prune(cutoff)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def _prune(self, cutoff: float) -> None:
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]
