"""Reconstruct a student profile dict from Postgres, shaped like the JSON one.

Placed alongside supabase_client.py rather than under features/ because it is a
data-access concern, not a feature concern: every caller already holds a
session-scoped client from build_client_for_token, and the feature runners stay
completely unaware of where their profile dict came from.

The output is structurally interchangeable with what
GradusIQ_career.api.load_student_profile returns from data/students/*.json, so
the runners in features/ need no change to consume it.

UNCONFIRMED ROWS
----------------
Rows whose confirmed_at is null are parser output pending student review. They
are excluded from the profile rather than silently dropped: every exclusion is
recorded as (row, reason) in the returned result, mirroring how
academics/gpa.py already treats "unconfirmed" as a first-class, reportable
reason rather than an invisible filter. Callers may ignore the list today, but
the record exists from the start so a review UI can explain omissions later.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from GradusIQ_career.academics.gpa import (
    CourseRecord,
    GradeMapRow,
    Institution,
    compute_both,
    compute_gpa,
)
from GradusIQ_career.planning.term_view import term_key
from GradusIQ_career.transcript.terms import SEASON_ORDER
from GradusIQ_career.student_intelligence_profile import (
    AcademicCompleteness,
    AcademicCourse,
    Academics,
    AcademicSummary,
    AcademicTerm,
    Career,
    CareerCompleteness,
    CareerItem,
    Completeness,
    GpaProfile,
    Identity,
    InstitutionProfile,
    Provenance,
    RepeatExclusionProfile,
    Skills,
    StudentIntelligenceProfile,
    TermGpaPoint,
)

# Matches academics/gpa.py's reason string exactly -- one vocabulary for
# "this row exists but was not counted", across GPA and career data alike.
UNCONFIRMED_REASON = "unconfirmed"

# Columns that exist on every career-side row but never appear in the JSON
# shape the runners read. Projected out so the reconstructed dict is
# field-for-field identical to the file-backed one.
_DB_ONLY_FIELDS = frozenset(
    {
        "id",
        "career_profile_id",
        "student_id",
        "created_at",
        "updated_at",
        "source",
        "confirmed_at",
    }
)

_CHILD_TABLES = ("certifications", "work_experience", "projects")


@dataclass(frozen=True)
class ProfileBuildResult:
    """A reconstructed profile plus the rows deliberately left out of it.

    NOTE: the brief specified `-> dict`; returning this dataclass instead is
    the only way to surface `exclusions` alongside the profile, which the same
    brief also required. `.profile` is the plain dict callers pass to runners.
    """

    profile: dict[str, Any]
    exclusions: list[tuple[Mapping[str, Any], str]] = field(default_factory=list)


def _strip_db_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project a DB row down to the keys the JSON shape carries."""
    return {k: v for k, v in row.items() if k not in _DB_ONLY_FIELDS}


def _partition_confirmed(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[Mapping[str, Any], str]]]:
    """Split rows into (included, excluded-with-reason) on confirmed_at.

    `.get()` rather than subscript: the confirmed_at column arrives with
    select("*") only once the provenance migration is applied, and a row
    predating it must be treated as unconfirmed rather than raising.
    """
    included: list[dict[str, Any]] = []
    excluded: list[tuple[Mapping[str, Any], str]] = []
    for row in rows:
        if row.get("confirmed_at") is None:
            excluded.append((row, UNCONFIRMED_REASON))
            continue
        included.append(_strip_db_fields(row))
    return included, excluded


