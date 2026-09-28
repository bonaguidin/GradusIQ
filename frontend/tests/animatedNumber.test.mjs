import assert from 'node:assert/strict'
import test from 'node:test'

import { decimalsOf, easeOutCubic, formatDelta, interpolate } from '../src/lib/animatedNumber.mjs'

test('the count starts fast and settles exactly on the target', () => {
  assert.equal(easeOutCubic(0), 0)
  assert.equal(easeOutCubic(1), 1)
  assert.ok(easeOutCubic(0.25) > 0.5, 'front-loaded, so the change reads immediately')
  assert.equal(interpolate(3.71, 3.82, 1), 3.82)
  assert.equal(interpolate(3.71, 3.82, 0), 3.71)
})

test('progress outside 0..1 is clamped rather than overshooting', () => {
  assert.equal(interpolate(80, 90, 1.4), 90)
  assert.equal(interpolate(80, 90, -0.2), 80)
})

test('a figure keeps the precision it already printed with', () => {
  assert.equal(decimalsOf(81.4), 1)
  assert.equal(decimalsOf(85), 0)
  assert.equal(decimalsOf(91.25), 2)
  assert.equal(decimalsOf(Number.NaN), 0)
})

test('the change reads with a sign at the figure’s precision, and a rounded-away change shows nothing', () => {
  assert.equal(formatDelta(0.11, 2), '+0.11')
  assert.equal(formatDelta(-0.11, 2), '−0.11')
  assert.equal(formatDelta(3.6, 1), '+3.6')
  assert.equal(formatDelta(0.004, 2), null)
  assert.equal(formatDelta(Number.NaN, 2), null)
})
