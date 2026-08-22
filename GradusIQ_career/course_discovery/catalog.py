"""Cached, institution-scoped reads over the repository catalog snapshots."""

import json
import re
from functools import lru_cache
from pathlib import Path

from .models import (
    CatalogInstitution,
    CourseCatalogRecord,
    CourseExistenceResult,
    CourseExistenceStatus,
    CourseSearchQuery,
    CourseSearchResult,
    MatchKind,
    PrerequisiteCoverage,
    canonical_course_code,
)


CATALOG_ROOT = Path(__file__).resolve().parents[2] / "data" / "catalog"
TAMU_SUBTREES = (
    "agriculture_life_sciences", "architecture", "arts_and_sciences",
    "business", "education_human_development", "engineering",
    "government_public_service", "nursing", "public_health",
    "veterinary_biomedical_sciences",
)
INSTITUTION_SUBTREES = {
    CatalogInstitution.TAMU: TAMU_SUBTREES,
    CatalogInstitution.SMU: ("smu",),
}
_TERMS = re.compile(r"[a-z0-9]+")


def _credits(row: dict) -> tuple[float, float]:
    if row.get("credit_min") is not None and row.get("credit_max") is not None:
        return float(row["credit_min"]), float(row["credit_max"])
    value = row.get("credit_hours")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), float(value)
    if isinstance(value, str) and "-" in value:
        left, right = value.split("-", 1)
        return float(left), float(right)
    return 0.0, 0.0


@lru_cache(maxsize=1)
def _catalogs() -> dict[CatalogInstitution, tuple[CourseCatalogRecord, ...]]:
    loaded: dict[CatalogInstitution, tuple[CourseCatalogRecord, ...]] = {}
    for institution, subtrees in INSTITUTION_SUBTREES.items():
        records: list[CourseCatalogRecord] = []
        seen: set[str] = set()
        for subtree in subtrees:
            for path in sorted((CATALOG_ROOT / subtree).rglob("*.json")):
                rows = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    code = canonical_course_code(str(row.get("code") or ""))
                    if not code or code in seen:
                        continue
                    seen.add(code)
                    credit_min, credit_max = _credits(row)
                    records.append(CourseCatalogRecord(
                        institution=institution,
                        course_code=code,
                        title=str(row.get("title") or ""),
                        description=str(row.get("description") or ""),
                        department=str(row.get("department") or ""),
                        credit_min=credit_min,
                        credit_max=credit_max,
                        course_level=row.get("course_level"),
                        prerequisite_text=row.get("prerequisites"),
                        prerequisite_courses=[
                            code for value in row.get("prerequisite_courses") or []
                            if (code := canonical_course_code(str(value)))
                        ],
                        restrictions=[str(value) for value in row.get("restrictions") or []],
                        cross_listings=[
                            code for value in row.get("cross_listings") or []
                            if (code := canonical_course_code(str(value)))
                        ],
                        catalog_year=str(row.get("catalog_year") or ""),
                        source_url=str(row.get("source_url") or ""),
                        source_last_checked=str(row.get("source_last_checked") or ""),
                    ))
        loaded[institution] = tuple(records)
    return loaded


class LocalCatalogRepository:
    """Read-only repository; catalog JSON is parsed once per process."""

    def __init__(self):
        catalogs = _catalogs()
        self._records = catalogs
        self._by_code = {
            institution: {record.course_code: record for record in records}
            for institution, records in catalogs.items()
        }

    def count(self, institution: CatalogInstitution) -> int:
        return len(self._records[institution])

    def records(self, institution: CatalogInstitution) -> tuple[CourseCatalogRecord, ...]:
        """Return the immutable institution snapshot for deterministic audits."""
        return self._records[institution]

    def prerequisite_coverage(self, institution: CatalogInstitution) -> PrerequisiteCoverage:
        records = self._records[institution]
        return PrerequisiteCoverage(
            institution=institution,
            total_courses=len(records),
            prerequisite_text_courses=sum(bool(item.prerequisite_text) for item in records),
            parsed_course_code_courses=sum(bool(item.prerequisite_courses) for item in records),
            parsed_restriction_courses=sum(bool(item.restrictions) for item in records),
        )

    def institutions_with_code(self, course_code: str) -> list[CatalogInstitution]:
        normalized = canonical_course_code(course_code)
        if normalized is None:
            return []
        return [
            institution for institution, values in self._by_code.items()
            if normalized in values
        ]

    def get(self, institution: CatalogInstitution, course_code: str) -> CourseCatalogRecord | None:
        normalized = canonical_course_code(course_code)
        return self._by_code[institution].get(normalized) if normalized else None

    def verify_course_exists(
        self, institution: CatalogInstitution, course_code: str
    ) -> CourseExistenceResult:
        normalized = canonical_course_code(course_code)
        course = self._by_code[institution].get(normalized) if normalized else None
        return CourseExistenceResult(
            institution=institution,
            requested_code=course_code,
            normalized_code=normalized,
            status=(CourseExistenceStatus.EXISTS if course else CourseExistenceStatus.NOT_FOUND),
            course=course,
            provenance=course.provenance if course else None,
        )

    def search(self, query: CourseSearchQuery) -> list[CourseSearchResult]:
        phrase = " ".join(query.query.lower().split())
        terms = list(dict.fromkeys(_TERMS.findall(phrase)))
        normalized_code = canonical_course_code(query.query)
        results: list[CourseSearchResult] = []
        for course in self._records[query.institution]:
            if query.subject and not course.course_code.startswith(query.subject.upper() + " "):
                continue
            if query.level and course.course_level != query.level:
                continue
            code = course.course_code.lower()
            title = course.title.lower()
            description = course.description.lower()
            kinds: list[MatchKind] = []
            matched: list[str] = []
            score = 0
            if normalized_code and course.course_code == normalized_code:
                kinds.append(MatchKind.COURSE_CODE); score += 100; matched.append(normalized_code)
            elif phrase and code.startswith(phrase):
                kinds.append(MatchKind.COURSE_CODE); score += 70; matched.append(phrase)
            if phrase and phrase in title:
                kinds.append(MatchKind.TITLE); score += 50 if title == phrase else 40; matched.append(phrase)
            title_terms = [term for term in terms if term in title]
            description_terms = [term for term in terms if term in description]
            if title_terms and MatchKind.TITLE not in kinds:
                kinds.append(MatchKind.TITLE); score += 12 * len(title_terms); matched.extend(title_terms)
            if description_terms:
                kinds.append(MatchKind.DESCRIPTION); score += 4 * len(description_terms); matched.extend(description_terms)
            if not kinds:
                continue
            results.append(CourseSearchResult(
                course=course, score=score,
                match_kinds=list(dict.fromkeys(kinds)),
                matched_terms=list(dict.fromkeys(matched)),
            ))
        results.sort(key=lambda result: (-result.score, result.course.course_code))
        return results[:query.limit]
