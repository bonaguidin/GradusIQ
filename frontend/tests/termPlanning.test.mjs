import test from 'node:test'
import assert from 'node:assert/strict'

import {
  MIN_SEARCH_LENGTH,
  SEASON_ORDER,
  catalogSearchUrl,
  currentGradeOptions,
  existingCourseStatusIndex,
  finalGradeOptions,
  findCrossListedMatch,
  formatCredits,
  formatTermDates,
  normalizeCrossListingsPayload,
  normalizeGradingSchemaPayload,
  normalizePlannedPayload,
  normalizeSearchPayload,
  normalizeTermsPayload,
  parseDate,
  pickDefaultTermKey,
  plannedCodes,
  plannedListUrl,
  plannedRemoveUrl,
  seasonOrdinal,
  sortTerms,
  termCourseGroups,
  termStatus,
} from '../src/lib/termPlanning.mjs'

const term = (over) => ({
  key: `${over.year}-${over.season}`,
  id: null,
  label: `${over.season} ${over.year}`,
  sequence: null,
  start_date: null,
  end_date: null,
  enrolled: false,
  is_upcoming: false,
  ...over,
})

const SUMMER_2026 = term({ year: 2026, season: 'Summer', start_date: '2026-05-26', end_date: '2026-08-06' })
const FALL_2026 = term({ year: 2026, season: 'Fall', start_date: '2026-08-24', end_date: '2026-12-10' })
const SPRING_2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })

// ── season ordering ─────────────────────────────────────────────────────────

test('season ordinals mirror SEASON_ORDER in transcript/terms.py', () => {
  assert.deepEqual(SEASON_ORDER, {
    Winter: 0, Spring: 1, May: 2, Summer: 3, August: 4, Fall: 5,
  })
})

test('SMU intersessions sort between the terms they fall between', () => {
  const ordered = sortTerms([
    term({ year: 2026, season: 'Fall' }),
    term({ year: 2026, season: 'August' }),
    term({ year: 2026, season: 'May' }),
    term({ year: 2026, season: 'Spring' }),
    term({ year: 2026, season: 'Summer' }),
    term({ year: 2026, season: 'Winter' }),
  ])
  assert.deepEqual(ordered.map((t) => t.season), [
    'Winter', 'Spring', 'May', 'Summer', 'August', 'Fall',
  ])
})

test('an unrecognized season sorts last within its own year', () => {
  const ordered = sortTerms([
    term({ year: 2027, season: 'Spring' }),
    term({ year: 2026, season: 'current', label: 'Current Term' }),
    term({ year: 2026, season: 'Fall' }),
  ])
  assert.deepEqual(ordered.map((t) => t.label), ['Fall 2026', 'Current Term', 'Spring 2027'])
})

test('seasonOrdinal does not resolve inherited object properties', () => {
  // A season literally named "constructor" must not sort as a number.
  assert.equal(seasonOrdinal('constructor'), 99)
  assert.equal(seasonOrdinal('toString'), 99)
})

// ── default term selection ──────────────────────────────────────────────────
//
// `today` is injected everywhere here: pickDefaultTermKey's rule 1 is a
// date-containment check, so a test that let it read the real clock would pass
// or fail depending on the day the suite runs.

const BEFORE_ALL = new Date(2026, 0, 1)      // nothing in progress yet
const MID_FALL_2026 = new Date(2026, 8, 6)   // inside Fall 2026 (Aug 24 - Dec 10)
const BETWEEN_TERMS = new Date(2026, 11, 20) // Fall 2026 over, Spring 2027 not begun
const AFTER_ALL = new Date(2028, 0, 1)       // every known term is past

test('opens on the term in progress, not the upcoming one', () => {
  // The regression: Sep 2026, Fall 2026 underway, Spring 2027 is upcoming.
  const key = pickDefaultTermKey(
    { terms: [FALL_2026, SPRING_2027], upcoming_term_key: '2027-Spring' },
    MID_FALL_2026,
  )
  assert.equal(key, '2026-Fall')
})

test('between terms, falls back to the backend upcoming_term_key', () => {
  const key = pickDefaultTermKey(
    { terms: [FALL_2026, SPRING_2027], upcoming_term_key: '2027-Spring' },
    BETWEEN_TERMS,
  )
  assert.equal(key, '2027-Spring')
})

