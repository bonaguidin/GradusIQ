// Types for degreeSchedule.mjs. The implementation is plain .mjs so the
// existing `node --test tests/` runner can import it directly; this file is
// what lets TS callers under src/ consume it with full checking.

import type { FeatureResult } from '../types/analysis';
import type { AnalysisIdentity } from './analysisApi.mjs';

export interface ScheduledCourse {
  course_code: string;
  credit_hours: number;
  requirement_group_id: string;
  limitations: string[];
}

export interface TermPlan {
  term_key: string;
  courses: ScheduledCourse[];
  total_credit_hours: number;
}

export type UnscheduledReason = 'SELECTION_DEFERRED' | 'FREEFORM_MANUAL_REVIEW';

export interface UnscheduledRequirement {
  requirement_group_id: string;
  name: string;
  reason: UnscheduledReason;
}

export interface ScheduleFailure {
  error_class: string;
  safe_message: string;
}

export type AcademicFeasibility = 'FEASIBLE' | 'EXCLUDED';

export type CandidateExclusionReason =
  | 'UNRESOLVED_COURSE'
  | 'RESTRICTION_REQUIRES_REVIEW'
  | 'PREREQUISITE_NEEDS_REVIEW'
  | 'DOUBLE_COUNTING_CONFLICT'
  | 'MISSING_CREDIT_DATA'
  | 'UNSCHEDULABLE';

export interface CandidateCourseDisplay {
  course_code: string;
  title: string | null;
  credits: number | null;
}

export interface RequirementCandidate {
  candidate_id: string;
  requirement_group_id: string;
  requirement_name: string;
  course_codes: string[];
  unresolved_course_codes: string[];
  candidate_courses: CandidateCourseDisplay[];
  existing_contribution: number;
  additional_course_count: number;
  additional_credits: number | null;
  academic_feasibility: AcademicFeasibility;
  completion_term_index: number | null;
  limitations: string[];
  source_order: number[];
  exclusion_reasons: CandidateExclusionReason[];
  exclusion_details: string[];
}

export interface RequirementCandidateSet {
  requirement_group_id: string;
  requirement_name: string;
  feasible_candidates: RequirementCandidate[];
  excluded_candidates: RequirementCandidate[];
}

export type RequirementDecisionState =
  | 'AUTO_SELECTED'
  | 'LOCKED'
  | 'CHOICE_REQUIRED'
  | 'ADVISER_REVIEW'
  | 'DATA_UNRESOLVED'
  | 'EXCLUDED';

export interface RequirementDecision {
  requirement_group_id: string;
  requirement_name: string;
  state: RequirementDecisionState;
  feasible_candidate_ids: string[];
  excluded_candidate_ids: string[];
  selected_candidate_id: string | null;
  // Phase 3: the term card this decision renders on, resolved server-side.
  // LOCKED -> the term its course was scheduled into; CHOICE_REQUIRED /
  // EXCLUDED -> the relevant candidate's completion_term_index mapped to a
  // term key; null for AUTO_SELECTED / ADVISER_REVIEW / DATA_UNRESOLVED, and
  // for an EXCLUDED decision whose candidate never joined a feasible plan.
  resolved_term_key: string | null;
}

export type PersistedSelectionStatus = 'NONE' | 'APPLIED' | 'RESELECTION_REQUIRED';

export type LockedSelectionFailureCode =
  | 'LOCK_DUPLICATE_REQUIREMENT'
  | 'LOCK_REQUIREMENT_NOT_FOUND'
  | 'LOCK_CANDIDATE_NOT_FOUND'
  | 'LOCK_CANDIDATE_EXCLUDED'
  | 'LOCK_PATH_MISMATCH'
  | 'LOCK_CHOICE_NO_LONGER_REQUIRED'
  | 'LOCK_INCOMPATIBLE';

export interface PersistedRequirementSelectionIdentity {
  requirement_group_id: string;
  candidate_id: string;
  course_codes: string[];
}

export interface PersistedSelectionFailure {
  code: LockedSelectionFailureCode;
  requirement_group_id: string | null;
  candidate_id: string | null;
  current_course_codes: string[];
  submitted_course_codes: string[];
  exclusion_reasons: CandidateExclusionReason[];
}

export interface PersistedSelectionState {
  status: PersistedSelectionStatus;
  selections: PersistedRequirementSelectionIdentity[];
  failure: PersistedSelectionFailure | null;
}

export interface PersistedExclusionState {
  excluded_group_ids: string[];
}

export interface ScheduleResult {
  student_id: string;
  program_id: string;
  terms: TermPlan[];
  unscheduled: UnscheduledRequirement[];
  status: 'SCHEDULED' | 'ERROR';
  failure: ScheduleFailure | null;
}

export interface DegreeScheduleResult extends ScheduleResult {
  schedule_version: string;
  decisions: RequirementDecision[];
  candidate_sets: RequirementCandidateSet[];
  selection_state: PersistedSelectionState;
  exclusion_state: PersistedExclusionState;
}

export type DegreeScheduleSkipped = FeatureResult<Record<string, never>>;
export type DegreeScheduleResponse = DegreeScheduleResult | DegreeScheduleSkipped;

export type DegreeScheduleChoiceWriteStatus = 'APPLIED' | 'UNCHANGED';

export interface DegreeScheduleChoiceWriteResponse {
  status: DegreeScheduleChoiceWriteStatus;
  schedule_version: string;
  selections: PersistedRequirementSelectionIdentity[];
}

export interface DegreeScheduleChoiceWriteRequest {
  scheduleVersion: string;
  selections: PersistedRequirementSelectionIdentity[];
}

export declare class DegreeScheduleChoiceError extends Error {
  code: string;
  detail: unknown;
  constructor(code: string, detail?: unknown);
}

export declare function isSkippedDegreeSchedule(result: DegreeScheduleResponse): result is DegreeScheduleSkipped;

export declare function fetchDegreeSchedule(identity: AnalysisIdentity): Promise<DegreeScheduleResponse>;

export declare function updateDegreeScheduleChoices(
  token: string,
  request: DegreeScheduleChoiceWriteRequest,
): Promise<DegreeScheduleChoiceWriteResponse>;

export interface DegreeScheduleExclusionWriteRequest {
  scheduleVersion: string;
  excludedGroupIds: string[];
}

export interface DegreeScheduleExclusionWriteResponse {
  status: DegreeScheduleChoiceWriteStatus;
  schedule_version: string;
  excluded_group_ids: string[];
}

export declare function updateDegreeScheduleExclusions(
  token: string,
  request: DegreeScheduleExclusionWriteRequest,
): Promise<DegreeScheduleExclusionWriteResponse>;
