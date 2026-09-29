// Mirrors GradusIQ_career/features/gap.py and academic.py's `output_contract`
// dicts. Confirmed against real (non-mocked) DeepSeek R1 output — see
// /tmp/career_result.json and /tmp/academic_result.json from the validation
// run. academic.py's shape matched on the first real call; gap.py's
// must_have_gaps/nice_to_have_gaps did not (contract said bare string[],
// real output was structured objects) and has been corrected here to match.

export type FeatureStatus = 'success' | 'skipped' | 'failed';

/**
 * One unmet precondition behind a 'skipped' result. `label` is authored in
 * base.py's FIELD_LABELS and is the only thing shown to a student; `path` is
 * the dotted profile path, carried for the deep link and never rendered.
 *
 * Optional on FeatureResult because a response produced before base.py started
 * sending it -- anything cached, replayed or captured in an older fixture --
 * has `errors` but no `missing_fields`.
 */
export interface MissingField {
  path: string;
  label: string;
}

export interface FeatureResult<T> {
  feature: string;
  status: FeatureStatus;
  summary: string;
  data: T;
  errors: string[];
  missing_fields?: MissingField[];
}

// ── GAP (readiness check) — gap.py output_contract ──────────────────────────

export interface GapMustHaveGap {
  gap: string;
  why_it_matters?: string;
  why_it_helps?: string;
  how_to_close: string;
}

export interface GapAnalysisData {
  readiness_score: number;
  strengths: string[];
  must_have_gaps: GapMustHaveGap[];
  nice_to_have_gaps: GapMustHaveGap[];
  recommended_next_steps: string[];
}

// ── FIT (role-fit check) — fit.py output_contract ───────────────────────────
// Confirmed against real (non-mocked) DeepSeek R1 output — see
// /tmp/career_result.json from the validation run.

export type FitLevel = 'high' | 'medium' | 'low';

export type FitHiringSignalCoverage = 'available' | 'no_market_data' | 'unavailable';

export interface FitHiringSignal {
  coverage: FitHiringSignalCoverage;
  employers: string[];
  posting_count: number | null;
}

export interface FitRoleMatch {
  role: string;
  fit_level: FitLevel;
  rationale: string;
  supporting_signals: string[];
  missing_signals: string[];
  // Optional: cached/demo results predating this field omit it. fit.py
  // always populates it for live runs (see fit.py's
  // _apply_hiring_signal_ground_truth).
  hiring_signal?: FitHiringSignal;
}

export interface FitAnalysisData {
  role_matches: FitRoleMatch[];
  overall_fit_summary: string;
}

// ── SHIFT (trend-aware guidance) — shift.py output_contract ─────────────────
// Types match ShiftRunner.output_contract field-for-field (task_shifts,
// durable_skills, adjacent_paths, ai_fluency_guidance) — not yet confirmed
// against real (non-mocked) model output, same caveat as GAP.

export interface ShiftTaskShift {
  task: string;
  changing: string;
  meaning: string;
}

export interface ShiftDurableSkill {
  task: string;
  reason: string;
}

export interface ShiftAdjacentPath {
  path: string;
  relevance: string;
  driver: string;
}

export interface ShiftAnalysisData {
  role_evolution_summary: string;
  task_shifts: ShiftTaskShift[];
  durable_skills: ShiftDurableSkill[];
  adjacent_paths: ShiftAdjacentPath[];
  ai_fluency_guidance: string[];
}

// ── PROFESSOR_COMMENTS (academic.py output_contract) ─────────────────────────

export type ThemeCategory = 'strength' | 'concern' | 'praise' | 'flag';

export interface ThemeReference {
  course_code: string;
  course_name: string;
  paraphrase: string;
}

export interface Theme {
  theme: string;
  category: ThemeCategory;
  summary: string;
  supporting_references: ThemeReference[];
}

export interface ProfessorCommentAnalysisData {
  themes: Theme[];
  overall_summary: string;
}

// ── COURSE_DISCOVERY — GradusIQ_career/course_discovery/agent_models.py's
// CourseDiscoveryResult, mirrored field-for-field. Three typed outcomes, not
// three qualities of the same list:
//   verified_recommendations — currently actionable now.
//   prerequisite_blocked     — relevant, but a deterministic prerequisite
//                               isn't met yet; never a failed recommendation.
//   requires_verification    — Course Discovery could not safely reach a
//                               verdict at all; never implies "recommended".
// A course can only ever appear in exactly one of the three.

