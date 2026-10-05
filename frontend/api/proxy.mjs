// Two routing schemes share this function.
//
//   SLUG-ADDRESSED (?student=<slug>&feature=<feature>)
//     Forwards to /api/students/<slug>/... . These serve the demo fixtures.
//     The browser sends no credential and none is forwarded -- the backend
//     identifies the student from the slug alone.
//
//   SESSION-SCOPED (?target=me-analyze&feature=<feature> | ?target=me-chat
//                   | ?target=me-profile | ?target=me-resume-upload)
//     Forwards to /api/v2/student/me/... . These serve real students, whose
//     identity comes from a Supabase session JWT, so the inbound Authorization
//     header MUST be forwarded for the backend to resolve them via RLS.
//     me-resume-upload additionally carries a binary multipart body -- see the
//     `binary` flag on ME_TARGETS and the body branch in the handler.
//
// Authorization is forwarded for `target` requests ONLY -- see the single
// `if (isMeTarget)` block below, which is the one place that distinction is
// enforced. Slug-addressed requests continue to forward no inbound header of
// any kind, preserving the anti-spoofing property those routes rely on.
//
// The proxy secret is attached to every forwarded request either way.

// POST features run AI work; the GET_FEATURES below are plain reads.
const ALLOWED_FEATURES = new Set([
  'gap',
  'fit',
  'shift',
  'professor-comments',
  'chat',
  'course-discovery',
  'action-plan',
])
// Degree planner reads: local (non-Postgres) demo counterparts to the
// session-scoped me-schedule/me-requirement-satisfaction/me-technical-
// electives targets below. See GradusIQ_career/demo/local_requirement_tree.py.
const GET_FEATURES = new Set([
  'profile',
  'schedule',
  'requirement-satisfaction',
  'technical-electives',
])
const STUDENT_SLUG_PATTERN = /^[A-Za-z0-9]{1,64}$/
const PROXY_SECRET_HEADER = 'X-GradusIQ-Proxy-Secret'

