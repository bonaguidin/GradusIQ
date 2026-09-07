import assert from 'node:assert/strict'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { planningRoutes } from './fixtures/planningRoutes.mjs'

const PROFILE_ID = 'profile-phys-207'

const EXTRACTED_MODEL = {
  schema_version: '1',
  course: { course_code: 'PHYS 207', course_title: null, section: '529', term: 'Fall 2026', instructor: null },
  grading_method: 'weighted',
  categories: [
    { name: 'Mid-term Exam', weight: 35, count: null, evidence: { page: 2, text: 'Mid-term Exam: 35%', confidence: 1.0 } },
    { name: 'Final Exam', weight: 50, count: null, evidence: { page: 2, text: 'Final Exam: 50%', confidence: 1.0 } },
    { name: 'Lecture Quizzes', weight: 5, count: null, evidence: { page: 2, text: 'Lecture Quizzes: 5%', confidence: 1.0 } },
    { name: 'Recitation Quizzes', weight: 10, count: null, evidence: { page: 2, text: 'Recitation Quizzes: 10%', confidence: 1.0 } },
  ],
  assessments: [],
  grade_thresholds: [
    { letter: 'B', minimum: 80, maximum: 89, evidence: { page: 2, text: 'B: 80-89', confidence: 1.0 } },
    { letter: 'B+', minimum: 85, maximum: 92, evidence: { page: 2, text: 'B+: 85-92', confidence: 1.0 } },
  ],
  rules: [
    {
      rule_type: 'replacement', description: 'Final replaces Midterm when higher.',
      source: 'Final Exam', target: 'Mid-term Exam', condition: 'final_score > midterm_score',
      evidence: { page: 2, text: 'Final replaces Midterm when higher.', confidence: 1.0 },
    },
    {
      rule_type: 'curve', description: 'Grades may be curved upward.',
      source: null, target: null, condition: null,
      evidence: { page: 2, text: 'Grades may be curved upward.', confidence: 1.0 },
    },
  ],
  warnings: [{ type: 'possible_curve', description: 'No deterministic curve formula is given.', related_field: null }],
}

// Confirmed model keeps the deterministic replacement rule (calculator-
// executed) plus a spread of informational rules -- curve / late work /
// makeup -- that must land in the persistent "Professor's rules" panel,
// not the review list.
const CONFIRMED_MODEL = {
  ...EXTRACTED_MODEL,
  rules: [
    EXTRACTED_MODEL.rules[0], // replacement (deterministic)
    EXTRACTED_MODEL.rules[1], // curve
    {
      rule_type: 'late_work', description: 'No late homework will be accepted.',
      source: null, target: null, condition: null,
      evidence: { page: 3, text: 'No late homework will be accepted.', confidence: 1.0 },
    },
    {
      rule_type: 'makeup', description: 'Makeup exams require a documented, university-excused absence.',
      source: null, target: null, condition: null,
      evidence: { page: 4, text: 'Makeup exams require a documented, university-excused absence.', confidence: 1.0 },
    },
  ],
  warnings: [],
}

// field values below use the real backend shapes (reconciliation.py): a
// per-rule-instance index for non_deterministic_grading_rule (rules[1] is
// the curve rule, index 1 in EXTRACTED_MODEL.rules), and the letter pair
// for overlapping_grade_thresholds. Messages are the real backend message
// templates, not placeholders -- this is what findingCopy()'s per-code
// templates in GradeCalculatorPanel.tsx actually parse.
const RECONCILIATION_REVIEW = {
  status: 'needs_student_review',
  findings: [
    { code: 'possible_curve', severity: 'warning', message: 'possible curve', field: null },
    {
      code: 'non_deterministic_grading_rule', severity: 'warning',
      message: 'curve rule is not structured precisely enough to apply deterministically: Grades may be curved upward.',
      field: 'rules[1]',
    },
    {
      code: 'overlapping_grade_thresholds', severity: 'error',
      message: "thresholds 'B' (80-89) and 'B+' (85-92) overlap",
      field: 'B,B+',
    },
  ],
  evidence_coverage: { total_claims: 6, supported_claims: 6, coverage_ratio: 1, unsupported_claims: [] },
}

const RECONCILIATION_ACCEPTED = {
  status: 'accepted',
  findings: [{ code: 'category_weight_validation', severity: 'valid', message: 'category weights sum to 100.0', field: 'categories' }],
  evidence_coverage: { total_claims: 5, supported_claims: 5, coverage_ratio: 1, unsupported_claims: [] },
}

function detail(overrides = {}) {
  return {
    id: PROFILE_ID,
    course: { institution: 'tamu', course_code: 'PHYS 207', term: 'Fall 2026', section: '529' },
    review_state: 'needs_review',
    calculator_ready: false,
    current_revision: { id: 'rev-1', source_filename: 'syllabus.pdf', source_page_count: 2, reconciliation_status: 'needs_student_review', confirmed_reconciliation_status: null, confirmed_at: null, created_at: '2026-01-01T00:00:00Z' },
    extracted_grade_model: EXTRACTED_MODEL,
    confirmed_grade_model: null,
    reconciliation: RECONCILIATION_REVIEW,
    confirmed_reconciliation: null,
    corrections: [],
    clarifying_answers: {},
    cutoff_overlap_resolution: { schema_version: '1', resolved: [], unresolved: [] },
    grade_state: null,
    grade_state_revision: null,
    possible_duplicate_profiles: [],
    revision_created: true,
    ...overrides,
  }
}

function readBody(request) {
  return new Promise((resolve) => {
    const chunks = []
    request.on('data', (chunk) => chunks.push(chunk))
    request.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
  })
}

function json(response, status, body) {
  response.statusCode = status
  response.setHeader('content-type', 'application/json')
  response.end(JSON.stringify(body))
}

