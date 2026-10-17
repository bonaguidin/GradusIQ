import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

// The demo dashboard and the real one share one Overview look (Noah,
// 2026-10-13: same source, only the data differs), so every check here runs
// against both pages until the demo is folded into the real dashboard.
const OVERVIEW_PAGES = ['pages/AuthenticatedDashboard.tsx', 'pages/DashboardPage.tsx']

test('Overview opens with the name, then the chat, then the stat tiles', async () => {
  for (const path of OVERVIEW_PAGES) {
    const page = await read(path)
    const start = page.indexOf('stage-section overview-page')
    assert.ok(start > 0, `${path} marks its Overview section`)
    const header = page.indexOf('className="overview-header"', start)
    const chat = page.indexOf('<ChatPanel', start)
    const stats = page.indexOf('className="overview-stats"', start)
    assert.ok(header < chat && chat < stats, path)
  }
})

test('headline figures count in, and words sit in a status pill instead of a number slot', async () => {
  for (const path of OVERVIEW_PAGES) {
    const page = await read(path)
    const stats = page.slice(page.indexOf('className="overview-stats"'))
    const tiles = stats.slice(0, stats.indexOf('className="overview-grid"'))
    assert.equal((tiles.match(/<AnimatedNumber [^>]*countIn/g) ?? []).length, 2, path)
    assert.match(tiles, /<StatusStat label=/, path)
    assert.doesNotMatch(tiles, /overview-stat-value readiness-state/, path)
  }
  const ring = await read('components/DegreeProgressRing.tsx')
  assert.match(ring, /<AnimatedNumber value=\{pct\} decimals=\{0\} suffix="%" countIn \/>/)
})

test('a count-in is opt-in, so other figures still only count on change', async () => {
  const number = await read('components/AnimatedNumber.tsx')
  assert.match(number, /countIn = false/)
  // Reduced motion skips the count-in like every other count.
  assert.match(number, /prefers-reduced-motion: reduce[^}]*pendingCountIn\.current = false/s)
})

test('Overview empty slots use the shared block: icon, one line, one action', async () => {
  const dashboard = await read('pages/AuthenticatedDashboard.tsx')
  for (const line of ['No current term.', 'No role match yet.', 'No readiness check yet.']) {
    const at = dashboard.indexOf(line)
    assert.ok(at > 0, line)
    const block = dashboard.slice(dashboard.lastIndexOf('<EmptyState', at), at)
    assert.match(block, /icon="[a-z]+"/, line)
    assert.match(block, /action=\{<button /, line)
  }
  assert.doesNotMatch(dashboard, /<p className="empty-state">No (current term|role match|readiness check)/)
})

test('the Overview entrance and ring draw only animate, so reduced motion keeps everything visible', async () => {
  const css = await read('index.css')
  // Up to the celebration block: its burst is decoration that starts hidden
  // on purpose and is removed outright under reduced motion
  // (requirementCelebration.test.mjs checks that).
  const block = css.slice(css.indexOf('OVERVIEW SHOWPIECE'), css.indexOf('REQUIREMENT CELEBRATION'))
  // `backwards` holds the start frame only while an animation runs; with
  // animations off (the global reduced-motion rule) nothing starts hidden.
  assert.match(block, /animation: overview-rise [^;]*backwards;/)
  assert.match(block, /animation: ring-draw [^;]*backwards;/)
  assert.doesNotMatch(block, /^\s*opacity:\s*0;/m)
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{\s*\*, \*::before, \*::after \{\s*transition: none !important;\s*animation: none !important;/)
})

test('the chat composer keeps Send quiet until there is something to send', async () => {
  const panel = await read('components/ChatPanel.tsx')
  assert.match(panel, /className="chat-input-row chat-composer"/)
  assert.match(panel, /className="btn btn-primary btn-sm chat-send"\s*disabled=\{sending \|\| !input\.trim\(\) \|\| !canSend\}/)
  const css = await read('components/ChatPanel.css')
  assert.match(css, /\.chat-send:disabled \{[^}]*opacity: 1;/)
  assert.match(css, /\.chat-composer:focus-within \{/)
})
