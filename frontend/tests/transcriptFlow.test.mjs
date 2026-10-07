import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { meProfile } from './fixtures/meProfile.mjs'
import { planningRoutes } from './fixtures/planningRoutes.mjs'

const ROW_ID = '11111111-1111-4111-8111-111111111111'
const REPEAT_ID = '22222222-2222-4222-8222-222222222222'
const ORPHAN_ID = '44444444-4444-4444-8444-444444444444'
const TERM_ID = '33333333-3333-4333-8333-333333333333'
const baseRow = { id: ROW_ID, course_code: 'MATH 251', title: 'Engineering Mathematics III', credit_hours: '3.00', letter_grade: 'B', status: 'completed', term_id: TERM_ID, catalog_course_id: null, counts_toward_credit: true, counts_toward_gpa: true, credit_type: 'resident', source: 'transcript_parse', needs_catalog_review: true, repeat_exclusion: null }
const repeatRow = { ...baseRow, id: REPEAT_ID, course_code: 'MATH 151', letter_grade: 'C', needs_catalog_review: false, repeat_exclusion: { excluded_from_gpa: true, reason: 'repeat_replacement', superseded_by_id: ROW_ID, superseded_by: { id: ROW_ID, course_code: 'MATH 251', letter_grade: 'B', term_id: TERM_ID }, still_counts_toward_earned_hours: true } }
// superseded_by is null whenever the superseding row is not among the caller's
// rows -- review.py still sends the id. The UI must degrade, not crash.
const orphanRepeatRow = { ...baseRow, id: ORPHAN_ID, course_code: 'CHEM 107', letter_grade: 'D', needs_catalog_review: false, repeat_exclusion: { excluded_from_gpa: true, reason: 'repeat_replacement', superseded_by_id: 'not-in-this-payload', superseded_by: null, still_counts_toward_earned_hours: true } }
const payload = (state) => ({ course_records: state.pending ? [state.row] : [], terms: [{ id: TERM_ID, label: 'Fall 2025', year: 2025, season: 'fall', sequence: 1, institution_id: 'i' }], institutions: [{ id: 'i', name: 'Texas A&M University' }], pending_catalog_review: state.pending ? 1 : 0, excluded_by_repeat: state.pending ? [repeatRow, orphanRepeatRow] : [] })
function respond(response, body, status = 200) { response.statusCode = status; response.setHeader('content-type', 'application/json'); response.end(JSON.stringify(status === 200 ? body : { detail: body })) }

