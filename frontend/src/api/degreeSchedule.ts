import type { FeatureResult } from '../types/analysis';

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

export interface ScheduleResult {
  student_id: string;
  program_id: string;
  terms: TermPlan[];
  unscheduled: UnscheduledRequirement[];
  status: 'SCHEDULED' | 'ERROR';
  failure: ScheduleFailure | null;
}

export type DegreeScheduleSkipped = FeatureResult<Record<string, never>>;
export type DegreeScheduleResponse = ScheduleResult | DegreeScheduleSkipped;

export function isSkippedDegreeSchedule(result: DegreeScheduleResponse): result is DegreeScheduleSkipped {
  return 'status' in result && result.status === 'skipped';
}

const DEGREE_SCHEDULE_URL = '/api/v2/student/me/schedule';

export async function fetchDegreeSchedule(token: string): Promise<DegreeScheduleResponse> {
  let response: Response;
  try {
    response = await fetch(DEGREE_SCHEDULE_URL, {
      method: 'GET',
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new Error('Degree schedule is unavailable.');
  }

  let body: unknown = null;
  try { body = await response.json(); } catch { /* handled by the status check */ }
  if (response.status === 200 && body && typeof body === 'object') {
    return body as DegreeScheduleResponse;
  }
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : 'Degree schedule is unavailable.';
  throw new Error(detail);
}