// Session-scoped targets. `feature` is required only by me-analyze, and is
// validated against the same analysis vocabulary the slug routes accept.
//
// `binary: true` marks a target whose body must NOT be read as text. Branching
// on an explicit target rather than sniffing Content-Type is deliberate:
// ME_TARGETS is already a closed allowlist, so the binary path is reachable
// only from a route we named, and a forged/absent Content-Type cannot flip an
// existing JSON target onto the binary branch.
//
// PROTOTYPE-LESS ON PURPOSE. As a plain object literal this map answers lookups
// for inherited keys -- ME_TARGETS['toString'] and ME_TARGETS['constructor']
// both return truthy values that were never allowlisted. The `method !==
// spec.method` check below happens to reject them today only because
// spec.method is undefined; if anything in the process pollutes
// Object.prototype.method, that accident stops holding and an unvalidated
// target reaches meBackendPath -- forwarded with the caller's bearer token and
// the proxy secret attached. Object.create(null) removes the inheritance
// entirely, so the allowlist is closed by construction rather than by a
// coincidence in an adjacent check. Object.assign keeps the entries readable.
const ME_TARGETS = Object.assign(Object.create(null), {
  'me-analyze': { method: 'POST', needsFeature: true },
  'me-chat': { method: 'POST', needsFeature: false },
  'me-profile': { methods: ['GET', 'PATCH'], needsFeature: false },
  'me-resume-upload': { method: 'POST', needsFeature: false, binary: true },
  'me-transcript-upload': { method: 'POST', needsFeature: false, binary: true },
  'me-transcript-review': { method: 'GET', needsFeature: false },
  'me-transcript-review-edit': { method: 'PATCH', needsFeature: false, needsTranscriptRecord: true },
  'me-transcript-confirm': { method: 'POST', needsFeature: false },
  'me-career-confirm': { method: 'POST', needsFeature: false },
  'me-career-review': { method: 'GET', needsFeature: false },
  // `needsRecord` marks the one target whose backend path is not fixed: it
  // carries {table}/{id} path segments. Rather than let a caller hand the
  // proxy a path fragment, the two pieces arrive as separate query params and
  // are each validated against a closed allowlist / a UUID shape below, then
  // re-encoded into the path. The backend validates `table` against the same
  // allowlist independently -- the double check mirrors how ALLOWED_FEATURES
  // is already enforced in both places.
  'me-career-review-edit': { method: 'PATCH', needsFeature: false, needsRecord: true },
  // Term-organized Academic Record.
  //
  // `me-planned-courses` is the one target that admits TWO methods, via
  // `methods` instead of `method`. Listing and adding share a path
  // (/planned-courses), and a Vercel rewrite matches on path only -- it cannot
  // route GET and POST to different targets. Splitting them would have meant
  // inventing a second URL for one of the two purely to work around the
  // rewrite table. The allowlist stays closed either way: a method absent from
  // the array is rejected by the same check that rejects a wrong single
  // method.
  //
  // `me-planned-course-remove` is the first DELETE on this proxy; the method
  // guard at the top of the handler was widened to admit it, and DELETE
  // remains reachable only through this entry.
  'me-terms': { method: 'GET', needsFeature: false },
  'me-planned-courses': { methods: ['GET', 'POST'], needsFeature: false, optionalTermId: true },
  'me-planned-course-remove': { method: 'DELETE', needsFeature: false, needsPlannedRecord: true },
  'me-catalog-search': { method: 'GET', needsFeature: false, needsQuery: true },
  // Action Plan's real backend route is /api/v2/student/me/action-plan --
  // NOT under /analyze/, so it cannot ride ME_ANALYZE_FEATURES/meBackendPath's
  // generic /analyze/:feature fallback the way gap/fit/shift/course-discovery
  // do. It needs its own target, same as me-terms/me-chat.
  'me-action-plan': { method: 'POST', needsFeature: false },
  // Degree planner: schedule, requirement satisfaction, technical electives,
  // and the opt-in career-ranked schedule preview. Same shape as
  // me-terms/me-action-plan -- fixed backend path, no extra params.
  'me-schedule': { method: 'GET', needsFeature: false },
  'me-requirement-satisfaction': { method: 'GET', needsFeature: false },
  'me-technical-electives': { method: 'GET', needsFeature: false },
  'me-schedule-career-optimize': { method: 'POST', needsFeature: false },
  // Syllabus What-If Calculator. Ingest is multipart/binary; the remaining
  // routes are JSON or bodyless reads. Profile-scoped routes require a UUID.
  'me-syllabus-profiles': { method: 'GET', needsFeature: false },
  'me-syllabus-ingest': { method: 'POST', needsFeature: false, binary: true },
  'me-syllabus-profile': { method: 'GET', needsFeature: false, needsSyllabusRecord: true },
  'me-syllabus-corrections': { method: 'POST', needsFeature: false, needsSyllabusRecord: true },
  'me-syllabus-confirm': { method: 'POST', needsFeature: false, needsSyllabusRecord: true },
  'me-syllabus-grade-state': { method: 'PUT', needsFeature: false, needsSyllabusRecord: true },
  'me-syllabus-calculate': { method: 'POST', needsFeature: false, needsSyllabusRecord: true },
  'me-syllabus-solve-target': { method: 'POST', needsFeature: false, needsSyllabusRecord: true },
  // GPA Calculator / Academic Record reads with no body and no path param.
  'me-gpa': { method: 'GET', needsFeature: false },
  'me-grading-schema': { method: 'GET', needsFeature: false },
  'me-catalog-cross-listings': { method: 'GET', needsFeature: false },
  'me-course-records-pending-final-grades': { method: 'GET', needsFeature: false },
  // Edits a single confirmed, in-progress course record; `needsCourseRecord`
  // validates the `id` query param as a UUID, same shape as
  // needsPlannedRecord/needsSyllabusRecord above.
  'me-course-record': { method: 'PATCH', needsFeature: false, needsCourseRecord: true },
  'me-course-record-finalize': { method: 'POST', needsFeature: false, needsCourseRecord: true },
  // GAP/FIT/SHIFT's persistent cache read. Its own `needsCacheFeature` flag
  // (not `needsFeature`/ME_ANALYZE_FEATURES) because the cache only ever
  // holds these three, not the wider analyze vocabulary (chat, action-plan,
  // course-discovery, professor-comments have no cache file).
  'me-analysis-cache': { method: 'GET', needsFeature: false, needsCacheFeature: true },
  'me-career-role-options': { method: 'GET', needsFeature: false },
  // Cached, role-filtered job postings -- reads only, never a live vendor
  // call. `needsRole` validates the `role` query param the same way
  // `needsQuery` validates catalog search's `q`.
  'me-job-search': { method: 'GET', needsFeature: false, needsRole: true },
  // Degree Schedule's two PUT replace-in-full routes. Same shape as
  // me-syllabus-grade-state -- the method guard at the top of the handler
  // was widened for both, same reasoning as that one.
  'me-schedule-choices': { method: 'PUT', needsFeature: false },
  'me-schedule-exclusions': { method: 'PUT', needsFeature: false },
})
const ME_ANALYZE_FEATURES = new Set(['gap', 'fit', 'shift', 'professor-comments', 'course-discovery'])
const ME_CACHE_FEATURES = new Set(['gap', 'fit', 'shift'])

