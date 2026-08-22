import assert from 'node:assert/strict'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { planningRoutes } from './fixtures/planningRoutes.mjs'

const need = (skill, needId) => ({
  need_id: needId,
  skill,
  category: 'skills',
  target_role: 'Software Engineer',
  importance: 'required',
  evidence_state: 'VERIFIED_LOCAL',
  evidence_source: 'O*NET 15-1252.00 onet',
  confidence: 0.8,
})

const provenance = (code) => ({
  institution: 'tamu',
  course_code: code,
  catalog_year: '2026-2027',
  source_url: `https://catalog.tamu.edu/undergraduate/course-descriptions/${code.split(' ')[0].toLowerCase()}/`,
  source_last_checked: '2026-06-20',
})

function verifiedCourse(overrides = {}) {
  return {
    institution: 'tamu',
    course_code: 'CSCE 331',
    title: 'Algorithms and Data Structures',
    description: 'Analysis and design of algorithms.',
    credit_min: 4,
    credit_max: 4,
    matched_needs: [need('Algorithms', 'need_algo1')],
    match_kinds: ['MATCHED_TITLE'],
    matched_terms: ['algorithms'],
    student_status: 'NOT_TAKEN',
    prerequisite_status: 'ELIGIBLE',
    prerequisite_evaluation: null,
    eligibility_status: 'ELIGIBLE',
    provenance: provenance('CSCE 331'),
    ranking_reason: 'Strengthens algorithms and software engineering skills relevant to the role.',
    skill_alignment_explanation: 'Directly covers algorithm design, a required skill for this role.',
    degree_applicability: 'UNKNOWN',
    offering_status: 'UNKNOWN',
    ...overrides,
  }
}

function blockedCourse(overrides = {}) {
  return {
    institution: 'tamu',
    course_code: 'FINC 446',
    title: 'Investment Analysis',
    matched_needs: [need('Financial Analysis', 'need_finc1')],
    match_kinds: ['MATCHED_TITLE'],
    eligibility_status: 'INELIGIBLE',
    prerequisite_status: 'INELIGIBLE',
    prerequisite_evaluation: {
      status: 'INELIGIBLE',
      requirement: { mode: 'ALL', course_codes: ['FINC 351', 'FINC 361', 'FINC 371'], restrictions: [], raw_text: null, unresolved_reasons: [] },
      satisfied_courses: [],
      missing_courses: ['FINC 351'],
      in_progress_courses: ['FINC 361'],
      planned_courses: ['FINC 371'],
      unknown_courses: [],
      reasons: ['one or more required prerequisite courses are not completed'],
    },
    provenance: provenance('FINC 446'),
    ...overrides,
  }
}

function unresolvedCourse(overrides = {}) {
  return {
    institution: 'tamu',
    course_code: 'CSCE 221',
    title: 'Data Structures and Algorithms',
    matched_needs: [need('Data Structures', 'need_ds1')],
    match_kinds: ['MATCHED_TITLE'],
    eligibility_status: 'UNRESOLVED',
    reasons: ['ambiguous restriction'],
    prerequisite_evaluation: null,
    provenance: provenance('CSCE 221'),
    ...overrides,
  }
}

function discoveryResult({ verified = [], blocked = [], unresolved = [] } = {}) {
  return {
    target_role: 'Software Engineer',
    current_major: 'Computer Science',
    intended_major: 'Computer Science',
    career_needs: [need('Algorithms', 'need_algo1')],
    verified_recommendations: verified,
    requires_verification: unresolved,
    prerequisite_blocked: blocked,
    summary: `Verified ${verified.length} institution-scoped course recommendation(s); ${unresolved.length} additional candidate(s) require human verification; ${blocked.length} candidate(s) blocked by an unmet prerequisite. Degree applicability and future offering remain unknown.`,
    degree_applicability: 'UNKNOWN',
    offering_status: 'UNKNOWN',
  }
}

function featureResult(data) {
  return { feature: 'COURSE_DISCOVERY', status: 'success', summary: data.summary, data, errors: [] }
}