test('Grade Calculator: empty state, upload, review, confirm, grade entry, save & calculate', { timeout: 45_000 }, async (t) => {
  // term id 'term-2' deliberately matches authenticatedDashboardPreview.tsx's
  // ?currentTerm=inprogress fixture (CS 221 / MATH 251, both in_progress),
  // so the eligible-course dropdown genuinely merges two sources under one
  // term: in-progress courses from the `courses` prop (CS 221, MATH 251)
  // and planned courses from this mock (PHYS 207) -- not just the latter.
  const planning = planningRoutes({
    terms: [{ key: '2026-Fall', id: 'term-2', label: 'Fall 2026', year: 2026, season: 'Fall', sequence: 1, start_date: '2026-08-24', end_date: '2026-12-10', enrolled: false, is_upcoming: true }],
    upcomingTermKey: '2026-Fall',
    state: { planned: [{ id: 'planned-phys', term_id: 'term-2', course_code: 'PHYS 207', title: 'Electricity and Magnetism', credit_hours: 4, catalog_course_id: null, created_at: null, kind: 'planned' }] },
  })
  let state = 'empty' // empty -> reviewing -> corrected -> confirmed
  let capturedIngestBody = null
  let capturedGradeStateBody = null

  const apiPlugin = {
    name: 'grade-calculator-api',
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/requirement-satisfaction') return json(response, 404, { detail: 'Not found.' })
        if (path?.startsWith('/api/v2/student/me/analysis-cache/')) return json(response, 404, { detail: 'Not found.' })

        if (path === '/api/v2/student/me/syllabus-grade-profiles' && request.method === 'GET') {
          return json(response, 200, { syllabus_grade_profiles: [] })
        }
        if (path === '/api/v2/student/me/syllabus-grade-profiles/ingest' && request.method === 'POST') {
          // Captured (not asserted here): an assertion failure thrown inside
          // this middleware would reject the in-flight upload request rather
          // than fail the test cleanly. Asserted after the upload completes.
          capturedIngestBody = await readBody(request)
          state = 'reviewing'
          return json(response, 200, detail())
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && request.method === 'POST') {
          await readBody(request)
          state = 'corrected'
          return json(response, 200, detail({
            confirmed_reconciliation: RECONCILIATION_ACCEPTED,
            current_revision: { ...detail().current_revision, confirmed_reconciliation_status: 'accepted' },
          }))
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/confirm` && request.method === 'POST') {
          state = 'confirmed'
          return json(response, 200, detail({
            review_state: 'confirmed',
            calculator_ready: true,
            confirmed_grade_model: CONFIRMED_MODEL,
            confirmed_reconciliation: RECONCILIATION_ACCEPTED,
            current_revision: { ...detail().current_revision, confirmed_reconciliation_status: 'accepted', confirmed_at: '2026-01-01T00:00:00Z' },
          }))
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && request.method === 'GET') {
          if (state === 'confirmed') {
            return json(response, 200, detail({
              review_state: 'confirmed', calculator_ready: true,
              confirmed_grade_model: CONFIRMED_MODEL, confirmed_reconciliation: RECONCILIATION_ACCEPTED,
            }))
          }
          return json(response, 200, detail())
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/grade-state` && request.method === 'PUT') {
          const body = JSON.parse(await readBody(request))
          capturedGradeStateBody = body
          return json(response, 200, { revision: 1, category_scores: body.category_scores, assessment_scores: body.assessment_scores })
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/calculate` && request.method === 'POST') {
          await readBody(request)
          return json(response, 200, {
            grading_method: 'weighted',
            components: [],
            completed_weight: 50.0,
            earned_course_percentage: 40.7,
            current_grade: 81.4,
            projected_grade: null,
            current_letter_grade: null,
            projected_letter_grade: null,
            applied_rules: [],
            warnings: [],
          })
        }
        next()
      })
    },
  }

  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-grade-calculator', import.meta.url).pathname,
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const origin = `http://127.0.0.1:${address.port}`

  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete&currentTerm=inprogress`)

  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Grade Calculator', exact: true }).click()

  // --- empty state ---
  await page.getByText('See what you need to reach your target grade').waitFor()
  assert.equal(await page.locator('.grade-calculator-panel [role="alert"]').count(), 0)
  assert.equal(await page.getByText('Not Found', { exact: true }).count(), 0)
  await page.getByRole('button', { name: 'Upload syllabus' }).click()

  // --- upload ---
  await page.setInputFiles('#syllabus-file', {
    name: 'syllabus.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 fake'),
  })
  await page.selectOption('#syllabus-term', { label: 'Fall 2026' })
  // --- the course dropdown genuinely merges eligibleCoursesByTerm from two
  //     sources for this term: CS 221 comes ONLY from the `courses` prop
  //     (an in_progress course, via ?currentTerm=inprogress), not from the
  //     fetchPlannedCourses mock -- proving the prop is actually wired in,
  //     not just passed through unused ---
  const courseOptionsText = await page.locator('#syllabus-course-code option').allTextContents()
  assert.ok(courseOptionsText.some((t) => t.includes('CS 221')), 'in_progress course from the courses prop must be selectable')
  assert.ok(courseOptionsText.some((t) => t.includes('PHYS 207')), 'planned course must still be selectable alongside it')
  await page.selectOption('#syllabus-course-code', 'PHYS 207')
  await page.getByRole('button', { name: 'Upload syllabus' }).click()

  // --- institutionName actually reaches the ingest request body, not just
  //     the component's own props ---
  await page.getByRole('heading', { name: 'Needs your review' }).waitFor()
  assert.ok(capturedIngestBody, 'ingest request body was captured')
  assert.match(capturedIngestBody, /name="institution"\r\n\r\nTexas A&M University\r\n/)

  // --- review-required state: the curve rule still lists under "Special
  //     grading rules" with its can't-calculate note, but the rule-based
  //     findings (non_deterministic_grading_rule, possible_curve) no longer
  //     appear in the review list -- they're informational now ---
  await page.getByText("The syllabus does not provide enough information").waitFor()

  // --- the old flat findings list is gone entirely ---
  assert.equal(await page.locator('.grade-findings-list').count(), 0)
  assert.equal(await page.locator('.grade-finding').count(), 0)

  const reviewCard = page.locator('.grade-review-card')
  // rule-informational findings are filtered out of the review list
  assert.equal(await reviewCard.locator('[data-finding-code="non_deterministic_grading_rule"]').count(), 0)
  assert.equal(await reviewCard.locator('[data-finding-code="possible_curve"]').count(), 0)
  assert.equal(await reviewCard.getByText('Your syllabus says grades may be curved').count(), 0)
  assert.equal(await reviewCard.getByText("CampusIQ can't calculate this curve rule automatically").count(), 0)
  // no inline finding on any rule card anymore
  assert.equal(await page.locator('.grade-rule-card .grade-inline-finding').count(), 0)
  // the "Ignore this rule for What-If calculations" button is gone
  assert.equal(await page.getByRole('button', { name: 'Ignore this rule for What-If calculations' }).count(), 0)

  // --- the grading breakdown no longer shows a per-category assessment
  //     count: it was never a blocker and it's meaningless to a student
  //     entering one average per category ---
  const breakdown = page.locator('[aria-label="Grading breakdown"]')
  await breakdown.waitFor()
  assert.equal(await breakdown.getByText('Number of assessments: Unknown').count(), 0)
  assert.equal(await breakdown.getByText(/\d+ assessments/).count(), 0)

  // --- overlapping_grade_thresholds is NOT reclassified: it still shows in
  //     the General section at the top of the review card, with the real
  //     letters/ranges ---
  const general = page.locator('.grade-inline-findings--general')
  await general.getByText('Letter grades B and B+ have overlapping cutoffs: B is 80–89, B+ is 85–92.').waitFor()

  // --- dismiss is session-only: dismissing the threshold finding hides it
  //     immediately, with no network call, and it comes back on reopen ---
  const thresholdFinding = general.locator('.grade-inline-finding', { hasText: 'overlapping cutoffs' })
  await thresholdFinding.getByRole('button', { name: 'Dismiss this finding' }).click()
  assert.equal(await general.getByText('overlapping cutoffs').count(), 0)

  await page.getByRole('button', { name: '← Back to your calculators' }).click()
  await page.locator('.grade-card', { hasText: 'PHYS 207' }).click()
  await page.getByRole('heading', { name: 'Needs your review' }).waitFor()
  // reopening re-fetched the same findings and dismissal did not persist
  await page.locator('.grade-inline-findings--general').getByText('overlapping cutoffs').waitFor()

  // --- confirm straight from review; rules no longer gate calculator_ready ---
  await page.getByRole('button', { name: 'Confirm' }).click()

  // --- grade entry ---
  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()

  // --- Professor's rules panel: persistent beside the calculator, fed
  //     from the grade model's rules[] (not findings). Every informational
  //     rule type renders with its label, text and page provenance; the
  //     deterministic replacement rule does NOT appear here; there is no
  //     dismiss / ignore control. ---
  const rulesPanel = page.locator('[data-testid="professors-rules"]')
  await rulesPanel.getByRole('heading', { name: "Professor's rules" }).waitFor()
  await rulesPanel.getByText('Grades may be curved upward.').waitFor()
  await rulesPanel.getByText('No late homework will be accepted.').waitFor()
  await rulesPanel.getByText('Makeup exams require a documented, university-excused absence.').waitFor()
  await rulesPanel.getByText('Curve', { exact: true }).waitFor()
  await rulesPanel.getByText('Late work', { exact: true }).waitFor()
  await rulesPanel.getByText('Makeup work', { exact: true }).waitFor()
  await rulesPanel.getByText('Source: page 3').waitFor()
  await rulesPanel.getByText('Source: page 4').waitFor()
  assert.equal(await rulesPanel.getByText('Score replacement').count(), 0, 'deterministic replacement rule must not appear in Professor\'s rules')
  assert.equal(await rulesPanel.getByText(/replaces Midterm/).count(), 0)
  assert.equal(await rulesPanel.getByRole('button').count(), 0, 'Professor\'s rules panel has no dismiss / ignore control')

  // --- Side-by-side layout: the calculator cards and the Professor's rules
  //     panel share one grid wrapper (.grade-calculator-layout), with the
  //     cards in .grade-calculator-main and the rules panel in
  //     .grade-calculator-aside. ---
  const layout = page.locator('.grade-calculator-layout')
  await layout.waitFor()
  await layout.locator('.grade-calculator-main').getByRole('heading', { name: 'Enter your grades' }).waitFor()
  await layout.locator('.grade-calculator-aside [data-testid="professors-rules"]').waitFor()

  await page.fill('#actual-category\\:Mid-term\\ Exam', '78')
  await page.fill('#actual-category\\:Lecture\\ Quizzes', '92')
  await page.fill('#actual-category\\:Recitation\\ Quizzes', '88')

  // --- one button now persists the actuals AND returns the calculation:
  //     the per-category averages the student typed are what gets persisted
  //     as category_scores[].actual_score (no per-assessment breakdown), and
  //     the result card renders from the /calculate response ---
  await page.getByRole('button', { name: 'Save & calculate' }).click()
  await page.getByText('81.4%').waitFor()
  await page.getByText('Based on 50% of the course completed').waitFor()
  await page.waitForFunction(() => !document.querySelector('button[aria-busy="true"]'))
  assert.ok(capturedGradeStateBody, 'Save & calculate sent a grade-state PUT')
  assert.deepEqual(
    [...capturedGradeStateBody.category_scores].sort((a, b) => a.category_name.localeCompare(b.category_name)),
    [
      { category_name: 'Lecture Quizzes', actual_score: 92 },
      { category_name: 'Mid-term Exam', actual_score: 78 },
      { category_name: 'Recitation Quizzes', actual_score: 88 },
    ],
  )
  assert.deepEqual(capturedGradeStateBody.assessment_scores, [])

  // --- the Target Grade card is gone entirely ---
  assert.equal(await page.locator('#target-component').count(), 0)
  assert.equal(await page.locator('#target-numeric').count(), 0)
  assert.equal(await page.getByRole('button', { name: 'Solve' }).count(), 0)

  // --- responsive: no horizontal overflow ---
  for (const width of [390, 834, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
      true,
      `horizontal overflow at ${width}px`,
    )
  }
})

test('Grade Calculator replaces a framework 404 with friendly list-load copy', { timeout: 30_000 }, async (t) => {
  const planning = planningRoutes({ terms: [] })
  const apiPlugin = {
    name: 'grade-calculator-list-error',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/requirement-satisfaction') return json(response, 404, { detail: 'Not found.' })
        if (path?.startsWith('/api/v2/student/me/analysis-cache/')) return json(response, 404, { detail: 'Not found.' })
        if (path === '/api/v2/student/me/syllabus-grade-profiles' && request.method === 'GET') {
          return json(response, 404, { detail: 'Not Found' })
        }
        next()
      })
    },
  }
  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-grade-calculator-list-error', import.meta.url).pathname,
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()
  await page.goto(`http://127.0.0.1:${address.port}/authenticated-dashboard-preview.html?mode=complete`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Grade Calculator', exact: true }).click()
  await page.getByRole('alert').getByText("We couldn't load your saved grade calculators. Try again.").waitFor()
  assert.equal(await page.getByText('Not Found', { exact: true }).count(), 0)
})

test('Grade Calculator: remove a calculator from the list (confirm-gated soft delete)', { timeout: 30_000 }, async (t) => {
  const planning = planningRoutes({ terms: [] })
  const PROFILE = {
    id: PROFILE_ID, institution: 'tamu', course_code: 'ECEN 248', term: 'Fall 2026', section: '501',
    review_state: 'needs_review', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    calculator_ready: false, current_grade: null,
  }
  let listRows = [PROFILE]
  let deleteCount = 0

  const apiPlugin = {
    name: 'grade-calculator-remove',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/requirement-satisfaction') return json(response, 404, { detail: 'Not found.' })
        if (path?.startsWith('/api/v2/student/me/analysis-cache/')) return json(response, 404, { detail: 'Not found.' })
        if (path === '/api/v2/student/me/syllabus-grade-profiles' && request.method === 'GET') {
          return json(response, 200, { syllabus_grade_profiles: listRows })
        }
        if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && request.method === 'DELETE') {
          deleteCount += 1
          listRows = []
          return json(response, 200, { removed: PROFILE_ID })
        }
        next()
      })
    },
  }
  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-grade-calculator-remove', import.meta.url).pathname,
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()
  await page.goto(`http://127.0.0.1:${address.port}/authenticated-dashboard-preview.html?mode=complete`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Grade Calculator', exact: true }).click()

  const row = page.locator('.grade-card-wrap', { hasText: 'ECEN 248' })
  await row.waitFor()
  const removeButton = row.getByRole('button', { name: /Remove grade calculator for ECEN 248/ })

  // --- cancelling the confirm does nothing ---
  page.once('dialog', (d) => d.dismiss())
  await removeButton.click()
  await page.waitForTimeout(100)
  assert.equal(deleteCount, 0, 'dismissing the confirm must not call DELETE')
  await row.waitFor()

  // --- accepting the confirm removes the row ---
  page.once('dialog', (d) => {
    assert.match(d.message(), /Remove the grade calculator for ECEN 248\?/)
    d.accept()
  })
  await removeButton.click()

  await page.locator('.grade-card-wrap', { hasText: 'ECEN 248' }).waitFor({ state: 'detached' })
  assert.equal(deleteCount, 1, 'accepting the confirm calls DELETE exactly once')
  await page.getByText('See what you need to reach your target grade').waitFor()
})

// --- cutoff-overlap clarifying questions -----------------------------------------

const CUTOFF_MODEL = {
  ...EXTRACTED_MODEL,
  grade_thresholds: [
    { letter: 'A', minimum: 91, maximum: 100, evidence: { page: 2, text: 'A: 91-100', confidence: 1.0 } },
    { letter: 'B', minimum: 80, maximum: 90, evidence: { page: 2, text: 'B: 80-90', confidence: 1.0 } },
    { letter: 'C', minimum: 70, maximum: 80, evidence: { page: 2, text: 'C: 70-80', confidence: 1.0 } },
  ],
  rules: [],
  warnings: [],
}