def _career_block(
    career_row: Mapping[str, Any],
    children: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Re-nest the flat career_profiles columns into the JSON career shape.

    The one non-flat mapping: skills_technical / skills_soft / ai_exposure are
    three separate columns that become a single nested skills_self_reported
    object. Note ai_exposure belongs INSIDE that object, not beside
    ai_anxiety_level -- an easy transposition to get wrong.

    Lists default to [] rather than None so the shape matches the JSON files,
    where every list key is always present.
    """
    return {
        "target_roles": career_row.get("target_roles") or [],
        "interests": career_row.get("interests") or [],
        "career_goals": career_row.get("career_goals") or "",
        "geographic_preference": career_row.get("geographic_preference") or "",
        "ai_anxiety_level": career_row.get("ai_anxiety_level") or "",
        "skills_self_reported": {
            "technical": career_row.get("skills_technical") or [],
            "soft": career_row.get("skills_soft") or [],
            "ai_exposure": career_row.get("ai_exposure") or "",
        },
        "certifications": children["certifications"],
        "work_experience": children["work_experience"],
        "projects": children["projects"],
    }


def _student_block(
    student_row: Mapping[str, Any], institution_name: str | None
) -> dict[str, Any]:
    """Shape the students row like the JSON student block.

    gpa_current has no column to source it from -- it is deliberately absent
    from the schema (GPA is always derived; see the students table comment in
    the first migration). Emitted as None so the key exists and consumers can
    guard on it.

    `institution` is resolved by the caller via _resolve_institution_name and
    passed in, since it needs its own two-hop query.

    auth_user_id / created_at / updated_at are projected out: they are not in
    the JSON shape and auth_user_id in particular has no business in a payload
    that ends up inside an LLM prompt.
    """
    return {
        "id": str(student_row["id"]),
        "name": student_row.get("name"),
        "classification": student_row.get("classification"),
        "major_current": student_row.get("major_current"),
        "major_intended": student_row.get("major_intended"),
        "expected_graduation": student_row.get("expected_graduation"),
        "onboarding_stage": student_row.get("onboarding_stage"),
        "institution": institution_name,
        "gpa_current": None,
    }


def _resolve_home_institution(
    client: Any, student_id: str
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    """The student's home institution name, or None if it can't be resolved.

    Same two-hop join GET /api/v2/student/me/gpa performs: student_institutions
    filtered to relationship='home', then institutions by id.

    Deliberately does NOT raise where the GPA route raises 409. That route is
    computing a GPA, which is meaningless without a grading scale, so incomplete
    reference data has to stop it. This constructor's job is to produce the best
    available profile -- a student with no home institution still has a name, a
    major, and a career block worth analyzing, and FIT/GAP/SHIFT read
    `institution` only as prompt context. Duplicating the 409s here would make a
    recoverable gap fatal at a layer that has no need to enforce it.
    """
    home_rows = (
        client.table("student_institutions")
        .select("institution_id")
        .eq("student_id", student_id)
        .eq("relationship", "home")
        .execute()
        .data
    )
    if not home_rows:
        return None, None

    institution_rows = (
        client.table("institutions")
        .select("*")
        .eq("id", home_rows[0]["institution_id"])
        .execute()
        .data
    )
    if not institution_rows:
        # Unreachable given the FK on student_institutions.institution_id, but
        # a dangling reference must degrade to null rather than IndexError.
        return home_rows[0], None

    return home_rows[0], institution_rows[0]


def _resolve_institution_name(client: Any, student_id: str) -> str | None:
    """Compatibility helper retained for callers/tests of the legacy builder."""
    _home, institution = _resolve_home_institution(client, student_id)
    return institution.get("name") if institution else None


def _career_items(rows: Sequence[Mapping[str, Any]]) -> list[CareerItem]:
    return [
        CareerItem.model_validate({**_strip_db_fields(row), "source": row.get("source")})
        for row in rows
        if row.get("confirmed_at") is not None
    ]


def _course_record(row: Mapping[str, Any]) -> CourseRecord:
    return CourseRecord(
        course_code=row["course_code"],
        credit_hours=float(row["credit_hours"]),
        letter_grade=row.get("letter_grade"),
        credit_type=row["credit_type"],
        status=row["status"],
        institution_id=row.get("institution_id") or "",
        confirmed_at=row.get("confirmed_at"),
        excluded_from_gpa_by=row.get("excluded_from_gpa_by"),
    )


def _term_order(row: Mapping[str, Any]) -> tuple[int, int, int]:
    season = str(row.get("season") or "").strip().title()
    return (int(row.get("year") or 0), SEASON_ORDER.get(season, 99), int(row.get("sequence") or 0))


def _gpa_by_term(
    confirmed_courses: Sequence[Mapping[str, Any]],
    term_rows: Sequence[Mapping[str, Any]],
    institution: Institution,
    grade_map: Mapping[str, GradeMapRow],
) -> list[TermGpaPoint]:
    """Term and running-cumulative GPA, one point per term, oldest first.

    Every figure goes through compute_gpa, so repeat exclusions, transfer and
    exam rules and grade mapping match the headline Official/Projected GPA.
    A term with in-progress courses uses the 'projected' scope (current
    grades); every other term uses 'official'. Rows with no term (transfer,
    exam credit) count toward the cumulative from the first point on.
    """
    records_by_term: dict[str, list[CourseRecord]] = {}
    running: list[CourseRecord] = []
    for row in confirmed_courses:
        record = _course_record(row)
        term_id = row.get("term_id")
        if term_id:
            records_by_term.setdefault(str(term_id), []).append(record)
        else:
            running.append(record)

    points: list[TermGpaPoint] = []
    for term in sorted(term_rows, key=_term_order):
        term_records = records_by_term.get(str(term["id"]), [])
        if not term_records:
            continue
        running.extend(term_records)
        projected = any(record.status == "in_progress" for record in term_records)
        mode = "projected" if projected else "official"
        term_result = compute_gpa(term_records, institution, dict(grade_map), mode=mode)
        if term_result.gpa is None:
            continue
        cumulative = compute_gpa(list(running), institution, dict(grade_map), mode=mode)
        points.append(
            TermGpaPoint(
                term_id=str(term["id"]),
                term_key=term_key(term.get("year"), term.get("season")),
                label=term.get("label") or term_key(term.get("year"), term.get("season")),
                term_gpa=term_result.gpa,
                cumulative_gpa=cumulative.gpa,
                gpa_hours=term_result.gpa_hours,
                projected=projected,
            )
        )
    return points


def build_student_intelligence_profile(
    client: Any, student_id: str
) -> StudentIntelligenceProfile:
    """Build the canonical, validated profile using only session-scoped reads."""
    student_rows = client.table("students").select("*").eq("id", student_id).execute().data
    if not student_rows:
        raise LookupError(f"No students row visible for id {student_id!r}.")
    student = student_rows[0]
    home, institution_row = _resolve_home_institution(client, student_id)

    career_rows = (
        client.table("career_profiles").select("*").eq("student_id", student_id).execute().data
    )
    career_row = career_rows[0] if career_rows else None
    career_confirmed = bool(career_row and career_row.get("confirmed_at") is not None)
    child_rows = {
        table: client.table(table).select("*").eq("student_id", student_id).execute().data
        if career_confirmed
        else []
        for table in _CHILD_TABLES
    }

    term_rows = (
        client.table("academic_terms").select("*").eq("student_id", student_id).execute().data
    )
    all_course_rows = (
        client.table("course_records").select("*").eq("student_id", student_id).execute().data
    )
    confirmed_courses = [row for row in all_course_rows if row.get("confirmed_at") is not None]
    confirmed_term_ids = {row.get("term_id") for row in confirmed_courses if row.get("term_id")}
    confirmed_terms = [row for row in term_rows if row.get("id") in confirmed_term_ids]

    both = None
    by_term: list[TermGpaPoint] = []
    if institution_row:
        grade_rows = (
            client.table("grade_point_map")
            .select("*")
            .eq("institution_id", institution_row["id"])
            .execute()
            .data
        )
        if grade_rows:
            grade_map = {
                row["letter"]: GradeMapRow(
                    letter=row["letter"],
                    points=float(row["points"]) if row.get("points") is not None else None,
                    counts_toward_gpa=bool(row["counts_toward_gpa"]),
                    counts_toward_credit=bool(row["counts_toward_credit"]),
                )
                for row in grade_rows
            }
            institution = Institution(
                id=str(institution_row["id"]),
                name=institution_row["name"],
                uses_plus_minus=bool(institution_row.get("uses_plus_minus", True)),
                transfer_grades_count_toward_gpa=bool(
                    institution_row.get("transfer_grades_count_toward_gpa", False)
                ),
            )
            # Confirmation is the canonical transcript boundary. The existing
            # GPA authority still performs every calculation; the adapter only
            # controls which persisted records belong to canonical history.
            both = compute_both(
                [_course_record(row) for row in confirmed_courses], institution, grade_map
            )
            by_term = _gpa_by_term(confirmed_courses, confirmed_terms, institution, grade_map)

    career = Career(
        confirmed=career_confirmed,
        target_roles=(career_row.get("target_roles") or []) if career_confirmed else [],
        interests=(career_row.get("interests") or []) if career_confirmed else [],
        career_goals=career_row.get("career_goals") if career_confirmed else None,
        geographic_preference=career_row.get("geographic_preference") if career_confirmed else None,
        ai_anxiety_level=career_row.get("ai_anxiety_level") if career_confirmed else None,
        skills=Skills(
            technical=(career_row.get("skills_technical") or []) if career_confirmed else [],
            soft=(career_row.get("skills_soft") or []) if career_confirmed else [],
            ai_exposure=career_row.get("ai_exposure") if career_confirmed else None,
        ),
        certifications=_career_items(child_rows["certifications"]),
        work_experience=_career_items(child_rows["work_experience"]),
        projects=_career_items(child_rows["projects"]),
    )
    gpa = GpaProfile(
        official=both.official.gpa if both else None,
        projected=both.projected.gpa if both else None,
        computable=bool(both and (both.official.gpa is not None or both.projected.gpa is not None)),
        in_progress_with_current_grade_count=sum(
            1
            for row in confirmed_courses
            if row.get("status") == "in_progress" and row.get("letter_grade")
        ),
        by_term=by_term,
    )
    academics = Academics(
        summary=AcademicSummary(
            major_current=student.get("major_current"),
            major_intended=student.get("major_intended"),
            confirmed_course_count=len(confirmed_courses),
            completed_hours=both.completed_hours if both else 0.0,
            in_progress_hours=both.in_progress_hours if both else 0.0,
            earned_hours=both.official.earned_hours if both else 0.0,
        ),
        terms=[AcademicTerm.model_validate({k: row[k] for k in ("id", "institution_id", "label", "year", "season", "sequence")}) for row in confirmed_terms],
        courses=[AcademicCourse.model_validate({
            "id": str(row["id"]), "term_id": row.get("term_id"),
            "institution_id": row.get("institution_id"), "course_code": row["course_code"],
            "title": row.get("title"), "credit_hours": float(row["credit_hours"]),
            "letter_grade": row.get("letter_grade"), "credit_type": row["credit_type"],
            "status": row["status"], "source": row["source"],
        }) for row in confirmed_courses],
        gpa=gpa,
        repeat_exclusions=[
            RepeatExclusionProfile(
                excluded_course_id=str(row["id"]),
                superseded_by_course_id=str(row["excluded_from_gpa_by"]),
            )
            for row in confirmed_courses if row.get("excluded_from_gpa_by")
        ],
    )
    career_ready = bool(career.confirmed and career.target_roles and (career.skills.technical or career.skills.soft))
    academic_ready = bool(academics.courses and academics.terms)
    completeness = Completeness(
        career=CareerCompleteness(
            confirmed_profile=career.confirmed,
            target_role_present=bool(career.target_roles),
            skills_present=bool(career.skills.technical or career.skills.soft),
            certifications_present=bool(career.certifications),
            work_experience_present=bool(career.work_experience),
            projects_present=bool(career.projects),
            ready_for_career_features=career_ready,
        ),
        academics=AcademicCompleteness(
            transcript_data_present=bool(academics.courses),
            terms_present=bool(academics.terms),
            gpa_computable=gpa.computable,
            ready_for_academic_features=academic_ready,
        ),
        overall="ready" if career_ready and academic_ready else "partial" if career_ready or academic_ready else "minimal",
    )
    course_sources = sorted({str(row.get("source")) for row in confirmed_courses if row.get("source")})
    return StudentIntelligenceProfile(
        identity=Identity(
            student_id=str(student["id"]), name=student.get("name"),
            classification=student.get("classification"),
            expected_graduation=student.get("expected_graduation"),
            onboarding_stage=student.get("onboarding_stage"),
        ),
        institution=InstitutionProfile(
            id=str(institution_row["id"]) if institution_row else None,
            name=institution_row.get("name") if institution_row else None,
            relationship="home" if home else None,
        ),
        academics=academics, career=career, completeness=completeness,
        provenance=Provenance(
            career_profile=career_row.get("source") if career_confirmed else None,
            certifications=sorted({str(row.get("source")) for row in child_rows["certifications"] if row.get("confirmed_at") and row.get("source")}),
            work_experience=sorted({str(row.get("source")) for row in child_rows["work_experience"] if row.get("confirmed_at") and row.get("source")}),
            projects=sorted({str(row.get("source")) for row in child_rows["projects"] if row.get("confirmed_at") and row.get("source")}),
            academics=course_sources,
            credit_type_limitation=("Transcript parsing currently defaults credit_type to resident; transfer and dual-enrollment classification is unresolved." if "transcript_parse" in course_sources else None),
        ),
    )


def canonical_to_legacy_profile(profile: StudentIntelligenceProfile) -> dict[str, Any]:
    """Compatibility view for consumers still expecting the demo-era shape.

    Career runners read ``student`` and ``career``. GAP additionally passes the
    top-level ``courses`` list into its prompt context. Keep that boundary as a
    pure in-memory projection of the canonical contract: these are already the
    confirmed-only courses selected by ``build_student_intelligence_profile``.
    """
    career = None
    if profile.career.confirmed:
        def legacy_items(items: Sequence[Any]) -> list[dict[str, Any]]:
            return [
                {key: value for key, value in item.model_dump().items() if key != "source"}
                for item in items
            ]

        career = {
            "target_roles": profile.career.target_roles,
            "interests": profile.career.interests,
            "career_goals": profile.career.career_goals or "",
            "geographic_preference": profile.career.geographic_preference or "",
            "ai_anxiety_level": profile.career.ai_anxiety_level or "",
            "skills_self_reported": {
                "technical": profile.career.skills.technical,
                "soft": profile.career.skills.soft,
                "ai_exposure": profile.career.skills.ai_exposure or "",
            },
            "certifications": legacy_items(profile.career.certifications),
            "work_experience": legacy_items(profile.career.work_experience),
            "projects": legacy_items(profile.career.projects),
        }
    return {
        "student": {
            "id": profile.identity.student_id,
            "name": profile.identity.name,
            "classification": profile.identity.classification,
            "major_current": profile.academics.summary.major_current,
            "major_intended": profile.academics.summary.major_intended,
            "expected_graduation": profile.identity.expected_graduation,
            "onboarding_stage": profile.identity.onboarding_stage,
            "institution": profile.institution.name,
            "gpa_current": None,
        },
        "career": career,
        "courses": [course.model_dump(mode="json") for course in profile.academics.courses],
    }


def build_profile_from_supabase(client: Any, student_id: str) -> ProfileBuildResult:
    """Assemble a runner-compatible profile dict for one student.

    `client` must already be session-scoped (build_client_for_token). RLS is the
    real boundary here: the students select carries no filter at all, exactly as
    GET /api/v2/student/me/gpa does, and the child selects filter on student_id
    only because they need to join, not because they are trusted to isolate.

    Returns career=None when the student has no career_profiles row -- the state
    right after signup, before any parser or manual entry has run. That mirrors
    the file-backed path, whose StudentProfile type declares
    `career: CareerBlock | null` and whose frontend adapter already handles null
    via emptyCareerBlock(). No demo JSON currently exercises it, but it is an
    anticipated shape, not an invented one.
    """
    student_rows = client.table("students").select("*").eq("id", student_id).execute().data
    if not student_rows:
        raise LookupError(f"No students row visible for id {student_id!r}.")
    student_row = student_rows[0]

    # Resolved before any early return so the student block is identical
    # whether or not a career_profiles row exists.
    institution_name = _resolve_institution_name(client, student_id)

    career_rows = (
        client.table("career_profiles").select("*").eq("student_id", student_id).execute().data
    )

    exclusions: list[tuple[Mapping[str, Any], str]] = []

    # No career_profiles row at all -- distinct from an unconfirmed one.
    if not career_rows:
        return ProfileBuildResult(
            profile={
                "student": _student_block(student_row, institution_name),
                "career": None,
            },
            exclusions=exclusions,
        )

    career_row = career_rows[0]

    # An unconfirmed career_profiles row takes the whole career block with it.
    # This is binary by construction: career_profiles is a single row, so there
    # is no schema-level notion of a half-confirmed profile. Returning the
    # scalars while dropping the child lists would be worse -- the runners would
    # see target_roles present and work_experience empty, and read that as "this
    # student has no work history" rather than "nothing here is reviewed yet".
    if career_row.get("confirmed_at") is None:
        exclusions.append((career_row, UNCONFIRMED_REASON))
        return ProfileBuildResult(
            profile={
                "student": _student_block(student_row, institution_name),
                "career": None,
            },
            exclusions=exclusions,
        )

    children: dict[str, list[dict[str, Any]]] = {}
    for table in _CHILD_TABLES:
        rows = client.table(table).select("*").eq("student_id", student_id).execute().data
        included, excluded = _partition_confirmed(rows)
        children[table] = included
        exclusions.extend(excluded)

    return ProfileBuildResult(
        profile={
            "student": _student_block(student_row, institution_name),
            "career": _career_block(career_row, children),
        },
        exclusions=exclusions,
    )