export type CatalogInstitution = 'tamu' | 'smu';
export type MatchKind = 'MATCHED_COURSE_CODE' | 'MATCHED_TITLE' | 'MATCHED_DESCRIPTION';
export type StudentCourseState = 'COMPLETED' | 'IN_PROGRESS' | 'PLANNED' | 'NOT_TAKEN' | 'UNKNOWN';
export type PrerequisiteStatus = 'ELIGIBLE' | 'INELIGIBLE' | 'UNRESOLVED';
export type PrerequisiteMode = 'NONE' | 'ALL' | 'ANY' | 'UNRESOLVED';
export type EvidenceState = 'VERIFIED_LOCAL' | 'EXTERNAL_EVIDENCE_PRESENT' | 'NO_EVIDENCE' | 'UNVERIFIED';

export interface CareerSkillNeed {
  need_id: string;
  skill: string;
  category: string | null;
  target_role: string;
  importance: 'required' | 'preferred' | 'exploratory';
  evidence_state: EvidenceState;
  evidence_source: string;
  confidence: number | null;
}

export interface CatalogProvenance {
  institution: CatalogInstitution;
  course_code: string;
  catalog_year: string;
  source_url: string;
  source_last_checked: string;
}

// requirement.course_codes is the full set for the mode (both alternatives
// for ANY, every course for ALL) — which of those are actually still
// outstanding lives in PrerequisiteEvaluation's status lists below, never
// re-derived on the frontend.
export interface PrerequisiteRequirement {
  mode: PrerequisiteMode;
  course_codes: string[];
  restrictions: string[];
  raw_text: string | null;
  unresolved_reasons: string[];
}

export interface PrerequisiteEvaluation {
  status: PrerequisiteStatus;
  requirement: PrerequisiteRequirement;
  satisfied_courses: string[];
  missing_courses: string[];
  in_progress_courses: string[];
  planned_courses: string[];
  unknown_courses: string[];
  reasons: string[];
}

export interface VerifiedCourseRecommendation {
  institution: CatalogInstitution;
  course_code: string;
  title: string;
  description: string;
  credit_min: number;
  credit_max: number;
  matched_needs: CareerSkillNeed[];
  match_kinds: MatchKind[];
  matched_terms: string[];
  student_status: StudentCourseState;
  prerequisite_status: PrerequisiteStatus;
  prerequisite_evaluation: PrerequisiteEvaluation | null;
  eligibility_status: 'ELIGIBLE';
  provenance: CatalogProvenance;
  ranking_reason: string;
  skill_alignment_explanation: string;
  degree_applicability: 'UNKNOWN';
  offering_status: 'UNKNOWN';
}

export interface UnresolvedCourseCandidate {
  institution: CatalogInstitution;
  course_code: string;
  title: string;
  matched_needs: CareerSkillNeed[];
  match_kinds: MatchKind[];
  eligibility_status: 'UNRESOLVED';
  reasons: string[];
  prerequisite_evaluation: PrerequisiteEvaluation | null;
  provenance: CatalogProvenance;
}

// eligibility_status is always INELIGIBLE here, and — structurally, per the
// backend contract — that can only mean an unmet prerequisite (every other
// rejection reason resolves to a different status before this type is ever
// built), so prerequisite_evaluation is always present, never null.
export interface PrerequisiteBlockedCourse {
  institution: CatalogInstitution;
  course_code: string;
  title: string;
  matched_needs: CareerSkillNeed[];
  match_kinds: MatchKind[];
  eligibility_status: 'INELIGIBLE';
  prerequisite_status: PrerequisiteStatus;
  prerequisite_evaluation: PrerequisiteEvaluation;
  provenance: CatalogProvenance;
}

export interface CourseDiscoveryData {
  target_role: string;
  current_major: string | null;
  intended_major: string | null;
  career_needs: CareerSkillNeed[];
  verified_recommendations: VerifiedCourseRecommendation[];
  requires_verification: UnresolvedCourseCandidate[];
  prerequisite_blocked: PrerequisiteBlockedCourse[];
  summary: string;
  degree_applicability: 'UNKNOWN';
  offering_status: 'UNKNOWN';
}

