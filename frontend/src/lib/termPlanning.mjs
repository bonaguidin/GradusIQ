export const TERMS_URL = '/api/v2/student/me/terms'
export const PLANNED_COURSES_URL = '/api/v2/student/me/planned-courses'
export const CATALOG_SEARCH_URL = '/api/v2/student/me/catalog/search'
export const COURSE_RECORDS_URL = '/api/v2/student/me/course-records'
export const PENDING_FINAL_GRADES_URL = '/api/v2/student/me/course-records/pending-final-grades'
export const GRADING_SCHEMA_URL = '/api/v2/student/me/grading-schema'
export const CROSS_LISTINGS_URL = '/api/v2/student/me/catalog/cross-listings'

/**
 * Mirrors lifecycle.ACTIVATION_WINDOW_DAYS (GradusIQ_career/planning/lifecycle.py).
 * Used only to preview, ahead of submitting, whether a term the student is
 * about to plan a course for will be treated as current -- the backend is
 * still the one that decides at write time, against its own clock.
 */
export const ACTIVATION_WINDOW_DAYS = 30

/**
 * Letter-grade options for the current-grade and final-grade selectors,
 * derived from the student's own institution's grade_point_map -- NOT a
 * hard-coded list. A TAMU student (uses_plus_minus=false) sees exactly TAMU's
 * letters; an institution configured with plus/minus grading sees its own
 * full scale. This is the same map resolve_grade() (academics/gpa.py)
 * authoritatively checks a letter against at GPA-computation time, fetched
 * once via GET /me/grading-schema rather than duplicated as a second,
 * independently-maintained list.
 *
 * currentGradeOptions is narrower than finalGradeOptions on purpose: a
 * current (non-final) grade exists only to project GPA performance, so a
 * grade the institution does not count toward GPA (W, I, SMU's P) would not
 * mean anything there. Final grade may legitimately be any of the
 * institution's recognized outcomes, GPA-bearing or not.
 */
export function currentGradeOptions(schema) {
  const grades = Array.isArray(schema?.grades) ? schema.grades : []
  return grades.filter((grade) => grade.counts_toward_gpa).map((grade) => grade.letter)
}

export function finalGradeOptions(schema) {
  const grades = Array.isArray(schema?.grades) ? schema.grades : []
  return grades.map((grade) => grade.letter)
}

export function normalizeGradingSchemaPayload(status, body) {
  if (status !== 200 || !body || typeof body !== 'object') {
    return { ok: false, schema: null }
  }
  return {
    ok: true,
    schema: {
      institutionId: body.institution_id ?? null,
      usesPlusMinus: Boolean(body.uses_plus_minus),
      grades: Array.isArray(body.grades) ? body.grades : [],
    },
  }
}

export function courseRecordUrl(id) {
  return `${COURSE_RECORDS_URL}/${encodeURIComponent(id)}`
}

export function finalizeCourseUrl(id) {
  return `${COURSE_RECORDS_URL}/${encodeURIComponent(id)}/finalize`
}

/**
 * Season ordinals, mirroring SEASON_ORDER in
 * GradusIQ_career/transcript/terms.py. Duplicated rather than fetched because
 * it is a sort key, not data: the dropdown must order terms it has already
 * received, and a round trip to learn "May comes before Summer" would be a
 * request to answer a question that is a constant.
 *
 * May and August are SMU intersession terms and sort where SMU's own calendar
 * puts them (May 16-Jun 2, Summer Jun 3-Aug 4, August Aug 6-20, Fall Aug 24).
 * If terms.py's ordering changes, this must change with it -- the backend
 * already sorts the payload, so a drift here shows up as a list that reorders
 * itself, not as a wrong answer.
 */
export const SEASON_ORDER = {
  Winter: 0,
  Spring: 1,
  May: 2,
  Summer: 3,
  August: 4,
  Fall: 5,
}

/** Sorts an unrecognized season last, matching the backend's fallback. */
export const UNKNOWN_SEASON_ORDINAL = 99

export function seasonOrdinal(season) {
  return Object.prototype.hasOwnProperty.call(SEASON_ORDER, season)
    ? SEASON_ORDER[season]
    : UNKNOWN_SEASON_ORDINAL
}

