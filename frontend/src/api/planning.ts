import {
  TERMS_URL,
  PLANNED_COURSES_URL,
  PENDING_FINAL_GRADES_URL,
  GRADING_SCHEMA_URL,
  CROSS_LISTINGS_URL,
  catalogSearchUrl,
  courseRecordUrl,
  finalizeCourseUrl,
  normalizeCrossListingsPayload,
  normalizeGradingSchemaPayload,
  normalizePendingFinalGradesPayload,
  normalizePlannedPayload,
  normalizeSearchPayload,
  normalizeTermsPayload,
  plannedListUrl,
  plannedRemoveUrl,
} from '../lib/termPlanning.mjs';
import type {
  AddedCourseResult,
  NormalizedCrossListings,
  NormalizedGradingSchema,
  NormalizedPendingFinalGrades,
  NormalizedPlanned,
  NormalizedSearch,
  NormalizedTerms,
} from '../lib/termPlanning.mjs';
import type { AnalysisIdentity } from './analysisApi.mjs';
import { buildDemoGradingSchema, buildDemoTerms, searchDemoCatalog } from '../data/demoTermFixtures';
import {
  addDemoPlannedCourse,
  editDemoCourseRecord,
  getDemoInstitution,
  removeDemoPlannedCourse,
  snapshotDemoPlannedCourses,
} from '../data/demoPlanningStore';

/**
 * Same shape as api/transcript.ts's send, minus the timeout parameter: none of
 * these routes runs AI work or reconciliation, so none of them has the cold
 * start the confirm routes budget for. They are plain reads and one small
 * insert.
 */
async function send(url: string, init: RequestInit): Promise<{ status: number; body: unknown }> {
  try {
    const response = await fetch(url, init);
    let body: unknown = null;
    try { body = await response.json(); } catch { /* normalizers accept null */ }
    return { status: response.status, body };
  } catch {
    return { status: 0, body: null };
  }
}

const auth = (token: string) => ({ Accept: 'application/json', Authorization: `Bearer ${token}` });

// identity.slug present -> every function below reads/writes only local,
// in-memory demo state (frontend/src/data/demoPlanningStore.ts,
// demoTermFixtures.ts) -- no fetch at all, so GPA Calculator never touches
// the network for a demo identity, matching "changes are local, never
// permanent" for reads as well as writes. Real accounts (no slug) are
// unchanged from before.

export async function fetchTerms(identity: AnalysisIdentity): Promise<NormalizedTerms> {
  if (identity.slug) {
    const terms = buildDemoTerms(new Date());
    const upcoming = terms.find((term) => term.is_upcoming);
    return normalizeTermsPayload(200, { terms, upcoming_term_key: upcoming?.key ?? null });
  }
  const { status, body } = await send(TERMS_URL, { method: 'GET', headers: auth(identity.accessToken ?? '') });
  return normalizeTermsPayload(status, body);
}

export async function fetchPlannedCourses(
  identity: AnalysisIdentity,
  termId?: string | null,
): Promise<NormalizedPlanned> {
  if (identity.slug) {
    return normalizePlannedPayload(200, { planned_courses: snapshotDemoPlannedCourses(identity.slug) });
  }
  const { status, body } = await send(plannedListUrl(termId), {
    method: 'GET',
    headers: auth(identity.accessToken ?? ''),
  });
  return normalizePlannedPayload(status, body);
}

export interface AddPlannedCourseInput {
  course_code: string;
  year?: number | null;
  season?: string | null;
  term_label?: string | null;
  title?: string | null;
  credit_hours?: number | null;
  catalog_course_id?: string | null;
  /**
   * Set only by the year-view add action. Forces a planned_courses row even
   * inside the 30-day activation window -- see PlannedCourseRequest.force_planned.
   * The response is always `kind: 'planned'` when this is true.
   */
  force_planned?: boolean;
}

/**
 * The response's `planned_course` key is either a planned_courses row
 * (kind: 'planned') or, when the term is already inside its activation
 * window, a course_records row written directly as in-progress
 * (kind: 'in_progress') -- see lifecycle.add_course_respecting_activation.
 * The key name stays 'planned_course' on the wire (the route is still "plan a
 * course"); only the payload shape branches on `kind`. The demo branch never
 * produces 'in_progress' -- see demoPlanningStore.ts's own note on why that
 * edge case is out of scope for a local-only store.
 */
