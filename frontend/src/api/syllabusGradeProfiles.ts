// Fetch layer for the Grade Calculator (syllabus What-If Calculator) feature.
//
// Mirrors resume.ts/degreeSchedule.mjs: same-origin relative paths (Vercel
// proxy attaches the session bearer + secret header), typed response shapes
// hand-mirrored from the backend Pydantic contracts. No calculator math, no
// PDF/reconciliation logic lives here -- every call is a thin wrapper over
// one /api/v2/student/me/syllabus-grade-profiles/* route.

const BASE_URL = '/api/v2/student/me/syllabus-grade-profiles';

export class SyllabusApiError extends Error {
  status: number;
  code: string | null;

  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.name = 'SyllabusApiError';
    this.status = status;
    this.code = code;
  }
}

export interface SyllabusEvidence {
  page: number | null;
  text: string | null;
  confidence: number | null;
}

export interface SyllabusCategory {
  name: string;
  weight: number | null;
  count: number | null;
  evidence: SyllabusEvidence | null;
}

export interface SyllabusAssessment {
  name: string;
  category: string | null;
  date: string | null;
  weight: number | null;
  points: number | null;
  evidence: SyllabusEvidence | null;
}

export interface SyllabusThreshold {
  letter: string;
  minimum: number | null;
  maximum: number | null;
  evidence: SyllabusEvidence | null;
}

export interface SyllabusRule {
  rule_type: 'replacement' | 'drop' | 'curve' | 'extra_credit' | 'late_work' | 'makeup' | 'other';
  description: string;
  source: string | null;
  target: string | null;
  condition: string | null;
  evidence: SyllabusEvidence | null;
}

export interface SyllabusWarning {
  type: string;
  description: string;
  related_field: string | null;
}

export interface SyllabusGradeModel {
  schema_version: string;
  course: { course_code: string | null; course_title: string | null; section: string | null; term: string | null; instructor: string | null };
  grading_method: 'weighted' | 'points' | 'hybrid' | 'unknown';
  categories: SyllabusCategory[];
  assessments: SyllabusAssessment[];
  grade_thresholds: SyllabusThreshold[];
  rules: SyllabusRule[];
  warnings: SyllabusWarning[];
}

export interface SyllabusFinding {
  code: string;
  severity: 'valid' | 'warning' | 'error';
  message: string;
  field: string | null;
}

export interface SyllabusReconciliation {
  status: 'accepted' | 'needs_student_review';
  findings: SyllabusFinding[];
  evidence_coverage: { total_claims: number; supported_claims: number; coverage_ratio: number; unsupported_claims: string[] };
}

// Cutoff-overlap resolution proposal (backend: cutoff_resolution.py). A
// `resolved` entry is a "higher grade wins the tie" default the student can
// confirm as-is; an `unresolved` entry (non-adjacent / multi-way /
// wider-than-a-point / single-bound / non-canonical) the backend refuses
// to guess at -- it needs a manual threshold correction. `letters` is
// [winner, loser] for resolved entries.
export interface SyllabusResolvedCutoffOverlap {
  letters: [string, string];
  boundary: number;
  winner: string;
  loser: string;
}

export interface SyllabusUnresolvedCutoffOverlap {
  letters: [string, string];
  reason: string;
}

export interface SyllabusCutoffOverlapResolution {
  schema_version: string;
  resolved: SyllabusResolvedCutoffOverlap[];
  unresolved: SyllabusUnresolvedCutoffOverlap[];
}

// Keyed answer log persisted on the revision (backend:
// apply_student_corrections merges these). Keys in use:
//   `cutoff_overlap:<winner>,<loser>`   -> { answer, boundary, winner, loser }
//   `claim_evidence:threshold:<letter>` -> { answer, letter }
//   `claim_evidence:category:<name>`   -> { answer, category_name }
// The category key is a separate namespace from the threshold one, not a
// variant of it -- mirrors reconcile_grade_model's separate
// confirmed_category_value_claims parameter (see corrections.py's
// CONFIRM_CATEGORY_VALUE).
export type SyllabusClarifyingAnswers = Record<
  string,
  { answer: string; boundary?: number; winner?: string; loser?: string; letter?: string; category_name?: string }
>;

export interface SyllabusCategoryScore {
  category_name: string;
  actual_score?: number | null;
  projected_score?: number | null;
}

export interface SyllabusAssessmentScore {
  assessment_name: string;
  actual_score?: number | null;
  projected_score?: number | null;
  earned_points?: number | null;
  possible_points?: number | null;
  points_status?: 'completed' | 'projected' | null;
}

export interface SyllabusGradeState {
  category_scores: SyllabusCategoryScore[];
  assessment_scores: SyllabusAssessmentScore[];
}