// Must stay in step with TABLE_BY_SEGMENT in GradusIQ_career/resume/review.py.
const REVIEW_TABLES = new Set([
  'career_profile',
  'certifications',
  'work_experience',
  'projects',
])
const RECORD_ID_PATTERN =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/

// Catalog search is the only target carrying free text through to the backend.
// The value is length-capped and restricted to characters that appear in a
// course code or title, then re-encoded into the forwarded query string --
// never concatenated into a path. Everything the backend does with it is a
// bound parameter to search_course_catalog(), so this bound is defence in
// depth rather than the only thing standing between a caller and a query.
const MAX_SEARCH_QUERY_LENGTH = 64
const SEARCH_QUERY_PATTERN = /^[A-Za-z0-9 .,'&:/+-]{1,64}$/

// Job Search's `role` carries a target-role name, not free text -- restricted
// to the characters the curated role vocabulary actually uses (letters,
// spaces, hyphens). The backend independently validates it against the
// caller's own career.target_roles, same defence-in-depth shape as
// SEARCH_QUERY_PATTERN above.
const MAX_ROLE_LENGTH = 80
const ROLE_PATTERN = /^[A-Za-z][A-Za-z -]{0,79}$/

function jsonError(status, detail) {
  return Response.json({ detail }, { status })
}

function backendBaseUrl(value) {
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null
    return url
  } catch {
    return null
  }
}

// Chat forwards to /chat, profile to /profile; analysis features to
// /analyze/{feature}.
function backendPath(student, feature) {
  const slug = encodeURIComponent(student)
  if (feature === 'chat') return `/api/students/${slug}/chat`
  if (feature === 'profile') return `/api/students/${slug}/profile`
  if (feature === 'schedule') return `/api/students/${slug}/schedule`
  if (feature === 'requirement-satisfaction') return `/api/students/${slug}/requirement-satisfaction`
  if (feature === 'technical-electives') return `/api/students/${slug}/degree-plan/technical-electives`
  return `/api/students/${slug}/analyze/${feature}`
}

