import assert from 'node:assert/strict'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { planningRoutes } from './fixtures/planningRoutes.mjs'

const academic = {
  student_id: 'sid', program_id: 'pid', status: 'SCHEDULED', failure: null,
  terms: [{
    term_key: '2026-Fall', total_credit_hours: 6,
    courses: [
      { course_code: 'CS 5323', credit_hours: 3, requirement_group_id: 'g-choice', limitations: [] },
      { course_code: 'MATH 3304', credit_hours: 3, requirement_group_id: 'g-fixed', limitations: [] },
    ],
  }],
  unscheduled: [],
}

const optimized = {
  ...academic,
  terms: [{
    term_key: '2026-Fall', total_credit_hours: 6,
    courses: [
      { course_code: 'CS 5316', credit_hours: 3, requirement_group_id: 'g-choice', limitations: [] },
      { course_code: 'MATH 3304', credit_hours: 3, requirement_group_id: 'g-fixed', limitations: [] },
    ],
  }],
}

function careerResponse(status = 'OPTIMIZED', { noChange = false } = {}) {
  const successful = status === 'OPTIMIZED' || status === 'PARTIAL'
  return {
    feature: 'CAREER_OPTIMIZED_SCHEDULE', status,
    selection_basis: successful ? 'CAREER_RANKED' : 'ACADEMIC_DEFAULT',
    target_role: 'Software Engineering Intern', fingerprint: successful ? 'fp' : null,
    generated_at: '2026-08-20T12:00:00Z', cache_status: 'MISS',
    academic_schedule: academic,
    optimized_schedule: successful && !noChange ? optimized : academic,
    requirement_rankings: successful ? [{
      requirement_group_id: 'g-choice',
      ranked_candidates: [{
        candidate_id: 'candidate-cs5316', rank: 1,
        ranking_reason: 'Stronger software engineering alignment.',
        skill_alignment_explanation: 'Supports software design and systems skills.',
      }],
    }] : [],
    ranking_failures: status === 'PARTIAL' ? [{
      requirement_group_id: 'g-other', requirement_name: 'Other choice',
      error_code: 'RANKING_UNAVAILABLE', detail: 'Unavailable.',
    }] : [],
    ranking_prompt_version: '1', resolved_model: 'test-model',
    summary: status === 'SKIPPED' ? 'Confirm one target role before optimizing.' : null,
  }
}

