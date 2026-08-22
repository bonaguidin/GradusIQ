import type { FeatureResult } from '../types/analysis';

export type RequirementGroupStatus = 'SATISFIED' | 'IN_PROGRESS' | 'NOT_STARTED' | 'MANUAL_REVIEW';

// Mirrors GradusIQ_career/course_discovery/requirement_satisfaction.py's
// RequirementGroupResult. children is the same shape recursively -- there is
// no depth limit on either side.
export interface RequirementGroupResult {
  id: string;
  coursedog_rule_id: string;
  name: string;
  group_type: string;
  status: RequirementGroupStatus;
  detail: string | null;
  matched_course_codes: string[];
  children: RequirementGroupResult[];
}

// The route's success payload is a bare RequirementSatisfactionResult, not a
// FeatureResult -- see api.py's get_me_requirement_satisfaction: evaluation is
// a pure, sub-second computation with no AI call to distinguish "ran and
// failed" from "ran fine", so there is no status field to check on this path.
// Only the "no program for this student yet" precondition uses FeatureResult
// (status: 'skipped'), the same shape every other analysis uses for that case.
export interface RequirementSatisfactionSuccess {
  student_id: string;
  program_id: string;
  groups: RequirementGroupResult[];
}

export type RequirementSatisfactionSkipped = FeatureResult<Record<string, never>>;

export type RequirementSatisfactionResponse = RequirementSatisfactionSuccess | RequirementSatisfactionSkipped;

export function isSkippedRequirementSatisfaction(
  result: RequirementSatisfactionResponse,
): result is RequirementSatisfactionSkipped {
  return 'status' in result && result.status === 'skipped';
}

const REQUIREMENT_SATISFACTION_URL = '/api/v2/student/me/requirement-satisfaction';

// Same send()/auth() shape as api/planning.ts: a plain authenticated read,
// with no AI work and no cold start to budget for.
async function send(url: string, init: RequestInit): Promise<{ status: number; body: unknown }> {
  try {
    const response = await fetch(url, init);
    let body: unknown = null;
    try { body = await response.json(); } catch { /* handled by the status check below */ }
    return { status: response.status, body };
  } catch {
    return { status: 0, body: null };
  }
}

export async function fetchRequirementSatisfaction(token: string): Promise<RequirementSatisfactionResponse> {
  const { status, body } = await send(REQUIREMENT_SATISFACTION_URL, {
    method: 'GET',
    headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
  });
  if (status === 200 && body && typeof body === 'object') {
    return body as RequirementSatisfactionResponse;
  }
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : 'Requirement satisfaction is unavailable.';
  throw new Error(detail);
}
