import test from 'node:test'
import assert from 'node:assert/strict'

import {
  academicYearKey,
  academicYearLabel,
  bucketDecisionsByTerm,
  buildDegreeScheduleYears,
  formatGradeBadge,
  semesterState,
} from '../src/lib/degreeScheduleYears.mjs'

const TODAY = new Date(2026, 7, 24) // 2026-08-24, matches currentDate in this session

const term = (over) => ({
  key: `${over.year}-${over.season}`,
  id: `${over.year}-${over.season}-id`,
  label: `${over.season} ${over.year}`,
  sequence: null,
  start_date: null,
  end_date: null,
  enrolled: false,
  is_upcoming: false,
  ...over,
})

const record = (over) => ({
  id: `rec-${over.course_code}`,
  term_id: null,
  course_code: 'XXXX 000',
  title: null,
  credit_hours: 3,
  letter_grade: null,
  status: 'completed',
  ...over,
})

const plannedRow = (over) => ({
  id: `plan-${over.course_code}`,
  term_id: null,
  course_code: 'XXXX 000',
  title: null,
  credit_hours: 3,
  catalog_course_id: null,
  created_at: '2026-09-01T00:00:00Z',
  kind: 'planned',
  ...over,
})

const GRADING_SCHEMA = {
  institutionId: 'inst-1',
  usesPlusMinus: true,
  grades: [
    { letter: 'A', points: 4.0, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'B+', points: 3.3, counts_toward_gpa: true, counts_toward_credit: true },
    { letter: 'P', points: null, counts_toward_gpa: false, counts_toward_credit: true },
  ],
}

// ── academicYearKey / academicYearLabel ─────────────────────────────────────

test('Fall pairs with the following Spring under the Fall calendar year', () => {
  assert.equal(academicYearKey(2026, 'Fall'), 2026)
  assert.equal(academicYearKey(2027, 'Spring'), 2026)
})

test('an intersession season is out of scope for year bucketing', () => {
  assert.equal(academicYearKey(2026, 'Summer'), null)
})

test('ordinal labels count up, falling back past the named words', () => {
  assert.equal(academicYearLabel(0), 'First year')
  assert.equal(academicYearLabel(3), 'Fourth year')
  assert.equal(academicYearLabel(6), 'Year 7')
})

// ── formatGradeBadge ─────────────────────────────────────────────────────────

test('formats a mapped grade with its GPA points', () => {
  assert.equal(formatGradeBadge('B+', GRADING_SCHEMA), 'B+ (3.3)')
})

test('falls back to the bare letter when the grade has no points', () => {
  assert.equal(formatGradeBadge('P', GRADING_SCHEMA), 'P')
})

test('falls back to the bare letter when the grade is unmapped entirely', () => {
  assert.equal(formatGradeBadge('W', GRADING_SCHEMA), 'W')
})

test('returns null for no grade', () => {
  assert.equal(formatGradeBadge(null, GRADING_SCHEMA), null)
})

// ── semesterState ────────────────────────────────────────────────────────────

test('a term with no calendar row at all is future', () => {
  assert.equal(semesterState(null, TODAY), 'future')
})

test('a term whose dates have passed is past', () => {
  const t = term({ year: 2025, season: 'Fall', start_date: '2025-08-25', end_date: '2025-12-10' })
  assert.equal(semesterState(t, TODAY), 'past')
})

test('a term underway today is in_progress', () => {
  const t = term({ year: 2026, season: 'Fall', start_date: '2026-08-24', end_date: '2026-12-10' })
  assert.equal(semesterState(t, TODAY), 'in_progress')
})

test('a term that has not started yet is future', () => {
  const t = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  assert.equal(semesterState(t, TODAY), 'future')
})

// ── buildDegreeScheduleYears ─────────────────────────────────────────────────

test('groups Fall/Spring terms into one academic year each, ordered ascending', () => {
  const years = buildDegreeScheduleYears({
    realTerms: [
      term({ year: 2025, season: 'Fall', start_date: '2025-08-25', end_date: '2025-12-10' }),
      term({ year: 2026, season: 'Spring', start_date: '2026-01-20', end_date: '2026-05-10' }),
      term({ year: 2026, season: 'Fall', start_date: '2026-08-24', end_date: '2026-12-10' }),
    ],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
  })
  assert.deepEqual(years.map((y) => y.label), ['First year', 'Second year'])
  assert.deepEqual(years.map((y) => y.semesters.map((s) => s.termKey)), [
    ['2025-Fall', '2026-Spring'],
    ['2026-Fall', '2027-Spring'],
  ])
})

