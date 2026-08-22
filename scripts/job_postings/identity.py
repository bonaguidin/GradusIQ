"""Cross-source posting identity -- deciding when two listings are one job.

Implements data/ats_fetcher/DEDUP.md. Job search APIs syndicate ATS listings,
so the same role arrives on one nightly run under two or three vendor ids.
Each one is a separate vote in any skill count, and a ranking built on that
reflects syndication reach rather than the DFW labor market.

DELIBERATELY PURE. Every function here is a string in, string out -- no
network, no database, no model call. That is the same constraint
data/ats_fetcher/README.md §1 puts on the counting path, for the same reason:
when a merge looks wrong it has to trace to a line rather than to a prompt or
a row that has since changed. The caller does the lookups; this module only
says what to look up.

THE EXACT PATH IS THE ONE THAT MATTERS. recover_ats_id() parses an ATS job id
back out of an apply URL, which matches a row already fetched directly from
that board with no threshold and no false positives. Verified against the real
corpus: for all 153 postings pulled 2026-08-05 (Greenhouse and Lever), the
stored external_id equals the last path segment of the posting URL. Fuzzy
matching exists only for vendor-native postings that carry no ATS link.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# URL normalization and ATS id recovery
# ---------------------------------------------------------------------------

# host -> (ats name, path regex whose first group is the job id)
#
# Greenhouse and Lever are confirmed against real pulled data. The other three
# are written from each board's public URL shape but have never been exercised
# -- the ATS fetcher's adapters for them have never run either. Treat a match
# from an unconfirmed host as good but unproven, not as evidence the adapter
# works.
_ATS_URL_PATTERNS: dict[str, tuple[str, re.Pattern[str]]] = {
    # CONFIRMED -- job-boards.greenhouse.io/pmg/jobs/8496729002
    "job-boards.greenhouse.io": ("greenhouse", re.compile(r"^/[^/]+/jobs/(\d+)")),
    "boards.greenhouse.io": ("greenhouse", re.compile(r"^/[^/]+/jobs/(\d+)")),
    # CONFIRMED -- jobs.lever.co/matchgroup/3414ba28-35f7-45d3-8e13-35c883959635
    "jobs.lever.co": ("lever", re.compile(r"^/[^/]+/([0-9a-f-]{36})")),
    # UNCONFIRMED below this line.
    "jobs.ashbyhq.com": ("ashby", re.compile(r"^/[^/]+/([0-9a-f-]{36})")),
    "jobs.smartrecruiters.com": ("smartrecruiters", re.compile(r"^/[^/]+/(\d+)")),
}

# Recruitee is per-tenant ({company}.recruitee.com/o/{slug}) so it cannot be
# keyed by a fixed host, and its identifier is a slug rather than an id.
_RECRUITEE_HOST = re.compile(r"^([a-z0-9-]+)\.recruitee\.com$")
_RECRUITEE_PATH = re.compile(r"^/o/([^/]+)")


def normalize_url(url: str | None) -> str | None:
    """Lowercase the host, drop query and fragment, strip a trailing slash.

    The query string is where syndicators put their referral tracking, so two
    links to the same posting routinely differ only there. Dropping it is what
    makes them comparable.
    """
    if not url or not url.strip():
        return None
    parts = urlsplit(url.strip())
    if not parts.netloc:
        return None
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    scheme = parts.scheme.lower() or "https"
    return f"{scheme}://{host}{path}"


def recover_ats_id(url: str | None) -> tuple[str, str] | None:
    """Return (ats_name, external_id) parsed out of an apply URL, or None.

    This is DEDUP.md §3.1 -- the exact path. A vendor listing whose apply link
    points at an ATS board yields that board's own job id, which matches a row
    already ingested from the board directly. An unrecognized host returns None
    and falls through to fuzzy matching rather than raising.
    """
    normalized = normalize_url(url)
    if normalized is None:
        return None
    parts = urlsplit(normalized)
    host, path = parts.netloc, parts.path

    known = _ATS_URL_PATTERNS.get(host)
    if known is not None:
        ats, pattern = known
        match = pattern.match(path)
        if match:
            return ats, match.group(1)
        return None

    if _RECRUITEE_HOST.match(host):
        match = _RECRUITEE_PATH.match(path)
        if match:
            return "recruitee", match.group(1)
    return None


# ---------------------------------------------------------------------------
# Employer and title normalization -- the fuzzy fallback, DEDUP.md §3.2
# ---------------------------------------------------------------------------

# Legal-form suffixes only. "Group", "Holdings" and the like are deliberately
# NOT here: they are part of the trading name, not a corporate form. Stripping
# them collapsed "Match Group" to "match", which would then collide with any
# real company called Match -- over-normalizing merges two employers, and a
# wrongly merged employer is worse than a missed duplicate.
_LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "l.l.c", "corp", "corporation", "co",
    "ltd", "limited", "plc", "lp", "llp", "gmbh", "sa", "nv", "ag",
}

# Seniority renderings are CANONICALIZED, not stripped.
#
# DEDUP.md originally said to strip these so "Sr. Data Analyst" and "Data
# Analyst" collapse. That is wrong and this module deliberately departs from
# it: at one employer those are plausibly two distinct openings, and merging
# them undercounts a real job. What actually needs to collapse is one job
# spelled two ways -- "Sr." and "Senior" -- which is a rendering difference a
# syndicator introduces. Mapping to a canonical token does that while keeping
# different levels apart.
_SENIORITY_CANON = {
    "sr": "senior", "snr": "senior", "senior": "senior",
    "jr": "junior", "jnr": "junior", "junior": "junior",
    "mgr": "manager", "manager": "manager",
    "dir": "director", "director": "director",
    "prin": "principal", "principal": "principal",
    "lead": "lead", "staff": "staff",
    "i": "1", "ii": "2", "iii": "3", "iv": "4",
    "1": "1", "2": "2", "3": "3", "4": "4",
}

_REQ_NUMBER = re.compile(r"""
      \(\s*(?:req|requisition|job|id)?\s*[#:]?\s*[a-z]*[-_]?\d{3,}\s*\)  # (R12345)
    | \#\s*[a-z]*[-_]?\d{3,}                                             # #12345
    | \b(?:req|requisition)\s*[#:]?\s*[a-z]*[-_]?\d{3,}\b                # req 12345
""", re.IGNORECASE | re.VERBOSE)

# A trailing parenthetical or bracketed aside. Syndicators append location and
# arrangement here ("(Dallas, TX)", "(Remote)", "[Hybrid]") far more often than
# anything identifying, so it is noise for matching purposes.
_TRAILING_ASIDE = re.compile(r"[\(\[][^\)\]]*[\)\]]\s*$")

_PUNCT = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")


def _fold(text: str) -> str:
    """Casefold and strip accents, so 'Peña' and 'Pena' compare equal."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def normalize_employer(name: str | None) -> str:
    """Canonical employer key: folded, legal suffixes and punctuation removed.

    An explicit alias map belongs on top of this for the curated DFW list --
    the employer set is small and hand-built, so a lookup table beats string
    distance and never merges two real companies by accident.
    """
    if not name:
        return ""
    folded = _PUNCT.sub(" ", _fold(name))
    tokens = [t for t in _WHITESPACE.split(folded) if t]
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_title(title: str | None) -> str:
    """Canonical title key: req numbers and trailing asides gone, seniority
    spellings unified, everything else preserved.

    Preserving is the point. Only variation a syndicator introduces should
    disappear; anything that distinguishes two real openings has to survive.
    """
    if not title:
        return ""
    working = _REQ_NUMBER.sub(" ", title)
    # Repeat: "Analyst (Dallas, TX) (Remote)" carries more than one aside.
    previous = None
    while previous != working:
        previous = working
        working = _TRAILING_ASIDE.sub("", working).rstrip()
    folded = _PUNCT.sub(" ", _fold(working))
    tokens = [_SENIORITY_CANON.get(t, t) for t in _WHITESPACE.split(folded) if t]
    return " ".join(tokens)


# ---------------------------------------------------------------------------
# DFW bucketing
# ---------------------------------------------------------------------------

# Matching is on the raw location string, but the RESULT is what clusters --
# never the string itself, which syndicators rewrite freely.
_DFW_LOCALITIES = frozenset({
    "dallas", "fort worth", "ft worth", "dfw", "dallas fort worth",
    "metroplex", "arlington", "plano", "irving", "garland", "frisco",
    "mckinney", "grand prairie", "mesquite", "carrollton", "denton",
    "richardson", "lewisville", "allen", "flower mound", "mansfield",
    "rowlett", "bedford", "euless", "grapevine", "cedar hill", "desoto",
    "coppell", "hurst", "duncanville", "the colony", "farmers branch",
    "southlake", "keller", "wylie", "little elm", "haltom city", "rockwall",
    "addison", "prosper", "celina", "sachse", "murphy", "balch springs",
    "lancaster", "waxahachie", "midlothian", "north richland hills",
})

_REMOTE = re.compile(r"\b(?:remote|work from home|wfh|anywhere|virtual)\b", re.IGNORECASE)
_HYBRID = re.compile(r"\bhybrid\b", re.IGNORECASE)
_TEXAS = re.compile(r"\b(?:tx|texas)\b", re.IGNORECASE)
_US_SCOPED = re.compile(r"\b(?:us|usa|u\.s\.?|united states|nationwide)\b", re.IGNORECASE)

# Multi-location strings separate with a semicolon or pipe far more reliably
# than with a comma, which is doing city/state duty inside each entry.
_LOCATION_SPLIT = re.compile(r"[;|]|\band\b", re.IGNORECASE)


class LocationKind(str, Enum):
    """Why a posting was or was not called DFW. Stored as a column.

    Adopted from the ats-puller-draft skeleton, which argued the case well: a
    bare is_dfw boolean records the verdict and throws away the reasoning, and
    the remote call is contested enough that it will be revisited. Re-deriving
    the reason months later means re-running a classifier that has since
    changed, so without this the decision is not actually revisitable. With it,
    reclassifying is one UPDATE.
    """

    DFW_METRO = "dfw_metro"
    MULTI_INCLUDES_DFW = "multi_includes_dfw"
    HYBRID_DFW = "hybrid_dfw"
    TEXAS_NON_DFW = "texas_non_dfw"
    REMOTE_US = "remote_us"
    REMOTE_ANYWHERE = "remote_anywhere"
    NON_DFW = "non_dfw"
    UNKNOWN = "unknown"


def classify_location(location: str | None) -> tuple[bool, LocationKind]:
    """Return (is_dfw, kind). The verdict is always definite; kind says why.

    Presence wins over absence -- "Dallas, TX; New York, NY" is a real DFW
    opportunity and the corpus actually contains that shape. Hybrid is a
    schedule rather than a geography, so a hybrid DFW role still requires
    living here and stays true.

    Remote with no DFW anchor is FALSE today, not undetermined. That is a
    deliberate call rather than a dodge: the kind records that it was remote,
    so flipping it later is a query rather than a re-pull.
    """
    if not location or not location.strip():
        return False, LocationKind.UNKNOWN

    folded = _WHITESPACE.sub(" ", _PUNCT.sub(" ", _fold(location))).strip()
    padded = f" {folded} "
    has_dfw = any(f" {locality} " in padded for locality in _DFW_LOCALITIES)

    if has_dfw:
        if _HYBRID.search(location):
            return True, LocationKind.HYBRID_DFW
        parts = [p for p in _LOCATION_SPLIT.split(location) if p.strip()]
        if len(parts) > 1:
            return True, LocationKind.MULTI_INCLUDES_DFW
        return True, LocationKind.DFW_METRO

    if _REMOTE.search(location):
        if _US_SCOPED.search(location):
            return False, LocationKind.REMOTE_US
        return False, LocationKind.REMOTE_ANYWHERE

    if _TEXAS.search(location):
        return False, LocationKind.TEXAS_NON_DFW

    return False, LocationKind.NON_DFW


def is_dfw(location: str | None) -> bool:
    """Just the verdict. Callers that persist a row want classify_location(),
    so the reasoning reaches the location_kind column."""
    verdict, _ = classify_location(location)
    return verdict


# ---------------------------------------------------------------------------
# The identity keys a caller looks up
# ---------------------------------------------------------------------------

def exact_key(url: str | None) -> str | None:
    """Cluster key for DEDUP.md §3.1, or None if no ATS id is recoverable."""
    recovered = recover_ats_id(url)
    if recovered is None:
        return None
    ats, external_id = recovered
    return f"ats:{ats}:{external_id}"


def fuzzy_key(
    employer: str | None,
    title: str | None,
    dfw: bool | None,
) -> str | None:
    """Cluster key for DEDUP.md §3.2, or None if there is too little to match on.

    Returning None matters: a posting with no employer or no title must start
    its own cluster rather than colliding with every other underspecified row
    in the corpus, which is what a key of "::" would do.
    """
    employer_key = normalize_employer(employer)
    title_key = normalize_title(title)
    if not employer_key or not title_key:
        return None
    bucket = {True: "dfw", False: "other"}.get(dfw, "unknown")
    return f"fuzzy:{employer_key}:{title_key}:{bucket}"


def identity_keys(posting: dict[str, object]) -> tuple[str | None, str | None]:
    """Both keys for one normalized posting, exact first.

    The caller resolves in that order and takes the first hit -- an exact match
    is evidence; a fuzzy one is an inference, and should never override it.
    """
    url = posting.get("url")
    location = posting.get("location")
    dfw = posting.get("is_dfw")
    if dfw is None:
        dfw = is_dfw(location if isinstance(location, str) else None)
    return (
        exact_key(url if isinstance(url, str) else None),
        fuzzy_key(
            posting.get("employer") or posting.get("company"),  # type: ignore[arg-type]
            posting.get("title"),  # type: ignore[arg-type]
            dfw if isinstance(dfw, bool) else None,
        ),
    )
