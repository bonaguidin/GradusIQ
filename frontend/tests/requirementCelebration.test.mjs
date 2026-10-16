import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  celebrationMessage,
  celebrationStorageKey,
  parseCelebrated,
  planCelebration,
  satisfiedLeafRequirements,
} from '../src/lib/requirementCelebration.mjs'

const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

const leaf = (id, status, name = id) => ({
  id, coursedog_rule_id: `rule-${id}`, name, group_type: 'enumerated_courses',
  status, detail: null, matched_course_codes: [], children: [],
})
const parent = (id, children) => ({ ...leaf(id, 'IN_PROGRESS'), group_type: 'compound_all', children })

test('only satisfied leaves count, in tree order, compound parents skipped', () => {
  const groups = [
    leaf('a', 'SATISFIED', 'Core Math'),
    parent('p', [leaf('b', 'IN_PROGRESS'), parent('q', [leaf('c', 'SATISFIED', 'Writing')])]),
    { ...parent('r', [leaf('d', 'SATISFIED')]), status: 'SATISFIED' },
  ]
  assert.deepEqual(satisfiedLeafRequirements(groups), [
    { id: 'a', name: 'Core Math' },
    { id: 'c', name: 'Writing' },
    { id: 'd', name: 'd' },
  ])
})

test('first sight records everything already satisfied without celebrating it', () => {
  const plan = planCelebration(null, [{ id: 'a', name: 'Core Math' }, { id: 'b', name: 'Writing' }])
  assert.deepEqual(plan, { fresh: [], remember: ['a', 'b'] })
})

test('a newly satisfied requirement is celebrated once and then remembered', () => {
  const first = planCelebration(['a'], [{ id: 'a', name: 'Core Math' }, { id: 'b', name: 'Writing' }])
  assert.deepEqual(first.fresh, [{ id: 'b', name: 'Writing' }])
  assert.deepEqual(first.remember, ['a', 'b'])
  const again = planCelebration(first.remember, [{ id: 'a', name: 'Core Math' }, { id: 'b', name: 'Writing' }])
  assert.deepEqual(again.fresh, [])
})

test('a requirement that drops out and comes back does not replay', () => {
  const dropped = planCelebration(['a', 'b'], [{ id: 'a', name: 'Core Math' }])
  assert.deepEqual(dropped.remember, ['a', 'b'], 'the remembered set only grows')
  assert.deepEqual(planCelebration(dropped.remember, [{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }]).fresh, [])
})

test('unreadable storage reads as nothing remembered', () => {
  assert.equal(parseCelebrated(null), null)
  assert.equal(parseCelebrated('not json'), null)
  assert.equal(parseCelebrated('{"a":1}'), null)
  assert.deepEqual(parseCelebrated('["a", 2, "b"]'), ['a', 'b'])
})

test('storage is per student', () => {
  assert.notEqual(celebrationStorageKey('s1'), celebrationStorageKey('s2'))
})

test('the message names what finished and where the student stands', () => {
  const one = [{ id: 'a', name: 'Core Math' }]
  assert.equal(celebrationMessage(one, { satisfied: 3, total: 8 }), 'Core Math done. 3 of 8 requirements complete.')
  const two = [...one, { id: 'b', name: 'Writing' }]
  assert.equal(celebrationMessage(two, { satisfied: 4, total: 8 }), 'Core Math and Writing done. 4 of 8 requirements complete.')
  const four = [...two, { id: 'c', name: 'Lab Science' }, { id: 'd', name: 'Ethics' }]
  assert.equal(celebrationMessage(four, { satisfied: 6, total: 8 }), 'Core Math, Writing and 2 more done. 6 of 8 requirements complete.')
  assert.equal(celebrationMessage(one, { satisfied: 8, total: 8 }), 'Core Math done. Every requirement is satisfied.')
})

test('the burst reuses the confirm animation slam and stops under reduced motion', async () => {
  const css = await read('index.css')
  const block = css.slice(css.indexOf('/* ─── REQUIREMENT CELEBRATION'))
  assert.match(block, /confirm-anim-slam/, 'the tile should take the shared confirm slam')
  const reduced = block.slice(block.indexOf('@media (prefers-reduced-motion: reduce)'))
  assert.match(reduced, /\.req-burst\s*\{\s*display: none;/)
  assert.match(reduced, /\.req-celebrate,/)
})

test('the burst is decorative and the message is a live region', async () => {
  const ring = await read('components/DegreeProgressRing.tsx')
  assert.match(ring, /className="req-burst" aria-hidden="true"/)
  const banner = await read('components/RequirementCelebration.tsx')
  assert.match(banner, /role="status" aria-live="polite"/)
})
