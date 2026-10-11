"""Classify a posting title against role_families.yaml's family rules.

role_families.yaml's own header has always documented its matching algorithm
(longest phrase first, globally across all families; exclude_phrases beats
any match; no match -> family NULL) and tests/test_job_postings_config.py
has always pinned the file's internal consistency -- but nothing has ever
actually executed that algorithm. ingest.py never writes a role_family
column, and FIT/GAP key off the query-supplied target_role instead. This
module is the first real implementation, built for the Job Search feed,
which classifies at READ time off title text alone (never description or
raw_payload) because Workday rows have no target_role to key off at all.

job_search_feed_families.yaml adds families role_families.yaml does not
carry (AI/ML, data engineering, QA/SDET/SRE, design engineering) plus the
related-family expansion map a student's own target roles pull in. Loading
and matching both files together is what "GLOBALLY across all families"
means here -- role_families.yaml's 14 are not edited or duplicated.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import yaml

from scripts.job_postings.identity import normalize_title

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "job_postings"
ROLE_FAMILIES_PATH = CONFIG_DIR / "role_families.yaml"
FEED_FAMILIES_PATH = CONFIG_DIR / "job_search_feed_families.yaml"

_TRAILING_INTERN = re.compile(r"\s+(?:intern|internship)$")
_MIN_CORE_PHRASE_LENGTH = 3


def _core_phrase(phrase: str) -> str | None:
    """Strip a trailing "intern"/"internship" token so the role words match
    regardless of where "intern" sits in the title. Every row in the feed's
    candidate pool is already internship-filtered (fetch_candidate_pool), so
    requiring that adjacency on top of that is redundant and is what breaks
    on titles like "Intern - Design Engineer, HBM", where "Intern" comes
    first. Returns None when there is nothing to strip, or when the result
    is too short/generic to trust as a standalone word-boundary match (bare
    2-letter acronyms like "ai"/"ml" are left to their longer sibling
    phrases -- "artificial intelligence intern", "machine learning intern" --
    instead).
    """
    core = _TRAILING_INTERN.sub("", phrase).strip()
    if core == phrase or len(core) < _MIN_CORE_PHRASE_LENGTH:
        return None
    return core


def load_role_families(path: Path = ROLE_FAMILIES_PATH) -> list[dict[str, Any]]:
    """The 14 target-role families -- the keys in data/role_requirements.json."""
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)["families"]


def load_feed_families(
    path: Path = FEED_FAMILIES_PATH,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """The feed-only families plus the related-family expansion map."""
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("families") or [], data.get("related_families") or {}


def load_all_families(
    role_families_path: Path = ROLE_FAMILIES_PATH,
    feed_families_path: Path = FEED_FAMILIES_PATH,
) -> list[dict[str, Any]]:
    """role_families.yaml's 14 plus job_search_feed_families.yaml's additions,
    as one list -- matching runs over this combined set, never role_families
    alone, so a feed family can win over a role family when its phrase is
    longer, exactly as role_families.yaml's header specifies for itself."""
    feed_families, _ = load_feed_families(feed_families_path)
    return load_role_families(role_families_path) + feed_families


def classify_title(title: str | None, families: Iterable[dict[str, Any]]) -> str | None:
    """Longest-phrase-first across every family in `families`; an
    exclude_phrase suppresses only the family that declares it, never any
    other family's match. Returns the family name, or None for no match.
    """
    if not title:
        return None
    folded = f" {normalize_title(title)} "

    # Exclude phrases are never core-stripped: QA/SDET/SRE's excludes rely on
    # their exact literal length ("quality assurance intern" must NOT reduce
    # to "quality assurance", which would wrongly exclude "quality assurance
    # engineering intern").
    entries: list[tuple[str, str, bool]] = []
    for fam in families:
        name = fam["family"]
        for phrase in fam["match_phrases"]:
            entries.append((phrase, name, False))
            core = _core_phrase(phrase)
            if core is not None:
                entries.append((core, name, False))
        for phrase in fam.get("exclude_phrases") or []:
            entries.append((phrase, name, True))

    # Exclusions resolve in their own pass, independent of phrase length: an
    # exclude_phrase may be shorter than the match_phrase it is meant to
    # suppress (job_search_feed_families.yaml's Design Engineering excludes
    # are deliberately short fragments), so length order cannot interleave
    # the two kinds of entry.
    excluded_families = {
        family for phrase, family, is_exclude in entries if is_exclude and f" {phrase} " in folded
    }

    matches = sorted(
        (entry for entry in entries if not entry[2]),
        key=lambda entry: len(entry[0]),
        reverse=True,
    )
    for phrase, family, _ in matches:
        if family in excluded_families:
            continue
        if f" {phrase} " in folded:
            return family
    return None


def expand_families(base_families: Iterable[str], related: dict[str, list[str]]) -> list[str]:
    """A student's own target-role families, plus whatever
    job_search_feed_families.yaml's related_families map adds for each one.
    Order-preserving, de-duplicated, not transitive -- a family that only
    appears as a mapped value is not expanded further."""
    seen: list[str] = []
    for family in base_families:
        if family not in seen:
            seen.append(family)
        for related_family in related.get(family, []):
            if related_family not in seen:
                seen.append(related_family)
    return seen