const RECONCILIATION_BC_OVERLAP = {
  status: 'needs_student_review',
  findings: [
    { code: 'overlapping_grade_thresholds', severity: 'error', message: "thresholds 'B' (80-90) and 'C' (70-80) overlap", field: 'B,C' },
  ],
  evidence_coverage: { total_claims: 5, supported_claims: 5, coverage_ratio: 1, unsupported_claims: [] },
}
const RESOLUTION_BC = { schema_version: '1', resolved: [{ letters: ['B', 'C'], boundary: 80, winner: 'B', loser: 'C' }], unresolved: [] }

// Boot the panel with a middleware `handle(path, method, request, response)`
// that returns true when it answered. Navigates into the single profile.
async function mountCutoffPanel(t, cacheKey, handle) {
  const planning = planningRoutes({ terms: [] })
  const apiPlugin = {
    name: cacheKey,
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/requirement-satisfaction') return json(response, 404, { detail: 'Not found.' })
        if (path?.startsWith('/api/v2/student/me/analysis-cache/')) return json(response, 404, { detail: 'Not found.' })
        if (path === '/api/v2/student/me/syllabus-grade-profiles' && request.method === 'GET') {
          return json(response, 200, { syllabus_grade_profiles: [{ id: PROFILE_ID, institution: 'tamu', course_code: 'PHYS 207', term: 'Fall 2026', section: '529', review_state: 'needs_review', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', calculator_ready: false, current_grade: null }] })
        }
        if (await handle(path, request.method, request, response)) return undefined
        next()
      })
    },
  }
  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL(`../node_modules/.vite-${cacheKey}`, import.meta.url).pathname,
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()
  await page.goto(`http://127.0.0.1:${address.port}/authenticated-dashboard-preview.html?mode=complete`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Grade Calculator', exact: true }).click()
  await page.locator('.grade-card', { hasText: 'PHYS 207' }).click()
  return page
}

test('Grade Calculator: cutoff-overlap question — propose, confirm, unblock', { timeout: 45_000 }, async (t) => {
  let confirmed = false
  let correctionBody = null
  const page = await mountCutoffPanel(t, 'grade-calculator-cutoff-confirm', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: CUTOFF_MODEL, reconciliation: RECONCILIATION_BC_OVERLAP, cutoff_overlap_resolution: RESOLUTION_BC }))
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && method === 'POST') {
      correctionBody = JSON.parse(await readBody(request))
      confirmed = true
      json(response, 200, detail({
        extracted_grade_model: CUTOFF_MODEL,
        confirmed_grade_model: CUTOFF_MODEL,
        calculator_ready: true,
        review_state: 'needs_review',
        reconciliation: RECONCILIATION_BC_OVERLAP,
        confirmed_reconciliation: RECONCILIATION_ACCEPTED,
        corrections: correctionBody.corrections,
        clarifying_answers: { 'cutoff_overlap:B,C': { answer: 'confirm_default', boundary: 80, winner: 'B', loser: 'C' } },
        cutoff_overlap_resolution: RESOLUTION_BC,
      }))
      return true
    }
    return false
  })

  // the table renders one row per grade threshold with current values
  await page.locator('[data-testid="cutoff-table"]').waitFor()
  assert.equal(await page.inputValue('#cutoff-A-min'), '91')
  assert.equal(await page.inputValue('#cutoff-A-max'), '100')
  assert.equal(await page.inputValue('#cutoff-B-min'), '80')
  assert.equal(await page.inputValue('#cutoff-C-max'), '80')

  // the resolvable overlap renders as a cross-row banner with ranges from
  // grade_thresholds and the "higher grade wins" default
  const banner = page.locator('.grade-cutoff-banner[data-cutoff-pair="B,C"]')
  await banner.getByText(/Your syllabus lists B as 80–90 and C as 70–80/).waitFor()
  await banner.getByText(/80 is B, not C\. Sound right\?/).waitFor()
  // the raw overlapping_grade_thresholds finding is NOT also shown for a resolvable pair
  assert.equal(await page.locator('.grade-inline-findings--general').getByText(/overlapping cutoffs/).count(), 0)

  await banner.getByRole('button', { name: "Yes, that's right" }).click()
  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()

  assert.ok(confirmed)
  assert.deepEqual(correctionBody.corrections, [
    { target_type: 'threshold', operation: 'resolve_cutoff_overlap', threshold_letter: 'B' },
  ])
  // banner gone once answered
  assert.equal(await page.locator('.grade-cutoff-banner[data-cutoff-pair="B,C"]').count(), 0)
})

test('Grade Calculator: unresolved overlap shows only a note; an inline row edit saves set_max + auto-appended confirm_threshold_value', { timeout: 45_000 }, async (t) => {
  let corrections = []
  const RESOLUTION_MIXED = {
    schema_version: '1',
    resolved: [{ letters: ['B', 'C'], boundary: 80, winner: 'B', loser: 'C' }],
    unresolved: [{ letters: ['A', 'C'], reason: 'non_adjacent_letters' }],
  }
  const RECON_MIXED = {
    status: 'needs_student_review',
    findings: [
      { code: 'overlapping_grade_thresholds', severity: 'error', message: "thresholds 'B' (80-90) and 'C' (70-80) overlap", field: 'B,C' },
      { code: 'overlapping_grade_thresholds', severity: 'error', message: "thresholds 'A' (75-100) and 'C' (70-80) overlap", field: 'A,C' },
    ],
    evidence_coverage: { total_claims: 5, supported_claims: 5, coverage_ratio: 1, unsupported_claims: [] },
  }
  // C's evidence range (70-80) still disagrees with the narrowed max (79)
  // after the edit -> a residual claim_evidence finding WOULD exist, so the
  // auto-appended confirm_threshold_value has something to suppress. (The
  // no-residual-finding case is covered by the backend test suite.)
  const model = { ...CUTOFF_MODEL, grade_thresholds: [
    { letter: 'A', minimum: 75, maximum: 100, evidence: null },
    { letter: 'B', minimum: 80, maximum: 90, evidence: null },
    { letter: 'C', minimum: 70, maximum: 80, evidence: { page: 2, text: 'C: 70-80', confidence: 1.0 } },
  ] }
  const page = await mountCutoffPanel(t, 'grade-calculator-cutoff-manual', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: model, reconciliation: RECON_MIXED, cutoff_overlap_resolution: RESOLUTION_MIXED }))
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && method === 'POST') {
      corrections = JSON.parse(await readBody(request)).corrections
      json(response, 200, detail({
        extracted_grade_model: model, confirmed_grade_model: model, calculator_ready: true,
        reconciliation: RECON_MIXED, confirmed_reconciliation: RECONCILIATION_ACCEPTED,
        corrections, cutoff_overlap_resolution: RESOLUTION_MIXED,
      }))
      return true
    }
    return false
  })

  // A/C is unresolved: only a note (no "Sound right?" proposal, no action
  // button), and its raw finding stays in the general review list.
  const unresolved = page.locator('.grade-cutoff-banner[data-cutoff-pair="A,C"]')
  await unresolved.getByText(/cutoffs for A and C overlap and CampusIQ can't pick a safe default/).waitFor()
  assert.equal(await unresolved.getByText(/Sound right\?/).count(), 0)
  assert.equal(await unresolved.getByRole('button').count(), 0)
  await page.locator('.grade-inline-findings--general').getByText("Letter grades A and C have overlapping cutoffs: A is 75–100, C is 70–80.").waitFor()

  // edit C's max in place; the row-level "Save cutoffs" appears once dirty
  await page.fill('#cutoff-C-max', '79')
  await page.getByRole('button', { name: 'Save cutoffs' }).click()
  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()
  assert.deepEqual(corrections, [
    { target_type: 'threshold', operation: 'set_maximum', threshold_letter: 'C', value: 79 },
    { target_type: 'threshold', operation: 'confirm_threshold_value', threshold_letter: 'C' },
  ])
})

test('Grade Calculator: an answered cutoff shows resolved and does not re-ask on reload', { timeout: 45_000 }, async (t) => {
  // Answered, but still in review because one unrelated finding blocks -- so
  // the clarifying-questions section stays on screen.
  const answered = detail({
    extracted_grade_model: CUTOFF_MODEL,
    reconciliation: RECONCILIATION_BC_OVERLAP,
    confirmed_grade_model: CUTOFF_MODEL,
    calculator_ready: false,
    corrections: [{ target_type: 'threshold', operation: 'resolve_cutoff_overlap', threshold_letter: 'B' }],
    clarifying_answers: { 'cutoff_overlap:B,C': { answer: 'confirm_default', boundary: 80, winner: 'B', loser: 'C' } },
    cutoff_overlap_resolution: RESOLUTION_BC,
    confirmed_reconciliation: {
      status: 'needs_student_review',
      findings: [{ code: 'grading_method_unknown', severity: 'warning', message: 'x', field: 'grading_method' }],
      evidence_coverage: RECONCILIATION_ACCEPTED.evidence_coverage,
    },
  })

  const page = await mountCutoffPanel(t, 'grade-calculator-cutoff-answered', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, answered)
      return true
    }
    return false
  })

  await page.locator('.grade-cutoff-resolved[data-cutoff-pair="B,C"]').getByText('80 counts as B, not C').waitFor()
  assert.equal(await page.locator('.grade-cutoff-banner[data-cutoff-pair="B,C"]').count(), 0)

  // navigate away and back — still resolved, still no banner
  await page.getByRole('button', { name: '← Back to your calculators' }).click()
  await page.locator('.grade-card', { hasText: 'PHYS 207' }).click()
  await page.locator('.grade-cutoff-resolved[data-cutoff-pair="B,C"]').waitFor()
  assert.equal(await page.locator('.grade-cutoff-banner[data-cutoff-pair="B,C"]').count(), 0)
})

test('Grade Calculator: non-blocking informational findings are filtered from the review list', { timeout: 45_000 }, async (t) => {
  const model = { ...EXTRACTED_MODEL, grade_thresholds: [], rules: [], warnings: [] }
  const recon = {
    status: 'needs_student_review',
    findings: [
      // non-blocking, no correction path -> must NOT show in the review list
      { code: 'unknown_assessment_count', severity: 'warning', message: 'The exact number of Lecture Quizzes is unknown.', field: 'Lecture Quizzes' },
      // genuinely blocking -> must still show
      { code: 'grading_method_unknown', severity: 'warning', message: 'grading_method could not be determined from the syllabus', field: 'grading_method' },
    ],
    evidence_coverage: { total_claims: 4, supported_claims: 4, coverage_ratio: 1, unsupported_claims: [] },
  }
  const page = await mountCutoffPanel(t, 'grade-calculator-nonblocking-filter', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: model, reconciliation: recon }))
      return true
    }
    return false
  })

  await page.getByRole('heading', { name: 'Needs your review' }).waitFor()
  // the blocking finding is still shown, so the review list isn't just empty
  assert.ok((await page.locator('[data-finding-code="grading_method_unknown"]').count()) >= 1)
  // unknown_assessment_count is filtered out entirely
  assert.equal(await page.locator('[data-finding-code="unknown_assessment_count"]').count(), 0)
  assert.equal(await page.getByText("doesn't say exactly how many assessments are in this category").count(), 0)
})