test('transcript flow covers upload, recovery, edits, repeats, failures, confirmation, and mobile', { timeout: 45_000 }, async (t) => {
  const state = { pending: false, recoveryFails: false, uploadFails: false, editFails: false, row: { ...baseRow }, uploads: 0, patches: [], academicsConfirmed: false, profileReads: 0 }
  // The Academic Record tab renders the term view, which calls three planning
  // routes on mount. Its terms are keyed to the meProfile fixture's own
  // term_id so the confirmed MATH 251 row lands under a selectable term.
  const planning = planningRoutes({
    terms: [
      { key: '2025-Fall', id: '33333333-3333-4333-8333-333333333333', label: 'Fall 2025', year: 2025, season: 'Fall', sequence: 1, start_date: '2025-08-25', end_date: '2025-12-17', enrolled: true, is_upcoming: false },
      { key: '2026-Fall', id: null, label: 'Fall 2026', year: 2026, season: 'Fall', sequence: null, start_date: '2026-08-24', end_date: '2026-12-10', enrolled: false, is_upcoming: true },
    ],
  })
  const plugin = { name: 'transcript-api', configureServer(server) { server.middlewares.use((request, response, next) => {
    const path = request.url?.split('?')[0]
    if (planning.handle(path, request.method, request, response)) return undefined
    if (path === '/api/v2/student/me/profile' && request.method === 'GET') { state.profileReads++; return respond(response, meProfile({ academics: state.academicsConfirmed })) }
    if (path === '/api/v2/student/me/transcript/review' && request.method === 'GET') return state.recoveryFails ? respond(response, 'Could not load course records for review.', 502) : respond(response, payload(state))
    if (path === '/api/v2/student/me/transcript/upload' && request.method === 'POST') { state.uploads++; if (state.uploadFails) return respond(response, { error: 'extraction_failed', extraction_status: 'encrypted', message: 'This looks like a scanned transcript.' }, 422); state.pending = true; return respond(response, { status: 'ok', warnings: [], rejected: [], written: { course_records: { inserted: 1, skipped_duplicate: 0 } }, catalog: { matched: 0, unmatched: 1, misses: ['MATH 251'] }, cross_check: { ok: false, terms_checked: 1, terms_skipped: 0, mismatches: [{ term_label: 'Fall 2025', field: 'gpa', printed: 3.5, computed: 3.0, difference: 0.5 }] } }) }
    if (path === `/api/v2/student/me/transcript/review/${ROW_ID}` && request.method === 'PATCH') { if (state.editFails) return respond(response, 'The grade was rejected.', 422); let body=''; request.on('data', (chunk) => { body += chunk }); request.on('end', () => { const parsed = JSON.parse(body); state.patches.push(parsed); state.row = { ...state.row, ...parsed, title: 'Server-canonical title' }; respond(response, state.row) }); return }
    if (path === '/api/v2/student/me/transcript/confirm' && request.method === 'POST') { state.pending = false; state.academicsConfirmed = true; return respond(response, { status: 'ok', confirmed: 1, scope: 'all_unconfirmed', repeats: {} }) }
    next()
  }) } }
  const server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), cacheDir: fileURLToPath(new URL('../node_modules/.vite-transcript-flow', import.meta.url)), logLevel: 'silent', plugins: [plugin], server: { host: '127.0.0.1' } }); await server.listen(); t.after(async () => server.close())
  const address = server.httpServer?.address(); assert.ok(address && typeof address === 'object'); const url = `http://127.0.0.1:${address.port}/transcript-preview.html`
  const browser = await chromium.launch(); t.after(async () => browser.close()); const page = await browser.newPage()

  // No transcript; failed extraction stays on upload with a useful error.
  // The encrypted case gets its own actionable headline, not a generic one.
  await page.goto(url); await page.getByRole('heading', { name: 'Add your transcript' }).waitFor()
  state.uploadFails = true; await page.locator('#transcript-file').setInputFiles({ name: 'scan.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF') }); await page.getByRole('button', { name: 'Upload transcript' }).click(); await page.getByText('This looks like a scanned transcript.').waitFor(); assert.equal(await page.getByRole('heading', { name: 'Verify your academic record' }).count(), 0)
  await page.getByText('That PDF is password-protected').waitFor()

  // Successful upload enters the review returned by persistent server state.
  state.uploadFails = false; await page.getByRole('button', { name: 'Choose another file' }).click(); await page.locator('#transcript-file').setInputFiles({ name: 'record.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF') }); await page.getByRole('button', { name: 'Upload transcript' }).click(); await page.getByRole('heading', { name: 'Verify your academic record' }).waitFor(); assert.equal(state.uploads, 2)
  await page.getByRole('heading', { name: 'Fall 2025' }).waitFor(); await page.getByText(/MATH 151 was replaced by MATH 251/).waitFor(); await page.getByText('Resident (default)').waitFor()

  // Repeat exclusions foreground the earned-hours rule, and degrade rather
  // than crash when the superseding row is not in the payload.
  await page.getByText('They still count toward your earned hours.').waitFor()
  await page.getByText('CHEM 107 was replaced by a later attempt on your record.').waitFor()

  // Cross-check is advisory: it renders, and confirmation stays available.
  await page.getByRole('heading', { name: /Totals on the page/ }).waitFor()
  await page.getByText(/printed 3.5/).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Confirm 1 courses' }).isEnabled(), true)

  // Edit failure never reaches stored data; success uses the server response.
  // Fields open in place on click, and blur commits -- no separate save button.
  //
  // The rejected text STAYS on screen, which is the shared commit
  // architecture's deliberate choice (CareerReview: keep what they typed so it
  // can be corrected, but make clear it did not save). The old transcript form
  // discarded it instead. What must hold either way is that nothing reached
  // the server and the failure is stated plainly.
  await page.getByRole('button', { name: 'Course title' }).click(); await page.getByLabel('Course title').fill('Client title'); state.editFails = true; await page.getByLabel('Course title').press('Enter'); await page.getByText('The grade was rejected.').waitFor()
  assert.equal(state.row.title, 'Engineering Mathematics III')
  assert.equal(state.patches.length, 0)
  state.editFails = false; await page.getByRole('button', { name: 'Course title' }).click(); await page.getByLabel('Course title').fill('Client title'); await page.getByLabel('Course title').press('Enter'); await page.getByText('Server-canonical title').waitFor()

  // credit_hours round-trips through a REAL save: the number the editor
  // produces is sent as the backend's 2dp string, not as a bare number.
  await page.getByRole('button', { name: 'Credits' }).click(); await page.getByLabel('Credits').fill('4'); await page.getByLabel('Credits').press('Enter')
  await page.waitForFunction(() => document.body.textContent.includes('4.00'))
  const creditPatch = state.patches.find((patch) => 'credit_hours' in patch)
  assert.equal(creditPatch.credit_hours, '4.00')

  // A pure reformat is NOT an edit: opening the field and committing the same
  // value must not PATCH, or every no-op blur would write to the server.
  const before = state.patches.length
  await page.getByRole('button', { name: 'Credits' }).click(); await page.getByLabel('Credits').press('Enter')
  await page.waitForTimeout(150)
  assert.equal(state.patches.length, before)

  // Pending state survives refresh and remains usable on mobile without page overflow.
  await page.reload(); await page.getByRole('heading', { name: 'Verify your academic record' }).waitFor(); await page.setViewportSize({ width: 390, height: 844 }); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)

  // CASE T1: a confirmed backend success goes straight to the dashboard.
  const profileReadsBeforeConfirm = state.profileReads
  await page.getByRole('button', { name: 'Confirm 1 courses' }).click()
  await page.waitForFunction(() => location.hash === '#/dashboard')

  // CASE T4: the dashboard says what happened, as an accessible status.
  const notice = page.locator('[role="status"] .dash-notice')
  await notice.waitFor()
  assert.equal(await notice.innerText().then((t) => t.includes('Transcript saved — 1 course added to your academic record.')), true)

  // CASES T2/T3: the terminal screen and its button are gone, not relocated.
  assert.equal(await page.getByText('Your transcript is saved').count(), 0)
  assert.equal(await page.getByRole('link', { name: 'Go to dashboard' }).count(), 0)
  assert.equal(await page.getByRole('button', { name: 'Go to dashboard' }).count(), 0)

  // CASE T5: the canonical profile was re-read as part of the handover.
  assert.ok(state.profileReads > profileReadsBeforeConfirm, 'confirmation must refetch /me/profile')

  // The confirm above happened at 390px (set for the mobile check), so the
  // notice is verified at the narrow layout before anything widens it.
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.setViewportSize({ width: 1280, height: 900 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)

  // CASE T6: and the newly confirmed course is on screen, not the pre-confirm
  // empty state -- which is what a stale profile would have rendered.
  //
  // The Academic top-level item opens on Academic Overview; the term view is
  // one level down, under GPA Calculator. It now opens on the UPCOMING term
  // (Fall 2026), so the confirmed Fall 2025 course is one dropdown selection
  // away rather than immediately visible. The assertion's point is unchanged
  // -- the row exists and the empty state is gone -- so it selects the
  // course's own term first.
  await page.getByRole('button', { name: 'Academic' }).click()
  await page.getByRole('button', { name: 'GPA Calculator' }).click()
  // Term selection is a year tab + a season tab (TermPlanner's academic-tabs
  // / term-season-tabs), not the old dropdown. 2025-Fall sits in a
  // different academic-year tab (2025–26) than the default 2026-Fall
  // (2026–27).
  await page.locator('.term-season-tabs').waitFor()
  const activeId = await page.locator('.term-season-tabs [aria-selected="true"]').getAttribute('id')
  assert.equal(activeId, 'term-season-tab-2026-Fall')
  await page.getByRole('tab', { name: '2025–26' }).click()
  await page.getByRole('tab', { name: 'Fall', exact: true }).click()
  await page.getByText('MATH 251').waitFor()
  assert.equal(await page.getByRole('link', { name: 'Upload transcript' }).count(), 0)

  // The notice is about one transition: it must not survive a reload of the
  // dashboard, and it must be dismissible before then.
  await page.locator('.dash-notice-dismiss').click()
  assert.equal(await page.locator('.dash-notice').count(), 0)
  await page.reload()
  await page.getByRole('button', { name: 'Academic' }).waitFor()
  assert.equal(await page.locator('.dash-notice').count(), 0)

  // CASE T11: the confirmed review does not come back.
  await page.goto(`${url}#/`); await page.getByRole('heading', { name: 'Add your transcript' }).waitFor()

  // Recovery failure is explicit and retryable, never an upload fallback.
  state.recoveryFails = true; await page.reload(); await page.getByText('Could not check your transcript').waitFor(); assert.equal(await page.getByRole('heading', { name: 'Add your transcript' }).count(), 0); state.recoveryFails = false; await page.getByRole('button', { name: 'Try again' }).click(); await page.getByRole('heading', { name: 'Add your transcript' }).waitFor()
})

