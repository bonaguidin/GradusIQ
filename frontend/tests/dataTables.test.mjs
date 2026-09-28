import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const SRC = new URL('../src/', import.meta.url)
const read = (path) => readFile(new URL(path, SRC), 'utf8')
const css = async () => (await read('index.css')).replace(/\/\*[\s\S]*?\*\//g, '')
const rule = (text, selector) => {
  const m = text.match(new RegExp(`(?:^|\\n)${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`))
  assert.ok(m, `${selector} rule exists`)
  return m[1]
}

test('term-planner rows share one set of column tracks, so figures line up down the list', async () => {
  const text = await css()
  assert.match(rule(text, '.real-course-table'), /grid-template-columns:\s*minmax\(0, 1fr\) auto auto/)
  const row = rule(text, '.real-course-row')
  assert.match(row, /grid-column:\s*1 \/ -1/)
  // The fallback must come first, or it would override subgrid where supported.
  assert.ok(row.indexOf('minmax(0, 1fr) auto auto') < row.indexOf('subgrid'), 'fallback before subgrid')
})

test('credits sit right-aligned on tabular numerals, and titles hold to one line with the full text on hover', async () => {
  const text = await css()
  const credits = rule(text, '.real-course-row > span:nth-child(2)')
  assert.match(credits, /justify-self:\s*end/)
  assert.match(credits, /font-variant-numeric:\s*tabular-nums/)
  assert.match(rule(text, '.real-course-row > span:first-child > small'), /text-overflow:\s*ellipsis/)
  const planner = await read('components/TermPlanner.tsx')
  assert.doesNotMatch(planner, /<small>\{course\.title/, 'every truncated title carries its full text')
  assert.equal((planner.match(/<small title=\{course\.title \?\? undefined\}>/g) ?? []).length, 5)
})

test('the grade table right-aligns its score column, header included', async () => {
  const text = await css()
  const score = rule(text, '.grade-table td:last-child')
  assert.match(score, /text-align:\s*right/)
  assert.match(score, /font-variant-numeric:\s*tabular-nums/)
  assert.match(rule(text, '.grade-table th:last-child'), /text-align:\s*right/)
})

test('on narrow screens the rows stack and figures return to the left edge', async () => {
  const text = await css()
  const mobile = text.slice(text.indexOf('.real-course-table {', text.indexOf('@media (max-width: 640px)', text.indexOf('.real-course-row > span:nth-child(3)'))))
  assert.match(mobile, /^\.real-course-table \{\s*grid-template-columns:\s*minmax\(0, 1fr\);/)
  assert.match(mobile, /\.real-course-row > span:nth-child\(n \+ 2\) \{\s*justify-self:\s*start;/)
})
