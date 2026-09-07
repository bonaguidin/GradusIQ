import { termStatus, existingCourseStatusIndex, findCrossListedMatch } from './termPlanning.mjs'
import { formatCredits } from './degreeSchedulePresentation.mjs'

/**
 * Seasons this view renders as columns. A student's real term list (and,
 * less often, course_records) can include intersession terms (Winter, May,
 * Summer, August -- see SEASON_ORDER in termPlanning.mjs), but the approved
 * two-column mockup is Fall | Spring only. Intersession terms are out of
 * scope for this view, not silently lost -- they still render in
 * TermPlanner, which is term-by-term rather than year-by-year.
 */
export const YEAR_SEMESTER_SEASONS = ['Fall', 'Spring']

const ORDINAL_WORDS = ['First', 'Second', 'Third', 'Fourth', 'Fifth', 'Sixth']

/**
 * Ordinal label for the Nth academic year (0-indexed), e.g. 0 -> 'First
 * year'. Falls back to 'Year N' past the words list rather than assuming
 * every student graduates in four years -- a fifth-year or transfer
 * student's schedule can run longer.
 */
export function academicYearLabel(index) {
  const word = ORDINAL_WORDS[index]
  return word ? `${word} year` : `Year ${index + 1}`
}

/**
 * The academic-year bucket a Fall/Spring term belongs to, keyed by the
 * Fall term's calendar year (US convention: Fall Y pairs with Spring Y+1).
 * Any other season is out of scope here -- see YEAR_SEMESTER_SEASONS.
 */
export function academicYearKey(year, season) {
  if (season === 'Fall') return year
  if (season === 'Spring') return year - 1
  return null
}

/**
 * Formats a letter grade with its GPA points, e.g. "B+ (3.3)". Falls back
 * to the bare letter when the institution's grade map has no points for it
 * (an unmapped or non-GPA letter like "P" or "W" still needs to display).
 */
export function formatGradeBadge(letterGrade, gradingSchema) {
  if (!letterGrade) return null
  const grades = Array.isArray(gradingSchema?.grades) ? gradingSchema.grades : []
  const row = grades.find((grade) => grade.letter === letterGrade)
  if (row && typeof row.points === 'number') {
    return `${letterGrade} (${row.points.toFixed(1)})`
  }
  return letterGrade
}

/**
 * One semester slot's state, collapsed from TermPlanner's vocabulary
 * (termStatus in termPlanning.mjs) to the three this view renders
 * differently: 'past' and 'in_progress' show real coursework from
 * course_records; everything else -- 'upcoming', 'unknown', or no calendar
 * row at all (a term this far out has no academic_terms row yet) --
 * collapses to 'future', which shows the empty-state + suggestions.
 */
export function semesterState(realTerm, today) {
  if (!realTerm) return 'future'
  const status = termStatus(realTerm, today)
  if (status === 'past') return 'past'
  if (status === 'in_progress') return 'in_progress'
  return 'future'
}

function sumCredits(courses) {
  return courses.reduce((total, course) => total + (Number(course.credit_hours) || 0), 0)
}

/** The three decision states Phase 3 relocates onto term cards. Everything
 * else (AUTO_SELECTED, ADVISER_REVIEW, DATA_UNRESOLVED) is deliberately not
 * surfaced anywhere in the planner UI -- see planning-docs Phase 3. */
export const TERM_CARD_DECISION_STATES = ['LOCKED', 'CHOICE_REQUIRED', 'EXCLUDED']

/**
 * Resolves the decisions the backend serialized (schedule.decisions +
 * schedule.candidate_sets) into per-term buckets, keyed by the
 * `resolved_term_key` the server already computed.
 *
 *  - Only LOCKED / CHOICE_REQUIRED / EXCLUDED are carried; the rest return
 *    nothing.
 *  - A decision with no `resolved_term_key` is dropped entirely (this is the
 *    documented behaviour for an EXCLUDED candidate that never joined a
 *    feasible combination, and a fail-safe for the others).
 *  - `candidates` holds the feasible candidates for LOCKED/CHOICE_REQUIRED
 *    and the excluded candidate(s) for EXCLUDED, purely for course-code
 *    display; the action handlers key off requirementGroupId + candidate_id.
 */