test('a slow confirm dims the page and says how long it may take', { timeout: 30_000 }, async (t) => {
  // The confirm request is held open deliberately. This is the bug being
  // covered: against a cold-started backend the request runs 20-50s, and the
  // review page used to sit at full opacity with every field still looking
  // editable for that entire window.
  const plugin = { name: 'transcript-slow-confirm', configureServer(server) { server.middlewares.use((request, response, next) => {
    const path = request.url?.split('?')[0]
    if (path === '/api/v2/student/me/profile' && request.method === 'GET') return respond(response, meProfile({ academics: true }))
    if (path === '/api/v2/student/me/transcript/review' && request.method === 'GET') return respond(response, payload({ pending: true, row: { ...baseRow } }))
    if (path === '/api/v2/student/me/transcript/confirm' && request.method === 'POST') { setTimeout(() => { respond(response, { status: 'ok', confirmed: 1, scope: 'all_unconfirmed', repeats: {} }) }, 1500); return }
    next()
  }) } }
  const server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), cacheDir: fileURLToPath(new URL('../node_modules/.vite-transcript-flow', import.meta.url)), logLevel: 'silent', plugins: [plugin], server: { host: '127.0.0.1' } }); await server.listen(); t.after(async () => server.close())
  const address = server.httpServer?.address(); assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch(); t.after(async () => browser.close()); const page = await browser.newPage()

  await page.goto(`http://127.0.0.1:${address.port}/transcript-preview.html`)
  await page.getByRole('button', { name: 'Confirm 1 courses' }).click()

  // The page-level signal, not just the bottom bar.
  await page.getByText('Saving your record').waitFor()
  await page.getByText('This can take up to a minute if the server is waking up.').waitFor()
  assert.equal(await page.locator('.rv-confirming').count(), 1)

  // The overlay covers the review CONTENT while leaving the commit bar legible
  // on top of it -- that ordering is the whole point of its z-index.
  const stacking = await page.evaluate(() => ({
    overlay: Number(getComputedStyle(document.querySelector('.rv-confirming')).zIndex),
    bar: Number(getComputedStyle(document.querySelector('.rv-commit')).zIndex),
  }))
  assert.ok(stacking.overlay < stacking.bar, 'the commit bar must stay above the scrim')

  // The pre-existing bar behaviour is kept, not replaced.
  const button = page.getByRole('button', { name: 'Saving…' })
  await button.waitFor()
  assert.equal(await button.isDisabled(), true)

  // Progress, never an alert: nothing has gone wrong.
  assert.equal(await page.getByRole('alert').count(), 0)

  // It stays up THROUGH the handover -- the review screen is never handed back
  // looking editable for records that no longer exist -- and it is gone once
  // the dashboard has replaced it.
  await page.waitForFunction(() => location.hash === '#/dashboard')
  assert.equal(await page.locator('.rv-confirming').count(), 0)
  await page.locator('.dash-notice').waitFor()
})

