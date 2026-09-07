import assert from 'node:assert/strict'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { planningRoutes } from './fixtures/planningRoutes.mjs'

// End-to-end guard for the GPA Calculator term selector, driving the REAL
// AuthenticatedDashboard through transcript-preview.html's PreviewFlowHarness.
// That harness's reloadStudentProfile genuinely re-resolves the account against
// GET /api/v2/student/me/profile, so a grade edit really does re-render the
// parent -- which is the exact condition that used to snap the dropdown back to
// its computed default (see fix/term-selector-current-default).
//
// Fixture mirrors TAMU student 85a3c88a-52fb-43df-97db-d8257d1098db: Fall 2026
// is in progress with four graded in-progress courses, Spring 2027 is the next
// (upcoming) term. Clock frozen at 2026-09-06 so "in progress" is deterministic.

const INSTITUTION_ID = '75d68331-91d2-47e8-9671-2a3b065955d0'
const FALL_2025_ID = 'term-fall-2025'
const SPRING_2026_ID = 'term-spring-2026'
const FALL_2026_ID = 'term-fall-2026'
const SPRING_2027_ID = 'term-spring-2027'

const TERMS = [
  { key: '2025-Fall', id: FALL_2025_ID, label: 'Fall 2025 - College Station', year: 2025, season: 'Fall', sequence: 0, start_date: '2025-08-25', end_date: '2025-12-16', enrolled: true, is_upcoming: false },
  { key: '2026-Spring', id: SPRING_2026_ID, label: 'Spring 2026 - College Station', year: 2026, season: 'Spring', sequence: 1, start_date: '2026-01-12', end_date: '2026-05-05', enrolled: true, is_upcoming: false },
  { key: '2026-Fall', id: FALL_2026_ID, label: 'Fall 2026 - College Station', year: 2026, season: 'Fall', sequence: 2, start_date: '2026-08-24', end_date: '2026-12-10', enrolled: true, is_upcoming: false },
  { key: '2027-Spring', id: SPRING_2027_ID, label: 'Spring 2027', year: 2027, season: 'Spring', sequence: 3, start_date: '2027-01-19', end_date: '2027-05-11', enrolled: true, is_upcoming: true },
]

const IN_PROGRESS = [
  { id: 'cr-phys207', term_id: FALL_2026_ID, institution_id: INSTITUTION_ID, course_code: 'PHYS 207', title: 'Electricity and Magnetism', credit_hours: 3, letter_grade: 'A', credit_type: 'resident', status: 'in_progress', source: 'transcript_parse' },
  { id: 'cr-phys217', term_id: FALL_2026_ID, institution_id: INSTITUTION_ID, course_code: 'PHYS 217', title: 'Electricity and Magnetism Lab', credit_hours: 2, letter_grade: 'A', credit_type: 'resident', status: 'in_progress', source: 'transcript_parse' },
  { id: 'cr-csce222', term_id: FALL_2026_ID, institution_id: INSTITUTION_ID, course_code: 'CSCE 222', title: 'Discrete Structures', credit_hours: 3, letter_grade: 'B', credit_type: 'resident', status: 'in_progress', source: 'transcript_parse' },
  { id: 'cr-ecen248', term_id: FALL_2026_ID, institution_id: INSTITUTION_ID, course_code: 'ECEN 248', title: 'Digital Systems Design', credit_hours: 4, letter_grade: 'A', credit_type: 'resident', status: 'in_progress', source: 'transcript_parse' },
]

const COMPLETED = [
  { id: 'cr-math151', term_id: FALL_2025_ID, institution_id: INSTITUTION_ID, course_code: 'MATH 151', title: 'Engineering Calculus I', credit_hours: 4, letter_grade: 'A', credit_type: 'resident', status: 'completed', source: 'transcript_parse' },
  { id: 'cr-csce120', term_id: SPRING_2026_ID, institution_id: INSTITUTION_ID, course_code: 'CSCE 120', title: 'Program Design and Concepts', credit_hours: 3, letter_grade: 'A', credit_type: 'resident', status: 'completed', source: 'transcript_parse' },
]