export function plannedRemoveUrl(id) {
  return `${PLANNED_COURSES_URL}/${encodeURIComponent(id)}`
}

export function plannedListUrl(termId) {
  return termId ? `${PLANNED_COURSES_URL}?term_id=${encodeURIComponent(termId)}` : PLANNED_COURSES_URL
}

export function catalogSearchUrl(query) {
  return `${CATALOG_SEARCH_URL}?q=${encodeURIComponent(query)}`
}

/**
 * Minimum characters before a search fires. Below this, a prefix search over
 * 4,623 catalog rows returns a page of near-arbitrary matches -- "C" matches
 * every CSCE, CHEM and COMM course -- which reads as noise rather than as
 * results, and spends a request per keystroke to produce it.
 */
export const MIN_SEARCH_LENGTH = 2

/** Debounce for search-as-you-type. One request per pause, not per keystroke. */
export const SEARCH_DEBOUNCE_MS = 250

export function sortTerms(terms) {
  return [...terms].sort((a, b) => {
    if (a.year !== b.year) return a.year - b.year
    const seasonDelta = seasonOrdinal(a.season) - seasonOrdinal(b.season)
    if (seasonDelta !== 0) return seasonDelta
    return String(a.label).localeCompare(String(b.label))
  })
}

/**
 * The term the GPA Calculator's dropdown should open on.
 *
 * Preference order:
 *   1. The term happening now -- start_date <= today <= end_date -- preferring
 *      one the student is enrolled in over one they are not. Summer sessions a
 *      student never registered for still come back as `enrolled: false`
 *      options, and an overlapping intersession must not win over the real
 *      term.
 *   2. The backend's `upcoming_term_key` (earliest start strictly after the
 *      server's date -- see term_view.py).
 *   3. Any term the payload flags `is_upcoming`.
 *   4. The latest term the student has coursework in, else the latest term of
 *      any kind -- a landing place for when every term predates today.
 *
 * Why the current term wins here, when it used to be `upcoming_term_key`
 * first: this dropdown lives under the GPA Calculator, whose "Projected GPA"
 * is a projection FROM the grades being earned right now. Opening on a future
 * term the student has no grades in points the whole view at an empty term
 * while the projection above it describes the current one. Course PLANNING
 * still wants the next term -- a student mid-semester registers for what comes
 * next, not the term whose registration has closed -- which is why the
 * planning/search affordance inside TermPlanner keys off termStatus() and
 * `is_upcoming` for its own behaviour rather than off this default.
 *
 * `today` is injectable for tests and defaults to now. Rule 1 goes through
 * termStatus(), the same date-containment check the status badge uses, so
 * "is this term happening now" has exactly one implementation. A term with a
 * missing or malformed start_date/end_date resolves to 'unknown' there, so it
 * never matches rule 1 and never throws.
 */
export function pickDefaultTermKey(payload, today = new Date()) {
  const terms = Array.isArray(payload?.terms) ? payload.terms : []
  if (terms.length === 0) return null

  const sorted = sortTerms(terms)

  const inProgress = sorted.filter((term) => termStatus(term, today) === 'in_progress')
  if (inProgress.length > 0) {
    return (inProgress.find((term) => term.enrolled) ?? inProgress[0]).key
  }

  if (payload?.upcoming_term_key) {
    const named = terms.find((term) => term.key === payload.upcoming_term_key)
    if (named) return named.key
  }

  const flagged = sorted.find((term) => term.is_upcoming)
  if (flagged) return flagged.key

  // Nothing is in progress and nothing is upcoming. Fall back to the latest
  // term the student actually has coursework in, then to the latest of any kind.
  const enrolled = sorted.filter((term) => term.enrolled)
  const pool = enrolled.length > 0 ? enrolled : sorted
  return pool[pool.length - 1].key
}

/**
 * Term status relative to `today`, for the badge beside the dropdown label.
 * 'unknown' covers a term with no calendar row -- the five seeded
 * 'Current Term' rows, and terms predating the seeded window. It is not an
 * error state and must not read as one.
 */
export function termStatus(term, today) {
  const start = parseDate(term?.start_date)
  const end = parseDate(term?.end_date)
  if (!start || !end) return 'unknown'
  const day = startOfDay(today)
  if (day < start) return 'upcoming'
  if (day > end) return 'past'
  return 'in_progress'
}

