import type { FeatureResult } from '../types/analysis';

export type TechnicalElectiveEligibility =
  | 'READY'
  | 'PREREQUISITES_PLANNED'
  | 'PREREQUISITES_MISSING';

export interface TechnicalElectiveCandidate {
  course_code: string;
  title: string;
  description: string;
  credit_min: number;
  credit_max: number;
  eligibility: TechnicalElectiveEligibility;
  satisfied_prerequisite_codes: string[];
  planned_prerequisite_codes: string[];
  missing_prerequisite_options: string[][];
  limitations: string[];
  catalog_year: string;
  source_url: string;
  source_last_checked: string;
}

export interface TechnicalElectiveCandidateSuccess {
  student_id: string;
  program_id: string;
  requirement_group_id: string;
  requirement_name: string;
  credits_required: number;
  review_required: boolean;
  institution: 'smu';
  catalog_year: string;
  candidates: TechnicalElectiveCandidate[];
  limitations: Array<
    | 'ADVISER_APPROVAL_REQUIRED'
    | 'TRACK_EXCLUSION_NOT_EVALUATED'
    | 'CROSS_DEPARTMENT_EXCEPTIONS_NOT_INCLUDED'
  >;
  stats: {
    catalog_courses_considered: number;
    cs_3000_plus_courses: number;
    excluded_already_used: number;
    excluded_zero_credit: number;
    excluded_restriction_or_review: number;
    candidate_count: number;
  };
}

export type TechnicalElectiveCandidateResponse =
  | TechnicalElectiveCandidateSuccess
  | FeatureResult<Record<string, never>>;

export function isSkippedTechnicalElectives(
  result: TechnicalElectiveCandidateResponse,
): result is FeatureResult<Record<string, never>> {
  return 'status' in result && result.status === 'skipped';
}

export async function fetchTechnicalElectiveCandidates(
  token: string,
): Promise<TechnicalElectiveCandidateResponse> {
  let response: Response;
  try {
    response = await fetch('/api/v2/student/me/degree-plan/technical-electives', {
      method: 'GET',
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new Error('Technical elective options are unavailable.');
  }
  let body: unknown = null;
  try { body = await response.json(); } catch { /* handled below */ }
  if (response.status === 200 && body && typeof body === 'object') {
    return body as TechnicalElectiveCandidateResponse;
  }
  const detail = body && typeof body === 'object' && 'detail' in body
    ? String((body as { detail: unknown }).detail)
    : 'Technical elective options are unavailable.';
  throw new Error(detail);
}
