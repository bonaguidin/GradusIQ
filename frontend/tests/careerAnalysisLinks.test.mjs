import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('GAP/FIT/SHIFT summaries link to their own Career Intelligence panel', async () => {
  const dashboard = await readFile(new URL('../src/pages/AuthenticatedDashboard.tsx', import.meta.url), 'utf8')
  for (const panel of ['fit', 'gap', 'shift']) {
    assert.match(dashboard, new RegExp(`id="career-intelligence-${panel}"`), panel)
  }
  assert.match(dashboard, /onClick=\{\(\) => openIntelligencePanel\('fit'\)\}>See Role Fit</)
  assert.match(dashboard, /onClick=\{\(\) => openIntelligencePanel\('gap'\)\}>See all skill gaps</)
  assert.match(dashboard, /\['Trend Guidance', 'shift', shiftRun\.state\]/)
  assert.match(dashboard, /onClick=\{\(\) => openIntelligencePanel\(panel\)\}/)
  assert.match(dashboard, /getElementById\(`career-intelligence-\$\{intelligenceTarget\}`\)\?\.scrollIntoView/)
})