// Trimmed per-component slice the list endpoint serializes for a course
// card's ring: one segment per component, sized by weight_percent, filled by
// effective_score. status null + effective_score null = ungraded (empty
// segment); effective_score 0 with a status = a real scored zero. The fuller
// SyllabusCalculationComponent (original_score, contribution, points) is only
// on the /calculate response, not here.
export interface SyllabusListCardComponent {
  name: string;
  source_type: 'category' | 'assessment';
  weight_percent: number | null;
  effective_score: number | null;
  status: 'completed' | 'projected' | null;
}

export interface SyllabusProfileSummary {
  id: string;
  institution: string | null;
  course_code: string | null;
  term: string | null;
  section: string | null;
  review_state: 'needs_review' | 'confirmed' | 'reconfirm_required';
  created_at: string;
  updated_at: string;
  calculator_ready?: boolean;
  current_grade?: number | null;
  current_letter_grade?: string | null;
  components?: SyllabusListCardComponent[];
}

export interface SyllabusProfileDetail {
  id: string;
  course: { institution: string | null; course_code: string | null; term: string | null; section: string | null };
  review_state: 'needs_review' | 'confirmed' | 'reconfirm_required';
  calculator_ready: boolean;
  current_revision: { id: string; source_filename: string | null; source_page_count: number | null; reconciliation_status: string; confirmed_reconciliation_status: string | null; confirmed_at: string | null; created_at: string } | null;
  extracted_grade_model: SyllabusGradeModel | null;
  confirmed_grade_model: SyllabusGradeModel | null;
  reconciliation: SyllabusReconciliation | null;
  confirmed_reconciliation: SyllabusReconciliation | null;
  corrections: SyllabusCorrection[];
  clarifying_answers: SyllabusClarifyingAnswers;
  cutoff_overlap_resolution: SyllabusCutoffOverlapResolution;
  // Names of confirmed_grade_model categories the backend proves decomposable
  // (weighting._decomposition_children): their assessments can be scored
  // individually. Empty when there is no confirmed model. Source of truth is
  // the backend -- never re-derive the gate client-side.
  decomposable_categories: string[];
  grade_state: SyllabusGradeState | null;
  grade_state_revision: number | null;
  possible_duplicate_profiles?: SyllabusProfileSummary[];
  revision_created?: boolean;
}

export interface SyllabusCorrection {
  target_type: 'category' | 'assessment' | 'threshold' | 'rule' | 'grading_method' | 'warning';
  operation: string;
  category_name?: string | null;
  assessment_name?: string | null;
  threshold_letter?: string | null;
  rule_index?: number | null;
  warning_index?: number | null;
  value?: unknown;
}

export interface SyllabusCalculationComponent {
  name: string;
  source_type: 'category' | 'assessment';
  status: 'completed' | 'projected' | null;
  original_score: number | null;
  effective_score: number | null;
  weight_percent: number | null;
  contribution: number | null;
  earned_points: number | null;
  possible_points: number | null;
}

export interface SyllabusAppliedRule {
  rule_type: string;
  source: string | null;
  target: string | null;
  changed_calculation: boolean;
  description: string;
}

export interface SyllabusCalculationResult {
  grading_method: string;
  components: SyllabusCalculationComponent[];
  completed_weight: number | null;
  earned_course_percentage: number | null;
  current_grade: number | null;
  projected_grade: number | null;
  current_letter_grade: string | null;
  projected_letter_grade: string | null;
  applied_rules: SyllabusAppliedRule[];
  warnings: string[];
}

export interface SyllabusTargetResult {
  target_component: string;
  target_grade: number;
  target_label: string | null;
  required_score: number | null;
  feasible: boolean;
  already_achieved: boolean;
  applied_rules: SyllabusAppliedRule[];
  warnings: string[];
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function detailMessage(body: unknown, fallback: string): { message: string; code: string | null } {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') {
      const normalized = detail.trim().toLowerCase();
      if (normalized === 'not found' || normalized === 'internal server error') {
        return { message: fallback, code: null };
      }
      return { message: detail, code: null };
    }
    if (detail && typeof detail === 'object') {
      const record = detail as Record<string, unknown>;
      const message = typeof record.message === 'string' ? record.message : fallback;
      const code = typeof record.error === 'string' ? record.error : null;
      return { message, code };
    }
  }
  return { message: fallback, code: null };
}

async function request<T>(url: string, init: RequestInit, fallbackMessage: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new SyllabusApiError(0, 'CampusIQ is unavailable right now. Try again in a moment.');
  }
  const body = await readJson(response);
  if (response.ok) return body as T;
  const { message, code } = detailMessage(body, fallbackMessage);
  throw new SyllabusApiError(response.status, message, code);
}

