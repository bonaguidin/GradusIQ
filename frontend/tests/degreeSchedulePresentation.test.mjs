import assert from 'node:assert/strict'
import test from 'node:test'

import {
  degreeScheduleContentState,
  displayTermKey,
  formatCredits,
  nextPlannedTerm,
  termPresentation,
} from '../src/lib/degreeSchedulePresentation.mjs'

test('term presentation preserves backend order, courses, totals, and limitations', () => {
  const terms = [
    {
      term_key: '2027-Spring',
      total_credit_hours: 6,
      courses: [{ course_code: 'CS 3341', credit_hours: 3, requirement_group_id: 'g1', limitations: ['First limitation', 'Second limitation'] }],
    },
    {
      term_key: '2026-Fall',
      total_credit_hours: 12,
      courses: [{ course_code: 'CS 2341', credit_hours: 3, requirement_group_id: 'g1', limitations: [] }],
    },
  ]

  const result = termPresentation(terms)

  assert.deepEqual(result.map((term) => term.term_key), ['2027-Spring', '2026-Fall'])
  assert.equal(result[0].displayName, 'Spring 2027')
  assert.equal(result[0].totalLabel, '6 credits')
  assert.equal(result[0].courses[0].course_code, 'CS 3341')
  assert.deepEqual(result[0].courses[0].limitations, ['First limitation', 'Second limitation'])
})

test('term and credit labels handle known, unknown, singular, and fractional values', () => {
  assert.equal(displayTermKey('2028-Fall'), 'Fall 2028')
  assert.equal(displayTermKey('Summer-Session-A'), 'Summer-Session-A')
  assert.equal(formatCredits(1), '1 credit')
  assert.equal(formatCredits(1.5), '1.5 credits')
})

test('planner summary derives the next planned term from the existing schedule', () => {
  const result = {
    student_id: 'sid', program_id: 'pid', status: 'SCHEDULED', failure: null,
    terms: [{ term_key: '2026-Fall', courses: [], total_credit_hours: 15 }],
    unscheduled: [
      { requirement_group_id: 'g1', name: 'Technical Electives', reason: 'FREEFORM_MANUAL_REVIEW' },
      { requirement_group_id: 'g2', name: 'Other', reason: 'SELECTION_DEFERRED' },
    ],
  }
  assert.equal(nextPlannedTerm(result).displayName, 'Fall 2026')
  assert.equal(nextPlannedTerm(result).totalLabel, '15 credits')
  assert.equal(nextPlannedTerm(null), null)
})

test('empty schedule presentation remains empty', () => {
  assert.deepEqual(termPresentation([]), [])
})

test('schedule content states distinguish scheduled, empty, skipped, and infeasible results', () => {
  const base = { student_id: 'sid', program_id: 'pid', unscheduled: [], failure: null }
  assert.equal(degreeScheduleContentState({ ...base, status: 'SCHEDULED', terms: [{ term_key: '2026-Fall', courses: [], total_credit_hours: 0 }] }), 'scheduled')
  assert.equal(degreeScheduleContentState({ ...base, status: 'SCHEDULED', terms: [] }), 'empty')
  assert.equal(degreeScheduleContentState({ ...base, status: 'ERROR', terms: [], failure: { error_class: 'OverConstrained', safe_message: 'No room.' } }), 'infeasible')
  assert.equal(degreeScheduleContentState({ feature: 'SCHEDULE', status: 'skipped', summary: 'Not supported.', data: {}, errors: [] }), 'skipped')
})