export async function addPlannedCourse(
  identity: AnalysisIdentity,
  input: AddPlannedCourseInput,
): Promise<{ ok: boolean; course: AddedCourseResult | null; message: string | null }> {
  if (identity.slug) {
    const course = addDemoPlannedCourse(identity.slug, {
      course_code: input.course_code,
      title: input.title,
      credit_hours: input.credit_hours,
      catalog_course_id: input.catalog_course_id,
    });
    return { ok: true, course, message: null };
  }
  const { status, body } = await send(PLANNED_COURSES_URL, {
    method: 'POST',
    headers: { ...auth(identity.accessToken ?? ''), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (status === 200 && body && typeof body === 'object' && 'planned_course' in body) {
    return {
      ok: true,
      course: (body as { planned_course: AddedCourseResult }).planned_course,
      message: null,
    };
  }
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : 'Could not add that course to your plan.';
  return { ok: false, course: null, message: detail };
}

export async function removePlannedCourse(
  identity: AnalysisIdentity,
  id: string,
): Promise<{ ok: boolean }> {
  if (identity.slug) {
    removeDemoPlannedCourse(identity.slug, id);
    return { ok: true };
  }
  const { status } = await send(plannedRemoveUrl(id), {
    method: 'DELETE',
    headers: auth(identity.accessToken ?? ''),
  });
  // 404 counts as removed: the row is gone either way, and surfacing an error
  // for "it was already not there" would be a worse answer to the same state.
  return { ok: status === 200 || status === 404 };
}

export async function searchCatalog(identity: AnalysisIdentity, query: string): Promise<NormalizedSearch> {
  if (identity.slug) {
    return normalizeSearchPayload(200, { results: searchDemoCatalog(getDemoInstitution(identity.slug), query) });
  }
  const { status, body } = await send(catalogSearchUrl(query), {
    method: 'GET',
    headers: auth(identity.accessToken ?? ''),
  });
  return normalizeSearchPayload(status, body);
}

export async function fetchGradingSchema(identity: AnalysisIdentity): Promise<NormalizedGradingSchema> {
  if (identity.slug) {
    return normalizeGradingSchemaPayload(200, buildDemoGradingSchema(getDemoInstitution(identity.slug)));
  }
  const { status, body } = await send(GRADING_SCHEMA_URL, {
    method: 'GET',
    headers: auth(identity.accessToken ?? ''),
  });
  return normalizeGradingSchemaPayload(status, body);
}

/**
 * code -> its cross-listed partner codes, for the caller's home institution.
 * Fetched once and cached by the caller (same "load once" shape as
 * fetchGradingSchema), not re-fetched per search keystroke.
 *
 * Demo identities get an empty map: the demo fixtures (data/students/*.json)
 * were not built against real cross-listing data, so there is nothing
 * correct to return -- matching fetchPendingFinalGrades's same reasoning for
 * an empty demo stub rather than a fabricated one.
 */
export async function fetchCrossListings(identity: AnalysisIdentity): Promise<NormalizedCrossListings> {
  if (identity.slug) {
    return normalizeCrossListingsPayload(200, { cross_listings: {} });
  }
  const { status, body } = await send(CROSS_LISTINGS_URL, {
    method: 'GET',
    headers: auth(identity.accessToken ?? ''),
  });
  return normalizeCrossListingsPayload(status, body);
}

export async function fetchPendingFinalGrades(
  identity: AnalysisIdentity,
): Promise<NormalizedPendingFinalGrades> {
  if (identity.slug) {
    // Demo never has a term that "just ended" with a still-in-progress
    // course to reconcile -- the "How did last semester go?" banner never
    // has anything to show, which is a fine simplification for a demo.
    return normalizePendingFinalGradesPayload(200, { pending_final_grades: [] });
  }
  const { status, body } = await send(PENDING_FINAL_GRADES_URL, {
    method: 'GET',
    headers: auth(identity.accessToken ?? ''),
  });
  return normalizePendingFinalGradesPayload(status, body);
}

export async function finalizeCourseGrade(
  identity: AnalysisIdentity,
  courseId: string,
  letterGrade: string,
): Promise<{ ok: boolean; message: string | null }> {
  if (identity.slug) {
    const ok = editDemoCourseRecord(identity.slug, courseId, { letter_grade: letterGrade });
    return ok ? { ok: true, message: null } : { ok: false, message: 'Could not save that grade.' };
  }
  const { status, body } = await send(finalizeCourseUrl(courseId), {
    method: 'POST',
    headers: { ...auth(identity.accessToken ?? ''), 'Content-Type': 'application/json' },
    body: JSON.stringify({ letter_grade: letterGrade }),
  });
  if (status === 200) return { ok: true, message: null };
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : 'Could not save that grade.';
  return { ok: false, message: detail };
}

export interface EditInProgressCourseInput {
  course_code?: string;
  title?: string | null;
  term_id?: string | null;
  credit_hours?: number | null;
  letter_grade?: string | null;
  status?: 'dropped';
}

export async function editInProgressCourse(
  identity: AnalysisIdentity,
  courseId: string,
  input: EditInProgressCourseInput,
): Promise<{ ok: boolean; message: string | null }> {
  if (identity.slug) {
    const ok = editDemoCourseRecord(identity.slug, courseId, {
      letter_grade: input.letter_grade,
      status: input.status,
    });
    return ok ? { ok: true, message: null } : { ok: false, message: 'Could not update that course.' };
  }
  const { status, body } = await send(courseRecordUrl(courseId), {
    method: 'PATCH',
    headers: { ...auth(identity.accessToken ?? ''), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (status === 200) return { ok: true, message: null };
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : 'Could not update that course.';
  return { ok: false, message: detail };
}
