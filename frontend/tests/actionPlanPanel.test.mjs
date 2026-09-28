import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { planningRoutes } from './fixtures/planningRoutes.mjs'

const need = (skill, needId) => ({
  need_id: needId,
  skill,
  category: 'skills',
  target_role: 'Robotics Engineer',
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

function verifiedCourse(code, title, overrides = {}) {
  return {
    institution: 'tamu',
    course_code: code,
    title,
    description: '',
    credit_min: 3,
    credit_max: 3,
    matched_needs: [need('Controls', `need_${code.replace(/\s/g, '')}`)],
    match_kinds: ['MATCHED_TITLE'],
    matched_terms: [],
    student_status: 'NOT_TAKEN',
    prerequisite_status: 'ELIGIBLE',
    prerequisite_evaluation: null,
    eligibility_status: 'ELIGIBLE',
    provenance: provenance(code),
    ranking_reason: `Builds toward Robotics Engineer.`,
    skill_alignment_explanation: null,
    degree_applicability: 'UNKNOWN',
    offering_status: 'UNKNOWN',
    ...overrides,
  }
}

function discoveryResult(verified = []) {
  return {
    target_role: 'Robotics Engineer',
    current_major: 'Computer Science',
    intended_major: 'Computer Science',
    career_needs: [need('Controls', 'need_ctl1')],
    verified_recommendations: verified,
    requires_verification: [],
    prerequisite_blocked: [],
    summary: `Verified ${verified.length} institution-scoped course recommendation(s).`,
    degree_applicability: 'UNKNOWN',
    offering_status: 'UNKNOWN',
  }
}

function featureResult(data) {
  return { feature: 'COURSE_DISCOVERY', status: 'success', summary: data.summary, data, errors: [] }
}

function planNode(nodeId, sourceRef = nodeId) {
  return { node_id: nodeId, node_type: 'course', source_ref: sourceRef, status: 'OPEN' }
}

function requiresEdge(fromId, toId) {
  return { from_node_id: fromId, to_node_id: toId, relation: 'requires' }
}

const CSCE221 = 'course:tamu:CSCE 221'
const CSCE331 = 'course:tamu:CSCE 331'
const CSCE411 = 'course:tamu:CSCE 411'
const ECEN248 = 'course:tamu:ECEN 248'

test('Action Plan preview: CTA lifecycle, ordering, dependency text, unconstrained actions, COMPLETE/PROVISIONAL, errors, invalidation, responsiveness', { timeout: 60_000 }, async (t) => {
  const planning = planningRoutes({ terms: [] })
  const actionPlanRequests = []
  let discoveryResponse = { status: 200, body: featureResult(discoveryResult([verifiedCourse('CSCE 221', 'Data Structures and Algorithms')])) }
  let actionPlanResponse = {
    status: 200,
    body: {
      feature: 'ACTION_PLAN',
      status: 'success',
      summary: 'ok',
      action_plan: {
        target_role: 'Robotics Engineer',
        nodes: [planNode(CSCE221), planNode(CSCE331)],
        edges: [requiresEdge(CSCE331, CSCE221)],
        conflicts: [],
        execution_status: 'SUCCESS',
        failure: null,
        summary: 'plan',
      },
      dependency_order: {
        ordered_node_ids: [CSCE221, CSCE331],
        unconstrained_node_ids: [],
        completeness: 'COMPLETE',
        limitations: [],
        status: 'ORDERED',
        failure: null,
      },
    },
  }

  const apiPlugin = {
    name: 'action-plan-api',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/analyze/course-discovery' && request.method === 'POST') {
          response.statusCode = discoveryResponse.status
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify(discoveryResponse.body))
          return
        }
        if (path === '/api/v2/student/me/action-plan' && request.method === 'POST') {
          let body = ''
          request.on('data', (chunk) => { body += chunk })
          request.on('end', () => {
            actionPlanRequests.push({ raw: body, authorization: request.headers.authorization })
            response.statusCode = actionPlanResponse.status
            response.setHeader('content-type', 'application/json')
            response.end(JSON.stringify(actionPlanResponse.body))
          })
          return
        }
        if (request.url?.startsWith('/api/v2/student/me/analyze/')) {
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
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-action-plan', import.meta.url)),
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

  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete`)
  // Course Discovery lives under Academic's own "Course Discovery" child nav
  // item, not inside Career.
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()
  const panel = page.locator('.card.analysis-panel', { has: page.getByRole('heading', { name: 'Course Discovery' }) })

  // ── CTA only appears once Course Discovery has succeeded ──────────────────
  assert.equal(await panel.getByRole('button', { name: 'Build my course path' }).count(), 0)
  await panel.getByRole('button', { name: 'Run analysis' }).click()
  await panel.getByText('Recommended courses').waitFor()
  const cta = panel.getByRole('button', { name: 'Build my course path' })
  await cta.waitFor()

  // ── loading state ──────────────────────────────────────────────────────────
  let releaseLoading
  const loadingGate = new Promise((resolve) => { releaseLoading = resolve })
  await page.route('**/api/v2/student/me/action-plan', async (route) => {
    await loadingGate
    await route.continue()
  })
  await cta.click()
  await panel.getByText('Working out the dependency order for your course path…').waitFor()
  releaseLoading()
  await page.unroute('**/api/v2/student/me/action-plan')

  // ── simple chain: B requires A displays A before B, with direct text ──────
  await panel.getByText('Suggested dependency order').waitFor()
  const orderedItems = panel.locator('.action-plan-ordered-item')
  assert.equal(await orderedItems.count(), 2)
  assert.match(await orderedItems.nth(0).innerText(), /CSCE 221/)
  assert.match(await orderedItems.nth(1).innerText(), /CSCE 331/)
  const orderedItemFor = (code) =>
    panel.locator(`.action-plan-ordered-item:has(.action-plan-item-label:text("${code}"))`)
  const item331 = orderedItemFor('CSCE 331')
  await item331.getByText('Requires: CSCE 221').waitFor()
  // direction is not reversed
  const item221 = orderedItemFor('CSCE 221')
  assert.equal(await item221.getByText(/Requires:/).count(), 0)

  // ── request sent only target_role, matching the role the results are for ──
  const lastPlanRequest = actionPlanRequests.at(-1)
  assert.deepEqual(JSON.parse(lastPlanRequest.raw), { target_role: 'Robotics Engineer' })
  assert.ok(lastPlanRequest.authorization)

  // ── COMPLETE state copy is scoped to dependency ordering ──────────────────
  await panel.getByText('Dependency order complete').waitFor()
  await panel.getByText('The prerequisites currently known for these actions can be represented in this course path.').waitFor()
  assert.equal(await panel.getByText(/graduat/i).count(), 0)

  // ── target-role change / Course Discovery rerun invalidates stale plan ────
  discoveryResponse = {
    status: 200,
    body: featureResult(discoveryResult([verifiedCourse('CSCE 221', 'Data Structures and Algorithms')])),
  }
  await panel.getByRole('button', { name: 'Re-run analysis' }).click()
  await panel.getByText('Recommended courses').waitFor()
  assert.equal(await panel.getByText('Suggested dependency order').count(), 0)
  assert.equal(await panel.getByText('Dependency order complete').count(), 0)
  await panel.getByRole('button', { name: 'Build my course path' }).waitFor()

  // ── fan-in: C requires A, C requires B -- no adjacency-implied A requires B,
  //    fan-out ordering, unconstrained actions shown separately ─────────────
  actionPlanResponse = {
    status: 200,
    body: {
      feature: 'ACTION_PLAN',
      status: 'success',
      summary: 'ok',
      action_plan: {
        target_role: 'Robotics Engineer',
        nodes: [planNode(CSCE221), planNode(CSCE331), planNode(CSCE411), planNode(ECEN248)],
        edges: [requiresEdge(CSCE411, CSCE221), requiresEdge(CSCE411, CSCE331)],
        conflicts: [],
        execution_status: 'SUCCESS',
        failure: null,
        summary: 'plan',
      },
      dependency_order: {
        ordered_node_ids: [CSCE221, CSCE331, CSCE411],
        unconstrained_node_ids: [ECEN248],
        completeness: 'COMPLETE',
        limitations: [],
        status: 'ORDERED',
        failure: null,
      },
    },
  }
  await panel.getByRole('button', { name: 'Build my course path' }).click()
  await panel.getByText('Suggested dependency order').waitFor()
  const item411 = orderedItemFor('CSCE 411')
  await item411.getByText(/Requires:.*CSCE 221.*CSCE 331/).waitFor()
  // adjacency between CSCE 221 and CSCE 331 (both fan-in prerequisites of 411,
  // not of each other) must not be implied
  assert.equal(await item331.getByText(/Requires:/).count(), 0)
  await panel.getByText('Can be considered independently').waitFor()
  await panel.getByText('No prerequisite order constrains these.').waitFor()
  const unconstrained = panel.locator('.action-plan-unconstrained-list li')
  assert.equal(await unconstrained.count(), 1)
  assert.match(await unconstrained.first().innerText(), /ECEN 248/)
  // not given a sequence number alongside ordered items
  assert.equal(await panel.locator('.action-plan-ordered-item', { hasText: 'ECEN 248' }).count(), 0)

  // ── PROVISIONAL: ANY limitation, unknown-course limitation ────────────────
  actionPlanResponse = {
    status: 200,
    body: {
      feature: 'ACTION_PLAN',
      status: 'success',
      summary: 'ok',
      action_plan: {
        target_role: 'Robotics Engineer',
        nodes: [planNode(CSCE221)],
        edges: [],
        conflicts: [],
        execution_status: 'SUCCESS',
        failure: null,
        summary: 'plan',
      },
      dependency_order: {
        ordered_node_ids: [CSCE221],
        unconstrained_node_ids: [],
        completeness: 'PROVISIONAL',
        limitations: [
          { node_id: CSCE331, reason_type: 'ANY_PREREQUISITE', course_codes: ['CSCE 121', 'CSCE 181'] },
          { node_id: CSCE411, reason_type: 'UNKNOWN_COURSE_STATE', course_codes: ['CSCE 350'] },
          { node_id: ECEN248, reason_type: 'UNRESOLVED_PREREQUISITE', course_codes: [] },
        ],
        status: 'ORDERED',
        failure: null,
      },
    },
  }
  await panel.getByRole('button', { name: 'Re-run analysis' }).click()
  await panel.getByText('Recommended courses').waitFor()
  await panel.getByRole('button', { name: 'Build my course path' }).click()
  await panel.getByText('Dependency order provisional').waitFor()
  await panel.getByText('Some prerequisite choices still need to be resolved.').waitFor()
  await panel.getByText('CSCE 331 requires one of: CSCE 121 / CSCE 181').waitFor()
  assert.equal(await panel.getByText('CSCE 331 requires: CSCE 121 and CSCE 181').count(), 0)
  await panel.getByText("We couldn't confirm your status for: CSCE 350").waitFor()
  assert.equal(await panel.getByText(/CSCE 350.*missing/i).count(), 0)
  await panel.getByText('this prerequisite could not be represented safely from the catalog evidence.').waitFor()

  // ── typed plan ERROR (safe_message, no error_class leak) ───────────────────
  actionPlanResponse = {
    status: 200,
    body: {
      feature: 'ACTION_PLAN',
      status: 'failed',
      summary: 'Graph assembly aborted.',
      action_plan: {
        target_role: 'Robotics Engineer',
        nodes: [],
        edges: [],
        conflicts: [],
        execution_status: 'ERROR',
        failure: { category: 'PLANNER_FAILURE', error_class: 'CycleDetected', safe_message: 'The dependency graph contains a cycle and cannot be planned safely.' },
        summary: 'Graph assembly aborted.',
      },
      dependency_order: null,
    },
  }
  await panel.getByRole('button', { name: 'Re-run analysis' }).click()
  await panel.getByText('Recommended courses').waitFor()
  await panel.getByRole('button', { name: 'Build my course path' }).click()
  await panel.getByText('The dependency graph contains a cycle and cannot be planned safely.').waitFor()
  assert.equal(await panel.getByText('CycleDetected').count(), 0)
  await panel.getByRole('button', { name: 'Try again' }).waitFor()

  // ── typed dependency-order ERROR (distinct from plan ERROR) ────────────────
  actionPlanResponse = {
    status: 200,
    body: {
      feature: 'ACTION_PLAN',
      status: 'success',
      summary: 'ok',
      action_plan: {
        target_role: 'Robotics Engineer',
        nodes: [planNode(CSCE221)],
        edges: [],
        conflicts: [],
        execution_status: 'SUCCESS',
        failure: null,
        summary: 'plan',
      },
      dependency_order: {
        ordered_node_ids: [],
        unconstrained_node_ids: [],
        completeness: 'COMPLETE',
        limitations: [],
        status: 'ERROR',
        failure: { category: 'PLANNER_FAILURE', error_class: 'OrderingFailure', safe_message: 'The dependency order could not be computed safely.' },
      },
    },
  }
  await panel.getByRole('button', { name: 'Try again' }).click()
  await panel.getByText('The dependency order could not be computed safely.').waitFor()
  assert.equal(await panel.getByText('OrderingFailure').count(), 0)

  // ── transport failure + retry ──────────────────────────────────────────────
  actionPlanResponse = { status: 502, body: { detail: 'Action plan preview is unavailable.' } }
  await panel.getByRole('button', { name: 'Try again' }).click()
  await panel.locator('.action-plan-section .analysis-failed').waitFor()
  const transportFailureText = await panel.locator('.action-plan-section .analysis-failed').innerText()
  assert.equal(/Traceback|Exception|at\s+\S+\.(py|ts|tsx):\d+/.test(transportFailureText), false)

  // ── no skill_need nodes rendered as dependency actions ─────────────────────
  actionPlanResponse = {
    status: 200,
    body: {
      feature: 'ACTION_PLAN',
      status: 'success',
      summary: 'ok',
      action_plan: {
        target_role: 'Robotics Engineer',
        nodes: [{ node_id: 'skill_need:need_ctl1', node_type: 'skill_need', source_ref: 'need_ctl1', status: 'OPEN' }, planNode(CSCE221)],
        edges: [{ from_node_id: CSCE221, to_node_id: 'skill_need:need_ctl1', relation: 'satisfies' }],
        conflicts: [],
        execution_status: 'SUCCESS',
        failure: null,
        summary: 'plan',
      },
      dependency_order: {
        ordered_node_ids: [CSCE221],
        unconstrained_node_ids: [],
        completeness: 'COMPLETE',
        limitations: [],
        status: 'ORDERED',
        failure: null,
      },
    },
  }
  await panel.getByRole('button', { name: 'Try again' }).click()
  await panel.getByText('Suggested dependency order').waitFor()
  assert.equal(await panel.locator('.action-plan-ordered-item').count(), 1)
  assert.equal(await panel.getByText('need_ctl1').count(), 0)
  assert.equal(await panel.getByText('skill_need').count(), 0)

  // ── stable IDs resolve to human labels; fallback to code when unavailable ──
  await panel.getByText('CSCE 221 — Data Structures and Algorithms').first().waitFor()

  // ── responsive: 390 / 834 / 1280, no page-level horizontal overflow ───────
  for (const width of [390, 834, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
      true,
      `page overflows horizontally at ${width}px`,
    )
  }
})
