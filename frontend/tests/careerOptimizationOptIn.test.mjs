import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const PANEL = new URL('../src/components/CareerOptimizationPanel.tsx', import.meta.url)
const SCHEDULE = new URL('../src/components/DegreeSchedulePanel.tsx', import.meta.url)

test('Degree Schedule mount auto-loads only academic GET and career optimization has no mount effect', async () => {
  const [panel, schedule] = await Promise.all([
    readFile(PANEL, 'utf8'),
    readFile(SCHEDULE, 'utf8'),
  ])
  assert.match(schedule, /useEffect\(\(\) => \{ trigger\(\); \}, \[trigger\]\)/)
  assert.match(schedule, /fetchDegreeSchedule\(accessToken\)/)
  assert.doesNotMatch(panel, /useEffect/)
  assert.match(panel, /onClick=\{\(\) => run\(false\)\}/)
  assert.match(panel, /fetchCareerOptimizedSchedule\(accessToken/)
})

test('loading is localized while the parent academic schedule stays rendered', async () => {
  const [panel, schedule] = await Promise.all([readFile(PANEL, 'utf8'), readFile(SCHEDULE, 'utf8')])
  assert.match(panel, /state\.phase === 'loading'/)
  assert.match(panel, /Finding career-aligned choices/)
  assert.match(panel, /disabled=\{!accessToken \|\| state\.phase === 'loading'\}/)
  assert.match(schedule, /<DegreeScheduleTerms terms=\{schedule\.terms\}/)
  assert.match(schedule, /<CareerOptimizationPanel/)
})

test('explicit refresh uses force refresh and preview controls are real buttons', async () => {
  const panel = await readFile(PANEL, 'utf8')
  assert.match(panel, /onClick=\{\(\) => run\(true\)\}/)
  assert.match(panel, /Refresh career optimization/)
  assert.match(panel, /aria-pressed=\{currentView === 'academic'\}/)
  assert.match(panel, /aria-pressed=\{currentView === 'optimized'\}/)
})