test('confirmation blocked by an unverified grade scale reads as a status, not a failure', { timeout: 30_000 }, async (t) => {
  const plugin = { name: 'transcript-gate', configureServer(server) { server.middlewares.use((request, response, next) => {
    const path = request.url?.split('?')[0]
    if (path === '/api/v2/student/me/profile' && request.method === 'GET') return respond(response, meProfile())
    if (path === '/api/v2/student/me/transcript/review' && request.method === 'GET') return respond(response, payload({ pending: true, row: { ...baseRow } }))
    if (path === '/api/v2/student/me/transcript/confirm' && request.method === 'POST') return respond(response, { error: 'grade_scale_unverified', message: "Course records for Texas A&M University can't be confirmed yet - grade scale verification is pending." }, 409)
    next()
  }) } }
  const server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), cacheDir: fileURLToPath(new URL('../node_modules/.vite-transcript-flow', import.meta.url)), logLevel: 'silent', plugins: [plugin], server: { host: '127.0.0.1' } }); await server.listen(); t.after(async () => server.close())
  const address = server.httpServer?.address(); assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch(); t.after(async () => browser.close()); const page = await browser.newPage()

  await page.goto(`http://127.0.0.1:${address.port}/transcript-preview.html`)
  await page.getByRole('button', { name: 'Confirm 1 courses' }).click()
  await page.getByText(/grade scale verification is pending/).waitFor()

  // The button stops offering an action that cannot succeed, and the message
  // is a status rather than an alert.
  await page.getByRole('button', { name: 'Verification pending' }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Verification pending' }).isDisabled(), true)
  assert.equal(await page.getByRole('alert').count(), 0)

  // CASE T9: a block is not a success. Nothing navigates, the review is still
  // on screen and usable, and no success notice was invented.
  assert.equal(await page.evaluate(() => location.hash), '')
  await page.getByRole('heading', { name: 'Verify your academic record' }).waitFor()
  assert.equal(await page.locator('.rv-confirming').count(), 0)
  assert.equal(await page.locator('.dash-notice').count(), 0)
})

