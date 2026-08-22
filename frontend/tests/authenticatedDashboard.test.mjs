import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { planningRoutes } from './fixtures/planningRoutes.mjs'

test('authenticated dashboard covers canonical states, routing, themes, errors, demo separation, and mobile', { timeout: 45_000 }, async (t) => {
  const requests = []
  const profilePatches = []
  // The Academic Record tab renders the term view. Its Fall 2025 term id
  // matches the preview harness's own course row, so that course is reachable
  // by selecting its term; Fall 2026 is the upcoming term the dropdown opens
  // on and the one planning is offered for. Spring 2027 is a third, further-out
  // term: not started, so plannable, but NOT is_upcoming -- which is the pair
  // the merged-vs-separate rendering of planned courses turns on.
  const planning = planningRoutes({
    terms: [
      { key: '2025-Fall', id: 'term-1', label: 'Fall 2025', year: 2025, season: 'Fall', sequence: 1, start_date: '2025-08-25', end_date: '2025-12-17', enrolled: true, is_upcoming: false },
      { key: '2026-Fall', id: null, label: 'Fall 2026', year: 2026, season: 'Fall', sequence: null, start_date: '2026-08-24', end_date: '2026-12-10', enrolled: false, is_upcoming: true },
      { key: '2027-Spring', id: null, label: 'Spring 2027', year: 2027, season: 'Spring', sequence: null, start_date: '2027-01-19', end_date: '2027-05-11', enrolled: false, is_upcoming: false },
    ],
  })
  const apiPlugin = { name: 'dashboard-api', configureServer(server) { server.middlewares.use((request, response, next) => {
    const path = request.url?.split('?')[0]
    if (planning.handle(path, request.method, request, response)) return undefined
    if (request.url?.startsWith('/api/v2/student/me/analyze/')) {
      requests.push({ url: request.url, authorization: request.headers.authorization })
      response.statusCode = 200; response.setHeader('content-type', 'application/json')
      // Mirrors base.py's skip result: `errors` carries the human sentence,
      // `missing_fields` carries the label and the dotted path together.
      response.end(JSON.stringify({
        feature: 'GAP',
        status: 'skipped',
        summary: '',
        data: {},
        errors: ['Missing required field: AI comfort level'],
        missing_fields: [{ path: 'career.ai_anxiety_level', label: 'AI comfort level' }],
      }))
      return
    }
    if (path === '/api/v2/student/me/profile' && request.method === 'PATCH') {
      let body = ''; request.on('data', (chunk) => { body += chunk })
      request.on('end', () => {
        profilePatches.push(JSON.parse(body))
        response.setHeader('content-type', 'application/json')
        if (profilePatches.length === 1) { response.statusCode = 502; response.end(JSON.stringify({ detail: 'Could not save your profile.' })) }
        else { response.statusCode = 200; response.end(JSON.stringify({ ok: true })) }
      })
      return
    }
    next()
  }) } }
  const server = await createServer({ root: new URL('..', import.meta.url).pathname, cacheDir: new URL('../node_modules/.vite-auth-dashboard', import.meta.url).pathname, logLevel: 'silent', plugins: [apiPlugin], server: { host: '127.0.0.1' } })
  await server.listen(); t.after(async () => server.close())
  const address = server.httpServer?.address(); assert.ok(address && typeof address === 'object')
  const origin = `http://127.0.0.1:${String(address.port)}`
  const browser = await chromium.launch(); t.after(async () => browser.close())
  const page = await browser.newPage()

  const TAMU_ID = '75d68331-91d2-47e8-9671-2a3b065955d0'
  const SMU_ID = '6b180bbf-66d7-4aef-b8c6-2ae534c78e9a'
  const themes = {
    [TAMU_ID]: { brand_primary_hex: '#500000', brand_rail_hex: '#2B0B0B', brand_on_primary_hex: '#FFFFFF' },
    [SMU_ID]: { brand_primary_hex: '#0033A0', brand_rail_hex: '#171E2B', brand_on_primary_hex: '#FFFFFF' },
  }
  const themeRequests = []
  await page.route('**/rest/v1/institutions*', async (route) => {
    const url = new URL(route.request().url())
    themeRequests.push(url.search)
    const idFilter = url.searchParams.get('id')
    const nameFilter = url.searchParams.get('name')
    const id = idFilter?.replace(/^eq\./, '')
    const theme = id ? themes[id] : nameFilter === 'eq.Texas A&M University' ? themes[TAMU_ID] : null
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'application/vnd.pgrst.object+json' },
      body: JSON.stringify(theme),
    })
  })

  // CASE 1: complete real identity, institution, official GPA, academics and career.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete`)
  await page.getByRole('heading', { name: 'Alex Morgan' }).waitFor()
  await page.getByText('Texas A&M University').waitFor()
  await page.getByText('Official GPA').first().waitFor()
  await page.getByRole('button', { name: 'Academic' }).click()

  // The top-level Academic item is itself the overview -- clicking it lands
  // on Academic Overview, expands exactly two nested children, and neither
  // child is named "Overview" (that state is internal, not a visible tab).
  await page.getByRole('heading', { name: 'Academic Overview' }).waitFor()
  assert.deepEqual(
    await page.locator('.rail-subitem').allTextContents(),
    ['GPA Calculator', 'Course Discovery'],
  )
  assert.equal(await page.locator('.rail-subitem', { hasText: 'Overview' }).count(), 0)
  await page.getByText('Official GPA').first().waitFor()
  await page.getByText('Projected GPA').first().waitFor()
  await page.getByText('Earned Hours').first().waitFor()

  // GPA Calculator: Academic stays the active parent while the child becomes
  // active, and the existing GPA/term machinery renders exactly as before.
  await page.getByRole('button', { name: 'GPA Calculator' }).click()
  assert.equal(
    await page.getByRole('button', { name: 'Academic', exact: true }).getAttribute('aria-current'),
    'page',
  )
  await page.getByRole('heading', { name: 'GPA Calculator' }).waitFor()

  // The term view opens on the UPCOMING term, not on the term holding the
  // student's coursework -- planning happens in the term that has not started.
  await page.locator('#term-select').waitFor()
  assert.equal(await page.locator('#term-select').inputValue(), '2026-Fall')
  await page.getByText('Aug 24, 2026').waitFor()
  await page.locator('.term-badge--upcoming').waitFor()

  // Selecting the term that does hold coursework shows it.
  await page.locator('#term-select').selectOption('2025-Fall')
  await page.getByText('CS 101').waitFor()

  // Planning: search, add, see it listed as distinctly PLANNED, remove it.
  await page.locator('#term-select').selectOption('2026-Fall')
  await page.locator('#course-search').fill('CSCE 2')
  await page.getByText('Data Structures and Algorithms').waitFor()
  await page.getByRole('button', { name: 'Add' }).first().click()
  await page.locator('.real-course-row--planned').waitFor()

  // A planned course must never be presentable as completed coursework: it
  // carries its own badge, its own dashed row, a Remove control, and says it
  // counts toward nothing -- whichever list it is sitting in.
  const plannedRow = page.locator('.real-course-row--planned').first()
  await plannedRow.getByText('CSCE 221').waitFor()
  await plannedRow.locator('.planned-badge').waitFor()
  await page.getByText(/not counted in GPA or hours/).waitFor()
  assert.equal(await page.locator('.real-course-row--planned .planned-badge').count(), 1)
  // 4 credits came from the catalog result, not invented by the UI.
  await plannedRow.getByText('4 credits').waitFor()
  assert.equal(planning.state.planned.length, 1)

  // In the UPCOMING term the planned row sits inside Coursework, and there is
  // no separate Planned section left to label.
  await page.locator('[aria-label="Coursework in this term"] .real-course-row--planned').waitFor()
  assert.equal(await page.locator('.term-courses--planned').count(), 0)

  // Re-searching the same course offers no second add.
  await page.locator('#course-search').fill('CSCE 22')
  await page.getByRole('button', { name: 'Planned' }).first().waitFor()

  await plannedRow.getByRole('button', { name: /Remove CSCE 221/ }).click()
  await page.locator('.real-course-row--planned').waitFor({ state: 'detached' })
  assert.equal(planning.state.planned.length, 0)

  // A term FURTHER OUT than the upcoming one keeps the two sections apart: it
  // has no confirmed coursework to interleave with, so a merged list would
  // present a wholly speculative term as though it were a settled one.
  await page.locator('#term-select').selectOption('2027-Spring')
  await page.locator('#course-search').fill('CSCE 2')
  await page.getByText('Data Structures and Algorithms').waitFor()
  await page.getByRole('button', { name: 'Add' }).first().click()
  await page.locator('.term-courses--planned .real-course-row--planned').waitFor()
  await page.locator('.term-courses--planned').getByText('Planned', { exact: true }).first().waitFor()
  assert.equal(
    await page.locator('[aria-label="Coursework in this term"] .real-course-row--planned').count(),
    0,
  )
  // The same row styling and controls survive the relocation.
  const futureRow = page.locator('.term-courses--planned .real-course-row--planned').first()
  await futureRow.locator('.planned-badge').waitFor()
  await futureRow.getByRole('button', { name: /Remove CSCE 221/ }).waitFor()
  await futureRow.getByRole('button', { name: /Remove CSCE 221/ }).click()
  await page.locator('.real-course-row--planned').waitFor({ state: 'detached' })
  assert.equal(planning.state.planned.length, 0)

  // Clicking the Academic parent again -- while a child was active -- returns
  // to Academic Overview rather than leaving GPA Calculator open.
  await page.getByRole('button', { name: 'Academic', exact: true }).click()
  await page.getByRole('heading', { name: 'Academic Overview' }).waitFor()

  // Course Discovery now lives under Academic, not Career -- and Academic
  // still stays the active parent while it is the active child.
  await page.getByRole('button', { name: 'Course Discovery' }).click()
  await page.getByRole('heading', { name: 'Course Discovery' }).waitFor()
  assert.equal(
    await page.getByRole('button', { name: 'Academic', exact: true }).getAttribute('aria-current'),
    'page',
  )
  await page.getByText('Explore courses at your school that could build skills for your career goals.').waitFor()

  await page.getByRole('button', { name: 'Career' }).click()
  await page.getByRole('heading', { name: 'Career Overview' }).waitFor()
  assert.deepEqual(
    await page.getByRole('group', { name: 'Career sections' }).getByRole('button').allTextContents(),
    ['Career Intelligence', 'Job Search', 'Career Profile'],
  )
  assert.equal(await page.getByRole('tab').count(), 0, 'old horizontal Career tabs remain')
  // CareerProfile now lives under the Career Profile sidebar child.
  await page.getByRole('button', { name: 'Career Profile' }).click()
  // Target roles now appear twice by design -- once as the Career summary
  // headline, once in the Career direction list -- so both are named rather
  // than matched loosely.
  await page.locator('.cp-summary-roles').getByText('Software Engineer').waitFor()
  await page.locator('.cp-roles li').getByText('Software Engineer').waitFor()
  await page.getByText('Cloud Fundamentals').waitFor()
  // Course Discovery no longer renders inside Career's Profile sub-tab.
  assert.equal(await page.getByRole('heading', { name: 'Course Discovery' }).count(), 0)

  // Career Intelligence is one page containing the three independent runs.
  await page.getByRole('button', { name: 'Career Intelligence' }).click()
  await page.getByRole('heading', { name: 'Career Intelligence' }).waitFor()
  await page.getByRole('heading', { name: /GAP/ }).waitFor()
  await page.getByRole('heading', { name: /FIT/ }).waitFor()
  await page.getByRole('heading', { name: /SHIFT/ }).waitFor()
  await page.getByRole('button', { name: 'Academic', exact: true }).click()
  await page.getByRole('heading', { name: 'Academic Overview' }).waitFor()
  await page.getByRole('button', { name: 'GPA Calculator' }).click()
  await page.locator('#term-select').waitFor()
  await page.getByRole('button', { name: 'Career' }).click()
  // Clicking the parent always returns to its internal overview.
  await page.getByRole('heading', { name: 'Career Overview' }).waitFor()

  // Job Search is intentionally honest until a production service exists.
  await page.getByRole('button', { name: 'Job Search' }).click()
  await page.getByRole('heading', { name: 'Job Search', exact: true }).waitFor()
  await page.getByText('Live job search is not connected yet').waitFor()
  assert.equal(await page.getByRole('button', { name: 'Search Jobs' }).isDisabled(), true)

  // CASE 2: career only renders academic onboarding.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=career`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('link', { name: 'Upload transcript' }).waitFor()

  // CASE 3: academics only renders career onboarding.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=academic`)
  await page.getByRole('button', { name: 'Career' }).click()
  await page.getByRole('link', { name: 'Upload resume' }).waitFor()

  // CASE 4: minimal profile renders both useful onboarding paths without a crash.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=minimal`)
  assert.equal(await page.getByText('minimal', { exact: true }).count() > 0, true)
  assert.equal(await page.getByRole('link', { name: 'Upload transcript' }).count(), 1)
  assert.equal(await page.getByRole('link', { name: 'Upload resume' }).count(), 1)

  // CASE 5: API/account failure is explicit and retryable, never a demo profile.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=error`)
  await page.getByText('Profile API failed.').waitFor()
  await page.getByRole('button', { name: 'Try again' }).click()
  assert.equal(await page.evaluate(() => document.body.dataset.retried), 'yes')
  assert.equal(await page.getByText('Jordan Reyes').count(), 0)

  // CASE 6: canonical institution rendering for TAMU and SMU.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete&institution=smu`)
  await page.getByText('Southern Methodist University').waitFor()

  // CASE 8: authenticated analysis uses /me and forwards the bearer token.
  await page.getByRole('button', { name: 'Career' }).click()
  await page.getByRole('button', { name: 'Career Intelligence' }).click()
  for (const title of ['Readiness Check (GAP)', 'Role Fit (FIT)', 'Trend Guidance (SHIFT)']) {
    await page.locator('.analysis-panel').filter({ hasText: title }).getByRole('button', { name: 'Run analysis' }).click()
  }
  await page.getByText(/missing information/).first().waitFor()

  // A skipped analysis names the field in the student's language, and sends
  // them to THAT field on the page they are already looking at. No dialog
  // opens, nothing is covered, and the dotted path never reaches the screen.
  const skipped = page.locator('.analysis-skipped').first()
  await skipped.getByText('AI comfort level').waitFor()
  assert.equal(await page.getByText('career.ai_anxiety_level').count(), 0)
  const trigger = skipped.getByRole('button', { name: 'Add this' }).first()
  await trigger.click()
  assert.equal(await page.getByRole('dialog').count(), 0, 'a dialog reappeared')
  assert.equal(await page.locator('[data-dashboard-source="authenticated"]').count(), 1)

  // The request landed on the field it named, and left the keyboard there.
  const aiRow = page.locator('[data-profile-field="career.ai_anxiety_level"]')
  await aiRow.waitFor()
  await page.waitForFunction(() =>
    document.activeElement?.closest('[data-profile-field="career.ai_anxiety_level"]') !== null)

  // The rest of the profile stays exactly as readable as it was -- this is the
  // half the modal used to cover.
  assert.equal(await page.getByRole('heading', { name: 'Career Profile' }).count(), 1)
  await page.locator('.cp-roles li').getByText('Software Engineer').waitFor()

  // No AI radio is selected while ai_anxiety_level is null.
  assert.equal(await aiRow.locator('input:checked').count(), 0)
  // Selection remains a local draft. The first explicit save is refused by
  // the harness, and the failure is reported without closing or losing it.
  await aiRow.getByLabel('Moderate').check()
  assert.equal(profilePatches.length, 0, 'selecting AI comfort autosaved')
  await aiRow.getByRole('button', { name: 'Save' }).click()
  await aiRow.getByRole('alert').waitFor()
  assert.equal(await aiRow.getByLabel('Moderate').isChecked(), true)
  await aiRow.getByRole('button', { name: 'Save' }).click()
  await page.waitForFunction(() => document.body.dataset.profileReloaded === 'yes')
  assert.deepEqual(profilePatches.at(-1), { ai_anxiety_level: 'moderate' })
  await page.getByRole('status').filter({ hasText: 'Profile saved' }).waitFor()

  // FIT routes through the same handler, and asking a SECOND time for a field
  // already visited still moves -- the request is keyed on a nonce, not on the
  // path, or the second click would be indistinguishable from no click.
  // Return to Career Intelligence, where FIT's independent skipped state is
  // unchanged; the AI-comfort jump above moved to Career Profile.
  await page.getByRole('button', { name: 'Career Intelligence' }).click()
  const fitSkipped = page.locator('.analysis-panel').filter({ hasText: 'Role Fit (FIT)' }).locator('.analysis-skipped')
  await fitSkipped.getByRole('button', { name: 'Add this' }).first().click()
  await page.waitForFunction(() =>
    document.querySelector('[data-profile-field="career.ai_anxiety_level"]')?.classList.contains('cp-field-flag') === true)
  assert.equal(await page.getByRole('dialog').count(), 0)

  // Every gating detail is answered in this fixture, so the dock reports the
  // settled state rather than inventing something to ask for.
  const dock = page.locator('[data-profile-checklist]')
  await dock.getByText('All details provided').waitFor()
  assert.equal(await dock.locator('.pc-dock-item').count(), 0)

  // The dock is sticky, not fixed: it participates in the page's own scroll
  // container rather than floating above it.
  assert.equal(await dock.evaluate((node) => getComputedStyle(node).position), 'sticky')

  // No page-level horizontal overflow on a phone now that the dock is there.
  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)

  assert.deepEqual(requests.map(({ url }) => url), [
    '/api/v2/student/me/analyze/gap',
    '/api/v2/student/me/analyze/fit',
    '/api/v2/student/me/analyze/shift',
  ])
  assert.equal(requests.every(({ authorization }) => authorization === 'Bearer real-access-token'), true)

  // CASE 10: mobile viewport has no page-level horizontal overflow.
  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)

  // CASES 7/9: source boundaries preserve demo loading and clear demo identity on real sign-in.
  const authSource = await readFile(new URL('../src/auth/AuthContext.tsx', import.meta.url), 'utf8')
  const dashboardSource = await readFile(new URL('../src/pages/DashboardPage.tsx', import.meta.url), 'utf8')
  assert.match(authSource, /staticJsonAdapter\.loadStudent/)
  assert.match(authSource, /sessionStorage\.removeItem\(SESSION_KEY\)/)
  assert.match(authSource, /previousUserId !== nextUserId/)
  assert.match(authSource, /fetchInstitutionThemeById\(institutionId\)/)
  assert.match(authSource, /fetchInstitutionThemeByName\(p\.student\.institution\)/)
  assert.match(dashboardSource, /return <DemoDashboardPage/)
  assert.match(dashboardSource, /return <AuthenticatedDashboard/)

  // Authenticated theme resolution is keyed only by the canonical ID. The
  // display-name variation deliberately never enters the lookup.
  const applyById = async (id) => page.evaluate(async (institutionId) => {
    const themeModule = await import('/src/lib/institutionTheme.ts')
    const theme = await themeModule.fetchInstitutionThemeById(institutionId)
    themeModule.applyInstitutionTheme(theme)
    const style = document.documentElement.style
    return {
      accent: style.getPropertyValue('--accent-rgb'),
      accentText: style.getPropertyValue('--accent-text-rgb'),
      onAccent: style.getPropertyValue('--on-accent-rgb'),
      rail: style.getPropertyValue('--rail-bg-rgb'),
    }
  }, id)

  assert.deepEqual(await applyById(TAMU_ID), {
    accent: '80 0 0', accentText: '68 0 0', onAccent: '255 255 255', rail: '43 11 11',
  })
  // Switching accounts replaces every institution token; TAMU values do not survive.
  assert.deepEqual(await applyById(SMU_ID), {
    accent: '0 51 160', accentText: '0 43 136', onAccent: '255 255 255', rail: '23 30 43',
  })
  assert.equal(themeRequests.some((query) => query.includes(`id=eq.${TAMU_ID}`)), true)
  assert.equal(themeRequests.some((query) => query.includes(`id=eq.${SMU_ID}`)), true)

  // Logout/reset clears inline values and exposes the neutral :root defaults.
  const cleared = await page.evaluate(async () => {
    const themeModule = await import('/src/lib/institutionTheme.ts')
    themeModule.clearInstitutionTheme()
    return {
      inlineAccent: document.documentElement.style.getPropertyValue('--accent-rgb'),
      computedAccent: getComputedStyle(document.documentElement).getPropertyValue('--accent-rgb').trim(),
    }
  })
  assert.deepEqual(cleared, { inlineAccent: '', computedAccent: '36 36 36' })

  // Demo compatibility remains the explicitly name-based path.
  const demoTheme = await page.evaluate(async () => {
    const themeModule = await import('/src/lib/institutionTheme.ts')
    return themeModule.fetchInstitutionThemeByName('Texas A&M University')
  })
  assert.deepEqual(demoTheme, themes[TAMU_ID])
  assert.equal(themeRequests.some((query) => query.includes('name=eq.Texas+A%26M+University')), true)
})