test('the dropdown opens on the term the backend named when nothing is in progress', () => {
  const key = pickDefaultTermKey(
    { terms: [SUMMER_2026, FALL_2026, SPRING_2027], upcoming_term_key: '2026-Fall' },
    BEFORE_ALL,
  )
  assert.equal(key, '2026-Fall')
})

test('falls back to the is_upcoming flag when no key is named', () => {
  const key = pickDefaultTermKey(
    { terms: [SUMMER_2026, { ...FALL_2026, is_upcoming: true }], upcoming_term_key: null },
    BEFORE_ALL,
  )
  assert.equal(key, '2026-Fall')
})

test('after every known term, falls back to the latest enrolled term without throwing', () => {
  let key
  assert.doesNotThrow(() => {
    key = pickDefaultTermKey(
      {
        terms: [
          { ...SUMMER_2026, enrolled: true },
          { ...FALL_2026, enrolled: true },
          SPRING_2027,
        ],
        upcoming_term_key: null,
      },
      AFTER_ALL,
    )
  })
  assert.equal(key, '2026-Fall')
})

test('after the last known term with no upcoming key still returns a term, not a throw', () => {
  let key
  assert.doesNotThrow(() => {
    key = pickDefaultTermKey(
      { terms: [FALL_2026, SPRING_2027], upcoming_term_key: null },
      AFTER_ALL,
    )
  })
  assert.equal(key, '2027-Spring')
})

test('an unknown upcoming key does not select a term that is not there', () => {
  const key = pickDefaultTermKey(
    { terms: [SUMMER_2026, FALL_2026], upcoming_term_key: '2099-Fall' },
    BEFORE_ALL,
  )
  assert.equal(key, '2026-Fall')
})

test('a term with null or malformed dates never matches the in-progress rule and never throws', () => {
  const noDates = term({ year: 2026, season: 'current', label: 'Current Term' }) // start/end null
  const badDates = term({ year: 2026, season: 'Spring', start_date: 'not-a-date', end_date: 'nope' })
  let key
  assert.doesNotThrow(() => {
    key = pickDefaultTermKey(
      { terms: [noDates, badDates, FALL_2026], upcoming_term_key: null },
      MID_FALL_2026,
    )
  })
  // Only FALL_2026 has parseable dates that contain `today`, so it wins rule 1
  // even though two other terms are present and unparseable.
  assert.equal(key, '2026-Fall')
})

test('with an in-progress enrolled term and an in-progress non-enrolled one, the enrolled term wins', () => {
  const overlapStart = new Date(2026, 8, 1) // Sep 1 -- inside both ranges below
  const intersession = term({ year: 2026, season: 'Summer', start_date: '2026-08-01', end_date: '2026-09-15' })
  assert.equal(
    pickDefaultTermKey(
      { terms: [{ ...intersession, enrolled: false }, { ...FALL_2026, enrolled: true }], upcoming_term_key: null },
      overlapStart,
    ),
    '2026-Fall',
  )
  // And it is the `enrolled` flag doing the work, not the list order.
  assert.equal(
    pickDefaultTermKey(
      { terms: [{ ...intersession, enrolled: true }, { ...FALL_2026, enrolled: false }], upcoming_term_key: null },
      overlapStart,
    ),
    '2026-Summer',
  )
})

test('no terms means no selection', () => {
  assert.equal(pickDefaultTermKey({ terms: [], upcoming_term_key: null }, MID_FALL_2026), null)
  assert.equal(pickDefaultTermKey(null, MID_FALL_2026), null)
  assert.equal(pickDefaultTermKey({ terms: [], upcoming_term_key: null }), null)
})

// ── term status ─────────────────────────────────────────────────────────────

test('term status is relative to the given day', () => {
  assert.equal(termStatus(FALL_2026, new Date(2026, 7, 11)), 'upcoming')
  assert.equal(termStatus(FALL_2026, new Date(2026, 9, 1)), 'in_progress')
  assert.equal(termStatus(FALL_2026, new Date(2027, 0, 5)), 'past')
})

test('a term boundary day is inside the term, not outside it', () => {
  assert.equal(termStatus(FALL_2026, new Date(2026, 7, 24)), 'in_progress')
  assert.equal(termStatus(FALL_2026, new Date(2026, 11, 10)), 'in_progress')
})