test('Grade Calculator: missing_grade_scale shows in the review list; no letter-target UI remains in the ready calculator', { timeout: 45_000 }, async (t) => {
  const NO_SCALE_MODEL = { ...EXTRACTED_MODEL, grade_thresholds: [], rules: [], warnings: [] }
  const REVIEW_RECON = {
    status: 'needs_student_review',
    findings: [
      // the Target Grade card that used to explain this is gone, so the
      // finding is no longer filtered -- it flows into the review list
      { code: 'missing_grade_scale', severity: 'warning', message: "This syllabus doesn't specify a letter-grade scale.", field: null },
      { code: 'grading_method_unknown', severity: 'warning', message: 'grading_method could not be determined from the syllabus', field: 'grading_method' },
    ],
    evidence_coverage: { total_claims: 4, supported_claims: 4, coverage_ratio: 1, unsupported_claims: [] },
  }

  // phase drives which detail payload the GET returns:
  //   'review'         -> not ready, review list on screen
  //   'ready-noscale'  -> ready, confirmed model has no grade_thresholds
  //   'ready-withscale'-> ready, confirmed model has grade_thresholds
  let phase = 'review'
  const readyDetail = (thresholds) => detail({
    review_state: 'confirmed',
    calculator_ready: true,
    extracted_grade_model: { ...NO_SCALE_MODEL, grade_thresholds: thresholds },
    confirmed_grade_model: { ...NO_SCALE_MODEL, grade_thresholds: thresholds },
    reconciliation: RECONCILIATION_ACCEPTED,
    confirmed_reconciliation: RECONCILIATION_ACCEPTED,
  })

  const page = await mountCutoffPanel(t, 'grade-calculator-missing-scale-in-review', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      if (phase === 'review') json(response, 200, detail({ extracted_grade_model: NO_SCALE_MODEL, reconciliation: REVIEW_RECON }))
      else if (phase === 'ready-noscale') json(response, 200, readyDetail([]))
      else json(response, 200, readyDetail(CUTOFF_MODEL.grade_thresholds))
      return true
    }
    return false
  })

  // --- the finding now appears in the review list (no relocation target) ---
  await page.getByRole('heading', { name: 'Needs your review' }).waitFor()
  assert.ok((await page.locator('[data-finding-code="grading_method_unknown"]').count()) >= 1)
  assert.ok((await page.locator('[data-finding-code="missing_grade_scale"]').count()) >= 1)
  await page.getByText("doesn't specify a letter-grade scale").waitFor()
  // the old target-card note never existed here and still doesn't
  assert.equal(await page.locator('.grade-no-scale-note').count(), 0)

  // --- ready calculator: no Target Grade card, with OR without a grade scale ---
  for (const p of ['ready-noscale', 'ready-withscale']) {
    phase = p
    await page.getByRole('button', { name: '← Back to your calculators' }).click()
    await page.locator('.grade-card', { hasText: 'PHYS 207' }).click()
    await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()
    assert.equal(await page.locator('#target-letter').count(), 0, `${p}: no target-letter select`)
    assert.equal(await page.locator('#target-component').count(), 0, `${p}: no target-component select`)
    assert.equal(await page.locator('.grade-no-scale-note').count(), 0, `${p}: no no-scale note`)
    assert.equal(await page.getByRole('button', { name: 'Solve' }).count(), 0, `${p}: no Solve button`)
  }
})

// --- per-threshold value-claim clarifying questions ------------------------------

// One otherwise-clean threshold whose evidence uses ">= / <" phrasing the
// backend range check cannot parse -> one claim_evidence_consistency_
// unverifiable finding, which is the only blocker.
const VALUE_CLAIM_MODEL = {
  ...EXTRACTED_MODEL,
  grade_thresholds: [
    { letter: 'A', minimum: 90, maximum: 100, evidence: { page: 2, text: 'A: 90-100', confidence: 1.0 } },
    { letter: 'B', minimum: 80, maximum: 89, evidence: { page: 2, text: 'B: >= 80% and < 90%', confidence: 1.0 } },
  ],
  rules: [],
  warnings: [],
}

const RECONCILIATION_B_UNVERIFIABLE = {
  status: 'needs_student_review',
  findings: [
    { code: 'category_weight_validation', severity: 'valid', message: 'category weights sum to 100.0', field: 'categories' },
    {
      code: 'claim_evidence_consistency_unverifiable',
      severity: 'warning',
      message: "could not deterministically verify threshold:B against its cited evidence text ('B: >= 80% and < 90%')",
      field: 'threshold:B',
    },
  ],
  evidence_coverage: { total_claims: 5, supported_claims: 5, coverage_ratio: 1, unsupported_claims: [] },
}

test('Grade Calculator: threshold value-claim question — affirm, unblock', { timeout: 45_000 }, async (t) => {
  let correctionBody = null
  const page = await mountCutoffPanel(t, 'grade-calculator-value-claim-confirm', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: VALUE_CLAIM_MODEL, reconciliation: RECONCILIATION_B_UNVERIFIABLE }))
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && method === 'POST') {
      correctionBody = JSON.parse(await readBody(request))
      json(response, 200, detail({
        extracted_grade_model: VALUE_CLAIM_MODEL,
        confirmed_grade_model: VALUE_CLAIM_MODEL,
        calculator_ready: true,
        reconciliation: RECONCILIATION_B_UNVERIFIABLE,
        confirmed_reconciliation: RECONCILIATION_ACCEPTED,
        corrections: correctionBody.corrections,
        clarifying_answers: { 'claim_evidence:threshold:b': { answer: 'confirm_value', letter: 'b' } },
      }))
      return true
    }
    return false
  })

  const row = page.locator('.grade-cutoff-row[data-threshold-letter="B"]')
  // Q2: the actual cutoff value is visible on the row, not just generic copy
  assert.equal(await page.inputValue('#cutoff-B-min'), '80')
  assert.equal(await page.inputValue('#cutoff-B-max'), '89')
  await row.getByText(/B: 80–89 — we couldn't confirm this against your syllabus/).waitFor()
  // the raw claim-evidence finding is NOT also shown as a bare review note
  assert.equal(await page.locator('.grade-inline-findings--general').getByText(/couldn't automatically confirm this value/).count(), 0)

  await row.getByRole('button', { name: "Yes, that's correct" }).click()
  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()

  assert.deepEqual(correctionBody.corrections, [
    { target_type: 'threshold', operation: 'confirm_threshold_value', threshold_letter: 'B' },
  ])
  assert.equal(await page.locator('.grade-cutoff-row[data-threshold-letter="B"] .grade-cutoff-row-affirm').count(), 0)
})

test('Grade Calculator: an affirmed threshold value shows confirmed and does not re-ask on reload', { timeout: 45_000 }, async (t) => {
  const answered = detail({
    extracted_grade_model: VALUE_CLAIM_MODEL,
    reconciliation: RECONCILIATION_B_UNVERIFIABLE,
    confirmed_grade_model: VALUE_CLAIM_MODEL,
    calculator_ready: false,
    corrections: [{ target_type: 'threshold', operation: 'confirm_threshold_value', threshold_letter: 'B' }],
    clarifying_answers: { 'claim_evidence:threshold:b': { answer: 'confirm_value', letter: 'b' } },
    // re-reconciled: the B finding is suppressed, one unrelated finding still blocks
    confirmed_reconciliation: {
      status: 'needs_student_review',
      findings: [{ code: 'grading_method_unknown', severity: 'warning', message: 'x', field: 'grading_method' }],
      evidence_coverage: RECONCILIATION_ACCEPTED.evidence_coverage,
    },
  })

  const page = await mountCutoffPanel(t, 'grade-calculator-value-claim-answered', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, answered)
      return true
    }
    return false
  })

  await page.locator('.grade-cutoff-resolved[data-threshold-letter="B"]').getByText('B cutoff confirmed as correct').waitFor()
  assert.equal(await page.locator('.grade-cutoff-row[data-threshold-letter="B"] .grade-cutoff-row-affirm').count(), 0)

  await page.getByRole('button', { name: '← Back to your calculators' }).click()
  await page.locator('.grade-card', { hasText: 'PHYS 207' }).click()
  await page.locator('.grade-cutoff-resolved[data-threshold-letter="B"]').waitFor()
  assert.equal(await page.locator('.grade-cutoff-row[data-threshold-letter="B"] .grade-cutoff-row-affirm').count(), 0)
})

// --- unified cutoff table: full-scale rendering + ECEN 248-style unblock --------

const AF_MODEL = {
  ...EXTRACTED_MODEL,
  grade_thresholds: [
    { letter: 'A', minimum: 90, maximum: 100, evidence: { page: 2, text: 'A: at least 90%', confidence: 1.0 } },
    { letter: 'B', minimum: 80, maximum: 89, evidence: { page: 2, text: 'B: >= 80% and < 90%', confidence: 1.0 } },
    { letter: 'C', minimum: 70, maximum: 79, evidence: { page: 2, text: 'C: >= 70% and < 80%', confidence: 1.0 } },
    { letter: 'D', minimum: 60, maximum: 69, evidence: { page: 2, text: 'D: >= 60% and < 70%', confidence: 1.0 } },
    { letter: 'F', minimum: 0, maximum: 59, evidence: { page: 2, text: 'F: below 60%', confidence: 1.0 } },
  ],
  rules: [],
  warnings: [],
}

test('Grade Calculator: the cutoff table renders one row per letter grade with its current min–max', { timeout: 45_000 }, async (t) => {
  const recon = {
    status: 'needs_student_review',
    findings: [{ code: 'grading_method_unknown', severity: 'warning', message: 'x', field: 'grading_method' }],
    evidence_coverage: { total_claims: 5, supported_claims: 5, coverage_ratio: 1, unsupported_claims: [] },
  }
  const page = await mountCutoffPanel(t, 'grade-calculator-cutoff-table-render', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: AF_MODEL, reconciliation: recon }))
      return true
    }
    return false
  })

  await page.locator('[data-testid="cutoff-table"]').waitFor()
  const rows = page.locator('.grade-cutoff-table-rows .grade-cutoff-row[data-threshold-letter]')
  assert.equal(await rows.count(), 5)
  for (const [letter, min, max] of [['A', '90', '100'], ['B', '80', '89'], ['C', '70', '79'], ['D', '60', '69'], ['F', '0', '59']]) {
    assert.equal(await page.inputValue(`#cutoff-${letter}-min`), min, `${letter} minimum`)
    assert.equal(await page.inputValue(`#cutoff-${letter}-max`), max, `${letter} maximum`)
  }

  // no horizontal overflow at any width
  for (const width of [390, 834, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
      true,
      `horizontal overflow at ${width}px`,
    )
  }
})

