import assert from 'node:assert/strict'
import test from 'node:test'

import {
  fetchRequirementSatisfaction,
  isSkippedRequirementSatisfaction,
} from '../src/api/requirementSatisfaction.ts'

function fakeFetch(calls, status, body) {
  return async (url, init) => {
    calls.push({ url, init })
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }
  }
}

test('fetchRequirementSatisfaction calls the authenticated GET route with the bearer token', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls, 200, {
    student_id: 'sid',
    program_id: 'pid',
    groups: [],
  }))

  await fetchRequirementSatisfaction('session-token')

  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/v2/student/me/requirement-satisfaction')
  assert.equal(calls[0].init.method, 'GET')
  assert.equal(calls[0].init.headers.Authorization, 'Bearer session-token')
})

test('fetchRequirementSatisfaction returns the success payload as-is', async (t) => {
  t.mock.method(globalThis, 'fetch', fakeFetch([], 200, {
    student_id: 'sid',
    program_id: 'pid',
    groups: [{ id: 'g1', coursedog_rule_id: 'r1', name: 'Core', group_type: 'all_of', status: 'SATISFIED', detail: null, matched_course_codes: [], children: [] }],
  }))

  const result = await fetchRequirementSatisfaction('session-token')

  assert.equal(result.program_id, 'pid')
  assert.equal(isSkippedRequirementSatisfaction(result), false)
})

test('fetchRequirementSatisfaction returns a skipped FeatureResult when the student has no program', async (t) => {
  const skipped = {
    feature: 'REQUIREMENT_SATISFACTION',
    status: 'skipped',
    summary: "Requirement tracking isn't available for your institution or program yet.",
    data: {},
    errors: [],
    missing_fields: [{ path: 'student_institutions.program', label: 'Supported degree program' }],
  }
  t.mock.method(globalThis, 'fetch', fakeFetch([], 200, skipped))

  const result = await fetchRequirementSatisfaction('session-token')

  assert.equal(isSkippedRequirementSatisfaction(result), true)
  assert.deepEqual(result.missing_fields, skipped.missing_fields)
})

test('fetchRequirementSatisfaction throws with the server detail on a non-200 response', async (t) => {
  t.mock.method(globalThis, 'fetch', fakeFetch([], 502, { detail: 'Requirement satisfaction is unavailable.' }))

  await assert.rejects(
    () => fetchRequirementSatisfaction('session-token'),
    /Requirement satisfaction is unavailable\./,
  )
})
