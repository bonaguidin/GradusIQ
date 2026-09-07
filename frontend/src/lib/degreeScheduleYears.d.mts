import type { PlanningTerm, GradingSchema, PlannedCourse, CrossListingMap } from './termPlanning.mjs';
import type {
  RequirementCandidate,
  RequirementCandidateSet,
  RequirementDecision,
  TermPlan,
} from '../api/degreeSchedule.mjs';

export type SemesterSeason = 'Fall' | 'Spring';
export type SemesterState = 'past' | 'in_progress' | 'future';

export interface CourseRecordLike {
  id: string;
  term_id: string | null;
  course_code: string;
  title: string | null;
  credit_hours: number | string;
  letter_grade: string | null;
  status: string;
}

export interface DegreeScheduleYearCourse {
  course_code: string;
  title: string | null;
  credit_hours: number | string;
  gradeBadge: string | null;
}

export interface DegreeScheduleSuggestedCourse {
  course_code: string;
  credit_hours: number;
}

/** A course the student added to a future term themselves (planned_courses).
 * `id` is the planned_courses row id, needed for the row's Remove action. */
export interface DegreeSchedulePlannedCourse {
  id: string;
  course_code: string;
  title: string | null;
  credit_hours: number | null;
}

/** Phase 3: a LOCKED / CHOICE_REQUIRED / EXCLUDED decision relocated onto
 * the term card the backend resolved for it. `candidates` are the feasible
 * candidates (LOCKED/CHOICE_REQUIRED) or the excluded candidate(s)
 * (EXCLUDED), carried for course-code display only. */
export type TermCardDecisionState = 'LOCKED' | 'CHOICE_REQUIRED' | 'EXCLUDED';

export interface DegreeScheduleTermDecision {
  requirementGroupId: string;
  requirementName: string;
  state: TermCardDecisionState;
  selectedCandidateId: string | null;
  candidates: RequirementCandidate[];
  termKey: string;
}

export interface DegreeScheduleSemester {
  season: SemesterSeason;
  termKey: string;
  state: SemesterState;
  totalCreditsLabel: string | null;
  courses: DegreeScheduleYearCourse[];
  suggestedCourses: DegreeScheduleSuggestedCourse[];
  planned: DegreeSchedulePlannedCourse[];
  decisions: DegreeScheduleTermDecision[];
}

export interface DegreeScheduleYear {
  yearKey: number;
  label: string;
  semesters: DegreeScheduleSemester[];
}

export declare const YEAR_SEMESTER_SEASONS: SemesterSeason[];

export declare function academicYearLabel(index: number): string;
export declare function academicYearKey(year: number, season: string): number | null;
export declare function formatGradeBadge(
  letterGrade: string | null,
  gradingSchema: GradingSchema | null | undefined,
): string | null;
export declare function semesterState(
  realTerm: PlanningTerm | null | undefined,
  today: Date,
): SemesterState;
export declare const TERM_CARD_DECISION_STATES: TermCardDecisionState[];

export declare function bucketDecisionsByTerm(
  decisions: RequirementDecision[] | null | undefined,
  candidateSets: RequirementCandidateSet[] | null | undefined,
): Map<string, DegreeScheduleTermDecision[]>;

export declare function buildDegreeScheduleYears(input: {
  realTerms: PlanningTerm[];
  scheduleTerms: TermPlan[];
  courseRecords: CourseRecordLike[];
  gradingSchema: GradingSchema | null;
  today: Date;
  plannedCourses?: PlannedCourse[];
  decisions?: RequirementDecision[];
  candidateSets?: RequirementCandidateSet[];
  /** code -> cross-listed partner codes, for reconciling a suggested course
   * against its cross-listed planned twin, not just an exact-code match. */
  crossListings?: CrossListingMap;
}): DegreeScheduleYear[];
