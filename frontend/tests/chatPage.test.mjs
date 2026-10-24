import test from 'node:test'
import assert from 'node:assert/strict'
import { chatPageKey, chatSuggestions } from '../src/lib/chatPage.mjs'

const key = (path, query = '', base) => chatPageKey(path, new URLSearchParams(query), base)

test('dashboard sections and tabs map to page keys', () => {
  assert.equal(key('/dashboard'), 'overview')
  assert.equal(key('/dashboard', 'section=overview'), 'overview')
  assert.equal(key('/dashboard', 'section=academic'), 'academic')
  assert.equal(key('/dashboard', 'section=academic&academic=gpa-calculator'), 'academic/gpa-calculator')
  assert.equal(key('/dashboard', 'section=career&career=job-search'), 'career/job-search')
  // A tab from the other section, or an unknown one, falls back to the section.
  assert.equal(key('/dashboard', 'section=career&career=gpa-calculator'), 'career')
  assert.equal(key('/dashboard', 'section=bogus'), 'overview')
})

test('upload and profile routes have their own keys; other routes have none', () => {
  assert.equal(key('/transcript'), 'transcript')
  assert.equal(key('/resume'), 'resume')
  assert.equal(key('/profile/complete'), 'profile-complete')
  assert.equal(key('/login'), null)
  assert.equal(key('/nope'), null)
})

test('the dashboard path can be moved (preview harness)', () => {
  assert.equal(key('/preview.html', 'section=academic', '/preview.html'), 'academic')
  assert.equal(key('/dashboard', 'section=academic', '/preview.html'), null)
})

test('every page has starter questions', () => {
  for (const page of ['overview', 'academic', 'academic/grade-calculator', 'career', 'career/profile', 'transcript', 'resume', 'profile-complete', null]) {
    const suggestions = chatSuggestions(page)
    assert.ok(suggestions.length >= 2, String(page))
  }
  assert.notDeepEqual(chatSuggestions('academic'), chatSuggestions('career'))
})
