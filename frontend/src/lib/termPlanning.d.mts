export interface PlanningTerm {
  key: string;
  id: string | null;
  label: string;
  year: number;
  season: string;
  sequence: number | null;
  start_date: string | null;
  end_date: string | null;
  enrolled: boolean;
  is_upcoming: boolean;
}

export interface PlannedCourse {
  id: string;
  term_id: string | null;
  course_code: string;
  title: string | null;
  credit_hours: number | null;
  catalog_course_id: string | null;
  created_at: string | null;
  kind: 'planned';
}

/** Returned from POST /planned-courses when the term was already inside its
 * activation window -- written straight into course_records, never through
 * planned_courses. */
export interface InProgressCourseResult {
  id: string;
  term_id: string | null;
  course_code: string;
  title: string | null;
  credit_hours: number | null;
  letter_grade: string | null;
  status: 'in_progress';
  kind: 'in_progress';
}

export type AddedCourseResult = PlannedCourse | InProgressCourseResult;

export interface PendingFinalGrade {
  id: string;
  term_id: string;
  term_label: string | null;
  course_code: string;
  title: string | null;
  credit_hours: number | null;
}

export interface GradingSchemaGrade {
  letter: string;
  points: number | null;
  counts_toward_gpa: boolean;
  counts_toward_credit: boolean;
}

export interface GradingSchema {
  institutionId: string | null;
  usesPlusMinus: boolean;
  grades: GradingSchemaGrade[];
}

export interface CatalogSearchResult {
  id: string;
  code: string;
  title: string;
  department: string | null;
  course_level: number | null;
  credit_min: number | null;
  credit_max: number | null;
}

export type TermStatus = 'upcoming' | 'in_progress' | 'past' | 'unknown';

export interface TermsPayload {
  terms: PlanningTerm[];
  upcoming_term_key: string | null;
}

export interface NormalizedTerms { ok: boolean; terms: PlanningTerm[]; upcomingTermKey: string | null }
export interface NormalizedPlanned { ok: boolean; plannedCourses: PlannedCourse[] }
export interface NormalizedSearch { ok: boolean; results: CatalogSearchResult[] }

export declare const TERMS_URL: string;
export declare const PLANNED_COURSES_URL: string;
export declare const CATALOG_SEARCH_URL: string;
export declare const SEASON_ORDER: Record<string, number>;
export declare const UNKNOWN_SEASON_ORDINAL: number;
export declare const MIN_SEARCH_LENGTH: number;
export declare const SEARCH_DEBOUNCE_MS: number;
export declare const TERM_STATUS_LABELS: Record<TermStatus, string>;
export declare const COURSE_RECORDS_URL: string;
export declare const PENDING_FINAL_GRADES_URL: string;
export declare const ACTIVATION_WINDOW_DAYS: number;
export declare const GRADING_SCHEMA_URL: string;
export declare const CROSS_LISTINGS_URL: string;

export declare function currentGradeOptions(schema: GradingSchema | null | undefined): string[];
export declare function finalGradeOptions(schema: GradingSchema | null | undefined): string[];

export declare function courseRecordUrl(id: string): string;
export declare function finalizeCourseUrl(id: string): string;
export declare function isTermActivated(term: PlanningTerm | null | undefined, today: Date): boolean;

export declare function seasonOrdinal(season: string): number;
export declare function plannedRemoveUrl(id: string): string;
export declare function plannedListUrl(termId: string | null | undefined): string;
export declare function catalogSearchUrl(query: string): string;
export declare function sortTerms(terms: PlanningTerm[]): PlanningTerm[];
export declare function pickDefaultTermKey(
  payload: Partial<TermsPayload> | null | undefined,
  today?: Date,
): string | null;
export declare function termStatus(term: PlanningTerm | null | undefined, today: Date): TermStatus;
export declare function parseDate(value: string | null | undefined): Date | null;
export declare function formatTermDates(term: PlanningTerm | null | undefined): string | null;
export declare function termCourseGroups<R extends { term_id: string | null }>(
  termId: string | null,
  courseRecords: R[],
  plannedCourses: PlannedCourse[],
): { records: R[]; planned: PlannedCourse[] };
export declare function plannedCodes(plannedCourses: PlannedCourse[]): Set<string>;
export declare function formatCredits(min: number | null, max: number | null): string | null;
export declare function normalizeTermsPayload(status: number, body: unknown): NormalizedTerms;
export declare function normalizePlannedPayload(status: number, body: unknown): NormalizedPlanned;
export declare function normalizeSearchPayload(status: number, body: unknown): NormalizedSearch;
export interface NormalizedPendingFinalGrades { ok: boolean; pendingFinalGrades: PendingFinalGrade[] }
export declare function normalizePendingFinalGradesPayload(
  status: number,
  body: unknown,
): NormalizedPendingFinalGrades;
export interface NormalizedGradingSchema { ok: boolean; schema: GradingSchema | null }
export declare function normalizeGradingSchemaPayload(
  status: number,
  body: unknown,
): NormalizedGradingSchema;

/** code -> its cross-listed partner codes, both sides uppercased. */
export type CrossListingMap = Record<string, string[]>;
export interface NormalizedCrossListings { ok: boolean; crossListings: CrossListingMap }
export declare function normalizeCrossListingsPayload(
  status: number,
  body: unknown,
): NormalizedCrossListings;

export type ExistingCourseStatus = 'in_progress' | 'completed' | 'planned';
export declare function existingCourseStatusIndex<R extends { course_code: string; status?: string }>(
  courseRecords: R[],
  plannedCourses: Array<{ course_code: string }>,
): Map<string, ExistingCourseStatus>;
export declare function findCrossListedMatch(
  code: string,
  crossListings: CrossListingMap,
  existingIndex: Map<string, ExistingCourseStatus>,
): { code: string; status: ExistingCourseStatus } | null;