test('a past semester carries real coursework with grade+GPA badges, dropped courses excluded', () => {
  const fall2025 = term({ year: 2025, season: 'Fall', start_date: '2025-08-25', end_date: '2025-12-10' })
  const years = buildDegreeScheduleYears({
    realTerms: [fall2025],
    scheduleTerms: [],
    courseRecords: [
      record({ course_code: 'CSCE 121', term_id: fall2025.id, letter_grade: 'A', status: 'completed', credit_hours: 4 }),
      record({ course_code: 'MATH 151', term_id: fall2025.id, letter_grade: 'B+', status: 'completed', credit_hours: 3 }),
      record({ course_code: 'PHYS 218', term_id: fall2025.id, letter_grade: 'A', status: 'dropped', credit_hours: 4 }),
    ],
    gradingSchema: GRADING_SCHEMA,
    today: TODAY,
  })
  const fall = years[0].semesters[0]
  assert.equal(fall.state, 'past')
  assert.equal(fall.totalCreditsLabel, '7 credits')
  assert.deepEqual(fall.courses.map((c) => c.course_code), ['CSCE 121', 'MATH 151'])
  assert.deepEqual(fall.courses.map((c) => c.gradeBadge), ['A (4.0)', 'B+ (3.3)'])
})

test('an in-progress semester never carries a grade badge, even with a current letter_grade entered', () => {
  const fall2026 = term({ year: 2026, season: 'Fall', start_date: '2026-08-24', end_date: '2026-12-10' })
  const years = buildDegreeScheduleYears({
    realTerms: [fall2026],
    scheduleTerms: [],
    courseRecords: [
      record({ course_code: 'CSCE 221', term_id: fall2026.id, letter_grade: 'A', status: 'in_progress', credit_hours: 3 }),
    ],
    gradingSchema: GRADING_SCHEMA,
    today: TODAY,
  })
  const fall = years[0].semesters[0]
  assert.equal(fall.state, 'in_progress')
  assert.equal(fall.courses[0].gradeBadge, null)
})