test('a term with no calendar row reports unknown, not an error', () => {
  const seeded = term({ year: 2026, season: 'current', label: 'Current Term' })
  assert.equal(termStatus(seeded, new Date(2026, 7, 11)), 'unknown')
})

// ── date parsing ────────────────────────────────────────────────────────────

test('dates parse in local time, not UTC', () => {
  // new Date('2026-08-24') is UTC midnight, which is Aug 23 locally anywhere
  // west of Greenwich -- a term starting tomorrow would compare as started.
  const parsed = parseDate('2026-08-24')
  assert.equal(parsed.getFullYear(), 2026)
  assert.equal(parsed.getMonth(), 7)
  assert.equal(parsed.getDate(), 24)
})

test('malformed dates return null rather than an Invalid Date', () => {
  assert.equal(parseDate(''), null)
  assert.equal(parseDate(null), null)
  assert.equal(parseDate('not-a-date'), null)
})

test('formatTermDates returns null when the term has no calendar row', () => {
  assert.equal(formatTermDates(term({ year: 2026, season: 'current' })), null)
  assert.match(formatTermDates(FALL_2026), /Aug 24, 2026/)
})

// ── course grouping ─────────────────────────────────────────────────────────

test('planned courses are returned separately from course records', () => {
  const records = [
    { id: 'c1', term_id: 't1', course_code: 'CSCE 121' },
    { id: 'c2', term_id: 't2', course_code: 'MATH 251' },
  ]
  const planned = [
    { id: 'p1', term_id: 't1', course_code: 'CSCE 221' },
    { id: 'p2', term_id: 't2', course_code: 'STAT 211' },
  ]
  const groups = termCourseGroups('t1', records, planned)

  assert.deepEqual(groups.records.map((r) => r.id), ['c1'])
  assert.deepEqual(groups.planned.map((r) => r.id), ['p1'])
})

test('a term with no id groups the rows that also have no term', () => {
  const groups = termCourseGroups(null, [{ id: 'c1', term_id: null }], [{ id: 'p1', term_id: null }])
  assert.equal(groups.records.length, 1)
  assert.equal(groups.planned.length, 1)
})

test('plannedCodes is case-insensitive', () => {
  const codes = plannedCodes([{ course_code: 'csce 121' }])
  assert.ok(codes.has('CSCE 121'))
})

// ── formatting ──────────────────────────────────────────────────────────────

test('credits render singular, plural, and as a range', () => {
  assert.equal(formatCredits(1, 1), '1 credit')
  assert.equal(formatCredits(3, 3), '3 credits')
  assert.equal(formatCredits(1, 4), '1-4 credits')
  assert.equal(formatCredits(null, null), null)
  // 0 is a real credit value in this catalog (variable-credit research and
  // internship courses), so it must not be treated as missing.
  assert.equal(formatCredits(0, 0), '0 credits')
  assert.equal(formatCredits(0, 23), '0-23 credits')
})

// ── urls ────────────────────────────────────────────────────────────────────

test('urls encode their parameters', () => {
  assert.equal(plannedRemoveUrl('a b'), '/api/v2/student/me/planned-courses/a%20b')
  assert.equal(catalogSearchUrl('MATH 251'), '/api/v2/student/me/catalog/search?q=MATH%20251')
  assert.equal(plannedListUrl(null), '/api/v2/student/me/planned-courses')
  assert.equal(plannedListUrl('t1'), '/api/v2/student/me/planned-courses?term_id=t1')
})

test('search does not fire on a single character', () => {
  assert.ok(MIN_SEARCH_LENGTH > 1)
})

// ── payload normalizers ─────────────────────────────────────────────────────

test('normalizers reject non-200 and malformed bodies without throwing', () => {
  for (const [status, body] of [[500, null], [200, null], [401, {}], [200, 'nope']]) {
    assert.equal(normalizeTermsPayload(status, body).ok, status === 200 && body === undefined)
    assert.deepEqual(normalizePlannedPayload(status, body).plannedCourses, [])
    assert.deepEqual(normalizeSearchPayload(status, body).results, [])
  }
})

