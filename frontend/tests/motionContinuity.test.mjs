import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const SRC = new URL('../src/', import.meta.url)
const read = (path) => readFile(new URL(path, SRC), 'utf8')
const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')
const msOf = (css, token) => Number(css.match(new RegExp(`${token}:\\s*(\\d+)ms`))[1])

test('expanders grow open through Reveal instead of cutting in', async () => {
  const cases = [
    ['components/RequirementGroupNode.tsx', /<Reveal open=\{expanded\}>/, /\{hasChildren && expanded && \(/],
    ['components/TechnicalElectiveCandidates.tsx', /<Reveal open=\{expanded\}>/, /\{expanded && \(/],
    ['components/CareerOptimizationPanel.tsx', /<Reveal open=\{scheduleExpanded\}>/, /\{scheduleExpanded && \(/],
  ]
  for (const [file, uses, cut] of cases) {
    const source = await read(file)
    assert.match(source, uses, `${file} wraps its expanding content in Reveal`)
    assert.doesNotMatch(source, cut, `${file} no longer cuts the content in`)
  }
})

test('Reveal mounts and unmounts children exactly as `open && children` did, and closing content is inert', async () => {
  const reveal = await read('components/Reveal.tsx')
  assert.match(reveal, /\{present \? children : null\}/)
  assert.match(reveal, /setPresent\(false\)/, 'children unmount once the close finishes')
  assert.match(reveal, /inert=\{!open\}/)
  assert.match(reveal, /prefers-reduced-motion: reduce/, 'no waiting on an animation that will not run')
})

test('the figures a student changes count to their new value', async () => {
  const sites = [
    ['pages/AuthenticatedDashboard.tsx', /<AnimatedNumber value=\{dashboard\.projectedGpa\} decimals=\{2\} showDelta \/>/g, 2],
    ['pages/DashboardPage.tsx', /<AnimatedNumber value=\{dashboard\.projectedGpa\} decimals=\{2\} showDelta \/>/g, 1],
    ['components/GradeCalculatorPanel.tsx', /<AnimatedNumber value=\{calcResult\.(current|projected)_grade\} suffix="%" showDelta \/>/g, 2],
  ]
  for (const [file, pattern, count] of sites) {
    assert.equal(((await read(file)).match(pattern) ?? []).length, count, file)
  }
})

test('the text of a counting figure is always its final value; the moving digits are drawn, not written', async () => {
  // Tests, copy-paste, and the Grade Calculator's aria-live region all read
  // text. Writing each frame into it would expose mid-count values to them.
  const component = await read('components/AnimatedNumber.tsx')
  assert.match(component, /\{target === null \? fallback : `\$\{target\.toFixed\(places\)\}\$\{suffix\}`\}/)
  assert.match(component, /setAttribute\('data-count'/)
  assert.doesNotMatch(component, /textContent\s*=|innerText\s*=|useState/, 'no per-frame text writes or re-renders')
  const layer = stripComments(await read('interaction.css'))
  assert.match(layer, /\.figure-count\[data-count\]::before\s*\{[^}]*content:\s*attr\(data-count\)/)
})

test('JS timings agree with the CSS timing set', async () => {
  const layer = await read('interaction.css')
  const count = Number((await read('components/AnimatedNumber.tsx')).match(/COUNT_MS = (\d+)/)[1])
  const settle = Number((await read('components/Reveal.tsx')).match(/SETTLE_MS = (\d+)/)[1])
  assert.equal(count, msOf(layer, '--t-data'), 'the count lasts --t-data')
  assert.ok(settle >= msOf(layer, '--t-move'), 'Reveal waits at least as long as the grow')
})

test('a tab only gives up its own underline once the travelling one is in place', async () => {
  const layer = stripComments(await read('interaction.css'))
  const handover = layer.match(/([^{}]+)\{\s*border-bottom-color:\s*transparent;\s*\}/)
  assert.ok(handover)
  assert.match(handover[1], /\[data-tab-indicator\]/)
  const script = await read('interaction.ts')
  assert.match(script, /setAttribute\('data-tab-indicator', ''\)/)
  assert.match(script, /attributeFilter: \['aria-selected'\]/, 'driven by selection, not by a click handler')
})