export function bucketDecisionsByTerm(decisions, candidateSets) {
  const byTermKey = new Map()
  if (!Array.isArray(decisions) || decisions.length === 0) return byTermKey

  const candidateById = new Map()
  for (const set of Array.isArray(candidateSets) ? candidateSets : []) {
    for (const candidate of [...(set.feasible_candidates ?? []), ...(set.excluded_candidates ?? [])]) {
      candidateById.set(candidate.candidate_id, candidate)
    }
  }

  for (const decision of decisions) {
    if (!TERM_CARD_DECISION_STATES.includes(decision.state)) continue
    const termKey = decision.resolved_term_key
    if (!termKey) continue

    const ids = decision.state === 'EXCLUDED'
      ? decision.excluded_candidate_ids ?? []
      : decision.feasible_candidate_ids ?? []
    const candidates = ids.map((id) => candidateById.get(id)).filter(Boolean)

    const entry = {
      requirementGroupId: decision.requirement_group_id,
      requirementName: decision.requirement_name,
      state: decision.state,
      selectedCandidateId: decision.selected_candidate_id ?? null,
      candidates,
      termKey,
    }
    const bucket = byTermKey.get(termKey) ?? []
    bucket.push(entry)
    byTermKey.set(termKey, bucket)
  }
  return byTermKey
}

/**
 * Ids of planned_courses rows that are display-duplicates of coursework the
 * student already has under a cross-listed alias -- either a course_records
 * row (in_progress/completed) or an earlier planned row for the same real
 * course under its other departmental code. The add-time check
 * (CourseSearchAdd's findCrossListedMatch call) blocks new duplicates like
 * this from being created; this is the retroactive display-only filter for
 * rows that predate that check (or otherwise slipped through). The
 * underlying planned_courses row is never written to here -- this only
 * decides what's rendered, matching the existingCourseStatusIndex /
 * findCrossListedMatch pair already used for the add-time check, not a new
 * lookup.
 *
 * Student-wide (every term, not just one), same scope as the add-time check.
 * Rows are walked in input order; the first row for a given course "wins"
 * and later cross-listed duplicates of it are hidden -- order isn't
 * otherwise meaningful here, it's just a deterministic tie-break.
 */
function hiddenPlannedIds(planned, courseRecords, crossListingMap) {
  const hidden = new Set()
  const recordIndex = existingCourseStatusIndex(courseRecords, [])
  const keptIndex = new Map()
  for (const row of planned) {
    const code = String(row.course_code ?? '').toUpperCase()
    const alreadyHasRecord = findCrossListedMatch(code, crossListingMap, recordIndex)
    const alreadyKeptPlanned = findCrossListedMatch(code, crossListingMap, keptIndex)
    if (alreadyHasRecord || alreadyKeptPlanned) {
      hidden.add(row.id)
      continue
    }
    keptIndex.set(code, 'planned')
  }
  return hidden
}

/**
 * Builds the year-tabbed, two-column data this view renders, merging four
 * sources that otherwise never meet:
 *  - realTerms (GET /terms): calendar terms, used for status + real dates
 *  - courseRecords (GET /course-records, passed down from the dashboard's
 *    own profile fetch): past/in-progress coursework with grades
 *  - scheduleTerms (GET /schedule's terms[]): the scheduler's forward plan,
 *    used both as the future column's "confirmed" list (there is none --
 *    nothing is confirmed until enrollment) and, per product decision, as
 *    the "Suggested courses" section, since it is the only real
 *    recommendation data currently exposed by any endpoint.
 *  - plannedCourses (GET /planned-courses): courses the student added to a
 *    future term themselves. Rendered only in the 'future' branch, in their
 *    own `planned` array with the "Added" treatment. A planned code also
 *    present in the scheduler's plan for that term is shown once, here --
 *    the suggestion is dropped (see below), matching the plannedCodes
 *    (case-insensitive) convention.
 *
 * plannedCourses defaults to [] so callers that predate it (and tests) keep
 * working unchanged. decisions/candidateSets likewise default to [] -- when
 * present, LOCKED/CHOICE_REQUIRED/EXCLUDED decisions are bucketed onto the
 * term card the backend resolved for each (semester.decisions); a decision
 * whose resolved term falls beyond every scheduled/enrolled year adds that
 * year to the grid, the same way a scheduler-only term already does.
 */
