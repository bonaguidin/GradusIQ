import assert from 'node:assert/strict'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { planningRoutes } from './fixtures/planningRoutes.mjs'

// Phase 3: decisions no longer live in a standalone "Decisions needed" /
// "Your academic choices" section -- LOCKED / CHOICE_REQUIRED / EXCLUDED
// cards are rendered inside the term column the backend resolved for each
// (schedule.decisions[].resolved_term_key), and ADVISER_REVIEW /
// DATA_UNRESOLVED / freeform-manual-review requirements are not surfaced at
// all. RESELECTION_REQUIRED stays a top-level alert above the year grid.

const candidate = (id, requirementId, requirementName, codes, credits, termIndex) => ({
  candidate_id: id, requirement_group_id: requirementId, requirement_name: requirementName,
  course_codes: codes, unresolved_course_codes: [],
  candidate_courses: codes.map((code, index) => ({
    course_code: code,
    title: code === 'ABC 123' ? null : `${code} catalog title`,
    credits: code === 'ABC 123' ? null : credits[index],
  })),
  existing_contribution: 0, additional_course_count: codes.length,
  additional_credits: credits.reduce((total, value) => total + value, 0),
  academic_feasibility: 'FEASIBLE', completion_term_index: termIndex,
  limitations: [], source_order: [], exclusion_reasons: [], exclusion_details: [],
})

const excludedCandidate = (id, requirementId, requirementName, code) => ({
  candidate_id: id, requirement_group_id: requirementId, requirement_name: requirementName,
  course_codes: [code], unresolved_course_codes: [],
  candidate_courses: [{ course_code: code, title: `${code} catalog title`, credits: 3 }],
  existing_contribution: 0, additional_course_count: 1, additional_credits: 3,
  academic_feasibility: 'EXCLUDED', completion_term_index: null,
  limitations: [], source_order: [], exclusion_reasons: ['UNSCHEDULABLE'], exclusion_details: [],
})

