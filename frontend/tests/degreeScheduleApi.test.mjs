import assert from 'node:assert/strict'
import test from 'node:test'

import {
  fetchDegreeSchedule,
  isSkippedDegreeSchedule,
} from '../src/api/degreeSchedule.ts'

function fakeFetch(calls, status, body) {
  return async (url, init) => {
    calls.push({ url, init })
    return { status, json: async () => body }
  }
}

test('fetchDegreeSchedule calls the authenticated GET route', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls, 200, {
    student_id: 'sid', program_id: 'pid', terms: [], unscheduled: [], status: 'SCHEDULED', failure: null,
  }))

  await fetchDegreeSchedule('session-token')

  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/v2/student/me/schedule')
  assert.equal(calls[0].init.method, 'GET')
  assert.equal(calls[0].init.headers.Authorization, 'Bearer session-token')
})

test('fetchDegreeSchedule preserves the complete schedule response', async (t) => {
  const payload = {
    student_id: 'sid',
    program_id: 'pid',
    status: 'SCHEDULED',
    failure: null,
    terms: [{
      term_key: '2026-Fall',
      total_credit_hours: 6,
      courses: [{ course_code: 'CS 2341', credit_hours: 3, requirement_group_id: 'g1', limitations: ['Review external prerequisite.'] }],
    }],
    unscheduled: [{ requirement_group_id: 'g2', name: 'Technical Electives', reason: 'FREEFORM_MANUAL_REVIEW' }],
  }
  t.mock.method(globalThis, 'fetch', fakeFetch([], 200, payload))

  const result = await fetchDegreeSchedule('session-token')

  assert.deepEqual(result, payload)
  assert.equal(isSkippedDegreeSchedule(result), false)
})

test('fetchDegreeSchedule returns a skipped FeatureResult', async (t) => {
  const skipped = {
    feature: 'SCHEDULE', status: 'skipped', summary: 'No supported program.', data: {}, errors: [], missing_fields: [],
  }
  t.mock.method(globalThis, 'fetch', fakeFetch([], 200, skipped))

  const result = await fetchDegreeSchedule('session-token')

  assert.equal(isSkippedDegreeSchedule(result), true)
  assert.equal(result.summary, skipped.summary)
})

test('fetchDegreeSchedule throws with backend detail on HTTP error', async (t) => {
  t.mock.method(globalThis, 'fetch', fakeFetch([], 502, { detail: 'Schedule is unavailable.' }))

  await assert.rejects(() => fetchDegreeSchedule('session-token'), /Schedule is unavailable\./)
})
