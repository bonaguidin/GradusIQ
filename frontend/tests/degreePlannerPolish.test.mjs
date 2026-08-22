import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const REQUIREMENTS = new URL('../src/components/RequirementSatisfactionPanel.tsx', import.meta.url)
const NODE = new URL('../src/components/RequirementGroupNode.tsx', import.meta.url)
const DASHBOARD = new URL('../src/pages/AuthenticatedDashboard.tsx', import.meta.url)

test('degree requirements auto-load with deterministic language and collapsed details', async () => {
  const [panel, node] = await Promise.all([readFile(REQUIREMENTS, 'utf8'), readFile(NODE, 'utf8')])
  assert.match(panel, /trigger\(\)/)
  assert.match(panel, /Checking degree requirements/)
  assert.match(panel, /Refresh degree progress/)
  assert.doesNotMatch(panel, /live model|Run analysis|Re-run analysis|Analyzing/)
  assert.match(node, /useState\(false\)/)
  assert.match(node, /aria-expanded=\{expanded\}/)
  assert.match(node, /Adviser review needed/)
})

test('planner hierarchy uses existing dashboard data and keeps Course Discovery separate', async () => {
  const dashboard = await readFile(DASHBOARD, 'utf8')
  const discovery = dashboard.indexOf('<CourseDiscoveryPanel')
  const summary = dashboard.indexOf('<DegreePlannerSummary')
  const schedule = dashboard.indexOf('<DegreeSchedulePanel')
  const requirements = dashboard.indexOf('<RequirementSatisfactionPanel')
  assert.ok(discovery >= 0 && discovery < summary)
  assert.ok(summary < schedule && schedule < requirements)
  assert.match(dashboard, /institution=\{dashboard\.institutionName\}/)
  assert.match(dashboard, /major=\{major\}/)
  assert.match(dashboard, /targetRole=\{dashboard\.career\.target_roles\[0\]\}/)
})