// PATCH mutates a grade here; each /profile read recomputes a projected GPA off
// it, so "the edit round-tripped" is observable as the header number changing.
const gradeState = new Map(IN_PROGRESS.map((c) => [c.id, c.letter_grade]))
const POINTS = { A: 4, 'A-': 3.7, 'B+': 3.3, B: 3, 'B-': 2.7, C: 2, D: 1, F: 0 }

function meProfileBody() {
  const courses = [
    ...COMPLETED,
    ...IN_PROGRESS.map((c) => ({ ...c, letter_grade: gradeState.get(c.id) })),
  ]
  let qp = 0
  let h = 0
  for (const c of courses) {
    const p = POINTS[c.letter_grade]
    if (p === undefined) continue
    qp += p * c.credit_hours
    h += c.credit_hours
  }
  const projected = Math.round((qp / h) * 100) / 100
  return {
    student: { id: 'student-verify', name: 'Verify Student', institution: 'Texas A&M University' },
    career: null,
    intelligence_profile: {
      contract_version: '1.0',
      identity: { student_id: 'student-verify', name: 'Verify Student', classification: 'Junior', expected_graduation: '2028-05', onboarding_stage: 3 },
      institution: { id: INSTITUTION_ID, name: 'Texas A&M University', relationship: 'home' },
      academics: {
        summary: { major_current: 'Computer Engineering', major_intended: null, confirmed_course_count: courses.length, completed_hours: 7, in_progress_hours: 12, earned_hours: 7 },
        terms: TERMS.map((t) => ({ id: t.id, institution_id: INSTITUTION_ID, label: t.label, year: t.year, season: t.season.toLowerCase(), sequence: t.sequence })),
        courses,
        gpa: { official: 3.7, projected, computable: true, in_progress_with_current_grade_count: 4, source: 'gpa_service' },
        repeat_exclusions: [],
      },
      career: { confirmed: false, target_roles: [], interests: [], career_goals: null, geographic_preference: null, ai_anxiety_level: null, skills: { technical: [], soft: [], ai_exposure: null }, certifications: [], work_experience: [], projects: [] },
      completeness: {
        career: { confirmed_profile: false, target_role_present: false, skills_present: false, certifications_present: false, work_experience_present: false, projects_present: false, ready_for_career_features: false },
        academics: { transcript_data_present: true, terms_present: true, gpa_computable: true, ready_for_academic_features: true },
        overall: 'partial',
      },
      provenance: { career_profile: null, certifications: [], work_experience: [], projects: [], academics: ['transcript_parse'], credit_type_limitation: null },
    },
  }
}

function respond(res, body, status = 200) {
  res.statusCode = status
  res.setHeader('content-type', 'application/json')
  res.end(JSON.stringify(body))
}

