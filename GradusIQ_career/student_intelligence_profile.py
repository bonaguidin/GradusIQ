"""Validated application contract for a real authenticated student profile.

The models here are a domain/API representation, not a persistence model.
Supabase remains normalized; :mod:`profile_builder` is the adapter boundary.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Identity(ContractModel):
    student_id: str
    name: str | None = None
    classification: str | None = None
    expected_graduation: str | None = None
    onboarding_stage: int | None = None


class InstitutionProfile(ContractModel):
    id: str | None = None
    name: str | None = None
    relationship: Literal["home"] | None = None


class AcademicSummary(ContractModel):
    major_current: str | None = None
    major_intended: str | None = None
    confirmed_course_count: int = 0
    completed_hours: float = 0.0
    in_progress_hours: float = 0.0
    earned_hours: float = 0.0


class AcademicTerm(ContractModel):
    id: str
    institution_id: str
    label: str
    year: int
    season: str
    sequence: int


class AcademicCourse(ContractModel):
    id: str
    term_id: str | None = None
    institution_id: str | None = None
    course_code: str
    title: str | None = None
    credit_hours: float
    letter_grade: str | None = None
    credit_type: str
    status: str
    source: str


class TermGpaPoint(ContractModel):
    """One term on the GPA-by-term chart.

    term_gpa covers only that term's courses; cumulative_gpa covers every
    confirmed course up to and including it (plus term-less transfer/exam
    rows), so the last completed point's cumulative equals the official GPA.
    A term holding in-progress courses is computed in the 'projected' scope
    from their current grades and flagged projected.
    """

    term_id: str
    term_key: str
    label: str
    term_gpa: float
    cumulative_gpa: float | None = None
    gpa_hours: float
    projected: bool = False


class GpaProfile(ContractModel):
    official: float | None = None
    projected: float | None = None
    computable: bool = False
    # Confirmed, in-progress courses that carry a current (non-final) letter
    # grade -- the only records that make projected differ from official.
    # Drives the dashboard's "Based on current grades in N in-progress
    # courses." / "Enter current grades to see your projected GPA." copy
    # without the frontend re-deriving it from the course list.
    in_progress_with_current_grade_count: int = 0
    # Chronological; terms with no GPA-counting grade are left out.
    by_term: list[TermGpaPoint] = Field(default_factory=list)
    source: Literal["gpa_service"] = "gpa_service"


class RepeatExclusionProfile(ContractModel):
    excluded_course_id: str
    superseded_by_course_id: str
    reason: Literal["excluded_by_repeat"] = "excluded_by_repeat"


class Academics(ContractModel):
    summary: AcademicSummary
    terms: list[AcademicTerm] = Field(default_factory=list)
    courses: list[AcademicCourse] = Field(default_factory=list)
    gpa: GpaProfile
    repeat_exclusions: list[RepeatExclusionProfile] = Field(default_factory=list)


class Skills(ContractModel):
    technical: list[str] = Field(default_factory=list)
    soft: list[str] = Field(default_factory=list)
    ai_exposure: str | None = None


class CareerItem(ContractModel):
    """Validated flexible payload for existing relational career child rows."""

    model_config = ConfigDict(extra="allow")
    source: str | None = None


class Career(ContractModel):
    confirmed: bool = False
    target_roles: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    career_goals: str | None = None
    geographic_preference: str | None = None
    ai_anxiety_level: str | None = None
    skills: Skills = Field(default_factory=Skills)
    certifications: list[CareerItem] = Field(default_factory=list)
    work_experience: list[CareerItem] = Field(default_factory=list)
    projects: list[CareerItem] = Field(default_factory=list)


class CareerCompleteness(ContractModel):
    confirmed_profile: bool
    target_role_present: bool
    skills_present: bool
    certifications_present: bool
    work_experience_present: bool
    projects_present: bool
    ready_for_career_features: bool


class AcademicCompleteness(ContractModel):
    transcript_data_present: bool
    terms_present: bool
    gpa_computable: bool
    ready_for_academic_features: bool


class Completeness(ContractModel):
    career: CareerCompleteness
    academics: AcademicCompleteness
    overall: Literal["minimal", "partial", "ready"]


class Provenance(ContractModel):
    career_profile: str | None = None
    certifications: list[str] = Field(default_factory=list)
    work_experience: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    academics: list[str] = Field(default_factory=list)
    credit_type_limitation: str | None = None


class StudentIntelligenceProfile(ContractModel):
    contract_version: Literal["1.0"] = "1.0"
    identity: Identity
    institution: InstitutionProfile
    academics: Academics
    career: Career
    completeness: Completeness
    provenance: Provenance