/**
 * Whether `term` is already inside its pre-term activation window, i.e.
 * whether a course planned for it right now would be created as IN_PROGRESS
 * rather than PLANNED. Preview only -- see ACTIVATION_WINDOW_DAYS above.
 */
export function isTermActivated(term, today) {
  const start = parseDate(term?.start_date)
  if (!start) return false
  const activation = new Date(start)
  activation.setDate(activation.getDate() - ACTIVATION_WINDOW_DAYS)
  return startOfDay(today) >= startOfDay(activation)
}

export const TERM_STATUS_LABELS = {
  upcoming: 'Upcoming',
  in_progress: 'In progress',
  past: 'Completed',
  unknown: '',
}

function startOfDay(value) {
  const date = value instanceof Date ? value : new Date(value)
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

/**
 * 'YYYY-MM-DD' -> Date in LOCAL time.
 *
 * new Date('2026-08-24') parses as UTC midnight, which in any timezone west of
 * Greenwich is the evening of the 23rd locally -- so a term starting tomorrow
 * can compare as having started today. Splitting the parts and using the
 * numeric Date constructor keeps the comparison in the same calendar the
 * student is reading.
 */
export function parseDate(value) {
  if (!value || typeof value !== 'string') return null
  const parts = value.slice(0, 10).split('-')
  if (parts.length !== 3) return null
  const [year, month, day] = parts.map(Number)
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null
  const date = new Date(year, month - 1, day)
  return Number.isNaN(date.getTime()) ? null : date
}

const DATE_FORMAT = { month: 'short', day: 'numeric', year: 'numeric' }

/** "Aug 24, 2026 – Dec 10, 2026", or null when the term has no calendar row. */
export function formatTermDates(term) {
  const start = parseDate(term?.start_date)
  const end = parseDate(term?.end_date)
  if (!start || !end) return null
  const fmt = (date) => date.toLocaleDateString('en-US', DATE_FORMAT)
  return `${fmt(start)} – ${fmt(end)}`
}

/**
 * Course rows for one term, tagged by origin.
 *
 * Planned courses are NOT merged into the completed/in-progress list. They come
 * from a different table, they mean something different, and nothing about a
 * planned row has been verified against a transcript. Returning two arrays
 * rather than one flagged array makes it awkward for a caller to render them
 * identically by accident.
 */
export function termCourseGroups(termId, courseRecords, plannedCourses) {
  const records = (Array.isArray(courseRecords) ? courseRecords : []).filter(
    (row) => (row.term_id ?? null) === (termId ?? null),
  )
  const planned = (Array.isArray(plannedCourses) ? plannedCourses : []).filter(
    (row) => (row.term_id ?? null) === (termId ?? null),
  )
  return { records, planned }
}

/**
 * Course codes already planned in a term, for disabling the add control.
 *
 * A UI affordance only: planned_courses carries no unique constraint, and the
 * backend accepts a duplicate add. Nothing downstream depends on this holding,
 * which is why it is a Set built at render time rather than a guard.
 */
export function plannedCodes(plannedCourses) {
  return new Set(
    (Array.isArray(plannedCourses) ? plannedCourses : []).map((row) =>
      String(row.course_code ?? '').toUpperCase(),
    ),
  )
}

/**
 * "3 credits" / "1 credit" / "1-4 credits" for a variable-credit course, or
 * null when the course carries no credit data at all.
 *
 * The null check is explicit rather than leaning on Number(): Number(null) is
 * 0, not NaN, so a missing value would otherwise render as "0 credits" -- and
 * 0 is a real value here (105 catalog rows have credit_min = 0, the lower
 * bound on variable-credit research and internship courses), so it must stay
 * distinguishable from absent.
 */
export function formatCredits(min, max) {
  if (min === null || min === undefined) return null
  const low = Number(min)
  if (!Number.isFinite(low)) return null
  const high = max === null || max === undefined ? low : Number(max)
  if (Number.isFinite(high) && high !== low) return `${low}-${high} credits`
  return low === 1 ? '1 credit' : `${low} credits`
}

export function normalizeTermsPayload(status, body) {
  if (status !== 200 || !body || typeof body !== 'object') {
    return { ok: false, terms: [], upcomingTermKey: null }
  }
  const terms = Array.isArray(body.terms) ? body.terms : []
  return {
    ok: true,
    terms: sortTerms(terms),
    upcomingTermKey: body.upcoming_term_key ?? null,
  }
}

export function normalizePlannedPayload(status, body) {
  if (status !== 200 || !body || typeof body !== 'object') {
    return { ok: false, plannedCourses: [] }
  }
  return {
    ok: true,
    plannedCourses: Array.isArray(body.planned_courses) ? body.planned_courses : [],
  }
}

export function normalizeSearchPayload(status, body) {
  if (status !== 200 || !body || typeof body !== 'object') {
    return { ok: false, results: [] }
  }
  return { ok: true, results: Array.isArray(body.results) ? body.results : [] }
}

export function normalizeCrossListingsPayload(status, body) {
  if (status !== 200 || !body || typeof body !== 'object') {
    return { ok: false, crossListings: {} }
  }
  const raw = body.cross_listings && typeof body.cross_listings === 'object' ? body.cross_listings : {}
  const crossListings = {}
  for (const [code, partners] of Object.entries(raw)) {
    if (!Array.isArray(partners)) continue
    crossListings[String(code).toUpperCase()] = partners.map((partner) => String(partner).toUpperCase())
  }
  return { ok: true, crossListings }
}

/**
 * code -> the status ('in_progress' | 'completed' | 'planned') of the
 * strongest evidence the student already has that course under THIS exact
 * code, student-wide (every term, not just the one being edited) -- unlike
 * plannedCodes()/alreadyAddedCodes, which are deliberately this-term-only
 * affordances for "don't re-add the identical row you're looking at".
 *
 * This is the other half of the cross-listing check: a course_records row
 * from a past/current term (in_progress or completed) and a planned_courses
 * row anywhere both count as "already have this", so a cross-listed alias
 * search hit can be matched against it regardless of which term it lives in.
 * 'dropped' course_records rows are deliberately excluded -- a dropped course
 * is not a reason to block re-planning it (or its cross-listed alias) later.
 *
 * When a code somehow appears under more than one status, in_progress wins
 * over completed wins over planned -- the most concrete evidence should
 * drive the copy, matching the order a student would think of them in.
 */
const STATUS_PRIORITY = { in_progress: 0, completed: 1, planned: 2 }

export function existingCourseStatusIndex(courseRecords, plannedCourses) {
  const index = new Map()
  const consider = (code, statusValue) => {
    const key = String(code ?? '').toUpperCase()
    if (!key) return
    const current = index.get(key)
    if (!current || STATUS_PRIORITY[statusValue] < STATUS_PRIORITY[current]) {
      index.set(key, statusValue)
    }
  }
  for (const row of Array.isArray(courseRecords) ? courseRecords : []) {
    if (row.status === 'in_progress' || row.status === 'completed') consider(row.course_code, row.status)
  }
  for (const row of Array.isArray(plannedCourses) ? plannedCourses : []) {
    consider(row.course_code, 'planned')
  }
  return index
}

/**
 * If `code` is cross-listed (per `crossListings`, from GET
 * /me/catalog/cross-listings) with something the student already has (per
 * `existingIndex`, from existingCourseStatusIndex above), returns the
 * matched partner code and its status. Returns null for an exact match --
 * callers already have a cheaper, existing check (alreadyAddedCodes.has) for
 * "the searched code itself is already planned in this term"; this function
 * answers only the alias case.
 */
export function findCrossListedMatch(code, crossListings, existingIndex) {
  const upper = String(code ?? '').toUpperCase()
  const partners = crossListings?.[upper] ?? []
  for (const partner of partners) {
    const status = existingIndex.get(partner)
    if (status) return { code: partner, status }
  }
  return null
}

export function normalizePendingFinalGradesPayload(status, body) {
  if (status !== 200 || !body || typeof body !== 'object') {
    return { ok: false, pendingFinalGrades: [] }
  }
  return {
    ok: true,
    pendingFinalGrades: Array.isArray(body.pending_final_grades) ? body.pending_final_grades : [],
  }
}
