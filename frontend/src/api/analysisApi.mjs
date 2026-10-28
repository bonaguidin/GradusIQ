import { detailToText } from '../lib/resumeApi.mjs';

async function analysisFailure(response) {
  const body = await response.json().catch(() => null);
  const detail = body?.detail;
  if (response.status === 429) {
    return new Error(
      typeof detail === 'string' && detail.toLowerCase().includes('busy')
        ? 'The analysis service is busy right now. Try again in a moment.'
        : 'Too many requests. Wait a minute and try again.',
    );
  }
  const fallback = `Analysis request failed (${response.status}).`;
  return new Error(detailToText(detail, fallback));
}

async function postAnalysis(path, accessToken, body) {
  const headers = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
    method: 'POST',
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw await analysisFailure(response);
  return response.json();
}

export async function getCachedAnalysis(feature, accessToken) {
  const response = await fetch(`/api/v2/student/me/analysis-cache/${feature}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (response.status === 404) return null;
  if (!response.ok) throw await analysisFailure(response);
  return response.json();
}

// GAP/FIT/SHIFT for a signed-in student run in the background on the server
// (a run often takes 4-7 minutes, longer than the proxy's 300s limit): one
// POST starts it, then the page reads its status on a timer until it settles.
const RUN_POLL_MS = 4000;
const RUN_MAX_WAIT_MS = 20 * 60 * 1000;
// Consecutive failed status reads tolerated (a network blip, a deploy).
const RUN_MAX_READ_FAILURES = 3;

function runPath(feature) {
  return `/api/v2/student/me/analysis-runs/${feature}`;
}

async function runRequest(method, feature, accessToken) {
  const response = await fetch(runPath(feature), {
    method,
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw await analysisFailure(response);
  return response.json();
}

function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function settledRun(status) {
  if (status.state === 'done') return status.result;
  if (status.state === 'failed') {
    if (status.status_code === 429) {
      return Promise.reject(new Error('The analysis service is busy right now. Try again in a moment.'));
    }
    return Promise.reject(
      new Error(detailToText(status.detail, `Analysis request failed (${status.status_code ?? 'unknown'}).`)),
    );
  }
  return Promise.reject(
    new Error('The analysis stopped before it finished, most likely because the server restarted. Run it again.'),
  );
}

/** Poll a run that is already going until it settles; resolves to its result. */
export async function waitForAnalysisRun(
  feature,
  accessToken,
  { pollMs = RUN_POLL_MS, maxWaitMs = RUN_MAX_WAIT_MS, sleep = defaultSleep, now = Date.now } = {},
) {
  const deadline = now() + maxWaitMs;
  let failures = 0;
  for (;;) {
    await sleep(pollMs);
    let status;
    try {
      status = await runRequest('GET', feature, accessToken);
      failures = 0;
    } catch (err) {
      failures += 1;
      if (failures > RUN_MAX_READ_FAILURES) throw err;
      continue;
    }
    if (status.state !== 'running') return settledRun(status);
    if (now() > deadline) {
      throw new Error(
        'The analysis is taking much longer than usual. Reload the page in a few minutes to see if it finished.',
      );
    }
  }
}

/** Start (or join) a background run and resolve to its result. */
export async function runAnalysisInBackground(feature, accessToken, options) {
  const status = await runRequest('POST', feature, accessToken);
  if (status.state !== 'running') return settledRun(status);
  return waitForAnalysisRun(feature, accessToken, options);
}

/**
 * If a run of `feature` is still going on the server (the page was reloaded
 * or reopened mid-run), `{ result }` holding a promise of its result;
 * otherwise null. Wrapped so awaiting this does not also wait for the run.
 */
export async function resumeAnalysisRun(feature, accessToken, options) {
  const status = await runRequest('GET', feature, accessToken);
  if (status.state !== 'running') return null;
  return { result: waitForAnalysisRun(feature, accessToken, options) };
}

function analysisPath(identity, feature) {
  if (identity.slug) {
    return [`/api/students/${encodeURIComponent(identity.slug)}/analyze/${feature}`];
  }
  if (!identity.accessToken) throw new Error('Authenticated analysis requires a session.');
  return [`/api/v2/student/me/analyze/${feature}`, identity.accessToken];
}

export function analyzeGap(identity) {
  if (!identity.slug && identity.accessToken) return runAnalysisInBackground('gap', identity.accessToken);
  return postAnalysis(...analysisPath(identity, 'gap'));
}

export function analyzeFit(identity) {
  if (!identity.slug && identity.accessToken) return runAnalysisInBackground('fit', identity.accessToken);
  return postAnalysis(...analysisPath(identity, 'fit'));
}

export function analyzeShift(identity) {
  if (!identity.slug && identity.accessToken) return runAnalysisInBackground('shift', identity.accessToken);
  return postAnalysis(...analysisPath(identity, 'shift'));
}

export function analyzeProfessorComments(identity) {
  return postAnalysis(...analysisPath(identity, 'professor-comments'));
}

export function analyzeCourseDiscovery(identity, targetRole) {
  const [path, token] = analysisPath(identity, 'course-discovery');
  return postAnalysis(path, token, targetRole ? { target_role: targetRole } : undefined);
}

export function analyzeActionPlan(identity, targetRole) {
  const body = targetRole ? { target_role: targetRole } : undefined;
  if (identity.slug) {
    // Demo counterpart to the real /me/action-plan route below. Named
    // .../analyze/action-plan (not .../action-plan) so it rides the same
    // slug-addressed /analyze/:feature route analysisPath() already builds.
    return postAnalysis(
      `/api/students/${encodeURIComponent(identity.slug)}/analyze/action-plan`,
      undefined,
      body,
    );
  }
  if (!identity.accessToken) throw new Error('Authenticated analysis requires a session.');
  return postAnalysis('/api/v2/student/me/action-plan', identity.accessToken, body);
}