test('Degree Schedule decisions render on their resolved term card; non-card states are absent; reselection stays top-level', { timeout: 60_000 }, async (t) => {
  const histPrimary = candidate('hist-1301', 'locked', 'American History', ['HIST 1301'], [3], 0)
  const histAlt = candidate('hist-1302', 'locked', 'American History', ['HIST 1302'], [3], 1)
  const statSingle = candidate('single', 'choice', 'Statistical Methods', ['ABC 123'], [3], 1)
  const statMulti = candidate('multi', 'choice', 'Statistical Methods', ['CEE 2302', 'CS 3377'], [3, 3], 2)
  const techExcluded = excludedCandidate('excl-1', 'excluded', 'Technical Elective', 'CSCE 4901')
  const mysteryExcluded = excludedCandidate('excl-2', 'excluded-noterm', 'Mystery Elective', 'MYST 1000')

  const schedule = {
    student_id: 'sid', program_id: 'pid', status: 'SCHEDULED', failure: null,
    schedule_version: `sha256:${'a'.repeat(64)}`,
    selection_state: {
      status: 'APPLIED',
      selections: [{ requirement_group_id: 'locked', candidate_id: 'hist-1301', course_codes: ['HIST 1301'] }],
      failure: null,
    },
    exclusion_state: { excluded_group_ids: ['excluded', 'excluded-noterm'] },
    terms: [{
      term_key: '2027-Fall', total_credit_hours: 6, courses: [
        { course_code: 'MATH 2413', credit_hours: 3, requirement_group_id: 'auto', limitations: [] },
        { course_code: 'HIST 1301', credit_hours: 3, requirement_group_id: 'locked', limitations: [] },
      ],
    }],
    decisions: [
      { requirement_group_id: 'auto', requirement_name: 'Calculus', state: 'AUTO_SELECTED', feasible_candidate_ids: ['auto'], excluded_candidate_ids: [], selected_candidate_id: 'auto', resolved_term_key: null },
      { requirement_group_id: 'locked', requirement_name: 'American History', state: 'LOCKED', feasible_candidate_ids: ['hist-1301', 'hist-1302'], excluded_candidate_ids: [], selected_candidate_id: 'hist-1301', resolved_term_key: '2027-Fall' },
      { requirement_group_id: 'choice', requirement_name: 'Statistical Methods', state: 'CHOICE_REQUIRED', feasible_candidate_ids: ['single', 'multi'], excluded_candidate_ids: [], selected_candidate_id: null, resolved_term_key: '2028-Spring' },
      { requirement_group_id: 'excluded', requirement_name: 'Technical Elective', state: 'EXCLUDED', feasible_candidate_ids: [], excluded_candidate_ids: ['excl-1'], selected_candidate_id: null, resolved_term_key: '2028-Fall' },
      { requirement_group_id: 'excluded-noterm', requirement_name: 'Mystery Elective', state: 'EXCLUDED', feasible_candidate_ids: [], excluded_candidate_ids: ['excl-2'], selected_candidate_id: null, resolved_term_key: null },
      { requirement_group_id: 'review', requirement_name: 'Restricted Elective', state: 'ADVISER_REVIEW', feasible_candidate_ids: [], excluded_candidate_ids: ['reviewed'], selected_candidate_id: null, resolved_term_key: null },
      { requirement_group_id: 'unknown', requirement_name: 'Unstructured Requirement', state: 'DATA_UNRESOLVED', feasible_candidate_ids: [], excluded_candidate_ids: ['unknown'], selected_candidate_id: null, resolved_term_key: null },
    ],
    candidate_sets: [
      { requirement_group_id: 'locked', requirement_name: 'American History', feasible_candidates: [histPrimary, histAlt], excluded_candidates: [] },
      { requirement_group_id: 'choice', requirement_name: 'Statistical Methods', feasible_candidates: [statSingle, statMulti], excluded_candidates: [] },
      { requirement_group_id: 'excluded', requirement_name: 'Technical Elective', feasible_candidates: [], excluded_candidates: [techExcluded] },
      { requirement_group_id: 'excluded-noterm', requirement_name: 'Mystery Elective', feasible_candidates: [], excluded_candidates: [mysteryExcluded] },
    ],
    unscheduled: [
      { requirement_group_id: 'choice', name: 'Statistical Methods', reason: 'SELECTION_DEFERRED' },
      { requirement_group_id: 'ucc', name: 'University Core Curriculum', reason: 'FREEFORM_MANUAL_REVIEW' },
    ],
  }

  const putBodies = []
  // Only 2025-Fall is a real (past) calendar term; every future column is
  // driven by schedule.terms + resolved_term_key, so the columns carrying
  // decision cards are unambiguously 'future' regardless of the wall clock.
  const planning = planningRoutes({
    terms: [{
      key: '2025-Fall', id: 'term-1', label: 'Fall 2025', year: 2025, season: 'Fall',
      sequence: 1, start_date: '2025-08-25', end_date: '2025-12-10', enrolled: true, is_upcoming: false,
    }],
    upcomingTermKey: '2027-Fall',
  })
  const apiPlugin = {
    name: 'degree-schedule-term-decisions-api',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/schedule' && request.method === 'GET') {
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify(schedule))
          return
        }
        if (path === '/api/v2/student/me/schedule/choices' && request.method === 'PUT') {
          let raw = ''
          request.on('data', (chunk) => { raw += chunk })
          request.on('end', () => {
            const body = JSON.parse(raw)
            putBodies.push(body)
            const chosen = body.selections.find((selection) => selection.requirement_group_id === 'choice')
            schedule.schedule_version = `sha256:${'b'.repeat(64)}`
            schedule.selection_state = { status: 'APPLIED', selections: body.selections, failure: null }
            if (chosen) {
              schedule.decisions = schedule.decisions.map((decision) => decision.requirement_group_id === 'choice'
                ? { ...decision, state: 'LOCKED', selected_candidate_id: chosen.candidate_id }
                : decision)
            }
            response.setHeader('content-type', 'application/json')
            response.end(JSON.stringify({ status: 'APPLIED', schedule_version: schedule.schedule_version, selections: body.selections }))
          })
          return
        }
        if (path === '/api/v2/student/me/requirement-satisfaction' && request.method === 'GET') {
          response.setHeader('content-type', 'application/json')
          response.end(JSON.stringify({ student_id: 'sid', program_id: 'pid', groups: [] }))
          return
        }
        next()
      })
    },
  }
  const server = await createServer({
    root: new URL('..', import.meta.url).pathname,
    cacheDir: new URL('../node_modules/.vite-degree-schedule-term-decisions', import.meta.url).pathname,
    logLevel: 'silent', plugins: [apiPlugin], server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  await page.route('**/rest/v1/institutions*', (route) => route.fulfill({ status: 200, body: 'null' }))
  await page.goto(`http://127.0.0.1:${address.port}/authenticated-dashboard-preview.html?mode=complete`)
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'Course Discovery' }).click()

  const years = page.locator('.degree-schedule-years')
  await years.waitFor()

  // The "Third year" tab only exists because the EXCLUDED decision resolves
  // to 2028-Fall -- waiting for it proves /me/terms, the schedule, and the
  // decision bucketing have all landed before any assertion runs.
  await page.getByRole('tab', { name: 'Third year' }).waitFor()

  // The standalone decision section is gone entirely.
  assert.equal(await page.getByText('Decisions needed to complete your plan').count(), 0)
  assert.equal(await page.getByText('Your academic choices').count(), 0)

  // ── Second year: LOCKED on Fall, CHOICE_REQUIRED on Spring ──────────────
  await page.getByRole('tab', { name: 'Second year' }).click()
  await page.getByRole('region', { name: 'Fall 2027' }).waitFor()

  const fall2027 = page.getByRole('region', { name: 'Fall 2027' })
  await fall2027.getByText('HIST 1301', { exact: true }).waitFor()

  // ── The resting (non-changing) LOCKED view is full visual parity with the
  //    Fall/planned plain rows: no bordered/backgrounded decision-card, no
  //    per-card heading naming the requirement, no "Selected" label, no
  //    per-group credits total. ────────────────────────────────────────────
  assert.equal(await fall2027.locator('.degree-schedule-locked-decision').count(), 1)
  assert.equal(await fall2027.locator('.degree-schedule-decision-card').count(), 0)
  assert.equal(await fall2027.getByText('American History').count(), 0)
  assert.equal(await fall2027.getByText('Selected', { exact: true }).count(), 0)
  assert.doesNotMatch(await fall2027.textContent(), /total/)
  assert.equal(await fall2027.getByRole('button', { name: 'Change choice' }).count(), 1)
  assert.equal(await fall2027.getByRole('button', { name: 'Clear choice' }).count(), 1)
  // Plain text-style actions, not the boxed btn-secondary/btn-ghost pair.
  assert.equal(await fall2027.locator('.degree-schedule-text-action').count(), 2)
  assert.equal(await fall2027.getByRole('button', { name: 'Change choice' }).evaluate((el) => el.className), 'degree-schedule-text-action')

  // ── The requirement-name signal moved to the term header: "Required
  //    courses" rides in the same span as the totalCreditsLabel text (here
  //    "Not scheduled"), not a new competing label, and only shows up on a
  //    term that actually has a LOCKED decision. ─────────────────────────
  const fall2027HeaderNote = fall2027.locator('.degree-schedule-semester-header span')
  assert.equal(await fall2027HeaderNote.textContent(), 'Not scheduled · Required courses')

  // ── A LOCKED card has exactly one candidate, already chosen -- the nested
  //    "Option 1" box was pure redundancy and is gone. Its course rows
  //    render directly inside the card, with no bordered wrapper. ─────────
  assert.equal(await fall2027.getByText('Option 1').count(), 0)
  assert.equal(await fall2027.locator('.degree-schedule-candidate-path').count(), 0)
  const histRow = fall2027.locator('.degree-schedule-candidate-courses > li').filter({ hasText: 'HIST 1301' })
  await histRow.first().waitFor()
  assert.equal(await histRow.locator('.degree-schedule-course-row').count(), 1)
  assert.equal(await histRow.getByText('3 credits').count(), 1)
  assert.equal(await histRow.getByText('Planned course').count(), 1)

  // ── "Change choice" on a LOCKED card flips to a genuine multi-candidate
  //    menu (this fixture's American History group has 2 feasible
  //    candidates) -- that view still needs the "Option N" box to
  //    distinguish them, the same reason CHOICE_REQUIRED keeps it, and it
  //    keeps the boxed decision-card treatment + "Selected" label. ────────
  await fall2027.getByRole('button', { name: 'Change choice' }).click()
  assert.equal(await fall2027.locator('.degree-schedule-decision-card.is-locked').count(), 1)
  assert.equal(await fall2027.locator('.degree-schedule-locked-decision').count(), 0)
  assert.equal(await fall2027.getByText('Selected', { exact: true }).count() >= 1, true)
  assert.equal(await fall2027.getByText('Option 1').count(), 1)
  assert.equal(await fall2027.getByText('Option 2').count(), 1)
  assert.equal(await fall2027.locator('.degree-schedule-candidate-path').count(), 2)
  await fall2027.getByRole('button', { name: 'Cancel change' }).click()
  assert.equal(await fall2027.getByText('Option 1').count(), 0)
  assert.equal(await fall2027.locator('.degree-schedule-candidate-path').count(), 0)
  assert.equal(await fall2027.locator('.degree-schedule-locked-decision').count(), 1)

  const spring2028 = page.getByRole('region', { name: 'Spring 2028' })
  await spring2028.getByText('Statistical Methods').waitFor()
  // No LOCKED decision here yet (CHOICE_REQUIRED only) -- no "Required
  // courses" note on this term's header.
  assert.equal(
    await spring2028.locator('.degree-schedule-semester-header span').textContent(),
    'Not scheduled',
  )
  assert.equal(await spring2028.getByText('Choice required').count(), 1)
  assert.equal(await spring2028.getByText('2 valid options').count(), 1)
  assert.match(await spring2028.textContent(), /may shift depending on which option/)
  assert.equal(await spring2028.getByText('ABC 123').count(), 1)
  assert.equal(await spring2028.getByText('CEE 2302', { exact: true }).count(), 1)
  assert.equal(await spring2028.getByText('CS 3377', { exact: true }).count(), 1)
  assert.equal(await spring2028.getByRole('button', { name: /Choose ABC 123 for Statistical Methods/ }).count(), 1)
  assert.equal(await spring2028.getByRole('button', { name: /Choose CEE 2302 and CS 3377 for Statistical Methods/ }).count(), 1)

  // ── CHOICE_REQUIRED is untouched: 2 genuinely distinct candidates still
  //    render as 2 separate bordered "Option N" boxes -- that grouping is
  //    load-bearing there (it's the only signal for which courses belong to
  //    which valid combination). ──────────────────────────────────────────
  assert.equal(await spring2028.locator('.degree-schedule-candidate-path').count(), 2)
  assert.equal(await spring2028.getByText('Option 1').count(), 1)
  assert.equal(await spring2028.getByText('Option 2').count(), 1)

  // ── A decision-option course row is the shared .degree-schedule-course-row
  //    shape: real title + credits visible, "Planned course" badge stacked
  //    below it in the institution accent (not the muted row default) ──────
  const cee2302Row = spring2028
    .locator('.degree-schedule-candidate-courses > li')
    .filter({ hasText: 'CEE 2302' })
  await cee2302Row.first().waitFor()
  assert.equal(await cee2302Row.locator('.degree-schedule-course-row').count(), 1)
  assert.equal(await cee2302Row.getByText('CEE 2302 catalog title').count(), 1)
  assert.match(await cee2302Row.textContent(), /3 credits/)
  // The fixture leaves ABC 123 with null credits -- the genuine exception path.
  const abc123Row = spring2028
    .locator('.degree-schedule-candidate-courses > li')
    .filter({ hasText: 'ABC 123' })
  assert.match(await abc123Row.textContent(), /Credits unavailable/)
  // The badge resolves to --accent, not --muted.
  const badgeColors = await page.evaluate(() => {
    const el = document.querySelector('.degree-schedule-candidate-courses .degree-schedule-badge--decision')
    const probe = document.createElement('span')
    document.body.append(probe)
    probe.style.color = 'var(--accent)'
    const accent = getComputedStyle(probe).color
    probe.style.color = 'var(--muted)'
    const muted = getComputedStyle(probe).color
    probe.remove()
    return { badge: getComputedStyle(el).color, accent, muted }
  })
  assert.equal(badgeColors.badge, badgeColors.accent)
  assert.notEqual(badgeColors.badge, badgeColors.muted)

  // ── Third year: EXCLUDED on Fall, with an estimate label ───────────────
  await page.getByRole('tab', { name: 'Third year' }).click()
  const fall2028 = page.getByRole('region', { name: 'Fall 2028' })
  await fall2028.getByText('Technical Elective').waitFor()
  assert.equal(await fall2028.getByText('Set aside').count(), 1)
  assert.equal(await fall2028.getByText('Est. Fall 2028').count(), 1)
  assert.equal(await fall2028.getByText('CSCE 4901').count(), 1)
  assert.equal(await fall2028.getByRole('button', { name: 'Add it back' }).count(), 1)
  // EXCLUDED is not LOCKED either -- no "Required courses" note here.
  const fall2028HeaderText = await fall2028.locator('.degree-schedule-semester-header span').textContent()
  assert.doesNotMatch(fall2028HeaderText, /Required courses/)

  // ── Non-card states produce zero UI anywhere on the page ───────────────
  const pageText = await page.locator('body').textContent()
  assert.doesNotMatch(pageText, /Mystery Elective/)
  assert.doesNotMatch(pageText, /Restricted Elective/)
  assert.doesNotMatch(pageText, /Unstructured Requirement/)
  assert.doesNotMatch(pageText, /University Core Curriculum/)
  assert.doesNotMatch(pageText, /Can't auto-verify/)
  assert.doesNotMatch(pageText, /need adviser review/)

  // ── Edit-courses popup: opens, is modal, Escape/Confirm close it, focus
  //    returns to the trigger, and it never stacks across terms ────────────
  await page.getByRole('tab', { name: 'Second year' }).click()
  await fall2027.getByRole('button', { name: 'Edit courses' }).click()
  const editDialog = page.getByRole('dialog', { name: 'Edit courses · Fall 2027' })
  await editDialog.waitFor()
  assert.equal(await editDialog.getAttribute('aria-modal'), 'true')
  assert.equal(await page.getByRole('dialog').count(), 1)
  // Escape closes it and hands focus back to the button that opened it.
  await page.keyboard.press('Escape')
  await editDialog.waitFor({ state: 'detached' })
  assert.equal(
    await page.evaluate(() => document.activeElement?.textContent?.trim()),
    'Edit courses',
  )
  // A different term opens its own popup -- still exactly one, and it is that
  // term's (the modal scrim is what keeps a second from ever being opened on
  // top; the single editingTermKey string is the model-level guarantee).
  await spring2028.getByRole('button', { name: 'Edit courses' }).click()
  await page.getByRole('dialog', { name: 'Edit courses · Spring 2028' }).waitFor()
  assert.equal(await page.getByRole('dialog').count(), 1)
  // The footer "Confirm" button is close-only.
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm' }).click()
  assert.equal(await page.getByRole('dialog').count(), 0)

  // ── Choosing an option persists it and the card locks in place ─────────
  await page.getByRole('tab', { name: 'Second year' }).click()
  await spring2028.getByRole('button', { name: /Choose CEE 2302 and CS 3377 for Statistical Methods/ }).click()
  // The choice card flips to the LOCKED treatment in place (Change/Clear).
  // It lands in the resting (non-changing) view, so it's the boxless
  // .degree-schedule-locked-decision, not the boxed .is-locked card.
  await spring2028.getByRole('button', { name: 'Change choice' }).waitFor()
  assert.equal(await spring2028.locator('.degree-schedule-locked-decision').count(), 1)
  assert.equal(await spring2028.locator('.degree-schedule-decision-card.is-locked').count(), 0)
  assert.equal(putBodies.length, 1)
  assert.deepEqual(putBodies[0].selections.find((s) => s.requirement_group_id === 'choice'), {
    requirement_group_id: 'choice', candidate_id: 'multi', course_codes: ['CEE 2302', 'CS 3377'],
  })
  assert.equal(await spring2028.getByRole('button', { name: 'Change choice' }).count(), 1)
  assert.equal(await spring2028.getByRole('button', { name: 'Clear choice' }).count(), 1)
  // Now that this decision is LOCKED, the term header picks up the note.
  assert.equal(
    await spring2028.locator('.degree-schedule-semester-header span').textContent(),
    'Not scheduled · Required courses',
  )

  // ── RESELECTION_REQUIRED is a top-level alert, not a term-card entry ───
  schedule.selection_state = {
    status: 'RESELECTION_REQUIRED',
    selections: [{ requirement_group_id: 'choice', candidate_id: 'removed', course_codes: ['OLD 1000'] }],
    failure: {
      code: 'LOCK_CANDIDATE_NOT_FOUND', requirement_group_id: 'choice', candidate_id: 'removed',
      current_course_codes: [], submitted_course_codes: ['OLD 1000'], exclusion_reasons: [],
    },
  }
  schedule.decisions = schedule.decisions.map((decision) => decision.requirement_group_id === 'choice'
    ? { ...decision, state: 'CHOICE_REQUIRED', selected_candidate_id: null }
    : decision)
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()

  const reselection = page.locator('.degree-schedule-reselection')
  await reselection.getByText('Your saved course choice needs attention').waitFor()
  assert.equal(await reselection.getByRole('button', { name: 'Clear saved choice' }).count(), 1)
  // It sits above the year grid, not inside any term column.
  assert.equal(await page.locator('.degree-schedule-semester .degree-schedule-reselection').count(), 0)
  const orderOk = await page.evaluate(() => {
    const alert = document.querySelector('.degree-schedule-reselection')
    const grid = document.querySelector('.degree-schedule-years')
    return Boolean(alert && grid) && (alert.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
  })
  assert.equal(orderOk, true)
})