test('a valid terms payload comes back sorted', () => {
  const result = normalizeTermsPayload(200, {
    terms: [SPRING_2027, SUMMER_2026, FALL_2026],
    upcoming_term_key: '2026-Fall',
  })
  assert.equal(result.ok, true)
  assert.deepEqual(result.terms.map((t) => t.key), ['2026-Summer', '2026-Fall', '2027-Spring'])
  assert.equal(result.upcomingTermKey, '2026-Fall')
})

test('a missing planned_courses array normalizes to empty, not undefined', () => {
  assert.deepEqual(normalizePlannedPayload(200, {}).plannedCourses, [])
  assert.deepEqual(normalizeSearchPayload(200, {}).results, [])
})

// ── institution-specific grading schema ─────────────────────────────────────

const TAMU_SCHEMA = {
  institutionId: 'tamu',
  usesPlusMinus: false,
  grades: [
    { letter: 'A', points: 4.0, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'B', points: 3.0, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'C', points: 2.0, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'D', points: 1.0, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'F', points: 0.0, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'W', points: null, counts_toward_gpa: false, counts_toward_credit: false },
    { letter: 'I', points: null, counts_toward_gpa: false, counts_toward_credit: false },
  ],
}

const SMU_SCHEMA = {
  institutionId: 'smu',
  usesPlusMinus: true,
  grades: [
    { letter: 'A', points: 4.0, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'A-', points: 3.7, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'B+', points: 3.3, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'B', points: 3.0, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'F', points: 0.0, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'P', points: null, counts_toward_gpa: false, counts_toward_credit: true },
  ],
}

test('TAMU current-grade options are exactly A-F, no plus/minus', () => {
  assert.deepEqual(currentGradeOptions(TAMU_SCHEMA), ['A', 'B', 'C', 'D', 'F'])
})

test('TAMU current-grade options never include A-, B+, B-, C+', () => {
  const options = currentGradeOptions(TAMU_SCHEMA)
  for (const letter of ['A-', 'B+', 'B-', 'C+', 'C-', 'D+', 'D-']) {
    assert.equal(options.includes(letter), false)
  }
})

test('TAMU final-grade options additionally include non-GPA-bearing W and I', () => {
  assert.deepEqual(finalGradeOptions(TAMU_SCHEMA), ['A', 'B', 'C', 'D', 'F', 'W', 'I'])
})

test('an institution configured with plus/minus grading keeps its own scale independently', () => {
  assert.deepEqual(currentGradeOptions(SMU_SCHEMA), ['A', 'A-', 'B+', 'B', 'F'])
  assert.deepEqual(finalGradeOptions(SMU_SCHEMA), ['A', 'A-', 'B+', 'B', 'F', 'P'])
})

test('current-grade options exclude grades the institution does not count toward GPA', () => {
  // SMU's P is credit-bearing but not GPA-bearing -- it must not appear as a
  // *current* grade (which exists only to project GPA), but must still
  // appear as a *final* grade (a legitimate final outcome).
  assert.equal(currentGradeOptions(SMU_SCHEMA).includes('P'), false)
  assert.equal(finalGradeOptions(SMU_SCHEMA).includes('P'), true)
})

test('a null or missing schema yields no grade options rather than throwing', () => {
  assert.deepEqual(currentGradeOptions(null), [])
  assert.deepEqual(finalGradeOptions(undefined), [])
  assert.deepEqual(currentGradeOptions({}), [])
})

test('normalizeGradingSchemaPayload reads uses_plus_minus and grades off a 200', () => {
  const result = normalizeGradingSchemaPayload(200, {
    institution_id: 'tamu',
    uses_plus_minus: false,
    grades: TAMU_SCHEMA.grades,
  })
  assert.equal(result.ok, true)
  assert.equal(result.schema.usesPlusMinus, false)
  assert.equal(result.schema.institutionId, 'tamu')
  assert.deepEqual(result.schema.grades, TAMU_SCHEMA.grades)
})

test('normalizeGradingSchemaPayload rejects non-200 and malformed bodies without throwing', () => {
  assert.deepEqual(normalizeGradingSchemaPayload(502, null), { ok: false, schema: null })
  assert.deepEqual(normalizeGradingSchemaPayload(200, undefined), { ok: false, schema: null })
})

// ── cross-listing-aware duplicate detection ─────────────────────────────────

