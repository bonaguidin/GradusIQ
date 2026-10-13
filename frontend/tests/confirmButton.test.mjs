import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

// The confirm animation is for big moments only (Noah, 2026-10-13): actions that
// change the student's record. These are the buttons that have it. A new one
// is added here on purpose, not by copying the classes onto another button.
const BIG_MOMENTS = [
  'components/review/CommitBar.tsx',
  'components/TranscriptUpload.tsx',
  'components/ResumeUpload.tsx',
  'components/CanvasCalendarPanel.tsx',
  'components/profile/ProfileCompletionForm.tsx',
  'pages/SignUpPage.tsx',
]

test('every big-moment button renders through the shared ConfirmButton', async () => {
  for (const path of BIG_MOMENTS) {
    const source = await read(path)
    assert.match(source, /<ConfirmButton\b/, `${path} should render ConfirmButton`)
  }
})

test('the animation markup lives only in ConfirmButton', async () => {
  // A hand-copied spinner/check/cross drifts from the shared one the first
  // time either changes, which is how the review screens and the upload
  // button ended up looking alike but behaving differently.
  for (const path of BIG_MOMENTS) {
    const source = await read(path)
    assert.equal(/confirm-anim-(spinner|check|cross|ring)|rv-commit-(spinner|check|cross|ring)/.test(source), false, path)
  }
})

test('the animation styles are keyed on .confirm-anim and still respect reduced motion', async () => {
  const css = await read('index.css')
  assert.equal(/\.rv-commit-button\.is-(loading|success|error)/.test(css), false, 'state styles should target .confirm-anim')
  const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce) {\n  .confirm-anim.is-success'))
  assert.ok(reduced.length > 0, 'reduced-motion block for the confirm animation is missing')
  for (const selector of ['.confirm-anim.is-success', '.confirm-anim.is-error', '.confirm-anim-ring', '.confirm-anim-spinner::before']) {
    assert.ok(reduced.slice(0, 400).includes(selector), `${selector} should stop animating under reduced motion`)
  }
})
