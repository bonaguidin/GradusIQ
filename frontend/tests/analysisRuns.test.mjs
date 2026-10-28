import assert from 'node:assert/strict'
import test from 'node:test'

import {
  analyzeGap,
  resumeAnalysisRun,
  runAnalysisInBackground,
  waitForAnalysisRun,
} from '../src/api/analysisApi.mjs'

const noSleep = async () => {}
const RESULT = { feature: 'GAP', status: 'success', summary: 'ok', data: {} }

// Answers each request with the next queued response; records every call.
function scriptedFetch(calls, responses) {
  return async (url, init) => {
    calls.push({ url, method: init.method, authorization: init.headers.Authorization })
    const next = responses.shift()
    if (next instanceof Error) throw next
    const { status = 200, body } = next
    return { ok: status >= 200 && status < 300, status, json: async () => body }
  }
}

test('runAnalysisInBackground starts a run, polls until done, and resolves to the result', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', scriptedFetch(calls, [
    { body: { state: 'running', elapsed_seconds: 0 } },
    { body: { state: 'running', elapsed_seconds: 4 } },
    { body: { state: 'done', elapsed_seconds: 8, result: RESULT } },
  ]))

  const result = await runAnalysisInBackground('gap', 'tok', { sleep: noSleep })

  assert.deepEqual(result, RESULT)
  assert.deepEqual(calls.map(({ method }) => method), ['POST', 'GET', 'GET'])
  assert.equal(calls.every(({ url }) => url === '/api/v2/student/me/analysis-runs/gap'), true)
  assert.equal(calls.every(({ authorization }) => authorization === 'Bearer tok'), true)
})

test('analyzeGap on a real account uses a background run, never the long analyze request', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', scriptedFetch(calls, [
    { body: { state: 'done', elapsed_seconds: 1, result: RESULT } },
  ]))

  assert.deepEqual(await analyzeGap({ slug: null, accessToken: 'tok' }), RESULT)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/v2/student/me/analysis-runs/gap')
  assert.equal(calls[0].method, 'POST')
})

test('a failed run rejects with the server detail', async (t) => {
  t.mock.method(globalThis, 'fetch', scriptedFetch([], [
    { body: { state: 'running' } },
    { body: { state: 'failed', status_code: 502, detail: 'Analysis service is unavailable.' } },
  ]))

  await assert.rejects(
    runAnalysisInBackground('fit', 'tok', { sleep: noSleep }),
    /Analysis service is unavailable\./,
  )
})

test('a busy start (429) rejects with the busy message', async (t) => {
  t.mock.method(globalThis, 'fetch', scriptedFetch([], [
    { body: { state: 'failed', status_code: 429, detail: 'busy' } },
  ]))

  await assert.rejects(runAnalysisInBackground('gap', 'tok', { sleep: noSleep }), /busy right now/)
})

test('a run that disappears mid-poll (server restart) asks the student to run it again', async (t) => {
  t.mock.method(globalThis, 'fetch', scriptedFetch([], [
    { body: { state: 'running' } },
    { body: { state: 'none' } },
  ]))

  await assert.rejects(runAnalysisInBackground('shift', 'tok', { sleep: noSleep }), /Run it again/)
})

test('waitForAnalysisRun rides out a few failed status reads', async (t) => {
  t.mock.method(globalThis, 'fetch', scriptedFetch([], [
    new Error('network down'),
    { status: 502, body: { detail: 'Bad gateway' } },
    new Error('network down'),
    { body: { state: 'done', result: RESULT } },
  ]))

  assert.deepEqual(await waitForAnalysisRun('gap', 'tok', { sleep: noSleep }), RESULT)
})

test('waitForAnalysisRun gives up after too many failed reads in a row', async (t) => {
  t.mock.method(globalThis, 'fetch', scriptedFetch([], [
    new Error('one'),
    new Error('two'),
    new Error('three'),
    new Error('four'),
  ]))

  await assert.rejects(waitForAnalysisRun('gap', 'tok', { sleep: noSleep }), /four/)
})

test('waitForAnalysisRun stops waiting after the deadline', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => ({
    ok: true,
    status: 200,
    json: async () => ({ state: 'running' }),
  }))
  let clock = 0
  const now = () => clock
  const sleep = async (ms) => { clock += ms }

  await assert.rejects(
    waitForAnalysisRun('gap', 'tok', { sleep, now, pollMs: 1000, maxWaitMs: 5000 }),
    /taking much longer than usual/,
  )
})

test('resumeAnalysisRun returns null when no run is going', async (t) => {
  t.mock.method(globalThis, 'fetch', scriptedFetch([], [{ body: { state: 'none' } }]))

  assert.equal(await resumeAnalysisRun('gap', 'tok', { sleep: noSleep }), null)
})

test('resumeAnalysisRun hands back a pending result without waiting for it', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', scriptedFetch(calls, [
    { body: { state: 'running' } },
    { body: { state: 'done', result: RESULT } },
  ]))

  const resumed = await resumeAnalysisRun('gap', 'tok', { sleep: noSleep })
  assert.ok(resumed)
  assert.ok(resumed.result instanceof Promise)
  assert.deepEqual(await resumed.result, RESULT)
  assert.deepEqual(calls.map(({ method }) => method), ['GET', 'GET'])
})
