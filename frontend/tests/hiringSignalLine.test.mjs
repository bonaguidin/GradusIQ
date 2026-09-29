import test from 'node:test'
import assert from 'node:assert/strict'

import { hiringSignalLine } from '../src/lib/hiringSignalLine.mjs'

test('coverage "available" with employers renders the employer list and count', () => {
  const line = hiringSignalLine({
    coverage: 'available',
    employers: ['Micron', 'Toyota'],
    posting_count: 4,
  })
  assert.deepEqual(line, { variant: 'signal', text: 'Hiring now: Micron, Toyota (4 listings)' })
})

test('a singular posting_count of 1 says "listing", not "listings"', () => {
  const line = hiringSignalLine({ coverage: 'available', employers: ['Micron'], posting_count: 1 })
  assert.equal(line.text, 'Hiring now: Micron (1 listing)')
})

test('coverage "available" with no named employers renders nothing', () => {
  assert.equal(hiringSignalLine({ coverage: 'available', employers: [], posting_count: 0 }), null)
})

test('coverage "no_market_data" renders the plain "no data" line', () => {
  const line = hiringSignalLine({ coverage: 'no_market_data', employers: [], posting_count: null })
  assert.deepEqual(line, { variant: 'empty', text: 'No posting data found for this role.' })
})

test('coverage "unavailable" renders nothing, matching the prompt\'s "skip the bullet" rule', () => {
  assert.equal(hiringSignalLine({ coverage: 'unavailable', employers: [], posting_count: null }), null)
})

test('a missing hiring_signal (older cached/demo results) renders nothing', () => {
  assert.equal(hiringSignalLine(undefined), null)
  assert.equal(hiringSignalLine(null), null)
})

test('a null posting_count omits the count parenthetical', () => {
  const line = hiringSignalLine({ coverage: 'available', employers: ['Micron'], posting_count: null })
  assert.equal(line.text, 'Hiring now: Micron')
})
