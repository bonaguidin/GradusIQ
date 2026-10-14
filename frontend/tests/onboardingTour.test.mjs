import assert from 'node:assert/strict'
import test from 'node:test'
import {
  TOUR_COMPLETED_METADATA_KEY,
  needsAccountBackfill,
  shouldAutoOpenTour,
  tourSeenStorageKey,
} from '../src/lib/onboardingTour.mjs'

const done = { [TOUR_COMPLETED_METADATA_KEY]: '2026-10-14T15:00:00.000Z' }

test('a brand-new account sees the tour', () => {
  assert.equal(shouldAutoOpenTour({ userMetadata: {}, seenInBrowser: false }), true)
  assert.equal(shouldAutoOpenTour({ userMetadata: undefined, seenInBrowser: false }), true)
})

test('an account that finished the tour never auto-opens it, even in a fresh browser', () => {
  assert.equal(shouldAutoOpenTour({ userMetadata: done, seenInBrowser: false }), false)
  assert.equal(shouldAutoOpenTour({ userMetadata: done, seenInBrowser: true }), false)
})

test('a browser that saw the tour before the account flag existed stays quiet and backfills', () => {
  assert.equal(shouldAutoOpenTour({ userMetadata: {}, seenInBrowser: true }), false)
  assert.equal(needsAccountBackfill({ userMetadata: {}, seenInBrowser: true }), true)
  assert.equal(needsAccountBackfill({ userMetadata: done, seenInBrowser: true }), false)
  assert.equal(needsAccountBackfill({ userMetadata: {}, seenInBrowser: false }), false)
})

test('the browser key stays the one already written by earlier builds', () => {
  assert.equal(tourSeenStorageKey('abc'), 'gradusiq_tour_seen_abc')
})