test('a future semester has no confirmed courses; the scheduler plan becomes suggestions', () => {
  const years = buildDegreeScheduleYears({
    realTerms: [],
    scheduleTerms: [
      {
        term_key: '2027-Spring',
        total_credit_hours: 6,
        courses: [
          { course_code: 'CSCE 314', credit_hours: 3, requirement_group_id: 'g1', limitations: [] },
          { course_code: 'CSCE 331', credit_hours: 3, requirement_group_id: 'g2', limitations: [] },
        ],
      },
    ],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.equal(spring.state, 'future')
  assert.equal(spring.totalCreditsLabel, 'Not scheduled')
  assert.deepEqual(spring.courses, [])
  assert.deepEqual(spring.suggestedCourses.map((c) => c.course_code), ['CSCE 314', 'CSCE 331'])
})

test('a year appears from scheduler output alone, with no real academic_terms row yet', () => {
  const years = buildDegreeScheduleYears({
    realTerms: [],
    scheduleTerms: [
      { term_key: '2029-Fall', total_credit_hours: 3, courses: [{ course_code: 'CSCE 482', credit_hours: 3, requirement_group_id: 'g1', limitations: [] }] },
    ],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
  })
  assert.equal(years.length, 1)
  assert.equal(years[0].yearKey, 2029)
})

test('no data at all yields no years, not a crash', () => {
  const years = buildDegreeScheduleYears({
    realTerms: [],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
  })
  assert.deepEqual(years, [])
})

test('a real term with no materialized id (never enrolled) matches no course_records, even ones with null term_id', () => {
  const fall2026 = term({ year: 2026, season: 'Fall', id: null, start_date: '2025-01-01', end_date: '2025-05-01' })
  const years = buildDegreeScheduleYears({
    realTerms: [fall2026],
    scheduleTerms: [],
    courseRecords: [
      record({ course_code: 'STRAY 101', term_id: null, status: 'completed' }),
    ],
    gradingSchema: null,
    today: TODAY,
  })
  const fall = years[0].semesters[0]
  assert.equal(fall.state, 'past')
  assert.deepEqual(fall.courses, [])
})

// ── plannedCourses (student-added, future terms only) ───────────────────────

test('plannedCourses is optional: absent input yields an empty planned array on every semester', () => {
  const years = buildDegreeScheduleYears({
    realTerms: [term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
  })
  for (const year of years) {
    for (const semester of year.semesters) assert.deepEqual(semester.planned, [])
  }
})

test('a student-added course for a future term appears in semester.planned with id/code/title/credits', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  const years = buildDegreeScheduleYears({
    realTerms: [spring2027],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
    plannedCourses: [
      plannedRow({ id: 'p1', course_code: 'CSCE 469', title: 'Special Topics', credit_hours: 3, term_id: spring2027.id }),
    ],
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.equal(spring.state, 'future')
  assert.deepEqual(spring.planned, [
    { id: 'p1', course_code: 'CSCE 469', title: 'Special Topics', credit_hours: 3 },
  ])
})

test('a course in BOTH the scheduler plan and the student plan for one term appears once, under planned, not suggested (case-insensitive)', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  const years = buildDegreeScheduleYears({
    realTerms: [spring2027],
    scheduleTerms: [
      {
        term_key: '2027-Spring',
        total_credit_hours: 6,
        courses: [
          { course_code: 'CSCE 314', credit_hours: 3, requirement_group_id: 'g1', limitations: [] },
          { course_code: 'CSCE 331', credit_hours: 3, requirement_group_id: 'g2', limitations: [] },
        ],
      },
    ],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
    plannedCourses: [
      // lower-case on purpose -- the reconciliation is case-insensitive
      plannedRow({ id: 'p1', course_code: 'csce 314', title: null, credit_hours: 3, term_id: spring2027.id }),
    ],
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.deepEqual(spring.planned.map((c) => c.course_code), ['csce 314'])
  assert.deepEqual(spring.suggestedCourses.map((c) => c.course_code), ['CSCE 331'])
})

test('a suggested course cross-listed with a planned one is dropped too, not just an exact-code match', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  const years = buildDegreeScheduleYears({
    realTerms: [spring2027],
    scheduleTerms: [
      {
        term_key: '2027-Spring',
        total_credit_hours: 6,
        courses: [
          // The scheduler suggests ECEN 222, the same course as CSCE 222
          // under its other departmental code.
          { course_code: 'ECEN 222', credit_hours: 3, requirement_group_id: 'g1', limitations: [] },
          { course_code: 'CSCE 331', credit_hours: 3, requirement_group_id: 'g2', limitations: [] },
        ],
      },
    ],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
    plannedCourses: [
      plannedRow({ id: 'p1', course_code: 'CSCE 222', title: null, credit_hours: 3, term_id: spring2027.id }),
    ],
    crossListings: { 'CSCE 222': ['ECEN 222'], 'ECEN 222': ['CSCE 222'] },
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.deepEqual(spring.planned.map((c) => c.course_code), ['CSCE 222'])
  // ECEN 222 is gone -- CSCE 331 (unrelated) still shows.
  assert.deepEqual(spring.suggestedCourses.map((c) => c.course_code), ['CSCE 331'])
})

test('with no crossListings map at all, reconciliation still works via exact match (backward compatible)', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  const years = buildDegreeScheduleYears({
    realTerms: [spring2027],
    scheduleTerms: [
      { term_key: '2027-Spring', total_credit_hours: 3, courses: [
        { course_code: 'CSCE 314', credit_hours: 3, requirement_group_id: 'g1', limitations: [] },
      ] },
    ],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
    plannedCourses: [
      plannedRow({ id: 'p1', course_code: 'CSCE 314', title: null, credit_hours: 3, term_id: spring2027.id }),
    ],
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.deepEqual(spring.suggestedCourses, [])
})

test('a planned row is not shown against a future term with no materialized academic_terms id', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', id: null, start_date: '2027-01-19', end_date: '2027-05-11' })
  const years = buildDegreeScheduleYears({
    realTerms: [spring2027],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
    plannedCourses: [plannedRow({ id: 'p1', course_code: 'CSCE 469', term_id: null })],
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.deepEqual(spring.planned, [])
})

// ── cross-listed duplicate planned rows are hidden from display, not deleted ─

test('a planned row cross-listed with an in-progress course_records entry is excluded from semester.planned', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  const plannedInput = [
    plannedRow({ id: 'p1', course_code: 'CSCE 222', title: null, credit_hours: 3, term_id: spring2027.id }),
  ]
  const years = buildDegreeScheduleYears({
    realTerms: [spring2027],
    scheduleTerms: [],
    courseRecords: [
      // ECEN 222 is the same course as planned CSCE 222 under its other
      // departmental code, already in progress under a *different* term.
      record({ course_code: 'ECEN 222', status: 'in_progress', term_id: 'term-1' }),
    ],
    gradingSchema: null,
    today: TODAY,
    plannedCourses: plannedInput,
    crossListings: { 'CSCE 222': ['ECEN 222'], 'ECEN 222': ['CSCE 222'] },
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.deepEqual(spring.planned, [])
  // Display-only: the input array itself is untouched -- no row was deleted,
  // it just isn't rendered. Same object reference, same length.
  assert.equal(plannedInput.length, 1)
  assert.equal(plannedInput[0].id, 'p1')
})

test('two planned rows that are cross-listed with each other: the later one is hidden, the earlier one still renders', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  const plannedInput = [
    plannedRow({ id: 'p1', course_code: 'CSCE 222', title: null, credit_hours: 3, term_id: spring2027.id }),
    // Retroactive bad data: a second planned row for the same real course
    // under its other departmental code -- the add-time check now prevents
    // new instances of this, but old data can still have it.
    plannedRow({ id: 'p2', course_code: 'ECEN 222', title: null, credit_hours: 3, term_id: spring2027.id }),
  ]
  const years = buildDegreeScheduleYears({
    realTerms: [spring2027],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
    plannedCourses: plannedInput,
    crossListings: { 'CSCE 222': ['ECEN 222'], 'ECEN 222': ['CSCE 222'] },
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.deepEqual(spring.planned.map((c) => c.id), ['p1'])
  // Neither underlying row was touched.
  assert.equal(plannedInput.length, 2)
})

test('a planned row with no cross-listing conflict still renders normally', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  const years = buildDegreeScheduleYears({
    realTerms: [spring2027],
    scheduleTerms: [],
    courseRecords: [record({ course_code: 'MATH 251', status: 'completed', term_id: 'term-1' })],
    gradingSchema: null,
    today: TODAY,
    plannedCourses: [plannedRow({ id: 'p1', course_code: 'CSCE 222', term_id: spring2027.id })],
    crossListings: { 'CSCE 222': ['ECEN 222'], 'ECEN 222': ['CSCE 222'] },
  })
  const spring = years[0].semesters.find((s) => s.termKey === '2027-Spring')
  assert.deepEqual(spring.planned.map((c) => c.id), ['p1'])
})

test('removing a planned row from the input removes it from the term card (disappears on next load)', () => {
  const spring2027 = term({ year: 2027, season: 'Spring', start_date: '2027-01-19', end_date: '2027-05-11' })
  const args = {
    realTerms: [spring2027],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
  }
  const withRow = buildDegreeScheduleYears({
    ...args,
    plannedCourses: [plannedRow({ id: 'p1', course_code: 'CSCE 469', term_id: spring2027.id })],
  })
  assert.equal(withRow[0].semesters.find((s) => s.termKey === '2027-Spring').planned.length, 1)

  const afterRemoval = buildDegreeScheduleYears({ ...args, plannedCourses: [] })
  assert.deepEqual(afterRemoval[0].semesters.find((s) => s.termKey === '2027-Spring').planned, [])
})

test('planned rows never appear on a past or in-progress term card', () => {
  const fall2025 = term({ year: 2025, season: 'Fall', start_date: '2025-08-25', end_date: '2025-12-10' })
  const years = buildDegreeScheduleYears({
    realTerms: [fall2025],
    scheduleTerms: [],
    courseRecords: [],
    gradingSchema: null,
    today: TODAY,
    // A stray planned row pointing at a past term must not surface here.
    plannedCourses: [plannedRow({ id: 'p1', course_code: 'HIST 101', term_id: fall2025.id })],
  })
  const fall = years[0].semesters[0]
  assert.equal(fall.state, 'past')
  assert.deepEqual(fall.planned, [])
})

// ── decisions relocated onto term cards (Phase 3) ───────────────────────────

const feasibleCandidate = (over) => ({
  candidate_id: `cand-${over.candidate_id ?? 'x'}`,
  requirement_group_id: over.requirement_group_id ?? 'rg',
  requirement_name: over.requirement_name ?? 'Requirement',
  course_codes: over.course_codes ?? ['XXX 100'],
  unresolved_course_codes: [],
  candidate_courses: (over.course_codes ?? ['XXX 100']).map((code) => ({
    course_code: code, title: `${code} title`, credits: 3,
  })),
  existing_contribution: 0,
  additional_course_count: (over.course_codes ?? ['XXX 100']).length,
  additional_credits: 3,
  academic_feasibility: 'FEASIBLE',
  completion_term_index: over.completion_term_index ?? 0,
  limitations: [], source_order: [], exclusion_reasons: [], exclusion_details: [],
  ...over,
})

const excludedCandidate = (over) => ({
  ...feasibleCandidate(over),
  academic_feasibility: 'EXCLUDED',
  completion_term_index: null,
  exclusion_reasons: ['UNSCHEDULABLE'],
})

const decision = (over) => ({
  requirement_group_id: over.requirement_group_id,
  requirement_name: over.requirement_name ?? over.requirement_group_id,
  state: over.state,
  feasible_candidate_ids: over.feasible_candidate_ids ?? [],
  excluded_candidate_ids: over.excluded_candidate_ids ?? [],
  selected_candidate_id: over.selected_candidate_id ?? null,
  resolved_term_key: over.resolved_term_key ?? null,
})

const flatDecisions = (years) =>
  years.flatMap((year) => year.semesters.flatMap((semester) =>
    semester.decisions.map((entry) => ({ termKey: semester.termKey, state: semester.state, entry }))))

test('a LOCKED decision lands on the term card matching its resolved_term_key', () => {
  const hist = feasibleCandidate({ candidate_id: 'hist', requirement_group_id: 'locked', course_codes: ['HIST 1301'] })
  const histAlt = feasibleCandidate({ candidate_id: 'hist-alt', requirement_group_id: 'locked', course_codes: ['HIST 1302'], completion_term_index: 1 })
  const years = buildDegreeScheduleYears({
    realTerms: [], courseRecords: [], gradingSchema: null, today: TODAY,
    scheduleTerms: [{ term_key: '2027-Spring', total_credit_hours: 3, courses: [{ course_code: 'HIST 1301', credit_hours: 3, requirement_group_id: 'locked', limitations: [] }] }],
    decisions: [decision({
      requirement_group_id: 'locked', requirement_name: 'American History', state: 'LOCKED',
      feasible_candidate_ids: [hist.candidate_id, histAlt.candidate_id], selected_candidate_id: hist.candidate_id,
      resolved_term_key: '2027-Spring',
    })],
    candidateSets: [{ requirement_group_id: 'locked', requirement_name: 'American History', feasible_candidates: [hist, histAlt], excluded_candidates: [] }],
  })
  const placed = flatDecisions(years)
  assert.equal(placed.length, 1)
  assert.equal(placed[0].termKey, '2027-Spring')
  assert.equal(placed[0].entry.state, 'LOCKED')
  assert.equal(placed[0].entry.selectedCandidateId, hist.candidate_id)
  // both feasible candidates are carried for the "Change choice" affordance
  assert.deepEqual(placed[0].entry.candidates.map((c) => c.candidate_id), [hist.candidate_id, histAlt.candidate_id])
})

test('an EXCLUDED decision with a resolvable term renders on that term; one without renders nowhere', () => {
  const excl = excludedCandidate({ candidate_id: 'excl', requirement_group_id: 'excluded', course_codes: ['CSCE 4901'] })
  const orphan = excludedCandidate({ candidate_id: 'orphan', requirement_group_id: 'excluded-noterm', course_codes: ['MYST 1000'] })
  const years = buildDegreeScheduleYears({
    realTerms: [], scheduleTerms: [], courseRecords: [], gradingSchema: null, today: TODAY,
    decisions: [
      decision({ requirement_group_id: 'excluded', requirement_name: 'Technical Elective', state: 'EXCLUDED', excluded_candidate_ids: [excl.candidate_id], resolved_term_key: '2028-Fall' }),
      decision({ requirement_group_id: 'excluded-noterm', requirement_name: 'Mystery Elective', state: 'EXCLUDED', excluded_candidate_ids: [orphan.candidate_id], resolved_term_key: null }),
    ],
    candidateSets: [
      { requirement_group_id: 'excluded', requirement_name: 'Technical Elective', feasible_candidates: [], excluded_candidates: [excl] },
      { requirement_group_id: 'excluded-noterm', requirement_name: 'Mystery Elective', feasible_candidates: [], excluded_candidates: [orphan] },
    ],
  })
  const placed = flatDecisions(years)
  assert.equal(placed.length, 1)
  assert.equal(placed[0].termKey, '2028-Fall')
  assert.equal(placed[0].entry.state, 'EXCLUDED')
  assert.deepEqual(placed[0].entry.candidates.map((c) => c.course_codes).flat(), ['CSCE 4901'])
  // the orphan never appears anywhere
  assert.equal(
    years.flatMap((y) => y.semesters).flatMap((s) => s.decisions).some((d) => d.requirementGroupId === 'excluded-noterm'),
    false,
  )
})

test('a CHOICE_REQUIRED whose options span two terms renders once, on the backend-resolved (earliest) term', () => {
  const early = feasibleCandidate({ candidate_id: 'early', requirement_group_id: 'choice', course_codes: ['STAT 3011'], completion_term_index: 1 })
  const late = feasibleCandidate({ candidate_id: 'late', requirement_group_id: 'choice', course_codes: ['STAT 4011'], completion_term_index: 3 })
  const years = buildDegreeScheduleYears({
    realTerms: [], scheduleTerms: [], courseRecords: [], gradingSchema: null, today: TODAY,
    decisions: [decision({
      requirement_group_id: 'choice', requirement_name: 'Statistical Methods', state: 'CHOICE_REQUIRED',
      feasible_candidate_ids: [early.candidate_id, late.candidate_id],
      resolved_term_key: '2027-Spring', // backend already picked min(completion_term_index)
    })],
    candidateSets: [{ requirement_group_id: 'choice', requirement_name: 'Statistical Methods', feasible_candidates: [early, late], excluded_candidates: [] }],
  })
  const placed = flatDecisions(years)
  assert.equal(placed.length, 1)
  assert.equal(placed[0].termKey, '2027-Spring')
  assert.equal(placed[0].entry.state, 'CHOICE_REQUIRED')
  assert.deepEqual(placed[0].entry.candidates.map((c) => c.candidate_id), [early.candidate_id, late.candidate_id])
})

test('ADVISER_REVIEW / DATA_UNRESOLVED / freeform-manual-review produce zero decision output and no extra years', () => {
  const years = buildDegreeScheduleYears({
    realTerms: [term({ year: 2026, season: 'Fall', start_date: '2026-08-24', end_date: '2026-12-10' })],
    scheduleTerms: [], courseRecords: [], gradingSchema: null, today: TODAY,
    decisions: [
      decision({ requirement_group_id: 'review', state: 'ADVISER_REVIEW', excluded_candidate_ids: ['r'], resolved_term_key: null }),
      decision({ requirement_group_id: 'data', state: 'DATA_UNRESOLVED', excluded_candidate_ids: ['d'], resolved_term_key: null }),
      // even if some upstream bug handed one a term, a non-card state must not render
      decision({ requirement_group_id: 'review2', state: 'ADVISER_REVIEW', excluded_candidate_ids: ['r2'], resolved_term_key: '2099-Fall' }),
    ],
    candidateSets: [],
  })
  // no decision anywhere, and 2099 did not spawn a year tab
  assert.deepEqual(flatDecisions(years), [])
  assert.equal(years.some((y) => y.yearKey === 2099), false)
  for (const year of years) for (const semester of year.semesters) assert.deepEqual(semester.decisions, [])
})

test('bucketDecisionsByTerm ignores AUTO_SELECTED outright', () => {
  const auto = feasibleCandidate({ candidate_id: 'auto', requirement_group_id: 'auto' })
  const buckets = bucketDecisionsByTerm(
    [decision({ requirement_group_id: 'auto', state: 'AUTO_SELECTED', feasible_candidate_ids: [auto.candidate_id], selected_candidate_id: auto.candidate_id, resolved_term_key: '2027-Fall' })],
    [{ requirement_group_id: 'auto', requirement_name: 'auto', feasible_candidates: [auto], excluded_candidates: [] }],
  )
  assert.equal(buckets.size, 0)
})

test('a decision never lands on a past or in-progress column even if its resolved term collides with one', () => {
  const past = term({ year: 2025, season: 'Fall', start_date: '2025-08-25', end_date: '2025-12-10' })
  const current = term({ year: 2026, season: 'Fall', start_date: '2026-08-24', end_date: '2026-12-10' })
  const cand = feasibleCandidate({ candidate_id: 'x', requirement_group_id: 'choice', course_codes: ['CS 1000'] })
  const years = buildDegreeScheduleYears({
    realTerms: [past, current], scheduleTerms: [], courseRecords: [], gradingSchema: null, today: TODAY,
    decisions: [
      decision({ requirement_group_id: 'choice', state: 'CHOICE_REQUIRED', feasible_candidate_ids: [cand.candidate_id, 'y'], requirement_name: 'Backdated Choice', resolved_term_key: '2025-Fall' }),
      decision({ requirement_group_id: 'choice2', state: 'CHOICE_REQUIRED', feasible_candidate_ids: [cand.candidate_id, 'y'], requirement_name: 'Current-term Choice', resolved_term_key: '2026-Fall' }),
    ],
    candidateSets: [
      { requirement_group_id: 'choice', requirement_name: 'Backdated Choice', feasible_candidates: [cand, { ...cand, candidate_id: 'y' }], excluded_candidates: [] },
      { requirement_group_id: 'choice2', requirement_name: 'Current-term Choice', feasible_candidates: [cand, { ...cand, candidate_id: 'y' }], excluded_candidates: [] },
    ],
  })
  for (const { state } of flatDecisions(years)) assert.equal(state, 'future')
  const past2025 = years.flatMap((y) => y.semesters).find((s) => s.termKey === '2025-Fall')
  const current2026 = years.flatMap((y) => y.semesters).find((s) => s.termKey === '2026-Fall')
  assert.equal(past2025.state, 'past')
  assert.deepEqual(past2025.decisions, [])
  assert.notEqual(current2026.state, 'future') // in_progress on TODAY
  assert.deepEqual(current2026.decisions, [])
})

test('a decision resolving beyond every scheduled/enrolled year adds that year to the grid', () => {
  const cand = feasibleCandidate({ candidate_id: 'x', requirement_group_id: 'choice', course_codes: ['CS 4000'], completion_term_index: 4 })
  const years = buildDegreeScheduleYears({
    realTerms: [term({ year: 2026, season: 'Fall', start_date: '2026-08-24', end_date: '2026-12-10' })],
    scheduleTerms: [], courseRecords: [], gradingSchema: null, today: TODAY,
    decisions: [decision({
      requirement_group_id: 'choice', requirement_name: 'Deep Elective', state: 'CHOICE_REQUIRED',
      feasible_candidate_ids: [cand.candidate_id, 'y'], resolved_term_key: '2028-Fall',
    })],
    candidateSets: [{ requirement_group_id: 'choice', requirement_name: 'Deep Elective', feasible_candidates: [cand, { ...cand, candidate_id: 'y' }], excluded_candidates: [] }],
  })
  assert.equal(years.some((y) => y.yearKey === 2028), true)
  const fall2028 = years.flatMap((y) => y.semesters).find((s) => s.termKey === '2028-Fall')
  assert.equal(fall2028.decisions.length, 1)
  assert.equal(fall2028.decisions[0].requirementName, 'Deep Elective')
})
