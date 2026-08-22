import type { ScheduleResult } from './degreeSchedule';

export type CareerOptimizationStatus = 'OPTIMIZED' | 'PARTIAL' | 'FALLBACK' | 'SKIPPED';
export type CareerSelectionBasis = 'CAREER_RANKED' | 'ACADEMIC_DEFAULT';
export type CareerOptimizationCacheStatus = 'HIT' | 'MISS' | 'BYPASSED';

export interface RankedRequirementCandidate {
  candidate_id: string;
  rank: number;
  ranking_reason: string;
  skill_alignment_explanation: string;
}

export interface RequirementCandidateRanking {
  requirement_group_id: string;
  ranked_candidates: RankedRequirementCandidate[];
}

export interface RequirementRankingFailure {
  requirement_group_id: string;
  requirement_name: string;
  error_code: string;
  detail: string;
}

export interface CareerOptimizedScheduleResponse {
  feature: 'CAREER_OPTIMIZED_SCHEDULE';
  status: CareerOptimizationStatus;
  selection_basis: CareerSelectionBasis;
  target_role: string | null;
  fingerprint: string | null;
  generated_at: string;
  cache_status: CareerOptimizationCacheStatus;
  academic_schedule: ScheduleResult;
  optimized_schedule: ScheduleResult;
  requirement_rankings: RequirementCandidateRanking[];
  ranking_failures: RequirementRankingFailure[];
  ranking_prompt_version: string;
  resolved_model: string;
  summary: string | null;
}

export interface CareerOptimizeScheduleRequest {
  target_role?: string;
  force_refresh?: boolean;
}

const CAREER_OPTIMIZE_URL = '/api/v2/student/me/schedule/career-optimize';
const STATUSES = new Set<CareerOptimizationStatus>(['OPTIMIZED', 'PARTIAL', 'FALLBACK', 'SKIPPED']);
const BASES = new Set<CareerSelectionBasis>(['CAREER_RANKED', 'ACADEMIC_DEFAULT']);
const CACHE_STATUSES = new Set<CareerOptimizationCacheStatus>(['HIT', 'MISS', 'BYPASSED']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isSchedule(value: unknown): value is ScheduleResult {
  if (!isRecord(value) || !Array.isArray(value.terms) || !Array.isArray(value.unscheduled)) return false;
  return typeof value.student_id === 'string'
    && typeof value.program_id === 'string'
    && (value.status === 'SCHEDULED' || value.status === 'ERROR')
    && (value.failure === null || isRecord(value.failure));
}

function isRanking(value: unknown): value is RequirementCandidateRanking {
  return isRecord(value)
    && typeof value.requirement_group_id === 'string'
    && Array.isArray(value.ranked_candidates)
    && value.ranked_candidates.every((candidate) => isRecord(candidate)
      && typeof candidate.candidate_id === 'string'
      && Number.isInteger(candidate.rank)
      && typeof candidate.ranking_reason === 'string'
      && typeof candidate.skill_alignment_explanation === 'string');
}

export function isCareerOptimizedScheduleResponse(value: unknown): value is CareerOptimizedScheduleResponse {
  if (!isRecord(value)) return false;
  return value.feature === 'CAREER_OPTIMIZED_SCHEDULE'
    && STATUSES.has(value.status as CareerOptimizationStatus)
    && BASES.has(value.selection_basis as CareerSelectionBasis)
    && (typeof value.target_role === 'string' || value.target_role === null)
    && (typeof value.fingerprint === 'string' || value.fingerprint === null)
    && typeof value.generated_at === 'string'
    && CACHE_STATUSES.has(value.cache_status as CareerOptimizationCacheStatus)
    && isSchedule(value.academic_schedule)
    && isSchedule(value.optimized_schedule)
    && Array.isArray(value.requirement_rankings)
    && value.requirement_rankings.every(isRanking)
    && Array.isArray(value.ranking_failures)
    && value.ranking_failures.every((failure) => isRecord(failure)
      && typeof failure.requirement_group_id === 'string'
      && typeof failure.requirement_name === 'string'
      && typeof failure.error_code === 'string'
      && typeof failure.detail === 'string')
    && typeof value.ranking_prompt_version === 'string'
    && typeof value.resolved_model === 'string'
    && (typeof value.summary === 'string' || value.summary === null);
}

export async function fetchCareerOptimizedSchedule(
  token: string,
  request: CareerOptimizeScheduleRequest = {},
): Promise<CareerOptimizedScheduleResponse> {
  const payload: CareerOptimizeScheduleRequest = {
    ...(request.target_role ? { target_role: request.target_role } : {}),
    force_refresh: request.force_refresh ?? false,
  };
  let response: Response;
  try {
    response = await fetch(CAREER_OPTIMIZE_URL, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error('Career optimization is unavailable.');
  }

  let body: unknown = null;
  try { body = await response.json(); } catch { /* handled below */ }
  if (response.status === 200) {
    if (isCareerOptimizedScheduleResponse(body)) return body;
    throw new Error('Career optimization returned an invalid response.');
  }
  const detail = isRecord(body) && 'detail' in body
    ? String(body.detail)
    : 'Career optimization is unavailable.';
  throw new Error(detail);
}
