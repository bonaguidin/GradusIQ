import assert from 'node:assert/strict'
import test from 'node:test'

import {
  fetchCareerOptimizedSchedule,
  isCareerOptimizedScheduleResponse,
} from '../src/api/careerOptimizedSchedule.ts'

const schedule = {
  student_id: 'sid', program_id: 'pid', terms: [], unscheduled: [], status: 'SCHEDULED', failure: null,
}

function response(status = 'OPTIMIZED', cache_status = 'MISS') {
  return {
    feature: 'CAREER_OPTIMIZED_SCHEDULE', status, selection_basis: status === 'OPTIMIZED' || status === 'PARTIAL' ? 'CAREER_RANKED' : 'ACADEMIC_DEFAULT',
    target_role: 'Software Engineering Intern', fingerprint: status === 'SKIPPED' ? null : 'fp',
    generated_at: '2026-08-20T12:00:00Z', cache_status,
    academic_schedule: schedule, optimized_schedule: schedule,
    requirement_rankings: [], ranking_failures: [], ranking_prompt_version: '1',
    resolved_model: 'test-model', summary: status === 'SKIPPED' ? 'Choose a role.' : null,
  }
}

function fakeFetch(calls, status, body) {
  return async (url, init) => {
    calls.push({ url, init })
    return { status, json: async () => body }
  }
}

test('authenticated POST defaults force_refresh to false and sends no academic inputs', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls, 200, response()))

  await fetchCareerOptimizedSchedule('session-token')

  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/v2/student/me/schedule/career-optimize')
  assert.equal(calls[0].init.method, 'POST')
  assert.equal(calls[0].init.headers.Authorization, 'Bearer session-token')
  assert.equal(calls[0].init.headers['Content-Type'], 'application/json')
  assert.deepEqual(JSON.parse(calls[0].init.body), { force_refresh: false })
})

test('supports an explicit target role without adding server-owned inputs', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls, 200, response()))
  await fetchCareerOptimizedSchedule('token', { target_role: 'Software Engineering Intern' })
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    target_role: 'Software Engineering Intern', force_refresh: false,
  })
})

test('force refresh sends force_refresh true', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', fakeFetch(calls, 200, response('OPTIMIZED', 'BYPASSED')))
  await fetchCareerOptimizedSchedule('token', { force_refresh: true })
  assert.deepEqual(JSON.parse(calls[0].init.body), { force_refresh: true })
})

for (const status of ['PARTIAL', 'FALLBACK', 'SKIPPED']) {
  test(`preserves a valid ${status} response`, async (t) => {
    const payload = response(status)
    t.mock.method(globalThis, 'fetch', fakeFetch([], 200, payload))
    assert.deepEqual(await fetchCareerOptimizedSchedule('token'), payload)
  })
}

test('strict response guard accepts exact enums and rejects invalid status/cache/contracts', () => {
  assert.equal(isCareerOptimizedScheduleResponse(response()), true)
  assert.equal(isCareerOptimizedScheduleResponse({ ...response(), status: 'DONE' }), false)
  assert.equal(isCareerOptimizedScheduleResponse({ ...response(), cache_status: 'STALE' }), false)
  assert.equal(isCareerOptimizedScheduleResponse({ ...response(), optimized_schedule: {} }), false)
})

test('invalid 200 response is rejected instead of cast', async (t) => {
  t.mock.method(globalThis, 'fetch', fakeFetch([], 200, { status: 'OPTIMIZED' }))
  await assert.rejects(() => fetchCareerOptimizedSchedule('token'), /invalid response/)
})

test('non-200 detail and transport errors are localized', async (t) => {
  t.mock.method(globalThis, 'fetch', fakeFetch([], 502, { detail: 'Ranking service is busy.' }))
  await assert.rejects(() => fetchCareerOptimizedSchedule('token'), /Ranking service is busy/)
  t.mock.restoreAll()
  t.mock.method(globalThis, 'fetch', async () => { throw new Error('offline') })
  await assert.rejects(() => fetchCareerOptimizedSchedule('token'), /Career optimization is unavailable/)
})