function meBackendPath(target, feature, reviewTable, recordId, searchQuery, termId, role) {
  if (target === 'me-terms') return '/api/v2/student/me/terms'
  if (target === 'me-gpa') return '/api/v2/student/me/gpa'
  if (target === 'me-grading-schema') return '/api/v2/student/me/grading-schema'
  if (target === 'me-catalog-cross-listings') return '/api/v2/student/me/catalog/cross-listings'
  if (target === 'me-course-records-pending-final-grades') {
    return '/api/v2/student/me/course-records/pending-final-grades'
  }
  if (target === 'me-course-record') {
    return `/api/v2/student/me/course-records/${encodeURIComponent(recordId)}`
  }
  if (target === 'me-course-record-finalize') {
    return `/api/v2/student/me/course-records/${encodeURIComponent(recordId)}/finalize`
  }
  if (target === 'me-analysis-cache') return `/api/v2/student/me/analysis-cache/${encodeURIComponent(feature)}`
  if (target === 'me-career-role-options') return '/api/v2/student/me/career-role-options'
  if (target === 'me-job-search') return `/api/v2/student/me/job-search?role=${encodeURIComponent(role)}`
  if (target === 'me-schedule-choices') return '/api/v2/student/me/schedule/choices'
  if (target === 'me-schedule-exclusions') return '/api/v2/student/me/schedule/exclusions'
  if (target === 'me-planned-courses') {
    // The only forwarded query string besides search. Built here from a
    // validated UUID rather than by copying the inbound search params, so a
    // caller cannot append parameters of their own to a backend route.
    return termId
      ? `/api/v2/student/me/planned-courses?term_id=${encodeURIComponent(termId)}`
      : '/api/v2/student/me/planned-courses'
  }
  if (target === 'me-planned-course-remove') {
    return `/api/v2/student/me/planned-courses/${encodeURIComponent(recordId)}`
  }
  if (target === 'me-catalog-search') {
    return `/api/v2/student/me/catalog/search?q=${encodeURIComponent(searchQuery)}`
  }
  if (target === 'me-action-plan') return '/api/v2/student/me/action-plan'
  if (target === 'me-schedule') return '/api/v2/student/me/schedule'
  if (target === 'me-requirement-satisfaction') return '/api/v2/student/me/requirement-satisfaction'
  if (target === 'me-technical-electives') return '/api/v2/student/me/degree-plan/technical-electives'
  if (target === 'me-schedule-career-optimize') return '/api/v2/student/me/schedule/career-optimize'
  if (target === 'me-syllabus-profiles') return '/api/v2/student/me/syllabus-grade-profiles'
  if (target === 'me-syllabus-ingest') return '/api/v2/student/me/syllabus-grade-profiles/ingest'
  if (target === 'me-syllabus-profile') {
    return `/api/v2/student/me/syllabus-grade-profiles/${encodeURIComponent(recordId)}`
  }
  if (target === 'me-syllabus-corrections') {
    return `/api/v2/student/me/syllabus-grade-profiles/${encodeURIComponent(recordId)}/corrections`
  }
  if (target === 'me-syllabus-confirm') {
    return `/api/v2/student/me/syllabus-grade-profiles/${encodeURIComponent(recordId)}/confirm`
  }
  if (target === 'me-syllabus-grade-state') {
    return `/api/v2/student/me/syllabus-grade-profiles/${encodeURIComponent(recordId)}/grade-state`
  }
  if (target === 'me-syllabus-calculate') {
    return `/api/v2/student/me/syllabus-grade-profiles/${encodeURIComponent(recordId)}/calculate`
  }
  if (target === 'me-syllabus-solve-target') {
    return `/api/v2/student/me/syllabus-grade-profiles/${encodeURIComponent(recordId)}/solve-target`
  }
  if (target === 'me-chat') return '/api/v2/student/me/chat'
  if (target === 'me-profile') return '/api/v2/student/me/profile'
  if (target === 'me-resume-upload') return '/api/v2/student/me/resume/upload'
  if (target === 'me-transcript-upload') return '/api/v2/student/me/transcript/upload'
  if (target === 'me-transcript-review') return '/api/v2/student/me/transcript/review'
  if (target === 'me-transcript-confirm') return '/api/v2/student/me/transcript/confirm'
  if (target === 'me-transcript-review-edit') {
    return `/api/v2/student/me/transcript/review/${encodeURIComponent(recordId)}`
  }
  if (target === 'me-career-confirm') return '/api/v2/student/me/career/confirm'
  if (target === 'me-career-review') return '/api/v2/student/me/career/review'
  if (target === 'me-career-review-edit') {
    return `/api/v2/student/me/career/review/${encodeURIComponent(reviewTable)}/${encodeURIComponent(recordId)}`
  }
  return `/api/v2/student/me/analyze/${encodeURIComponent(feature)}`
}

