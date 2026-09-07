export function isSkippedDegreeSchedule(result) {
  return 'status' in result && result.status === 'skipped';
}

export class DegreeScheduleChoiceError extends Error {
  constructor(code, detail = null) {
    super('Degree schedule choice could not be saved.');
    this.name = 'DegreeScheduleChoiceError';
    this.code = code;
    this.detail = detail;
  }
}

// identity.slug present -> the local, non-Postgres demo counterpart (no
// token sent); otherwise the session-scoped /me route, same identity-branch
// shape analysisApi.mjs's analysisPath() already uses.
function degreeSchedulePath(identity) {
  if (identity.slug) return [`/api/students/${encodeURIComponent(identity.slug)}/schedule`, undefined];
  if (!identity.accessToken) throw new Error('Degree schedule requires a session.');
  return ['/api/v2/student/me/schedule', identity.accessToken];
}

export async function fetchDegreeSchedule(identity) {
  const [url, token] = degreeSchedulePath(identity);
  const headers = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetch(url, { method: 'GET', headers });
  } catch {
    throw new Error('Degree schedule is unavailable.');
  }

  let body = null;
  try { body = await response.json(); } catch { /* handled by the status check */ }
  if (response.status === 200 && body && typeof body === 'object') {
    return body;
  }
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String(body.detail)
      : 'Degree schedule is unavailable.';
  throw new Error(detail);
}

export async function updateDegreeScheduleChoices(token, { scheduleVersion, selections }) {
  let response;
  try {
    response = await fetch('/api/v2/student/me/schedule/choices', {
      method: 'PUT',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ schedule_version: scheduleVersion, selections }),
    });
  } catch {
    throw new DegreeScheduleChoiceError('NETWORK_ERROR');
  }
  let body = null;
  try { body = await response.json(); } catch { /* handled below */ }
  if (response.status === 200 && body && typeof body === 'object') return body;
  const detail = body && typeof body === 'object' ? body.detail : null;
  const code = detail && typeof detail === 'object' && typeof detail.code === 'string'
    ? detail.code
    : 'UNKNOWN_ERROR';
  throw new DegreeScheduleChoiceError(code, detail);
}

export async function updateDegreeScheduleExclusions(token, { scheduleVersion, excludedGroupIds }) {
  let response;
  try {
    response = await fetch('/api/v2/student/me/schedule/exclusions', {
      method: 'PUT',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ schedule_version: scheduleVersion, excluded_group_ids: excludedGroupIds }),
    });
  } catch {
    throw new DegreeScheduleChoiceError('NETWORK_ERROR');
  }
  let body = null;
  try { body = await response.json(); } catch { /* handled below */ }
  if (response.status === 200 && body && typeof body === 'object') return body;
  const detail = body && typeof body === 'object' ? body.detail : null;
  const code = detail && typeof detail === 'object' && typeof detail.code === 'string'
    ? detail.code
    : 'UNKNOWN_ERROR';
  throw new DegreeScheduleChoiceError(code, detail);
}