test('Grade Calculator: affirming every unverified cutoff value in the table clears review and unblocks the calculator', { timeout: 45_000 }, async (t) => {
  // ECEN 248-style: A/B/C each carry an unparseable-evidence finding; the
  // table shows a per-row affirm for each. Affirming the last one clears
  // the re-reconciliation and the calculator becomes ready.
  const OPEN = ['a', 'b', 'c']
  const findingFor = (letter) => ({
    code: 'claim_evidence_consistency_unverifiable',
    severity: 'warning',
    message: `could not deterministically verify threshold:${letter.toUpperCase()} against its cited evidence text ('x')`,
    field: `threshold:${letter.toUpperCase()}`,
  })
  const answers = {}
  const reconWith = () => ({
    status: Object.keys(answers).length >= OPEN.length ? 'accepted' : 'needs_student_review',
    findings: [
      { code: 'category_weight_validation', severity: 'valid', message: 'ok', field: 'categories' },
      ...OPEN.filter((l) => !(`claim_evidence:threshold:${l}` in answers)).map(findingFor),
    ],
    evidence_coverage: { total_claims: 5, supported_claims: 5, coverage_ratio: 1, unsupported_claims: [] },
  })
  const bodyNow = () => detail({
    extracted_grade_model: AF_MODEL,
    confirmed_grade_model: AF_MODEL,
    reconciliation: RECONCILIATION_ACCEPTED,
    confirmed_reconciliation: reconWith(),
    calculator_ready: Object.keys(answers).length >= OPEN.length,
    corrections: Object.keys(answers).map((k) => ({ target_type: 'threshold', operation: 'confirm_threshold_value', threshold_letter: k.slice(-1).toUpperCase() })),
    clarifying_answers: { ...answers },
  })

  const page = await mountCutoffPanel(t, 'grade-calculator-cutoff-table-unblock', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, bodyNow())
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && method === 'POST') {
      const { corrections } = JSON.parse(await readBody(request))
      for (const c of corrections) {
        if (c.operation === 'confirm_threshold_value') {
          const l = c.threshold_letter.toLowerCase()
          answers[`claim_evidence:threshold:${l}`] = { answer: 'confirm_value', letter: l }
        }
      }
      json(response, 200, bodyNow())
      return true
    }
    return false
  })

  await page.locator('[data-testid="cutoff-table"]').waitFor()
  // affirm A then B; each removes only its own row's affirm control
  for (const letter of ['A', 'B']) {
    await page.locator(`.grade-cutoff-row[data-threshold-letter="${letter}"]`)
      .getByRole('button', { name: "Yes, that's correct" }).click()
    await page.waitForFunction(() => !document.querySelector('button[aria-busy="true"]'))
    await page.locator(`.grade-cutoff-resolved[data-threshold-letter="${letter}"]`).waitFor()
  }
  // still in review with C outstanding
  await page.getByRole('heading', { name: /needs your review/i }).waitFor()
  // affirm the last one -> re-reconciliation accepted -> calculator ready
  await page.locator('.grade-cutoff-row[data-threshold-letter="C"]')
    .getByRole('button', { name: "Yes, that's correct" }).click()
  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()
})

// --- re-open cutoff review after calculator_ready ------------------------------