test('Course Discovery panel: CTA, loading, three typed outcomes, empty/failure states, role selection, responsiveness', { timeout: 45_000 }, async (t) => {
  const planning = planningRoutes({ terms: [] })
  const requestBodies = []
  let discoveryResponse = { status: 200, body: featureResult(discoveryResult()) }

  const apiPlugin = {
    name: 'course-discovery-api',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/analyze/course-discovery' && request.method === 'POST') {
          let body = ''
          request.on('data', (chunk) => { body += chunk })
          request.on('end', () => {
            requestBodies.push({ raw: body, authorization: request.headers.authorization })
            response.statusCode = discoveryResponse.status
            response.setHeader('content-type', 'application/json')
            response.end(JSON.stringify(discoveryResponse.body))
          })
          return
        }
        if (request.url?.startsWith('/api/v2/student/me/analyze/')) {
          // GAP/FIT/SHIFT: idle by default (never auto-clicked), but must not
          // 404 if the harness or a future change triggers them.
          response.statusCode = 200
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify({ feature: 'GAP', status: 'skipped', summary: '', data: {}, errors: [], missing_fields: [] }))
          return
        }
        next()
      })
    },
  }

  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-course-discovery', import.meta.url).pathname,
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const origin = `http://127.0.0.1:${String(address.port)}`

  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()

  await page.route('**/rest/v1/institutions*', async (route) => {
    await route.fulfill({ status: 200, headers: { 'content-type': 'application/vnd.pgrst.object+json' }, body: JSON.stringify(null) })
  })

  // ── single confirmed target role: no selector, plain CTA ──────────────────
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete`)
  // Course Discovery lives under Academic's own "Course Discovery" child nav
  // item, not inside Career.
  await page.getByRole('button', { name: 'Academic' }).click()

  // Before any run exists, Academic Overview offers a lightweight CTA
  // instead of a summary -- no result to summarize yet, and no full panel
  // rendered here either.
  await page.getByRole('heading', { name: 'Academic Overview' }).waitFor()
  const cdSummary = page.locator('.academic-overview-course-discovery')
  await cdSummary.getByRole('button', { name: 'Discover courses that support your career goals →' }).waitFor()
  assert.equal(await cdSummary.getByText(/^For:/).count(), 0)

  await page.getByRole('button', { name: 'Course Discovery' }).click()
  await page.getByRole('heading', { name: 'Course Discovery' }).waitFor()
  assert.equal(await page.locator('#course-discovery-target-role').count(), 0)
  await page.getByText('Explore courses at your school that could build skills for your career goals.').waitFor()

  // Course Discovery no longer renders inside Career's Profile sub-tab.
  await page.getByRole('button', { name: 'Career' }).click()
  await page.getByRole('button', { name: 'Career Profile' }).click()
  assert.equal(await page.getByRole('heading', { name: 'Course Discovery' }).count(), 0)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()

  // ── loading state: click through a deliberately delayed response ──────────
  let releaseLoading
  const loadingGate = new Promise((resolve) => { releaseLoading = resolve })
  discoveryResponse = {
    status: 200,
    get body() { return featureResult(discoveryResult()) },
  }
  const courseDiscoveryPanel = page.locator('.card.analysis-panel', { has: page.getByRole('heading', { name: 'Course Discovery' }) })
  const runButton = courseDiscoveryPanel.getByRole('button', { name: 'Run analysis' })

  // Delay this one response so the loading state is observable.
  await page.route('**/api/v2/student/me/analyze/course-discovery', async (route) => {
    await loadingGate
    await route.continue()
  })
  await runButton.click()
  await courseDiscoveryPanel.locator('[role="status"]').waitFor()
  await courseDiscoveryPanel.getByText(/Running this analysis against a live model/).waitFor()
  releaseLoading()
  await page.unroute('**/api/v2/student/me/analyze/course-discovery')
  await courseDiscoveryPanel.locator('.empty-state').waitFor()
  await courseDiscoveryPanel.getByText('No verified course recommendations found from the current evidence.').waitFor()

  // ── verified recommendation ────────────────────────────────────────────────
  discoveryResponse = { status: 200, body: featureResult(discoveryResult({ verified: [verifiedCourse()] })) }
  await courseDiscoveryPanel.getByRole('button', { name: 'Re-run analysis' }).click()
  await courseDiscoveryPanel.getByText('Recommended courses').waitFor()
  await courseDiscoveryPanel.getByText('CSCE 331 — Algorithms and Data Structures').waitFor()
  await courseDiscoveryPanel.getByText('Strengthens algorithms and software engineering skills relevant to the role.').waitFor()
  await courseDiscoveryPanel.getByText('Algorithms', { exact: true }).waitFor()
  await courseDiscoveryPanel.getByText('Ready to consider').waitFor()
  // only the populated section renders
  assert.equal(await courseDiscoveryPanel.getByText('Courses to work toward').count(), 0)
  assert.equal(await courseDiscoveryPanel.getByText('Needs verification').count(), 0)

  // ── Academic Overview reflects this exact run: same result, no re-run ─────
  await page.getByRole('button', { name: 'Academic', exact: true }).click()
  await page.getByRole('heading', { name: 'Academic Overview' }).waitFor()
  await cdSummary.getByText('For: Software Engineer').waitFor()
  await cdSummary.getByText('1 recommended course').waitFor()
  await cdSummary.getByText('CSCE 331').waitFor()
  await cdSummary.getByText('Algorithms and Data Structures').waitFor()

  // Following the summary's link lands back on Academic > Course Discovery,
  // with Academic still the active parent and the same result still shown --
  // clicking through never re-ran the analysis.
  await cdSummary.getByRole('button', { name: 'View Course Discovery →' }).click()
  await page.getByRole('heading', { name: 'Course Discovery' }).waitFor()
  assert.equal(
    await page.getByRole('button', { name: 'Academic', exact: true }).getAttribute('aria-current'),
    'page',
  )
  await courseDiscoveryPanel.getByText('CSCE 331 — Algorithms and Data Structures').waitFor()

  // ── prerequisite-blocked: multiple prerequisites, each status distinct ────
  discoveryResponse = { status: 200, body: featureResult(discoveryResult({ blocked: [blockedCourse()] })) }
  await courseDiscoveryPanel.getByRole('button', { name: 'Re-run analysis' }).click()
  await courseDiscoveryPanel.getByText('Courses to work toward').waitFor()
  await courseDiscoveryPanel.getByText('FINC 446 — Investment Analysis').waitFor()
  await courseDiscoveryPanel.getByText('Not yet actionable').waitFor()
  await courseDiscoveryPanel.getByText('Relevant to your target role').waitFor()
  const finc351 = courseDiscoveryPanel.locator('.course-discovery-prereq', { hasText: 'FINC 351' })
  const finc361 = courseDiscoveryPanel.locator('.course-discovery-prereq', { hasText: 'FINC 361' })
  const finc371 = courseDiscoveryPanel.locator('.course-discovery-prereq', { hasText: 'FINC 371' })
  await finc351.getByText('Not yet started').waitFor()
  await finc361.getByText('In progress').waitFor()
  await finc371.getByText('Planned').waitFor()
  assert.equal(await courseDiscoveryPanel.locator('.course-discovery-prereq').count(), 3)
  // not shown as a failed recommendation
  assert.equal(await courseDiscoveryPanel.getByText('Recommended courses').count(), 0)

  // ── requires verification: visually/semantically distinct from both ───────
  discoveryResponse = { status: 200, body: featureResult(discoveryResult({ unresolved: [unresolvedCourse()] })) }
  await courseDiscoveryPanel.getByRole('button', { name: 'Re-run analysis' }).click()
  await courseDiscoveryPanel.getByText('Needs verification', { exact: true }).first().waitFor()
  await courseDiscoveryPanel.getByText('CSCE 221 — Data Structures and Algorithms').waitFor()
  await courseDiscoveryPanel.getByText('Course Discovery could not safely confirm this course from current evidence.').waitFor()
  assert.equal(await courseDiscoveryPanel.getByText('Ready to consider').count(), 0)
  assert.equal(await courseDiscoveryPanel.getByText('Not yet actionable').count(), 0)

  // ── API/domain failure: inline retry pattern, no stack trace ───────────────
  discoveryResponse = { status: 502, body: { detail: 'Course discovery is unavailable.' } }
  await courseDiscoveryPanel.getByRole('button', { name: 'Re-run analysis' }).click()
  await courseDiscoveryPanel.locator('.analysis-failed').waitFor()
  const failureText = await courseDiscoveryPanel.locator('.analysis-failed').innerText()
  assert.equal(/Traceback|Exception|at\s+\S+\.(py|ts|tsx):\d+/.test(failureText), false)

  // ── multiple confirmed roles: selector present, only real roles offered ───
  discoveryResponse = { status: 200, body: featureResult(discoveryResult()) }
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete&career=rich`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()
  const roleSelect = page.locator('#course-discovery-target-role')
  await roleSelect.waitFor()
  const options = await roleSelect.locator('option').allTextContents()
  assert.deepEqual(options, ['AI Engineer', 'ML Engineer', 'Robotics Engineer'])
  await roleSelect.selectOption('Robotics Engineer')
  const multiRolePanel = page.locator('.card.analysis-panel', { has: page.getByRole('heading', { name: 'Course Discovery' }) })
  await multiRolePanel.getByRole('button', { name: 'Run analysis' }).click()
  await page.waitForTimeout(50)
  const lastRequest = requestBodies.at(-1)
  assert.deepEqual(JSON.parse(lastRequest.raw), { target_role: 'Robotics Engineer' })

  // ── missing target role: existing profile-completion flow, no new modal ───
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete&career=partial`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()
  discoveryResponse = {
    status: 200,
    body: {
      feature: 'COURSE_DISCOVERY', status: 'skipped', summary: '', data: {}, errors: [],
      missing_fields: [{ path: 'career.target_roles', label: 'Confirmed target role' }],
    },
  }
  const noRolePanel = page.locator('.card.analysis-panel', { has: page.getByRole('heading', { name: 'Course Discovery' }) })
  await noRolePanel.getByRole('button', { name: 'Run analysis' }).click()
  await noRolePanel.getByText('Confirmed target role').waitFor()
  await noRolePanel.getByRole('button', { name: 'Add this' }).waitFor()
  // no bespoke second modal/page introduced for this
  assert.equal(await page.locator('.course-discovery-modal').count(), 0)

  // ── existing FIT/GAP/SHIFT panels remain independently usable on the
  // unified Career Intelligence page; Course Discovery stays under Academic.
  await page.getByRole('button', { name: 'Career' }).click()
  await page.getByRole('button', { name: 'Career Intelligence' }).click()
  await page.getByRole('heading', { name: /GAP/ }).waitFor()
  await page.getByRole('heading', { name: /FIT/ }).waitFor()
  await page.getByRole('heading', { name: /SHIFT/ }).waitFor()

  // ── responsive: 390 / 834 / 1280, no page-level horizontal overflow ───────
  discoveryResponse = { status: 200, body: featureResult(discoveryResult({ verified: [verifiedCourse({ title: 'A Very Long Course Title That Should Wrap Instead Of Overflowing The Card On A Narrow Screen' })], blocked: [blockedCourse()] })) }
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()
  const wideRunButton = page.locator('.card.analysis-panel', { has: page.getByRole('heading', { name: 'Course Discovery' }) }).getByRole('button', { name: 'Run analysis' })
  await wideRunButton.click()
  await page.getByText('Recommended courses').waitFor()
  for (const width of [390, 834, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
      true,
      `page overflows horizontally at ${width}px`,
    )
  }
})
