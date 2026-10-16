import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('unknown addresses get the 404 page, and the bare domain still goes to sign-in', async () => {
  const app = await read('App.tsx')
  assert.match(app, /<Route path="\*" element={<NotFoundPage \/>} \/>/)
  assert.match(app, /<Route path="\/" element={<Navigate to="\/login" replace \/>} \/>/)
})

test('the 404 page always offers a way back in', async () => {
  const page = await read('pages/NotFoundPage.tsx')
  assert.match(page, /to="\/dashboard" className="btn btn-primary">Back to Overview/)
  assert.match(page, /to="\/dashboard" state={{ ask: true }}[^>]*>Ask GradusIQ/)
  assert.match(page, /to="\/login" className="btn btn-primary">Go to sign in/)
})

test('"Ask GradusIQ" focuses the chat once on arrival', async () => {
  const dashboard = await read('pages/AuthenticatedDashboard.tsx')
  assert.match(dashboard, /<ChatPanel autoFocus={askOnArrival} \/>/)
  assert.match(dashboard, /if \(askOnArrival\) setAskOnArrival\(false\)/)
})
