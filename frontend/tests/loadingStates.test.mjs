import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import test from 'node:test'

const SRC = new URL('../src/', import.meta.url)
const read = (path) => readFile(new URL(path, SRC), 'utf8')
const stripComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')

async function sourceFiles(dir = SRC) {
  const out = []
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const url = new URL(entry.name + (entry.isDirectory() ? '/' : ''), dir)
    if (entry.isDirectory()) out.push(...(await sourceFiles(url)))
    else if (/\.(tsx?|mjs)$/.test(entry.name) && !entry.name.endsWith('.d.mts')) out.push(url)
  }
  return out
}

test('every analysis-style loader keeps the spinner element the skeleton is drawn from', async () => {
  const css = stripComments(await read('index.css'))
  const covered = [...css.matchAll(/\.([a-z-]+-loading) > \.spinner/g)].map((m) => m[1])
  assert.deepEqual(covered.sort(), ['analysis-loading', 'career-optimization-loading'])
  for (const url of await sourceFiles()) {
    const source = await readFile(url, 'utf8')
    for (const cls of covered) {
      for (const m of source.matchAll(new RegExp(`className="${cls}"[\\s\\S]*?</div>`, 'g'))) {
        assert.match(m[0], /className="spinner"/, `${url.pathname.split('/src/')[1]}: a ${cls} block without its skeleton`)
      }
    }
  }
})

test('skeletons breathe on the shared timing token and never sweep', async () => {
  const css = stripComments(await read('index.css'))
  const pulse = css.match(/@keyframes skeleton-pulse\s*\{([\s\S]*?\}\s*)\}/)
  assert.ok(pulse)
  assert.match(pulse[1], /opacity/)
  assert.doesNotMatch(pulse[1], /background-position|transform|translate/, 'no shimmer sweep')
  assert.match(css, /animation:\s*skeleton-pulse var\(--t-pulse\)/)
  assert.match(await read('interaction.css'), /--t-pulse:\s*1600ms/)
})

test('the grade calculator list loads as placeholder cards and still announces itself', async () => {
  const panel = await read('components/GradeCalculatorPanel.tsx')
  assert.match(panel, /className="grade-card-loading" role="status"/)
  assert.match(panel, /grade-card grade-card--skeleton/)
  assert.match(panel, /Loading your grade calculators…/)
})

test('placeholder copy is set upright, not as italic filler', async () => {
  const css = stripComments(await read('index.css'))
  for (const selector of ['.empty-state', '.analysis-empty']) {
    const rule = css.match(new RegExp(`(?:^|\\n)${selector.replace('.', '\\.')}\\s*\\{([^}]*)\\}`))
    assert.ok(rule, selector)
    assert.doesNotMatch(rule[1], /font-style:\s*italic/, selector)
  }
})

test('overview readiness gaps offer the way to fill them', async () => {
  const dashboard = await read('pages/AuthenticatedDashboard.tsx')
  assert.doesNotMatch(dashboard, /Not yet available — run/)
  assert.match(dashboard, /onClick=\{\(\) => navigateToCareerSubTab\('intelligence'\)\}>Open Role Fit</)
  assert.match(dashboard, /onClick=\{\(\) => navigateToCareerSubTab\('intelligence'\)\}>Open Readiness Check</)
})

test('the old CampusIQ name appears nowhere in code outside comments', async () => {
  // Deliberately blunt: any string, JSX text or template the old name could
  // hide in is code, so none may carry it. Comments (history) are exempt.
  for (const url of await sourceFiles()) {
    const code = (await readFile(url, 'utf8'))
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/(^|[^:'"`])\/\/.*$/gm, '$1')
    const hits = code.split('\n').filter((line) => line.includes('CampusIQ')).map((line) => line.trim())
    assert.deepEqual(hits, [], url.pathname.split('/src/')[1])
  }
})