test('Career Optimize stays opt-in and preserves the academic plan through every result state', { timeout: 60_000 }, async (t) => {
  const planning = planningRoutes({ terms: [] })
  const posts = []
  let resolvePostReceived
  const postReceived = new Promise((resolve) => { resolvePostReceived = resolve })
  let response = { status: 200, body: careerResponse() }
  let releaseFirst
  let delayNext = true
  const firstGate = new Promise((resolve) => { releaseFirst = resolve })

  const apiPlugin = {
    name: 'career-optimization-api',
    configureServer(server) {
      server.middlewares.use((request, serverResponse, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, serverResponse)) return undefined
        if (path === '/api/v2/student/me/schedule' && request.method === 'GET') {
          serverResponse.setHeader('content-type', 'application/json')
          serverResponse.end(JSON.stringify(academic))
          return
        }
        if (path === '/api/v2/student/me/requirement-satisfaction' && request.method === 'GET') {
          serverResponse.setHeader('content-type', 'application/json')
          serverResponse.end(JSON.stringify({ student_id: 'sid', program_id: 'pid', groups: [] }))
          return
        }
        if (path === '/api/v2/student/me/schedule/career-optimize' && request.method === 'POST') {
          let raw = ''
          request.on('data', (chunk) => { raw += chunk })
          request.on('end', async () => {
            posts.push(JSON.parse(raw))
            resolvePostReceived()
            if (delayNext) { delayNext = false; await firstGate }
            serverResponse.statusCode = response.status
            serverResponse.setHeader('content-type', 'application/json')
            serverResponse.end(JSON.stringify(response.body))
          })
          return
        }
        if (request.url?.startsWith('/api/v2/student/me/analyze/')) {
          serverResponse.setHeader('content-type', 'application/json')
          serverResponse.end(JSON.stringify({ feature: 'GAP', status: 'skipped', summary: '', data: {}, errors: [], missing_fields: [] }))
          return
        }
        next()
      })
    },
  }

  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-career-optimization', import.meta.url).pathname,
    logLevel: 'silent', plugins: [apiPlugin], server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  await page.route('**/rest/v1/institutions*', (route) => route.fulfill({ status: 200, headers: { 'content-type': 'application/vnd.pgrst.object+json' }, body: 'null' }))

  await page.goto(`http://127.0.0.1:${address.port}/authenticated-dashboard-preview.html?mode=complete`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()
  const degreePanel = page.locator('.degree-schedule-panel')
  // CS 5323 is scheduler headroom -- it now lives in the Edit-courses popup,
  // not on the card. The rendered term column is the "academic plan is
  // showing" proxy.
  const academicPlanColumn = degreePanel.getByRole('region', { name: 'Fall 2026' })
  await academicPlanColumn.waitFor()
  assert.equal(posts.length, 0, 'mount must issue no Career Optimize POST')

  const careerPanel = page.locator('.career-optimization')
  await careerPanel.getByText('Software Engineer').waitFor()
  assert.match(await careerPanel.textContent(), /optional preview/)
  const optimize = careerPanel.locator('button').first()
  await optimize.click()
  await careerPanel.getByText('Finding career-aligned choices…').waitFor()
  assert.equal(await optimize.isDisabled(), true)
  assert.equal(await academicPlanColumn.count() > 0, true, 'academic plan remains visible while loading')
  await postReceived
  assert.equal(posts.length, 1)
  assert.deepEqual(posts[0], { force_refresh: false })
  releaseFirst()

  await careerPanel.getByText('Career optimized').waitFor()
  await careerPanel.getByText('Stronger software engineering alignment.').waitFor()
  await careerPanel.getByText('Supports software design and systems skills.').waitFor()
  assert.match(await careerPanel.textContent(), /1 degree choice changed/)
  assert.match(await careerPanel.textContent(), /Graduation timing did not change/)
  assert.match(await careerPanel.textContent(), /Removed/)
  assert.match(await careerPanel.textContent(), /Added/)
  assert.doesNotMatch(await careerPanel.textContent(), /Degree requirement choice 1/)
  const disclosure = careerPanel.getByRole('button', { name: 'View complete career-optimized schedule' })
  assert.equal(await disclosure.getAttribute('aria-expanded'), 'false')
  await disclosure.click()
  assert.match(await careerPanel.textContent(), /Nothing has been added to your official or planned coursework/)
  await careerPanel.getByRole('button', { name: 'Academic schedule' }).click()
  assert.equal(await careerPanel.getByRole('button', { name: 'Academic schedule' }).getAttribute('aria-pressed'), 'true')

  await careerPanel.getByRole('button', { name: 'Refresh career optimization' }).click()
  await careerPanel.getByText('Career optimized').waitFor()
  assert.deepEqual(posts.at(-1), { force_refresh: true })

  response = { status: 200, body: careerResponse('OPTIMIZED', { noChange: true }) }
  await page.reload()
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()
  await page.locator('.career-optimization').getByRole('button', { name: 'Optimize for career' }).click()
  await page.getByText(/already matches the strongest career-aligned choices/).waitFor()
  assert.equal(await page.getByRole('button', { name: 'View complete career-optimized schedule' }).count(), 0)

  response = { status: 200, body: careerResponse('PARTIAL') }
  await page.reload()
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()
  await page.locator('.career-optimization').getByRole('button', { name: 'Optimize for career' }).click()
  await page.getByText('Some degree choices were career-ranked').waitFor()

  response = { status: 200, body: careerResponse('FALLBACK') }
  await page.reload()
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()
  await page.locator('.career-optimization').getByRole('button', { name: 'Optimize for career' }).click()
  await page.getByText("Career optimization wasn't available right now").waitFor()
  assert.equal(await page.locator('.degree-schedule-panel').getByRole('region', { name: 'Fall 2026' }).count() > 0, true)

  response = { status: 200, body: careerResponse('SKIPPED') }
  await page.reload()
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()
  await page.locator('.career-optimization').getByRole('button', { name: 'Optimize for career' }).click()
  await page.getByText('Confirm one target role before optimizing.').waitFor()

  response = { status: 502, body: { detail: 'Ranking service is busy.' } }
  await page.reload()
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()
  await page.locator('.career-optimization').getByRole('button', { name: 'Optimize for career' }).click()
  await page.getByText('Ranking service is busy. Your academic plan remains unchanged.').waitFor()
  assert.equal(await page.locator('.degree-schedule-panel').getByRole('region', { name: 'Fall 2026' }).count() > 0, true)

  await page.setViewportSize({ width: 390, height: 844 })
  const overflow = await page.locator('.degree-planner-flow').evaluate((element) => element.scrollWidth - element.clientWidth)
  assert.ok(overflow <= 1, `career optimization panel overflows mobile by ${overflow}px`)
})