export function createProxyHandler({ env = process.env, fetchImpl = globalThis.fetch } = {}) {
  return {
    async fetch(request) {
      const method = request.method
      const requestUrl = new URL(request.url)
      const target = requestUrl.searchParams.get('target') ?? ''
      const supportedMethod =
        method === 'POST' || method === 'GET' || method === 'PATCH' || method === 'DELETE' ||
        (method === 'PUT' &&
          (target === 'me-syllabus-grade-state' ||
            target === 'me-schedule-choices' ||
            target === 'me-schedule-exclusions'))
      if (!supportedMethod) return jsonError(405, 'Method not allowed.')

      const student = requestUrl.searchParams.get('student') ?? ''
      const feature = requestUrl.searchParams.get('feature') ?? ''
      const reviewTable = requestUrl.searchParams.get('table') ?? ''
      const recordId = requestUrl.searchParams.get('id') ?? ''
      const searchQuery = requestUrl.searchParams.get('q') ?? ''
      const termId = requestUrl.searchParams.get('term_id') ?? ''
      const role = requestUrl.searchParams.get('role') ?? ''

      const isMeTarget = target !== ''
      let path
      let isBinaryTarget = false

      if (isMeTarget) {
        const spec = ME_TARGETS[target]
        // Array.isArray, not a truthiness check on spec.methods: an inherited
        // property would not survive it, which is the same property
        // Object.create(null) is protecting above.
        const methodAllowed = Array.isArray(spec?.methods)
          ? spec.methods.includes(method)
          : method === spec?.method
        if (!spec || !methodAllowed) {
          return jsonError(400, 'Invalid analysis route.')
        }
        if (spec.needsFeature && !ME_ANALYZE_FEATURES.has(feature)) {
          return jsonError(400, 'Invalid analysis route.')
        }
        if (spec.needsRecord && (!REVIEW_TABLES.has(reviewTable) || !RECORD_ID_PATTERN.test(recordId))) {
          return jsonError(400, 'Invalid analysis route.')
        }
        if (spec.needsTranscriptRecord && !RECORD_ID_PATTERN.test(recordId)) {
          return jsonError(400, 'Invalid analysis route.')
        }
        if (spec.needsPlannedRecord && !RECORD_ID_PATTERN.test(recordId)) {
          return jsonError(400, 'Invalid analysis route.')
        }
        if (spec.needsSyllabusRecord && !RECORD_ID_PATTERN.test(recordId)) {
          return jsonError(400, 'Invalid analysis route.')
        }
        if (spec.needsCourseRecord && !RECORD_ID_PATTERN.test(recordId)) {
          return jsonError(400, 'Invalid analysis route.')
        }
        if (spec.needsCacheFeature && !ME_CACHE_FEATURES.has(feature)) {
          return jsonError(400, 'Invalid analysis route.')
        }
        if (spec.needsRole && (role.length > MAX_ROLE_LENGTH || !ROLE_PATTERN.test(role))) {
          return jsonError(400, 'Invalid analysis route.')
        }
        if (
          spec.needsQuery &&
          (searchQuery.length > MAX_SEARCH_QUERY_LENGTH || !SEARCH_QUERY_PATTERN.test(searchQuery))
        ) {
          return jsonError(400, 'Invalid analysis route.')
        }
        // term_id is optional -- absent means "all terms" -- but must be a
        // UUID when present rather than an arbitrary string appended to a
        // backend query string.
        if (spec.optionalTermId && termId !== '' && !RECORD_ID_PATTERN.test(termId)) {
          return jsonError(400, 'Invalid analysis route.')
        }
        isBinaryTarget = spec.binary === true
        path = meBackendPath(target, feature, reviewTable, recordId, searchQuery, termId, role)
      } else {
        // PATCH exists only for the session-scoped review edit above. The
        // slug-addressed surface stays GET/POST-only: without this guard a
        // PATCH would fall through to the ALLOWED_FEATURES branch below and
        // could reach an AI route.
        if (method !== 'GET' && method !== 'POST') {
          return jsonError(400, 'Invalid analysis route.')
        }
        // Method and feature must agree: a GET may only reach a read route, and
        // a POST may only reach an AI route. This stops a GET from triggering
        // billable work and keeps the read route out of the POST-only surface.
        const allowed = method === 'GET' ? GET_FEATURES : ALLOWED_FEATURES
        if (!STUDENT_SLUG_PATTERN.test(student) || !allowed.has(feature)) {
          return jsonError(400, 'Invalid analysis route.')
        }
        path = backendPath(student, feature)
      }

      const backendUrl = backendBaseUrl(env.GRADUSIQ_BACKEND_URL ?? '')
      const proxySecret = (env.GRADUSIQ_PROXY_SECRET ?? '').trim()
      if (!backendUrl || !proxySecret) {
        return jsonError(503, 'Analysis proxy is not configured.')
      }

      const target_url = new URL(path, backendUrl)

      // Forward the request body. Analyze routes send none (path params only);
      // chat carries { message, history } in the body, so it must pass through.
      // A GET has no body to read or forward.
      //
      // BINARY TARGETS take a separate path. request.text() decodes the body as
      // UTF-8, which silently replaces every byte sequence that is not valid
      // UTF-8 with U+FFFD -- it does not throw, it corrupts. That is fine for
      // JSON and fatal for a PDF or DOCX, so file uploads are read as raw bytes
      // via arrayBuffer() and forwarded untouched.
      const headers = {
        Accept: 'application/json',
        [PROXY_SECRET_HEADER]: proxySecret,
      }

      let body
      if (isBinaryTarget) {
        const buffer = await request.arrayBuffer()
        body = buffer.byteLength ? buffer : undefined
        // Preserve the inbound Content-Type verbatim: multipart is unparseable
        // without its boundary parameter, so this must never be defaulted or
        // rewritten. When the caller sent none, forward none rather than
        // inventing application/json and mislabelling a file as JSON.
        const inboundContentType = request.headers.get('content-type')
        if (inboundContentType) headers['Content-Type'] = inboundContentType
      } else {
        const bodyText = method === 'GET' ? '' : await request.text()
        body = bodyText.length ? bodyText : undefined
        headers['Content-Type'] = request.headers.get('content-type') ?? 'application/json'
      }

      // THE distinction: session-scoped targets forward the caller's bearer
      // token so the backend can resolve them through RLS. Slug-addressed
      // requests never do -- a browser-supplied Authorization header on those
      // is ignored, exactly as before.
      if (isMeTarget) {
        const authorization = request.headers.get('authorization')
        if (authorization) headers.Authorization = authorization
      }

      try {
        const backendResponse = await fetchImpl(target_url, {
          method,
          headers,
          body,
        })
        const responseHeaders = new Headers()
        const respContentType = backendResponse.headers.get('content-type')
        if (respContentType) responseHeaders.set('content-type', respContentType)
        return new Response(await backendResponse.arrayBuffer(), {
          status: backendResponse.status,
          headers: responseHeaders,
        })
      } catch {
        return jsonError(502, 'Analysis backend is unavailable.')
      }
    },
  }
}

export default createProxyHandler()