// ── ACTION PLAN (dependency-order preview) — action_planning/models.py ──────
// Mirrors GradusIQ_career/action_planning/models.py exactly (read directly,
// not from memory). Node/edge shape only; no graph layout, no scheduling.
//
// Edge orientation (easy to get backwards): a stored PlanEdge with
// relation "requires" is dependent --requires--> prerequisite, i.e.
// from_node_id is the dependent, to_node_id is the prerequisite. In
// dependency_order.ordered_node_ids the prerequisite appears BEFORE the
// dependent. Render "from_node_id requires to_node_id", never the reverse.

export type PlanNodeType = 'skill_need' | 'course' | 'project' | 'experience';
export type PlanNodeStatus = 'OPEN' | 'IN_PROGRESS' | 'SATISFIED';
export type PlanEdgeRelation = 'requires' | 'satisfies' | 'blocks';
export type PlanConflictResolution = 'UNRESOLVED' | 'DEFERRED' | 'MANUAL_REVIEW_REQUIRED';
export type PlanExecutionStatus = 'SUCCESS' | 'PARTIAL' | 'ERROR';
export type DependencyOrderCompleteness = 'COMPLETE' | 'PROVISIONAL';
export type DependencyOrderStatus = 'ORDERED' | 'ERROR';
export type DependencyOrderReasonType =
  | 'ANY_PREREQUISITE'
  | 'UNRESOLVED_PREREQUISITE'
  | 'UNKNOWN_COURSE_STATE';

export interface PlanNode {
  node_id: string;
  node_type: PlanNodeType;
  // Back-reference to already-validated evidence (a CareerSkillNeed.need_id,
  // or a course_code/institution pair) — never a copy of that data.
  source_ref: string;
  status: PlanNodeStatus;
}

export interface PlanEdge {
  from_node_id: string;
  to_node_id: string;
  relation: PlanEdgeRelation;
}

export interface PlanConflict {
  node_ids: string[];
  reason: string;
  resolution: PlanConflictResolution;
}

export interface PlanFailure {
  category: 'PLANNER_FAILURE';
  error_class: string | null;
  safe_message: string;
}

export interface DependencyOrderLimitation {
  node_id: string;
  reason_type: DependencyOrderReasonType;
  // The ANY-mode alternative set, or the UNKNOWN-state course codes, verbatim
  // from source evidence — never invented.
  course_codes: string[];
}

export interface DependencyOrderResult {
  ordered_node_ids: string[];
  // Action nodes with zero `requires` edges — no proven ordering constraint,
  // deliberately excluded from ordered_node_ids rather than given an
  // arbitrary position that would imply one.
  unconstrained_node_ids: string[];
  completeness: DependencyOrderCompleteness;
  limitations: DependencyOrderLimitation[];
  status: DependencyOrderStatus;
  failure: PlanFailure | null;
}

export interface UnifiedActionPlan {
  target_role: string;
  nodes: PlanNode[];
  edges: PlanEdge[];
  conflicts: PlanConflict[];
  execution_status: PlanExecutionStatus;
  failure: PlanFailure | null;
  summary: string;
}

// POST /api/v2/student/me/action-plan's response is NOT a FeatureResult — it
// is one of two distinct shapes depending on how far the request got:
//
// - Precondition not met, or the Course Discovery run itself failed: the
//   endpoint returns _resolve_course_discovery_inputs's/the course-discovery
//   failure's FeatureResult.to_dict() verbatim (same data/errors/
//   missing_fields shape as every other analyze endpoint).
// - Course Discovery succeeded: build_action_plan always ran, so action_plan
//   is always present; dependency_order is present only when the plan itself
//   didn't hit execution_status "ERROR".
export interface ActionPlanFeatureFailure {
  feature: string;
  status: 'skipped' | 'failed';
  summary: string;
  data: Record<string, never>;
  errors: string[];
  missing_fields?: MissingField[];
}

export interface ActionPlanResult {
  feature: 'ACTION_PLAN';
  status: 'failed' | 'success';
  summary: string;
  action_plan: UnifiedActionPlan;
  dependency_order: DependencyOrderResult | null;
}

export type ActionPlanPreviewResponse = ActionPlanFeatureFailure | ActionPlanResult;