test('normalizeCrossListingsPayload uppercases both codes and partners', () => {
  const result = normalizeCrossListingsPayload(200, {
    cross_listings: { 'csce 222': ['ecen 222'], 'ECEN 222': ['CSCE 222'] },
  })
  assert.equal(result.ok, true)
  assert.deepEqual(result.crossListings, { 'CSCE 222': ['ECEN 222'], 'ECEN 222': ['CSCE 222'] })
})

test('normalizeCrossListingsPayload rejects non-200 and malformed bodies without throwing', () => {
  assert.deepEqual(normalizeCrossListingsPayload(502, null), { ok: false, crossListings: {} })
  assert.deepEqual(normalizeCrossListingsPayload(200, { cross_listings: 'not an object' }), {
    ok: true,
    crossListings: {},
  })
})

test('existingCourseStatusIndex is student-wide, not scoped to one term', () => {
  const courseRecords = [
    { course_code: 'CSCE 222', status: 'in_progress', term_id: 'fall-2026' },
    { course_code: 'MATH 251', status: 'completed', term_id: 'spring-2026' },
    { course_code: 'CSCE 999', status: 'dropped', term_id: 'fall-2026' },
  ]
  const plannedCourses = [{ course_code: 'ENGL 210', term_id: 'fall-2028' }]

  const index = existingCourseStatusIndex(courseRecords, plannedCourses)

  assert.equal(index.get('CSCE 222'), 'in_progress')
  assert.equal(index.get('MATH 251'), 'completed')
  assert.equal(index.get('ENGL 210'), 'planned')
  // 'dropped' is deliberately excluded -- a dropped course is not a reason to
  // block re-planning it or its cross-listed alias later.
  assert.equal(index.has('CSCE 999'), false)
})

test('existingCourseStatusIndex prefers in_progress over completed over planned for the same code', () => {
  const courseRecords = [
    { course_code: 'CSCE 222', status: 'completed', term_id: 't1' },
    { course_code: 'CSCE 222', status: 'in_progress', term_id: 't2' },
  ]
  const plannedCourses = [{ course_code: 'CSCE 222', term_id: 't3' }]

  const index = existingCourseStatusIndex(courseRecords, plannedCourses)

  assert.equal(index.get('CSCE 222'), 'in_progress')
})

test('existingCourseStatusIndex is case-insensitive and tolerates missing arrays', () => {
  const index = existingCourseStatusIndex([{ course_code: 'csce 222', status: 'in_progress' }], null)
  assert.equal(index.get('CSCE 222'), 'in_progress')
  assert.deepEqual([...existingCourseStatusIndex(undefined, undefined).entries()], [])
})

test('findCrossListedMatch finds a cross-listed alias regardless of which code is searched', () => {
  const crossListings = { 'CSCE 222': ['ECEN 222'], 'ECEN 222': ['CSCE 222'] }
  const existingIndex = new Map([['CSCE 222', 'in_progress']])

  // Searching the code that is NOT the one on record still resolves, because
  // the map is keyed both ways (it comes from the backend already listing
  // both directions -- see cross_listing.py's module comment).
  const match = findCrossListedMatch('ECEN 222', crossListings, existingIndex)
  assert.deepEqual(match, { code: 'CSCE 222', status: 'in_progress' })
})

test('findCrossListedMatch returns null for a non-cross-listed code', () => {
  const crossListings = { 'CSCE 222': ['ECEN 222'] }
  const existingIndex = new Map([['MATH 251', 'completed']])
  assert.equal(findCrossListedMatch('CSCE 121', crossListings, existingIndex), null)
})

test('findCrossListedMatch returns null when the cross-listed partner is not something the student already has', () => {
  const crossListings = { 'CSCE 222': ['ECEN 222'] }
  const existingIndex = new Map()
  assert.equal(findCrossListedMatch('CSCE 222', crossListings, existingIndex), null)
})

test('findCrossListedMatch is case-insensitive on the searched code', () => {
  const crossListings = { 'CSCE 222': ['ECEN 222'] }
  const existingIndex = new Map([['ECEN 222', 'planned']])
  assert.deepEqual(findCrossListedMatch('csce 222', crossListings, existingIndex), {
    code: 'ECEN 222',
    status: 'planned',
  })
})
