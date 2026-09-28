import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { countLabel } from '../src/lib/countLabel.mjs'

test('the noun agrees with the count', () => {
  assert.equal(countLabel(1, 'term'), '1 term')
  assert.equal(countLabel(0, 'term'), '0 terms')
  assert.equal(countLabel(3, 'confirmed course'), '3 confirmed courses')
  assert.equal(countLabel(2, 'analysis', 'analyses'), '2 analyses')
})

test('the overview summaries no longer read "1 confirmed courses across 1 terms"', async () => {
  const dashboard = await readFile(new URL('../src/pages/AuthenticatedDashboard.tsx', import.meta.url), 'utf8')
  assert.doesNotMatch(dashboard, /\} confirmed courses across \$\{|\} target roles and \$\{|\} skills confirmed/)
  assert.match(dashboard, /countLabel\(dashboard\.courses\.length, 'confirmed course'\)/)
  assert.match(dashboard, /countLabel\(dashboard\.career\.target_roles\.length, 'target role'\)/)
})