test('transcript confirm failures and timeouts stay on the review screen', { timeout: 45_000 }, async (t) => {
  // CASE T7 (500) and CASE T8 (a confirm that never completes). Both must
  // leave the student exactly where they were, with the button live again.
  //
  // T8 aborts the request at the network layer rather than letting the real
  // CONFIRM_TIMEOUT_MS (60s) elapse. That is the same branch either way -- the
  // client-side abort produces REQUEST_TIMEOUT_STATUS, which normalizes to an
  // `ok: false` confirm result exactly like this does, and transcriptApi.test
  // .mjs already pins that mapping. What is untested without this is the
  // SCREEN's half of it: that an unfinished confirm does not navigate.
  const plugin = { name: 'transcript-confirm-failures', configureServer(server) { server.middlewares.use((request, response, next) => {
    const path = request.url?.split('?')[0]
    if (path === '/api/v2/student/me/profile' && request.method === 'GET') return respond(response, meProfile())
    if (path === '/api/v2/student/me/transcript/review' && request.method === 'GET') return respond(response, payload({ pending: true, row: { ...baseRow } }))
    if (path === '/api/v2/student/me/transcript/confirm' && request.method === 'POST') return respond(response, 'The record could not be confirmed.', 500)
    next()
  }) } }
  const server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), cacheDir: fileURLToPath(new URL('../node_modules/.vite-transcript-failures', import.meta.url)), logLevel: 'silent', plugins: [plugin], server: { host: '127.0.0.1' } }); await server.listen(); t.after(async () => server.close())
  const address = server.httpServer?.address(); assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch(); t.after(async () => browser.close()); const page = await browser.newPage()
  const url = `http://127.0.0.1:${address.port}/transcript-preview.html`

  // CASE T7: API failure.
  await page.goto(url)
  await page.getByRole('button', { name: 'Confirm 1 courses' }).click()
  await page.getByText('The record could not be confirmed.').waitFor()
  assert.equal(await page.evaluate(() => location.hash), '')
  await page.getByRole('heading', { name: 'Verify your academic record' }).waitFor()
  assert.equal(await page.locator('.dash-notice').count(), 0)
  // The confirming state resolved cleanly and retry is available.
  assert.equal(await page.locator('.rv-confirming').count(), 0)
  assert.equal(await page.getByRole('button', { name: 'Confirm 1 courses' }).isEnabled(), true)

  // CASE T8: a confirm that never completes.
  //
  // Waits on the SETTLED outcome, never on the intermediate "Saving…" label. An
  // aborted request can resolve inside a single render, so that label is not
  // guaranteed to be observable -- waiting for it is a race that hangs for the
  // full locator timeout when it loses. What matters here is where the student
  // ends up, and that is deterministic.
  await page.route('**/api/v2/student/me/transcript/confirm', (route) => route.abort('timedout'))
  await page.getByRole('button', { name: 'Confirm 1 courses' }).click()
  await page.getByText('Could not reach the server.').waitFor()
  assert.equal(await page.evaluate(() => location.hash), '')
  await page.getByRole('heading', { name: 'Verify your academic record' }).waitFor()
  assert.equal(await page.locator('.dash-notice').count(), 0)
  assert.equal(await page.locator('.rv-confirming').count(), 0)
  // Retry remains possible: the button is live and clicking it re-requests.
  assert.equal(await page.getByRole('button', { name: 'Confirm 1 courses' }).isEnabled(), true)
})