export function buildDegreeScheduleYears({ realTerms, scheduleTerms, courseRecords, gradingSchema, today, plannedCourses, decisions, candidateSets, crossListings }) {
  const terms = Array.isArray(realTerms) ? realTerms : []
  const schedule = Array.isArray(scheduleTerms) ? scheduleTerms : []
  const records = Array.isArray(courseRecords) ? courseRecords : []
  const planned = Array.isArray(plannedCourses) ? plannedCourses : []
  const crossListingMap = crossListings && typeof crossListings === 'object' ? crossListings : {}
  const hiddenIds = hiddenPlannedIds(planned, records, crossListingMap)

  const termsByKey = new Map(terms.map((term) => [term.key, term]))
  const scheduleByKey = new Map(schedule.map((term) => [term.term_key, term]))
  const decisionsByTermKey = bucketDecisionsByTerm(decisions, candidateSets)

  const yearKeys = new Set()
  for (const term of terms) {
    if (!YEAR_SEMESTER_SEASONS.includes(term.season)) continue
    const yearKey = academicYearKey(term.year, term.season)
    if (yearKey !== null) yearKeys.add(yearKey)
  }
  for (const termKey of [...scheduleByKey.keys(), ...decisionsByTermKey.keys()]) {
    const match = /^(\d{4})-(Fall|Spring)$/.exec(termKey)
    if (!match) continue
    yearKeys.add(academicYearKey(Number(match[1]), match[2]))
  }

  const sortedYearKeys = [...yearKeys].sort((a, b) => a - b)

  return sortedYearKeys.map((yearKey, index) => ({
    yearKey,
    label: academicYearLabel(index),
    semesters: YEAR_SEMESTER_SEASONS.map((season) => {
      const calendarYear = season === 'Fall' ? yearKey : yearKey + 1
      const termKey = `${calendarYear}-${season}`
      const realTerm = termsByKey.get(termKey) ?? null
      const state = semesterState(realTerm, today)

      if (state === 'past' || state === 'in_progress') {
        // realTerm.id can still be null for a term with calendar dates the
        // student has never enrolled in (no academic_terms row materialized
        // yet) -- that has no course_records to match, by construction, so
        // it must not fall through to matching other records' null term_id.
        const semesterCourses = realTerm.id === null
          ? []
          : records
              .filter((record) => record.term_id === realTerm.id)
              .filter((record) => record.status !== 'dropped')
        return {
          season,
          termKey,
          state,
          totalCreditsLabel: formatCredits(sumCredits(semesterCourses)),
          courses: semesterCourses.map((record) => ({
            course_code: record.course_code,
            title: record.title ?? null,
            credit_hours: record.credit_hours,
            gradeBadge: state === 'past' ? formatGradeBadge(record.letter_grade, gradingSchema) : null,
          })),
          suggestedCourses: [],
          planned: [],
          // A past/in-progress term is satisfied coursework -- the requirement
          // pipeline never emits a decision for it (scope_schedule_input's
          // SATISFIED early-return), and resolved_term_key is always a future
          // term anyway. Hard-empty here so a decision can never surface on
          // one of these columns regardless of upstream data.
          decisions: [],
        }
      }

      const scheduled = scheduleByKey.get(termKey) ?? null

      // A planned row always carries a real term_id (ensure_term_row makes one
      // on add); a term with no materialized id therefore has none, by
      // construction -- same guard the past/in_progress branch applies to
      // course_records.
      const plannedRowsForTerm = realTerm?.id == null
        ? []
        : planned.filter((row) => row.term_id === realTerm.id)

      // Display-only: a row cross-listed with something the student already
      // has (course_records or an earlier planned row -- see hiddenPlannedIds
      // above) is excluded from what renders, but it still counts as
      // genuinely planned for the suggested-course reconciliation just below,
      // so that reconciliation is computed off plannedRowsForTerm (pre-hide),
      // not plannedForTerm.
      const plannedForTerm = plannedRowsForTerm
        .filter((row) => !hiddenIds.has(row.id))
        .map((row) => ({
          id: row.id,
          course_code: row.course_code,
          title: row.title ?? null,
          credit_hours: row.credit_hours,
        }))

      // Reconcile against the scheduler's plan: a course the student already
      // added is shown once, under the added treatment -- drop the matching
      // suggestion. Case-insensitive, matching plannedCodes (termPlanning.mjs).
      // Cross-listing-aware: a planned CSCE 222 must also drop a suggested
      // ECEN 222 (the same course under its other departmental code), not
      // just an exact-code match -- otherwise the suggestion sits unfiltered
      // next to its own cross-listed twin. Done by pre-expanding the set with
      // each planned code's cross-listed partners, so the .has() check below
      // stays a single, unchanged lookup.
      const plannedCodeSet = new Set()
      for (const row of plannedRowsForTerm) {
        const code = String(row.course_code ?? '').toUpperCase()
        plannedCodeSet.add(code)
        for (const partner of crossListingMap[code] ?? []) {
          plannedCodeSet.add(String(partner).toUpperCase())
        }
      }

      return {
        season,
        termKey,
        state,
        totalCreditsLabel: 'Not scheduled',
        courses: [],
        suggestedCourses: (scheduled?.courses ?? [])
          .filter((course) => !plannedCodeSet.has(String(course.course_code ?? '').toUpperCase()))
          .map((course) => ({
            course_code: course.course_code,
            credit_hours: course.credit_hours,
          })),
        planned: plannedForTerm,
        decisions: decisionsByTermKey.get(termKey) ?? [],
      }
    }),
  }))
}