test('Grade Calculator: a ready calculator can re-open cutoff review; editing a cutoff sends it back for re-confirm', { timeout: 45_000 }, async (t) => {
  const CUTOFF_A92 = { ...CUTOFF_MODEL, grade_thresholds: [
    { ...CUTOFF_MODEL.grade_thresholds[0], minimum: 92 },
    CUTOFF_MODEL.grade_thresholds[1],
    CUTOFF_MODEL.grade_thresholds[2],
  ] }
  const readyDetail = () => detail({
    review_state: 'confirmed',
    calculator_ready: true,
    extracted_grade_model: CUTOFF_MODEL,
    confirmed_grade_model: CUTOFF_MODEL,
    reconciliation: RECONCILIATION_ACCEPTED,
    confirmed_reconciliation: RECONCILIATION_ACCEPTED,
  })
  let correctionBody = null
  let reconfirmed = false

  const page = await mountCutoffPanel(t, 'grade-calculator-cutoff-reopen', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, readyDetail())
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && method === 'POST') {
      correctionBody = JSON.parse(await readBody(request))
      // backend reset: an edit against a confirmed profile drops it to
      // reconfirm_required and takes calculator_ready offline
      json(response, 200, detail({
        review_state: 'reconfirm_required',
        calculator_ready: false,
        extracted_grade_model: CUTOFF_MODEL,
        confirmed_grade_model: CUTOFF_A92,
        reconciliation: RECONCILIATION_ACCEPTED,
        confirmed_reconciliation: RECONCILIATION_ACCEPTED,
        corrections: correctionBody.corrections,
      }))
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/confirm` && method === 'POST') {
      reconfirmed = true
      json(response, 200, detail({
        review_state: 'confirmed',
        calculator_ready: true,
        extracted_grade_model: CUTOFF_MODEL,
        confirmed_grade_model: CUTOFF_A92,
        reconciliation: RECONCILIATION_ACCEPTED,
        confirmed_reconciliation: RECONCILIATION_ACCEPTED,
      }))
      return true
    }
    return false
  })

  // ready calculator: the cutoff table is NOT shown, but a discreet re-open
  // control is
  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()
  assert.equal(await page.locator('[data-testid="cutoff-table"]').count(), 0)
  await page.getByRole('button', { name: 'Review letter-grade cutoffs' }).click()

  const table = page.locator('[data-testid="cutoff-table"]')
  await table.waitFor()
  assert.equal(await page.inputValue('#cutoff-A-min'), '91')

  await page.fill('#cutoff-A-min', '92')
  await page.getByRole('button', { name: 'Save cutoffs' }).click()

  // the edit reopens the normal review card (calculator_ready is now false)
  await page.getByRole('heading', { name: 'Still needs your review' }).waitFor()
  assert.deepEqual(correctionBody.corrections, [
    { target_type: 'threshold', operation: 'set_minimum', threshold_letter: 'A', value: 92 },
    { target_type: 'threshold', operation: 'confirm_threshold_value', threshold_letter: 'A' },
  ])

  // an explicit re-confirm restores the ready calculator
  await page.getByRole('button', { name: 'Confirm' }).click()
  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()
  assert.ok(reconfirmed)
})

// --- cross-row edits survive a sibling row's submit (no remount) ---------------

test('Grade Calculator: in-progress edits in other rows survive a sibling row affirm', { timeout: 45_000 }, async (t) => {
  const RECON_C_UNVERIFIABLE = {
    status: 'needs_student_review',
    findings: [
      { code: 'grading_method_unknown', severity: 'warning', message: 'x', field: 'grading_method' },
      {
        code: 'claim_evidence_consistency_unverifiable', severity: 'warning',
        message: "could not deterministically verify threshold:C against its cited evidence text ('x')",
        field: 'threshold:C',
      },
    ],
    evidence_coverage: { total_claims: 5, supported_claims: 5, coverage_ratio: 1, unsupported_claims: [] },
  }
  // C's finding suppressed after the affirm; the unrelated blocker keeps the
  // table on screen so we can inspect the other rows' inputs.
  const RECON_AFTER = {
    status: 'needs_student_review',
    findings: [{ code: 'grading_method_unknown', severity: 'warning', message: 'x', field: 'grading_method' }],
    evidence_coverage: RECON_C_UNVERIFIABLE.evidence_coverage,
  }
  let correctionBody = null

  const page = await mountCutoffPanel(t, 'grade-calculator-cutoff-no-remount', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: AF_MODEL, reconciliation: RECON_C_UNVERIFIABLE }))
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && method === 'POST') {
      correctionBody = JSON.parse(await readBody(request))
      json(response, 200, detail({
        extracted_grade_model: AF_MODEL,
        confirmed_grade_model: AF_MODEL, // thresholds unchanged by an affirm
        reconciliation: RECON_C_UNVERIFIABLE,
        confirmed_reconciliation: RECON_AFTER,
        calculator_ready: false,
        corrections: correctionBody.corrections,
        clarifying_answers: { 'claim_evidence:threshold:c': { answer: 'confirm_value', letter: 'c' } },
      }))
      return true
    }
    return false
  })

  await page.locator('[data-testid="cutoff-table"]').waitFor()

  // edit two different rows, save neither
  await page.fill('#cutoff-A-min', '88')
  await page.fill('#cutoff-D-max', '66')
  await page.getByRole('button', { name: 'Save cutoffs' }).waitFor()

  // affirm a third, untouched row -> a correction submits mid-edit
  await page.locator('.grade-cutoff-row[data-threshold-letter="C"]')
    .getByRole('button', { name: "Yes, that's correct" }).click()
  await page.waitForFunction(() => !document.querySelector('button[aria-busy="true"]'))
  await page.locator('.grade-cutoff-resolved[data-threshold-letter="C"]').waitFor()

  // the in-progress edits in rows A and D are still there (no remount wiped them)
  assert.equal(await page.inputValue('#cutoff-A-min'), '88')
  assert.equal(await page.inputValue('#cutoff-D-max'), '66')
  await page.getByRole('button', { name: 'Save cutoffs' }).waitFor()
  assert.deepEqual(correctionBody.corrections, [
    { target_type: 'threshold', operation: 'confirm_threshold_value', threshold_letter: 'C' },
  ])
})

// --- category-weight editor (CategoryWeightEditor) -------------------------------

// Mirrors a real incomplete extraction: Homework and Final are known (35%
// each), midterm exam's count is known (2) but its total weight was never
// stated -- weight: null, the exact category a student needs to fill in.
// 35 + 35 = 70, matching category_weight_validation's real message shape.
const WEIGHT_GAP_MODEL = {
  ...EXTRACTED_MODEL,
  categories: [
    { name: 'Homework assignment', weight: 35, count: null, evidence: { page: 3, text: 'Homework assignment (35%)', confidence: 1.0 } },
    { name: 'midterm exam', weight: null, count: 2, evidence: { page: 2, text: '2 midterms', confidence: 1.0 } },
    { name: 'final exam', weight: 35, count: 1, evidence: { page: 3, text: 'final exam (35%)', confidence: 1.0 } },
  ],
  assessments: [],
  grade_thresholds: [],
  rules: [],
  warnings: [],
}

const RECON_WEIGHT_GAP = {
  status: 'needs_student_review',
  findings: [
    { code: 'category_weight_validation', severity: 'warning', message: 'category weights sum to 70.0, not 100 (possibly incomplete extraction)', field: 'categories' },
    { code: 'unknown_weight', severity: 'warning', message: 'The total weight for the midterm exam category is not explicitly stated; each midterm is 15% but the category total is not given.', field: 'midterm exam' },
  ],
  evidence_coverage: { total_claims: 3, supported_claims: 3, coverage_ratio: 1, unsupported_claims: [] },
}

test('Grade Calculator: category weight editor renders every category (including one with no weight yet), shows blocking non-dismissible notes, and a live running total that closes as you type', { timeout: 45_000 }, async (t) => {
  const page = await mountCutoffPanel(t, 'grade-calculator-weight-editor-render', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: WEIGHT_GAP_MODEL, reconciliation: RECON_WEIGHT_GAP }))
      return true
    }
    return false
  })

  const table = page.locator('[data-testid="category-weight-table"]')
  await table.waitFor()

  // every category renders, including the one with weight: null -- the read-
  // only breakdown would have hidden it entirely
  assert.equal(await table.locator('[data-category-name]').count(), 3)
  assert.equal(await page.getByLabel('Homework assignment weight').inputValue(), '35')
  assert.equal(await page.getByLabel('midterm exam weight').inputValue(), '')
  assert.equal(await page.getByLabel('midterm exam count').inputValue(), '2')
  assert.equal(await page.getByLabel('final exam weight').inputValue(), '35')

  // category_weight_validation is blocking here (severity: warning) -- shown
  // as a non-dismissible note anchored to the editor, not in the dismissible
  // general findings list it used to render in
  const totalNote = table.locator('[data-finding-code="category_weight_validation"]')
  await totalNote.getByText('category weights in this syllabus may not add up to 100%').waitFor()
  assert.equal(await totalNote.getByRole('button', { name: 'Dismiss this finding' }).count(), 0)
  assert.equal(await page.locator('.grade-inline-findings--general [data-finding-code="category_weight_validation"]').count(), 0)
  assert.equal(await page.locator('.grade-inline-findings--general').getByText('may not add up to 100%').count(), 0)

  // unknown_weight is per-category, also blocking and non-dismissible, and
  // likewise gone from the general dismissible list
  const row = table.locator('[data-category-name="midterm exam"]')
  const rowNote = row.locator('[data-finding-code="unknown_weight"]')
  await rowNote.getByText("couldn't determine this category's weight").waitFor()
  assert.equal(await rowNote.getByRole('button', { name: 'Dismiss this finding' }).count(), 0)
  assert.equal(await page.locator('.grade-inline-findings--general [data-finding-code="unknown_weight"]').count(), 0)

  // live running total reflects the declared categories before any edit
  await table.getByText('Total: 70%').waitFor()
  await table.getByText('30% short of 100%').waitFor()

  // typing the missing weight updates the total live, before Save is clicked
  await page.getByLabel('midterm exam weight').fill('30')
  await table.getByText('Total: 100%').waitFor()
  assert.equal(await table.getByText(/short of 100%|over 100%/).count(), 0)
})

test('Grade Calculator: category weight editor save emits category/set_weight and category/set_count for touched fields only', { timeout: 45_000 }, async (t) => {
  let correctionBody = null
  const page = await mountCutoffPanel(t, 'grade-calculator-weight-editor-save', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: WEIGHT_GAP_MODEL, reconciliation: RECON_WEIGHT_GAP }))
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && method === 'POST') {
      correctionBody = JSON.parse(await readBody(request))
      const FIXED_MODEL = {
        ...WEIGHT_GAP_MODEL,
        categories: WEIGHT_GAP_MODEL.categories.map((c) => (c.name === 'midterm exam' ? { ...c, weight: 30 } : c)),
      }
      json(response, 200, detail({
        extracted_grade_model: WEIGHT_GAP_MODEL,
        confirmed_grade_model: FIXED_MODEL,
        reconciliation: RECON_WEIGHT_GAP,
        confirmed_reconciliation: {
          status: 'accepted',
          findings: [{ code: 'category_weight_validation', severity: 'valid', message: 'category weights sum to 100.0', field: 'categories' }],
          evidence_coverage: RECON_WEIGHT_GAP.evidence_coverage,
        },
        calculator_ready: true,
        corrections: correctionBody.corrections,
      }))
      return true
    }
    return false
  })

  const table = page.locator('[data-testid="category-weight-table"]')
  await table.waitFor()

  // touch a count on one row and a weight on another; leave the third alone
  await page.getByLabel('Homework assignment count').fill('12')
  await page.getByLabel('midterm exam weight').fill('30')
  await page.getByRole('button', { name: 'Save weights' }).click()
  await page.waitForFunction(() => !document.querySelector('button[aria-busy="true"]'))

  // only the two touched fields become corrections -- nothing invented for
  // the untouched "final exam" row, and only existing operations are used
  assert.deepEqual(correctionBody.corrections, [
    { target_type: 'category', operation: 'set_count', category_name: 'Homework assignment', value: 12 },
    { target_type: 'category', operation: 'set_weight', category_name: 'midterm exam', value: 30 },
  ])

  // the fix unblocks the calculator
  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()
})

test('Grade Calculator: a category_weight_validation instance that is already valid shows no blocking note', { timeout: 45_000 }, async (t) => {
  const CLEAN_MODEL = {
    ...WEIGHT_GAP_MODEL,
    categories: WEIGHT_GAP_MODEL.categories.map((c) => (c.name === 'midterm exam' ? { ...c, weight: 30 } : c)),
  }
  const RECON_CLEAN = {
    status: 'needs_student_review',
    findings: [
      { code: 'category_weight_validation', severity: 'valid', message: 'category weights sum to 100.0', field: 'categories' },
      { code: 'grading_method_unknown', severity: 'warning', message: 'grading_method could not be determined from the syllabus', field: 'grading_method' },
    ],
    evidence_coverage: { total_claims: 3, supported_claims: 3, coverage_ratio: 1, unsupported_claims: [] },
  }
  const page = await mountCutoffPanel(t, 'grade-calculator-weight-editor-valid', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: CLEAN_MODEL, reconciliation: RECON_CLEAN }))
      return true
    }
    return false
  })

  const table = page.locator('[data-testid="category-weight-table"]')
  await table.waitFor()
  // category_weight_validation's own instance is VALID (weights already sum
  // to 100) -- the code is not treated as unconditionally blocking, so no
  // note renders here even though the code is on the relocated list
  assert.equal(await table.locator('[data-finding-code="category_weight_validation"]').count(), 0)
  await table.getByText('Total: 100%').waitFor()
  assert.equal(await table.getByText(/short of 100%|over 100%/).count(), 0)
  // a genuinely blocking, unrelated finding still shows in the general list
  assert.ok((await page.locator('[data-finding-code="grading_method_unknown"]').count()) >= 1)
})

// --- category weight claim-evidence (confirm_category_value) --------------------

// claim_evidence_consistency_unverifiable / claim_evidence_value_mismatch on a
// category weight cannot exist at extraction time -- _check_category_weight_
// consistency skips a category outright while weight is null (matches
// WEIGHT_GAP_MODEL's 'midterm exam' row). They only appear in the SERVER
// RESPONSE to a set_weight correction, once the category actually has a
// weight to check against its (possibly stale) evidence text.

test('Grade Calculator: a category claim-evidence finding does not exist on initial load, only appears in the correction response, and affirming it emits confirm_category_value', { timeout: 45_000 }, async (t) => {
  let corrections = []
  const RECON_UNVERIFIABLE = {
    status: 'needs_student_review',
    findings: [
      { code: 'category_weight_validation', severity: 'valid', message: 'category weights sum to 100.0', field: 'categories' },
      { code: 'unknown_weight', severity: 'warning', message: 'The total weight for the midterm exam category is not explicitly stated; each midterm is 15% but the category total is not given.', field: 'midterm exam' },
      { code: 'claim_evidence_consistency_unverifiable', severity: 'warning', message: "could not deterministically verify category:midterm exam.weight against its cited evidence text ('2 midterms')", field: 'category:midterm exam.weight' },
    ],
    evidence_coverage: { total_claims: 3, supported_claims: 3, coverage_ratio: 1, unsupported_claims: [] },
  }
  const RECON_CONFIRMED = {
    status: 'accepted',
    findings: [
      { code: 'category_weight_validation', severity: 'valid', message: 'category weights sum to 100.0', field: 'categories' },
      { code: 'unknown_weight', severity: 'warning', message: 'The total weight for the midterm exam category is not explicitly stated; each midterm is 15% but the category total is not given.', field: 'midterm exam' },
    ],
    evidence_coverage: { total_claims: 3, supported_claims: 3, coverage_ratio: 1, unsupported_claims: [] },
  }
  const WEIGHT_SET_MODEL = {
    ...WEIGHT_GAP_MODEL,
    categories: WEIGHT_GAP_MODEL.categories.map((c) => (c.name === 'midterm exam' ? { ...c, weight: 30 } : c)),
  }

  const page = await mountCutoffPanel(t, 'grade-calculator-category-claim-evidence-affirm', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: WEIGHT_GAP_MODEL, reconciliation: RECON_WEIGHT_GAP }))
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && method === 'POST') {
      corrections = JSON.parse(await readBody(request)).corrections
      const justAffirmed = corrections.some((c) => c.operation === 'confirm_category_value')
      // calculator_ready stays false throughout (an unrelated finding --
      // grading_method_unknown -- keeps the model genuinely incomplete) so
      // the editor stays mounted after affirming and its own "answered"
      // display (✓ ... confirmed as correct) can be observed directly,
      // independent of the separate "everything is now accepted" transition
      // already covered by the cutoff-table equivalent test.
      const findingsAfterAffirm = [
        ...RECON_CONFIRMED.findings,
        { code: 'grading_method_unknown', severity: 'warning', message: 'grading_method could not be determined from the syllabus', field: 'grading_method' },
      ]
      json(response, 200, detail({
        extracted_grade_model: WEIGHT_GAP_MODEL,
        confirmed_grade_model: WEIGHT_SET_MODEL,
        calculator_ready: false,
        reconciliation: RECON_WEIGHT_GAP,
        confirmed_reconciliation: justAffirmed ? { ...RECON_CONFIRMED, status: 'needs_student_review', findings: findingsAfterAffirm } : RECON_UNVERIFIABLE,
        corrections,
        clarifying_answers: justAffirmed ? { 'claim_evidence:category:midterm exam': { answer: 'confirm_value', category_name: 'midterm exam' } } : {},
      }))
      return true
    }
    return false
  })

  const table = page.locator('[data-testid="category-weight-table"]')
  await table.waitFor()
  const row = table.locator('[data-category-name="midterm exam"]')

  // --- initial load: the claim-evidence finding does not exist yet (the
  //     category's weight is still null), so there is no affirm banner ---
  assert.equal(await row.getByRole('button', { name: "Yes, that's correct" }).count(), 0)
  assert.equal(await table.locator('[data-finding-code="claim_evidence_consistency_unverifiable"]').count(), 0)

  // --- set the weight and save -> the response is the ONLY place this
  //     finding can appear ---
  await page.getByLabel('midterm exam weight').fill('30')
  await page.getByRole('button', { name: 'Save weights' }).click()
  await page.waitForFunction(() => !document.querySelector('button[aria-busy="true"]'))

  assert.deepEqual(corrections, [
    { target_type: 'category', operation: 'set_weight', category_name: 'midterm exam', value: 30 },
  ])

  // the affirm banner now renders reactively against the POST-CORRECTION
  // findings (detail.confirmed_reconciliation), not any initial-load snapshot
  await row.getByText("We couldn't confirm midterm exam's weight against your syllabus.").waitFor()
  const affirmButton = row.getByRole('button', { name: "Yes, that's correct" })
  await affirmButton.waitFor()

  // unknown_weight is still present in this response's findings (the
  // backend never clears it), but its text ("we couldn't determine this
  // category's weight") is now factually wrong -- the weight IS 30 -- so it
  // must not render here once weight is no longer null
  assert.equal(await row.locator('[data-finding-code="unknown_weight"]').count(), 0)
  assert.equal(await row.getByText("couldn't determine this category's weight").count(), 0)

  // --- affirming emits category/confirm_category_value, cumulative with
  //     the prior set_weight correction ---
  await affirmButton.click()
  await page.waitForFunction(() => !document.querySelector('button[aria-busy="true"]'))

  assert.deepEqual(corrections, [
    { target_type: 'category', operation: 'set_weight', category_name: 'midterm exam', value: 30 },
    { target_type: 'category', operation: 'confirm_category_value', category_name: 'midterm exam' },
  ])
  await row.getByText('✓ midterm exam weight confirmed as correct.').waitFor()
  assert.equal(await row.getByRole('button', { name: "Yes, that's correct" }).count(), 0)
})

test('Grade Calculator: a category weight mismatch renders as blocking with no affirm button', { timeout: 45_000 }, async (t) => {
  const RECON_MISMATCH = {
    status: 'needs_student_review',
    findings: [
      { code: 'category_weight_validation', severity: 'valid', message: 'category weights sum to 100.0', field: 'categories' },
      { code: 'claim_evidence_value_mismatch', severity: 'error', message: "category:midterm exam.weight claims 30.0, but its cited evidence text ('Midterm Exam (25%)') states 25.0", field: 'category:midterm exam.weight' },
    ],
    evidence_coverage: { total_claims: 3, supported_claims: 3, coverage_ratio: 1, unsupported_claims: [] },
  }
  const WEIGHT_SET_MODEL = {
    ...WEIGHT_GAP_MODEL,
    categories: WEIGHT_GAP_MODEL.categories.map((c) =>
      c.name === 'midterm exam' ? { ...c, weight: 30, evidence: { page: 1, text: 'Midterm Exam (25%)', confidence: 1.0 } } : c,
    ),
  }
  let corrections = []

  const page = await mountCutoffPanel(t, 'grade-calculator-category-claim-evidence-mismatch', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: WEIGHT_GAP_MODEL, reconciliation: RECON_WEIGHT_GAP }))
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/corrections` && method === 'POST') {
      corrections = JSON.parse(await readBody(request)).corrections
      json(response, 200, detail({
        extracted_grade_model: WEIGHT_GAP_MODEL,
        confirmed_grade_model: WEIGHT_SET_MODEL,
        calculator_ready: false,
        reconciliation: RECON_WEIGHT_GAP,
        confirmed_reconciliation: RECON_MISMATCH,
        corrections,
      }))
      return true
    }
    return false
  })

  const table = page.locator('[data-testid="category-weight-table"]')
  await table.waitFor()
  await page.getByLabel('midterm exam weight').fill('30')
  await page.getByRole('button', { name: 'Save weights' }).click()
  await page.waitForFunction(() => !document.querySelector('button[aria-busy="true"]'))

  const row = table.locator('[data-category-name="midterm exam"]')
  const mismatchFinding = row.locator('[data-finding-code="claim_evidence_value_mismatch"]')
  await mismatchFinding.getByText(/You entered 30%, but the syllabus text \("Midterm Exam \(25%\)"\) says 25%/).waitFor()

  // blocking, non-dismissible, and -- unlike the unverifiable case -- never
  // gets an affirm button anywhere on this row: the backend deliberately
  // does not suppress claim_evidence_value_mismatch for a category
  assert.equal(await mismatchFinding.getByRole('button', { name: 'Dismiss this finding' }).count(), 0)
  assert.equal(await row.getByRole('button', { name: "Yes, that's correct" }).count(), 0)
  assert.equal(await row.getByRole('button', { name: /confirm/i }).count(), 0)
})