test('GPA Calculator term selector defaults to the in-progress term and survives grade edits', { timeout: 45_000 }, async (t) => {
  // Fresh grade state per run.
  for (const c of IN_PROGRESS) gradeState.set(c.id, c.letter_grade)

  const planning = planningRoutes({ terms: TERMS, upcomingTermKey: '2027-Spring' })
  const apiPlugin = {
    name: 'term-selector-api',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = req.url?.split('?')[0]
        if (planning.handle(path, req.method, req, res)) return undefined
        if (path === '/api/v2/student/me/profile' && req.method === 'GET') return respond(res, meProfileBody())
        if (path === '/api/v2/student/me/course-records/pending-final-grades') return respond(res, { pending_final_grades: [] })
        if (path?.startsWith('/api/v2/student/me/course-records/') && req.method === 'PATCH') {
          const id = path.split('/').pop()
          let body = ''
          req.on('data', (c) => { body += c })
          req.on('end', () => {
            const parsed = JSON.parse(body || '{}')
            if (parsed.letter_grade !== undefined && gradeState.has(id)) gradeState.set(id, parsed.letter_grade)
            respond(res, { id, ...parsed })
          })
          return undefined
        }
        if (path === '/api/v2/student/me/requirement-satisfaction') return respond(res, { detail: 'Not found.' }, 404)
        if (path?.startsWith('/api/v2/student/me/analysis-cache/')) return respond(res, { detail: 'Not found.' }, 404)
        return next()
      })
    },
  }

  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-term-selector', import.meta.url).pathname,
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

  await page.clock.setFixedTime(new Date('2026-09-06T12:00:00Z'))
  await page.route('**/rest/v1/institutions*', (route) =>
    route.fulfill({ status: 200, headers: { 'content-type': 'application/vnd.pgrst.object+json' }, body: JSON.stringify(null) }),
  )

  const termSelect = page.locator('#term-select')
  const projectedGpa = page
    .locator('.overview-stat', { hasText: 'Projected GPA' })
    .locator('.overview-stat-value')

  // Wait for the reload triggered by a grade edit to land, observed as the
  // header projection changing -- no fixed sleep.
  const awaitReprojection = (previous) =>
    page.waitForFunction(
      (prev) => {
        const stat = [...document.querySelectorAll('.overview-stat')]
          .find((n) => n.textContent?.includes('Projected GPA'))
        return stat?.querySelector('.overview-stat-value')?.textContent !== prev
      },
      previous,
      { timeout: 10_000 },
    )

  const editGrade = async (courseCode, grade) => {
    const before = await projectedGpa.textContent()
    await page
      .locator('.real-course-row--in-progress', { hasText: courseCode })
      .locator('select.current-grade-select')
      .selectOption(grade)
    await awaitReprojection(before)
  }

  await page.goto(`${origin}/transcript-preview.html#/dashboard`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'GPA Calculator' }).click()
  await termSelect.waitFor()

  // 1. Opens on the in-progress term, not the upcoming one, with the right
  //    badge and calendar range.
  assert.equal(await termSelect.inputValue(), '2026-Fall')
  await page.locator('.term-badge--in_progress').waitFor()
  await page.getByText('Aug 24, 2026 – Dec 10, 2026').waitFor()

  // 2. Its four in-progress courses render under Coursework.
  for (const code of ['PHYS 207', 'PHYS 217', 'CSCE 222', 'ECEN 248']) {
    await page.locator('[aria-label="Coursework in this term"]').getByText(code).waitFor()
  }

  // 3. Editing one of them leaves the dropdown on Fall 2026 and moves the
  //    projected GPA -- the original regression.
  const projBeforeEdit = await projectedGpa.textContent()
  await editGrade('CSCE 222', 'C')
  assert.equal(await termSelect.inputValue(), '2026-Fall')
  assert.notEqual(await projectedGpa.textContent(), projBeforeEdit)

  // 4. An explicit pick of a different term is not clobbered by a later grade
  //    edit's reload, nor by TermPlanner re-rendering when a planned course is
  //    added.
  await termSelect.selectOption('2027-Spring')
  assert.equal(await termSelect.inputValue(), '2027-Spring')
  await termSelect.selectOption('2026-Fall')
  await editGrade('ECEN 248', 'B')
  await termSelect.selectOption('2027-Spring')
  assert.equal(await termSelect.inputValue(), '2027-Spring')

  // 5. Planning still works on the upcoming term; the planned row keeps its
  //    badge and its "not counted" caveat, and the selector stays put.
  await page.locator('#course-search').fill('CSCE 2')
  await page.getByText('Data Structures and Algorithms').waitFor()
  await page.getByRole('button', { name: 'Add' }).first().click()
  await page.locator('.real-course-row--planned').first().waitFor()
  await page.locator('.real-course-row--planned .planned-badge').first().waitFor()
  await page.getByText(/not counted in GPA or hours/i).waitFor()
  assert.equal(await termSelect.inputValue(), '2027-Spring')
})
