import assert from 'node:assert/strict'
import test from 'node:test'

import { formatFixed } from '../src/lib/format.mjs'

test('formatFixed prints the same digits toFixed would, in the default locale', () => {
  assert.equal(formatFixed(3.7, 2), '3.70')
  assert.equal(formatFixed(3.999, 2), '4.00')
  assert.equal(formatFixed(85, 1), '85.0')
  assert.equal(formatFixed(0, 0), '0')
})

test('negative values and rounding behave the same as toFixed', () => {
  assert.equal(formatFixed(-1.25, 1), '-1.3')
  assert.equal(formatFixed(100, 1), '100.0')
})
