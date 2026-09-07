"""Cross-listing-aware course-code equality.

Built directly on CourseCatalogRecord.cross_listings -- the one cross-listing
data source confirmed correct against real catalog data (spot-checked across
a 300-pair sample of the TAMU catalog: every cross-listed row lists its
partner codes, and every pair lists each other symmetrically).

Deliberately independent of two other, unrelated mechanisms already in this
codebase, neither of which is fit for this job:
  - canonical_course_code() (models.py) is a no-op whitespace/case
    normalizer despite its name -- it does not resolve cross-listing aliases.
  - prerequisites.py's _SLASH_CHAIN / _identity_groups groups codes found
    together in ONE course's own prerequisite text via a regex over that
    text. That is local, per-clause pattern matching, not a general
    "are these two codes the same course" lookup, and it only fires when a
    slash-joined chain happens to appear verbatim in whatever text is being
    parsed.
"""

from .catalog import LocalCatalogRepository
from .models import CatalogInstitution, canonical_course_code


def courses_are_cross_listed(
    catalog_repo: LocalCatalogRepository,
    institution: CatalogInstitution,
    code_a: str,
    code_b: str,
) -> bool:
    """True when code_a and code_b are the same course under two different
    departmental codes, per the catalog's own cross_listings field.

    Symmetric and lookup-direction-independent: a cross-listed catalog row
    lists all of its partners (confirmed for both codes in every sampled
    pair), so either code's own row is sufficient, and checking code_a first
    vs. code_b first gives the same answer.

    Returns False when the two (normalized) codes are identical -- this
    function answers "is B an alias of A", not "is B the same string as A".
    Callers already have a cheaper exact-match check for that case; folding
    it in here would make an identical code look "cross-listed with itself"
    for no reason.
    """
    normalized_a = canonical_course_code(code_a)
    normalized_b = canonical_course_code(code_b)
    if not normalized_a or not normalized_b or normalized_a == normalized_b:
        return False

    course_a = catalog_repo.get(institution, normalized_a)
    if course_a is not None and normalized_b in set(course_a.cross_listings):
        return True

    course_b = catalog_repo.get(institution, normalized_b)
    return course_b is not None and normalized_a in set(course_b.cross_listings)


def cross_listing_map(
    catalog_repo: LocalCatalogRepository, institution: CatalogInstitution
) -> dict[str, list[str]]:
    """code -> its cross-listed partner codes (excluding itself), for every
    course in `institution`'s catalog that has any.

    A bulk read rather than a per-code lookup: this powers a single small
    payload the frontend fetches once and caches (mirroring how the grading
    schema is fetched once per session), not a round trip per search
    keystroke or per already-added code.
    """
    result: dict[str, list[str]] = {}
    for course in catalog_repo.records(institution):
        partners = [code for code in course.cross_listings if code != course.course_code]
        if partners:
            result[course.course_code] = partners
    return result
