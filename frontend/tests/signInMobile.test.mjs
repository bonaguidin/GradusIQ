import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('sign-in and sign-up put the pitch beside the form, and the demo gets its own footer', async () => {
  for (const path of ['pages/LoginPage.tsx', 'pages/SignUpPage.tsx']) {
    const page = await read(path)
    assert.match(page, /<div className="login-bg login-bg--split">\s*<LoginPitch \/>\s*<div className="login-card">/, path)
  }
  const login = await read('pages/LoginPage.tsx')
  const demo = login.slice(login.indexOf('<section className="login-demo"'))
  assert.match(demo, /id="student-select"/)
  assert.match(demo, /Enter Dashboard/)
  // The pitch is decoration on wide windows only; the form stands alone on a phone.
  const css = await read('index.css')
  const block = css.slice(css.indexOf('SIGN-IN + MOBILE'))
  assert.match(block, /\.login-pitch \{[^}]*display: none;/)
  assert.match(block, /@media \(min-width: 900px\) \{\s*\.login-pitch \{\s*display: block;/)
})

test('the account shell stays on the neutral palette, since no school is known before sign-in', async () => {
  const css = await read('index.css')
  const block = css.slice(css.indexOf('SIGN-IN + MOBILE'), css.indexOf('/* ── mobile ── */'))
  assert.doesNotMatch(block, /var\(--accent\)/)
  assert.match(block, /\.login-header::before \{[^}]*background-color: var\(--neutral-accent\);/)
  // The shell's entrance only animates, so reduced motion shows it at rest.
  assert.match(block, /animation: login-rise [^;]*backwards;/)
})

test('Course Discovery has a page title like every other Academic tab, and its card names what it holds', async () => {
  for (const path of ['pages/AuthenticatedDashboard.tsx', 'pages/DashboardPage.tsx']) {
    const page = await read(path)
    const section = page.slice(page.indexOf("academicSubTab === 'course-discovery'"))
    assert.match(section.slice(0, 600), /<h2 className="academic-section-heading">Course Discovery<\/h2>/, path)
  }
  const panel = await read('components/CourseDiscoveryPanel.tsx')
  assert.match(panel, /title="Courses for your target role"/)
})

test('Career Profile opens with its title, then the checklist', async () => {
  for (const path of ['pages/AuthenticatedDashboard.tsx', 'pages/DashboardPage.tsx']) {
    const page = await read(path)
    const section = page.slice(page.indexOf("careerSubTab === 'profile'"))
    assert.match(section, /<h2 className="career-section-heading">Career Profile<\/h2>\s*<ProfileChecklist/, path)
  }
})

test('on a phone, card headers wrap instead of clipping their button, and an odd stat tile fills its row', async () => {
  const css = await read('index.css')
  const mobile = css.slice(css.indexOf('/* ── mobile ── */'))
  assert.match(mobile, /\.editable-section-header \{\s*flex-wrap: wrap;/)
  assert.match(mobile, /\.overview-stats > \.overview-stat:last-child:nth-child\(odd\) \{\s*grid-column: 1 \/ -1;/)
})
