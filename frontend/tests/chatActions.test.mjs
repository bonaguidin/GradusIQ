import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { CHAT_ACTIONS, MAX_CHAT_ACTIONS, usableActions } from '../src/lib/chatActions.mjs'

test('only known, unique ids are drawn, at most three', () => {
  assert.deepEqual(
    usableActions(['gpa-calculator', 'nope', 'gpa-calculator', 7, 'job-search', 'career-profile', 'resume'], { demo: false }),
    ['gpa-calculator', 'job-search', 'career-profile'],
  )
  assert.equal(MAX_CHAT_ACTIONS, 3)
  assert.deepEqual(usableActions(undefined, { demo: false }), [])
  assert.deepEqual(usableActions(['__proto__', 'toString'], { demo: false }), [])
})

test('demo personas never get account-only pages', () => {
  assert.deepEqual(usableActions(['transcript', 'resume', 'canvas-calendar', 'job-search'], { demo: true }), ['job-search'])
})

test('every action has a label and exactly one kind of destination', () => {
  for (const [id, action] of Object.entries(CHAT_ACTIONS)) {
    assert.ok(action.label, id)
    const kinds = [action.to, action.dashboard, action.dialog].filter(Boolean)
    assert.equal(kinds.length, 1, id)
    if (action.to) assert.match(action.to, /^\/[a-z/-]+$/, id)
  }
})

test('dashboard destinations use the real section and tab params', async () => {
  const pageLib = await readFile(fileURLToPath(new URL('../src/lib/chatPage.mjs', import.meta.url)), 'utf8')
  for (const action of Object.values(CHAT_ACTIONS)) {
    if (!action.dashboard) continue
    const params = new URLSearchParams(action.dashboard)
    const section = params.get('section')
    assert.ok(['academic', 'career'].includes(section), action.dashboard)
    const tab = params.get(section)
    if (tab) assert.ok(pageLib.includes(`'${tab}'`), `${tab} is a known tab`)
  }
})