test('Grade Calculator: an unknown_weight finding that matches no category renders unattached instead of disappearing', { timeout: 45_000 }, async (t) => {
  // related_field is untyped free text (extraction.py:132) -- it can name
  // an assessment or rule instead of a category, or just not match
  // anything. "Final Project" matches none of WEIGHT_GAP_MODEL's three
  // categories (Homework assignment / midterm exam / final exam).
  const RECON_UNMATCHED = {
    status: 'needs_student_review',
    findings: [
      { code: 'category_weight_validation', severity: 'warning', message: 'category weights sum to 70.0, not 100 (possibly incomplete extraction)', field: 'categories' },
      { code: 'unknown_weight', severity: 'warning', message: 'The total weight for the Final Project is not explicitly stated.', field: 'Final Project' },
    ],
    evidence_coverage: { total_claims: 3, supported_claims: 3, coverage_ratio: 1, unsupported_claims: [] },
  }
  const page = await mountCutoffPanel(t, 'grade-calculator-unknown-weight-unmatched', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, detail({ extracted_grade_model: WEIGHT_GAP_MODEL, reconciliation: RECON_UNMATCHED }))
      return true
    }
    return false
  })

  const table = page.locator('[data-testid="category-weight-table"]')
  await table.waitFor()

  // renders unattached in the editor's general area -- not dropped, and
  // not attached to any of the three (non-matching) category rows
  await table.getByText('The syllabus doesn\'t state a weight for "Final Project", but CampusIQ couldn\'t match that to one of the categories below.').waitFor()
  for (const name of ['Homework assignment', 'midterm exam', 'final exam']) {
    assert.equal(
      await table.locator(`[data-category-name="${name}"]`).locator('[data-finding-code="unknown_weight"]').count(),
      0,
      `unmatched finding must not attach to the ${name} row`,
    )
  }

  // informational only: no affirm button, no dismiss button anywhere for it
  const unmatchedNote = table.locator('[data-finding-code="unknown_weight"]', { hasText: 'Final Project' })
  await unmatchedNote.waitFor()
  assert.equal(await unmatchedNote.getByRole('button').count(), 0)
})

// --- live projection: merged save+calculate button, and reactive What-if ---------

const PROJECTION_READY_DETAIL = () => detail({
  review_state: 'confirmed',
  calculator_ready: true,
  extracted_grade_model: CUTOFF_MODEL,
  confirmed_grade_model: CUTOFF_MODEL,
  reconciliation: RECONCILIATION_ACCEPTED,
  confirmed_reconciliation: RECONCILIATION_ACCEPTED,
  grade_state_revision: 4,
})

function calcResponse(overrides = {}) {
  return {
    grading_method: 'weighted',
    components: [],
    completed_weight: null,
    earned_course_percentage: null,
    current_grade: null,
    projected_grade: null,
    current_letter_grade: null,
    projected_letter_grade: null,
    applied_rules: [],
    warnings: [],
    ...overrides,
  }
}

test('Grade Calculator: "Save & calculate" persists the actuals then calculates, in one action', { timeout: 45_000 }, async (t) => {
  const calls = []
  let gradeStateBody = null

  const page = await mountCutoffPanel(t, 'grade-calculator-save-and-calculate', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, PROJECTION_READY_DETAIL())
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/grade-state` && method === 'PUT') {
      calls.push('grade-state')
      gradeStateBody = JSON.parse(await readBody(request))
      json(response, 200, { revision: 5, category_scores: gradeStateBody.category_scores, assessment_scores: gradeStateBody.assessment_scores })
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/calculate` && method === 'POST') {
      calls.push('calculate')
      await readBody(request)
      json(response, 200, calcResponse({ completed_weight: 35, current_grade: 85 }))
      return true
    }
    return false
  })

  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()
  await page.fill('#actual-category\\:Mid-term\\ Exam', '85')
  await page.getByRole('button', { name: 'Save & calculate' }).click()

  // the result card renders from the /calculate response
  await page.getByText('Based on 35% of the course completed').waitFor()
  await page.locator('.overview-stat-value', { hasText: '85%' }).waitFor()
  await page.waitForFunction(() => !document.querySelector('button[aria-busy="true"]'))

  // the typed actual was persisted (PUT /grade-state) with the optimistic
  // revision, then the calculation ran (POST /calculate) -- that order, each once
  assert.ok(gradeStateBody, 'a grade-state PUT was sent')
  assert.deepEqual(gradeStateBody.category_scores, [{ category_name: 'Mid-term Exam', actual_score: 85 }])
  assert.deepEqual(gradeStateBody.assessment_scores, [])
  assert.equal(gradeStateBody.expected_revision, 4)
  assert.deepEqual(calls, ['grade-state', 'calculate'])
})

test('Grade Calculator: entering a What-if score recalculates with no button press and no save', { timeout: 45_000 }, async (t) => {
  const calls = []

  const page = await mountCutoffPanel(t, 'grade-calculator-reactive-whatif', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, PROJECTION_READY_DETAIL())
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/grade-state` && method === 'PUT') {
      calls.push('grade-state')
      json(response, 200, { revision: 5, category_scores: [], assessment_scores: [] })
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/calculate` && method === 'POST') {
      calls.push('calculate')
      await readBody(request)
      json(response, 200, calcResponse({ projected_grade: 91.2 }))
      return true
    }
    return false
  })

  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()

  // type a hypothetical score -- no button is clicked anywhere after this
  await page.fill('#hypo-category\\:Mid-term\\ Exam', '95')

  // the projected grade updates on its own
  await page.locator('.overview-stat-value', { hasText: '91.2%' }).waitFor()

  // and it got there via /calculate only -- the debounced projection never
  // writes grade-state
  await page.waitForTimeout(700)
  assert.deepEqual(calls, ['calculate'])
})

test('Grade Calculator: clicking "Save & calculate" cancels a pending live projection (one result, from the button)', { timeout: 45_000 }, async (t) => {
  const calls = []
  let calcCount = 0
  let gradeStateCount = 0

  const page = await mountCutoffPanel(t, 'grade-calculator-projection-race', async (path, method, request, response) => {
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}` && method === 'GET') {
      json(response, 200, PROJECTION_READY_DETAIL())
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/grade-state` && method === 'PUT') {
      gradeStateCount += 1
      calls.push('grade-state')
      await readBody(request)
      json(response, 200, { revision: 5, category_scores: [{ category_name: 'Mid-term Exam', actual_score: 88 }], assessment_scores: [] })
      return true
    }
    if (path === `/api/v2/student/me/syllabus-grade-profiles/${PROFILE_ID}/calculate` && method === 'POST') {
      calcCount += 1
      calls.push('calculate')
      await readBody(request)
      // a slow response: a raced debounce call would still be in flight here
      // and would bump the count if it hadn't been cancelled
      await new Promise((r) => setTimeout(r, 150))
      json(response, 200, calcResponse({ completed_weight: 35, current_grade: 88.8 }))
      return true
    }
    return false
  })

  await page.getByRole('heading', { name: 'Enter your grades' }).waitFor()

  // start the 500ms projection debounce, then immediately commit via the
  // button -- well inside the debounce window
  await page.fill('#actual-category\\:Mid-term\\ Exam', '88')
  await page.getByRole('button', { name: 'Save & calculate' }).click()

  await page.getByText('Based on 35% of the course completed').waitFor()
  await page.locator('.overview-stat-value', { hasText: '88.8%' }).waitFor()
  await page.waitForFunction(() => !document.querySelector('button[aria-busy="true"]'))

  // give the cancelled debounce well past its 500ms window to prove it never fires
  await page.waitForTimeout(900)

  assert.equal(gradeStateCount, 1)
  assert.equal(calcCount, 1, 'exactly one /calculate ran -- the button cancelled the pending projection')
  // the one calculation was the button's: preceded by its save
  assert.deepEqual(calls, ['grade-state', 'calculate'])
})