function authHeaders(accessToken: string): Record<string, string> {
  return { Accept: 'application/json', Authorization: `Bearer ${accessToken}` };
}

function jsonHeaders(accessToken: string): Record<string, string> {
  return { ...authHeaders(accessToken), 'Content-Type': 'application/json' };
}

export async function listSyllabusGradeProfiles(accessToken: string): Promise<SyllabusProfileSummary[]> {
  const data = await request<{ syllabus_grade_profiles: SyllabusProfileSummary[] }>(
    BASE_URL,
    { method: 'GET', headers: authHeaders(accessToken) },
    "We couldn't load your saved grade calculators. Try again.",
  );
  return data.syllabus_grade_profiles;
}

export async function getSyllabusGradeProfile(accessToken: string, profileId: string): Promise<SyllabusProfileDetail> {
  return request<SyllabusProfileDetail>(
    `${BASE_URL}/${encodeURIComponent(profileId)}`,
    { method: 'GET', headers: authHeaders(accessToken) },
    'Could not load this grade calculator.',
  );
}

export async function ingestSyllabus(
  accessToken: string,
  file: File,
  course: { institution?: string; course_code?: string; term?: string; section?: string; profile_id?: string },
): Promise<SyllabusProfileDetail> {
  const form = new FormData();
  form.append('file', file);
  if (course.institution) form.append('institution', course.institution);
  if (course.course_code) form.append('course_code', course.course_code);
  if (course.term) form.append('term', course.term);
  if (course.section) form.append('section', course.section);
  if (course.profile_id) form.append('profile_id', course.profile_id);

  return request<SyllabusProfileDetail>(
    `${BASE_URL}/ingest`,
    { method: 'POST', headers: authHeaders(accessToken), body: form },
    "CampusIQ couldn't process this syllabus.",
  );
}

export async function submitSyllabusCorrections(
  accessToken: string,
  profileId: string,
  corrections: SyllabusCorrection[],
): Promise<SyllabusProfileDetail> {
  return request<SyllabusProfileDetail>(
    `${BASE_URL}/${encodeURIComponent(profileId)}/corrections`,
    { method: 'POST', headers: jsonHeaders(accessToken), body: JSON.stringify({ corrections }) },
    'Could not save your corrections.',
  );
}

export async function confirmSyllabusGradeModel(accessToken: string, profileId: string): Promise<SyllabusProfileDetail> {
  return request<SyllabusProfileDetail>(
    `${BASE_URL}/${encodeURIComponent(profileId)}/confirm`,
    { method: 'POST', headers: authHeaders(accessToken) },
    'Could not confirm this grading model.',
  );
}

export async function deleteSyllabusGradeProfile(accessToken: string, profileId: string): Promise<void> {
  await request<{ removed: string }>(
    `${BASE_URL}/${encodeURIComponent(profileId)}`,
    { method: 'DELETE', headers: authHeaders(accessToken) },
    'Could not remove this grade calculator.',
  );
}

export async function saveSyllabusGradeState(
  accessToken: string,
  profileId: string,
  gradeState: SyllabusGradeState,
  expectedRevision: number | null,
): Promise<{ revision: number; category_scores: SyllabusCategoryScore[]; assessment_scores: SyllabusAssessmentScore[] }> {
  return request(
    `${BASE_URL}/${encodeURIComponent(profileId)}/grade-state`,
    {
      method: 'PUT',
      headers: jsonHeaders(accessToken),
      body: JSON.stringify({ ...gradeState, expected_revision: expectedRevision }),
    },
    'Could not save your grades.',
  );
}

export async function calculateSyllabusGrade(
  accessToken: string,
  profileId: string,
  gradeState: SyllabusGradeState,
): Promise<SyllabusCalculationResult> {
  return request<SyllabusCalculationResult>(
    `${BASE_URL}/${encodeURIComponent(profileId)}/calculate`,
    { method: 'POST', headers: jsonHeaders(accessToken), body: JSON.stringify(gradeState) },
    'Could not calculate your grade.',
  );
}

// NOTE: currently unused. The Target Grade card that called this was removed
// from GradeCalculatorPanel in favour of the live projection flow; the
// `.../solve-target` endpoint and its engine path are still in place and this
// wrapper is kept ready for a future caller.
export async function solveSyllabusTarget(
  accessToken: string,
  profileId: string,
  gradeState: SyllabusGradeState,
  target: { target_component: string; target_grade?: number; target_letter?: string },
): Promise<SyllabusTargetResult> {
  return request<SyllabusTargetResult>(
    `${BASE_URL}/${encodeURIComponent(profileId)}/solve-target`,
    { method: 'POST', headers: jsonHeaders(accessToken), body: JSON.stringify({ ...gradeState, ...target }) },
    'Could not solve for that target.',
  );
}