// --- course cards: ring segments, states, and the aria-label breakdown ----------

test('Grade Calculator: the list renders a segmented ring card per calculator', { timeout: 30_000 }, async (t) => {
  const planning = planningRoutes({ terms: [] })
  const listRows = [
    {
      id: 'p-ready', institution: 'tamu', course_code: 'PHYS 207', term: 'Fall 2026', section: '529',
      review_state: 'confirmed', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      calculator_ready: true, current_grade: 85, current_letter_grade: 'B',
      components: [
        { name: 'Midterm', source_type: 'category', weight_percent: 30, effective_score: 90, status: 'completed' },
        { name: 'Final', source_type: 'category', weight_percent: 40, effective_score: null, status: null },
        { name: 'Project', source_type: 'category', weight_percent: 30, effective_score: 0, status: 'completed' },
      ],
    },
    {
      id: 'p-setup', institution: 'tamu', course_code: 'ECEN 248', term: 'Fall 2026', section: '501',
      review_state: 'needs_review', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      calculator_ready: false, current_grade: null, current_letter_grade: null, components: [],
    },
    {
      id: 'p-nogap', institution: 'tamu', course_code: 'MATH 251', term: 'Fall 2026', section: '200',
      review_state: 'confirmed', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      calculator_ready: true, current_grade: 63.5, current_letter_grade: null,
      components: [{ name: 'Exam', source_type: 'category', weight_percent: 100, effective_score: 63.5, status: 'completed' }],
    },
    {
      // categories sum to 70 -> a shortfall segment for the missing 30
      id: 'p-short', institution: 'tamu', course_code: 'CHEM 101', term: 'Fall 2026', section: '300',
      review_state: 'confirmed', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      calculator_ready: true, current_grade: 78, current_letter_grade: 'C',
      components: [
        { name: 'Labs', source_type: 'category', weight_percent: 30, effective_score: 82, status: 'completed' },
        { name: 'Exams', source_type: 'category', weight_percent: 40, effective_score: null, status: null },
      ],
    },
    {
      // points-based: all assessments, no categories -> one full-circle arc
      id: 'p-points', institution: 'tamu', course_code: 'ENGR 102', term: 'Fall 2026', section: '400',
      review_state: 'confirmed', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      calculator_ready: true, current_grade: 91, current_letter_grade: 'A',
      components: [
        { name: 'Project 1', source_type: 'assessment', weight_percent: 50, effective_score: 88, status: 'completed' },
        { name: 'Project 2', source_type: 'assessment', weight_percent: 50, effective_score: 94, status: 'completed' },
      ],
    },
    // A pair identical except for course_title, to check the title renders
    // and does not change the card's height.
    {
      id: 'p-title', institution: 'tamu', course_code: 'PHYS 218', term: 'Fall 2026', section: '500',
      review_state: 'confirmed', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      calculator_ready: true, current_grade: 80, current_letter_grade: 'B',
      course_title: 'Mechanics for Engineering and Science Majors',
      components: [{ name: 'Exams', source_type: 'category', weight_percent: 100, effective_score: 80, status: 'completed' }],
    },
    {
      id: 'p-notitle', institution: 'tamu', course_code: 'PHYS 219', term: 'Fall 2026', section: '500',
      review_state: 'confirmed', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      calculator_ready: true, current_grade: 80, current_letter_grade: 'B',
      course_title: null,
      components: [{ name: 'Exams', source_type: 'category', weight_percent: 100, effective_score: 80, status: 'completed' }],
    },
  ]

  const apiPlugin = {
    name: 'grade-calculator-cards',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/requirement-satisfaction') return json(response, 404, { detail: 'Not found.' })
        if (path?.startsWith('/api/v2/student/me/analysis-cache/')) return json(response, 404, { detail: 'Not found.' })
        if (path === '/api/v2/student/me/syllabus-grade-profiles' && request.method === 'GET') {
          return json(response, 200, { syllabus_grade_profiles: listRows })
        }
        next()
      })
    },
  }
  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-grade-calculator-cards', import.meta.url).pathname,
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()
  await page.goto(`http://127.0.0.1:${address.port}/authenticated-dashboard-preview.html?mode=complete`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Grade Calculator', exact: true }).click()

  // --- ready card: one ring, three category segments, fill only where graded ---
  const ready = page.locator('.grade-card', { hasText: 'PHYS 207' })
  await ready.waitFor()
  assert.equal(await ready.getAttribute('data-kind'), 'ring')
  assert.equal(await ready.getAttribute('data-grade'), 'b')
  assert.equal(await ready.locator('.grade-card-track').count(), 3, 'a track per category')
  // Midterm 90% is the only graded, non-zero fill; Final is ungraded, Project is a scored 0
  assert.equal(await ready.locator('.grade-card-fill').count(), 1)
  await ready.locator('.grade-card-center-primary', { hasText: 'B' }).waitFor()
  await ready.locator('.grade-card-center-secondary', { hasText: '85%' }).waitFor()

  // --- aria-label carries the full breakdown, so nothing is hover-only ---
  const label = await ready.locator('svg.grade-card-ring').getAttribute('aria-label')
  assert.match(label, /PHYS 207, Fall 2026\./)
  assert.match(label, /Current grade B, 85%\./)
  assert.match(label, /Midterm: weight 30%, score 90%\./)
  assert.match(label, /Final: weight 40%, not yet graded\./)
  assert.match(label, /Project: weight 30%, score 0%\./)

  // --- segments are not individually focusable (decorative to AT) ---
  assert.equal(await ready.locator('svg.grade-card-ring [tabindex]').count(), 0)
  assert.equal(await ready.locator('svg.grade-card-ring path[role]').count(), 0)

  // --- setup card: no ring, dashed, and still a tap target that opens ---
  const setup = page.locator('.grade-card', { hasText: 'ECEN 248' })
  assert.equal(await setup.getAttribute('data-kind'), 'setup')
  assert.equal(await setup.locator('svg.grade-card-ring').count(), 0)
  assert.equal(await setup.locator('.grade-card-track').count(), 0)

  // --- letter-null card: percentage alone, neutral (no data-grade), no dash ---
  const noLetter = page.locator('.grade-card', { hasText: 'MATH 251' })
  assert.equal(await noLetter.getAttribute('data-grade'), null)
  await noLetter.locator('.grade-card-center-primary', { hasText: '63.5%' }).waitFor()
  assert.equal(await noLetter.locator('.grade-card-center-primary', { hasText: 'B' }).count(), 0)

  // --- sub-100 weights: a distinct shortfall segment, and the aria-label says so ---
  const short = page.locator('.grade-card', { hasText: 'CHEM 101' })
  assert.equal(await short.locator('.grade-card-track').count(), 3, '2 categories + 1 shortfall track')
  assert.equal(await short.locator('.grade-card-track--shortfall').count(), 1)
  // the shortfall segment is never a hover target
  assert.equal(await short.locator('.grade-card-seg[data-shortfall] .grade-card-hit').count(), 0)
  const shortLabel = await short.locator('svg.grade-card-ring').getAttribute('aria-label')
  assert.match(shortLabel, /Labs: weight 30%, score 82%\./)
  assert.match(shortLabel, /Exams: weight 40%, not yet graded\./)
  assert.match(shortLabel, /30% of the course weight is not accounted for by any component/)

  // --- points-based: one full-circle arc, no segments, letter + percentage centre ---
  const points = page.locator('.grade-card', { hasText: 'ENGR 102' })
  assert.equal(await points.getAttribute('data-kind'), 'categoryless')
  assert.equal(await points.getAttribute('data-grade'), 'a')
  assert.equal(await points.locator('.grade-card-track').count(), 1, 'one full-circle track')
  assert.equal(await points.locator('.grade-card-fill').count(), 1)
  assert.equal(await points.locator('.grade-card-hit').count(), 0, 'no hover reveal on a categoryless card')
  await points.locator('.grade-card-center-primary', { hasText: 'A' }).waitFor()
  await points.locator('.grade-card-center-secondary', { hasText: '91%' }).waitFor()
  const pointsLabel = await points.locator('svg.grade-card-ring').getAttribute('aria-label')
  assert.match(pointsLabel, /Graded by individual assessments, not weighted categories\./)

  // --- course title: rendered under the code when present; identical card
  //     height when absent (reserved line, no placeholder, no shift) ---
  const titled = page.locator('.grade-card', { hasText: 'PHYS 218' })
  const untitled = page.locator('.grade-card', { hasText: 'PHYS 219' })
  await titled.locator('.grade-card-title-name', { hasText: 'Mechanics for Engineering and Science Majors' }).waitFor()
  assert.equal((await untitled.locator('.grade-card-title-name').textContent()).trim(), '', 'no title -> empty, no placeholder text')
  const [ht, hu] = await Promise.all([
    titled.evaluate((el) => el.getBoundingClientRect().height),
    untitled.evaluate((el) => el.getBoundingClientRect().height),
  ])
  assert.ok(Math.abs(ht - hu) < 0.5, `card height is identical with (${ht}) and without (${hu}) a title`)

  // --- grade colour ramp: a continuous green -> red hue sweep, one step per
  //     grade, no blue break, A vs B still a clear hue apart ---
  const hues = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement)
    const parse = (name) => {
      const m = root.getPropertyValue(name).trim().replace('#', '')
      return [0, 2, 4].map((i) => parseInt(m.slice(i, i + 2), 16))
    }
    const hueOf = ([r, g, b]) => {
      const rr = r / 255, gg = g / 255, bb = b / 255
      const max = Math.max(rr, gg, bb), min = Math.min(rr, gg, bb), d = max - min
      if (d === 0) return 0
      let h
      if (max === rr) h = ((gg - bb) / d) % 6
      else if (max === gg) h = (bb - rr) / d + 2
      else h = (rr - gg) / d + 4
      h *= 60
      return h < 0 ? h + 360 : h
    }
    const names = ['--grade-a', '--grade-b', '--grade-c', '--grade-d', '--grade-f']
    return names.map((n) => ({ rgb: parse(n), hue: hueOf(parse(n)) }))
  })
  const H = hues.map((x) => x.hue)
  // green (~130) monotonically down to red (~0)
  assert.ok(H[0] > 110 && H[0] < 160, `A is green (hue ${Math.round(H[0])})`)
  assert.ok(H[4] >= 0 && H[4] < 15, `F is deep red (hue ${Math.round(H[4])})`)
  for (let i = 1; i < H.length; i += 1) {
    assert.ok(H[i] < H[i - 1], `hue steps down from grade ${i - 1} (${Math.round(H[i - 1])}) to ${i} (${Math.round(H[i])})`)
  }
  assert.ok(H[0] - H[1] > 30, `A and B are a clear hue apart (${Math.round(H[0])} vs ${Math.round(H[1])})`)
  assert.ok(hues.every((x) => x.rgb[2] <= 90), 'no blue break anywhere on the ramp')

  // --- Remove + Upload another are preserved ---
  await page.getByRole('button', { name: /Remove grade calculator for PHYS 207/ }).waitFor()
  await page.getByRole('button', { name: 'Upload another syllabus' }).waitFor()
})
