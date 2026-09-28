// The in-flight upload experience, driven through a real browser.
//
// Every server here controls when it answers, which is the only way to observe
// a state that exists only while a request is outstanding. The isolated
// cacheDir per server follows the Phase 1 pattern and keeps these off the
// shared Vite cache.

import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { meProfile } from './fixtures/meProfile.mjs'

const TERM_ID = '33333333-3333-4333-8333-333333333333'
const ROW_ID = '11111111-1111-4111-8111-111111111111'
const courseRow = { id: ROW_ID, course_code: 'MATH 251', title: 'Engineering Mathematics III', credit_hours: '3.00', letter_grade: 'B', status: 'completed', term_id: TERM_ID, catalog_course_id: null, counts_toward_credit: true, counts_toward_gpa: true, credit_type: 'resident', source: 'transcript_parse', needs_catalog_review: false, repeat_exclusion: null }
const EMPTY_CAREER = { career_profile: null, certifications: [], work_experience: [], projects: [] }
const PARSED_CAREER = {
  career_profile: { id: 'cp-1', source: 'resume_parse', target_roles: ['Software Engineer'], interests: ['systems'], career_goals: null, geographic_preference: null, ai_anxiety_level: null, skills_technical: ['TypeScript'], skills_soft: [], ai_exposure: null },
  certifications: [],
  work_experience: [{ id: 'w-1', source: 'resume_parse', employer: 'Acme', role: 'Intern', duration: null, location: null, description: null, skills_gained: ['TypeScript'] }],
  projects: [],
}
const RESUME_UPLOAD_OK = { status: 'ok', extraction: { status: 'ok', page_count: 1 }, warnings: [], model: 'test', career_profile: { outcome: 'inserted' }, academics: { major_current: 'Computer Engineering', expected_graduation: 'Spring 2029' }, written: { certifications: { inserted: 0, skipped_duplicate: 0 }, work_experience: { inserted: 1, skipped_duplicate: 0 }, projects: { inserted: 0, skipped_duplicate: 0 } } }
const TRANSCRIPT_UPLOAD_OK = { status: 'ok', warnings: [], rejected: [], written: { course_records: { inserted: 1, skipped_duplicate: 0 } }, catalog: { matched: 1, unmatched: 0, misses: [] }, cross_check: { ok: true, terms_checked: 1, terms_skipped: 0, mismatches: [] } }

function send(response, body, status = 200) {
  response.statusCode = status
  response.setHeader('content-type', 'application/json')
  response.end(JSON.stringify(status === 200 ? body : { detail: body }))
}

const PDF = { name: 'Deepak Murali Resume Main.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-test') }
const TRANSCRIPT_PDF = { name: 'Fall 2025 Official Transcript.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-test') }

/**
 * A preview server whose upload endpoint answers only when `state` says so.
 * `cacheKey` gives each one its own Vite cacheDir.
 */
async function startServer(t, cacheKey, handler) {
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL(`../node_modules/.vite-${cacheKey}`, import.meta.url)),
    logLevel: 'silent',
    plugins: [{ name: `dp-${cacheKey}`, configureServer(s) { s.middlewares.use(handler) } }],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  return `http://127.0.0.1:${String(address.port)}`
}

async function startBrowser(t) {
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  return browser
}

// ── RESUME ─────────────────────────────────────────────────────────────────

test('resume processing: status, filename, stages, disabled controls, no duplicate request', { timeout: 45_000 }, async (t) => {
  const state = { release: null, uploads: 0, parsed: false }
  const origin = await startServer(t, 'dp-resume-slow', (request, response, next) => {
    const path = request.url?.split('?')[0]
    if (path === '/api/v2/student/me/profile') return send(response, meProfile())
    if (path === '/api/v2/student/me/career/review') return send(response, state.parsed ? PARSED_CAREER : EMPTY_CAREER)
    if (path === '/api/v2/student/me/resume/upload' && request.method === 'POST') {
      state.uploads += 1
      // Held open deliberately: the processing state exists only here.
      state.release = () => { state.parsed = true; send(response, RESUME_UPLOAD_OK) }
      return
    }
    next()
  })
  const page = await (await startBrowser(t)).newPage()
  await page.goto(`${origin}/resume-recovery-preview.html`)
  await page.getByText('Add your resume').waitFor()

  await page.locator('#resume-file').setInputFiles(PDF)
  await page.getByRole('button', { name: 'Upload resume' }).click()

  // CASE R1 / P1: the processing state appears, as an accessible status.
  const panel = page.locator('.dp-panel')
  await panel.waitFor()
  const status = page.locator('.dp-stage[role="status"]')
  assert.equal(await status.count(), 1)
  assert.equal(await status.getAttribute('aria-live'), 'polite')

  // CASE P2 / R-filename: what is being read stays on screen.
  await page.getByText('Deepak Murali Resume Main.pdf').waitFor()

  // CASE P3: the first stage is current immediately, then stages advance while
  // the request is still outstanding.
  await page.getByText('Uploading your resume…').waitFor()
  await page.getByText('Reading your resume…').waitFor({ timeout: 5000 })
  await page.getByText('Extracting experience, projects, and certifications…').waitFor({ timeout: 8000 })

  // Trust copy survives the redesign. On the resume screen the panel is the
  // ONLY place it appears while working -- the intro and footnote that
  // otherwise carry it are hidden -- so it must be here, exactly once.
  await page.getByText('You’ll review everything before it is saved to your profile.').waitFor()
  assert.equal(await page.locator('.dp-note').count(), 1)
  const resumePromises = (await page.locator('body').innerText())
    .split('\n')
    .filter((line) => /before it is saved|Nothing is saved/i.test(line))
  assert.equal(resumePromises.length, 1, `expected one trust statement, found: ${JSON.stringify(resumePromises)}`)

  // The indeterminate rail is present and decorative -- never announced.
  assert.equal(await page.locator('.dp-rail').count(), 1)
  assert.equal(await page.locator('.dp-rail').getAttribute('aria-hidden'), 'true')
  // CASE: no invented percentage anywhere on the screen.
  assert.equal(/\d+\s*%/.test(await page.locator('body').innerText()), false)

  // CASE R2: the action is disabled and re-labelled while working.
  const button = page.getByRole('button', { name: 'Processing resume…' })
  await button.waitFor()
  assert.equal(await button.isDisabled(), true)
  // The picker is gone rather than sitting greyed out beside the panel.
  assert.equal(await page.locator('#resume-file').count(), 0)

  // CASE R3 / P5: a second click cannot start a second request, and no stage
  // has decided anything -- we are still waiting on the server.
  await button.click({ force: true }).catch(() => undefined)
  await page.waitForTimeout(200)
  assert.equal(state.uploads, 1, 'a duplicate upload must not be issued')
  assert.equal(await page.getByRole('heading', { name: 'Here’s what we read.' }).count(), 0)

  // CASE R7 / P10: past the last threshold it rests on the final stage and
  // never wraps back to the first.
  await page.getByText('Preparing your review…').waitFor({ timeout: 10_000 })
  await page.waitForTimeout(2500)
  await page.getByText('Preparing your review…').waitFor()
  assert.equal(await page.getByText('Uploading your resume…').count(), 0, 'stages must not loop')
  assert.equal(await page.locator('.dp-rail').count(), 1, 'motion continues while waiting')

  // CASE R4 / P6: the backend answer immediately overrides the visual stage.
  state.release()
  await page.getByRole('heading', { name: 'Here’s what we read.' }).waitFor()
  assert.equal(await page.getByLabel('Current major').inputValue(), 'Computer Engineering')
  assert.equal(await page.getByLabel('Expected graduation').inputValue(), 'Spring 2029')
  assert.equal(await page.locator('.dp-panel').count(), 0, 'processing must not survive the handover')
})

test('resume processing: failure stops it immediately and retry stays possible', { timeout: 45_000 }, async (t) => {
  const state = { fail: true, parsed: false }
  const origin = await startServer(t, 'dp-resume-fail', (request, response, next) => {
    const path = request.url?.split('?')[0]
    if (path === '/api/v2/student/me/profile') return send(response, meProfile())
    if (path === '/api/v2/student/me/career/review') return send(response, state.parsed ? PARSED_CAREER : EMPTY_CAREER)
    if (path === '/api/v2/student/me/resume/upload' && request.method === 'POST') {
      if (state.fail) return send(response, 'We could not read that resume.', 422)
      state.parsed = true
      return send(response, RESUME_UPLOAD_OK)
    }
    next()
  })
  const page = await (await startBrowser(t)).newPage()
  await page.goto(`${origin}/resume-recovery-preview.html`)
  await page.getByText('Add your resume').waitFor()
  await page.locator('#resume-file').setInputFiles(PDF)
  await page.getByRole('button', { name: 'Upload resume' }).click()

  // CASE R5 / P7: the error ends the processing state outright. No animation
  // continues behind it, and nothing implies the parse got as far as "Preparing".
  await page.getByRole('alert').waitFor()
  assert.equal(await page.locator('.dp-panel').count(), 0)
  assert.equal(await page.locator('.dp-rail').count(), 0)
  assert.equal(await page.getByText('Preparing your review…').count(), 0)
  // The picker is back and the action is live again.
  await page.locator('#resume-file').waitFor()
  assert.equal(await page.getByRole('button', { name: 'Upload resume' }).isEnabled(), true)

  // CASE P8: an upload that never completes ends the processing state too.
  //
  // Aborted at the network layer. The upload endpoints pass no client timeout
  // today -- only the confirms do (api/resume.ts's `send` makes timeoutMs
  // opt-in), which is pre-existing and out of scope to change here. What must
  // hold either way is that the processing state cannot outlive the request:
  // whatever settles it, settled is settled.
  await page.route('**/api/v2/student/me/resume/upload', (route) => route.abort('timedout'))
  await page.locator('#resume-file').setInputFiles(PDF)
  await page.getByRole('button', { name: 'Upload resume' }).click()
  await page.getByRole('alert').waitFor()
  assert.equal(await page.locator('.dp-panel').count(), 0, 'processing outlived an unfinished request')
  assert.equal(await page.getByText('Preparing your review…').count(), 0)
  assert.equal(await page.getByRole('button', { name: 'Upload resume' }).isEnabled(), true)
  await page.unroute('**/api/v2/student/me/resume/upload')

  // Retry succeeds and goes straight to review.
  state.fail = false
  await page.locator('#resume-file').setInputFiles(PDF)
  await page.getByRole('button', { name: 'Upload resume' }).click()
  await page.getByRole('heading', { name: 'Here’s what we read.' }).waitFor()
})

test('resume processing: a fast response goes straight to review', { timeout: 45_000 }, async (t) => {
  const state = { parsed: false }
  const origin = await startServer(t, 'dp-resume-fast', (request, response, next) => {
    const path = request.url?.split('?')[0]
    if (path === '/api/v2/student/me/profile') return send(response, meProfile())
    if (path === '/api/v2/student/me/career/review') return send(response, state.parsed ? PARSED_CAREER : EMPTY_CAREER)
    if (path === '/api/v2/student/me/resume/upload' && request.method === 'POST') { state.parsed = true; return send(response, RESUME_UPLOAD_OK) }
    next()
  })
  const page = await (await startBrowser(t)).newPage()
  await page.goto(`${origin}/resume-recovery-preview.html`)
  await page.getByText('Add your resume').waitFor()
  await page.locator('#resume-file').setInputFiles(PDF)

  // CASE R6 / P6: no artificial delay is added to let the stages play out.
  const started = Date.now()
  await page.getByRole('button', { name: 'Upload resume' }).click()
  await page.getByRole('heading', { name: 'Here’s what we read.' }).waitFor()
  const elapsed = Date.now() - started
  assert.ok(elapsed < 2000, `review was delayed by the stage schedule (${String(elapsed)}ms)`)

  // Nothing lingers, and no later stage flashes in after the handover.
  assert.equal(await page.locator('.dp-panel').count(), 0)
  await page.waitForTimeout(1200)
  assert.equal(await page.locator('.dp-panel').count(), 0, 'a timer outlived the request')
  assert.equal(await page.getByText('Reading your resume…').count(), 0)
})

// ── TRANSCRIPT ─────────────────────────────────────────────────────────────

test('transcript processing: status, filename, stages, disabled controls, no duplicate request', { timeout: 45_000 }, async (t) => {
  const state = { release: null, uploads: 0, pending: false }
  const origin = await startServer(t, 'dp-transcript-slow', (request, response, next) => {
    const path = request.url?.split('?')[0]
    if (path === '/api/v2/student/me/profile') return send(response, meProfile())
    if (path === '/api/v2/student/me/transcript/review') return send(response, { course_records: state.pending ? [courseRow] : [], terms: [{ id: TERM_ID, label: 'Fall 2025', year: 2025, season: 'fall', sequence: 1, institution_id: 'i' }], institutions: [{ id: 'i', name: 'Texas A&M University' }], pending_catalog_review: 0, excluded_by_repeat: [] })
    if (path === '/api/v2/student/me/transcript/upload' && request.method === 'POST') {
      state.uploads += 1
      state.release = () => { state.pending = true; send(response, TRANSCRIPT_UPLOAD_OK) }
      return
    }
    next()
  })
  const page = await (await startBrowser(t)).newPage()
  await page.goto(`${origin}/transcript-preview.html`)
  await page.getByRole('heading', { name: 'Add your transcript' }).waitFor()

  await page.locator('#transcript-file').setInputFiles(TRANSCRIPT_PDF)
  await page.getByRole('button', { name: 'Upload transcript' }).click()

  // CASE T1 / P1: accessible processing status.
  await page.locator('.dp-panel').waitFor()
  const status = page.locator('.dp-stage[role="status"]')
  assert.equal(await status.count(), 1)
  assert.equal(await status.getAttribute('aria-live'), 'polite')

  // CASE P2: filename retained.
  await page.getByText('Fall 2025 Official Transcript.pdf').waitFor()

  // CASE P4: transcript stages progress while the request is pending.
  await page.getByText('Uploading your transcript…').waitFor()
  await page.getByText('Reading your transcript…').waitFor({ timeout: 5000 })
  await page.getByText('Extracting courses and grades…').waitFor({ timeout: 8000 })
  assert.equal(/\d+\s*%/.test(await page.locator('body').innerText()), false)

  // The "nothing is saved yet" promise is made exactly ONCE on this screen, by
  // the masthead standfirst -- which is deliberately NOT hidden during
  // processing, so the page hierarchy stays put and the header does not jump.
  // The panel carries no note of its own here: two statements of the same
  // reassurance on one screen read as protesting rather than reassuring.
  await page.getByText(/Nothing is saved to your record until you/).waitFor()
  const promises = (await page.locator('body').innerText())
    .split('\n')
    .filter((line) => /saved to your record|added to your academic record|before it is saved/i.test(line))
  assert.equal(promises.length, 1, `expected one trust statement, found: ${JSON.stringify(promises)}`)
  assert.equal(await page.locator('.dp-note').count(), 0, 'the transcript panel must carry no note')

  // CASE T2: control disabled and re-labelled.
  const button = page.getByRole('button', { name: 'Processing transcript…' })
  await button.waitFor()
  assert.equal(await button.isDisabled(), true)
  assert.equal(await page.locator('#transcript-file').count(), 0)

  // CASE T3: no duplicate request.
  await button.click({ force: true }).catch(() => undefined)
  await page.waitForTimeout(200)
  assert.equal(state.uploads, 1)
  assert.equal(await page.getByRole('heading', { name: 'Verify your academic record' }).count(), 0)

  // CASE T7 / P10: rests on the final stage, never loops.
  await page.getByText('Preparing your review…').waitFor({ timeout: 10_000 })
  await page.waitForTimeout(2500)
  await page.getByText('Preparing your review…').waitFor()
  assert.equal(await page.getByText('Uploading your transcript…').count(), 0)

  // CASE T4 / P6: backend success overrides the stage immediately.
  state.release()
  await page.getByRole('heading', { name: 'Verify your academic record' }).waitFor()
  assert.equal(await page.locator('.dp-panel').count(), 0)
})

test('transcript processing: failure stops it immediately and retry stays possible', { timeout: 45_000 }, async (t) => {
  const state = { fail: true, pending: false }
  const origin = await startServer(t, 'dp-transcript-fail', (request, response, next) => {
    const path = request.url?.split('?')[0]
    if (path === '/api/v2/student/me/profile') return send(response, meProfile())
    if (path === '/api/v2/student/me/transcript/review') return send(response, { course_records: state.pending ? [courseRow] : [], terms: [{ id: TERM_ID, label: 'Fall 2025', year: 2025, season: 'fall', sequence: 1, institution_id: 'i' }], institutions: [{ id: 'i', name: 'Texas A&M University' }], pending_catalog_review: 0, excluded_by_repeat: [] })
    if (path === '/api/v2/student/me/transcript/upload' && request.method === 'POST') {
      if (state.fail) return send(response, { error: 'extraction_failed', extraction_status: 'encrypted', message: 'This looks like a scanned transcript.' }, 422)
      state.pending = true
      return send(response, TRANSCRIPT_UPLOAD_OK)
    }
    next()
  })
  const page = await (await startBrowser(t)).newPage()
  await page.goto(`${origin}/transcript-preview.html`)
  await page.getByRole('heading', { name: 'Add your transcript' }).waitFor()
  await page.locator('#transcript-file').setInputFiles(TRANSCRIPT_PDF)
  await page.getByRole('button', { name: 'Upload transcript' }).click()

  // CASE T5 / P7: processing ends at once; the existing guidance takes over.
  await page.getByText('That PDF is password-protected').waitFor()
  assert.equal(await page.locator('.dp-panel').count(), 0)
  assert.equal(await page.locator('.dp-rail').count(), 0)
  assert.equal(await page.getByText('Preparing your review…').count(), 0)
  await page.locator('#transcript-file').waitFor()
  assert.equal(await page.getByRole('button', { name: 'Upload transcript' }).isEnabled(), true)

  // CASE P8: an upload that never completes ends the processing state too.
  await page.route('**/api/v2/student/me/transcript/upload', (route) => route.abort('timedout'))
  await page.locator('#transcript-file').setInputFiles(TRANSCRIPT_PDF)
  await page.getByRole('button', { name: 'Upload transcript' }).click()
  await page.getByRole('alert').waitFor()
  assert.equal(await page.locator('.dp-panel').count(), 0, 'processing outlived an unfinished request')
  assert.equal(await page.getByText('Preparing your review…').count(), 0)
  assert.equal(await page.getByRole('button', { name: 'Upload transcript' }).isEnabled(), true)
  await page.unroute('**/api/v2/student/me/transcript/upload')

  state.fail = false
  await page.locator('#transcript-file').setInputFiles(TRANSCRIPT_PDF)
  await page.getByRole('button', { name: 'Upload transcript' }).click()
  await page.getByRole('heading', { name: 'Verify your academic record' }).waitFor()
})

test('transcript processing: a fast response goes straight to review', { timeout: 45_000 }, async (t) => {
  const state = { pending: false }
  const origin = await startServer(t, 'dp-transcript-fast', (request, response, next) => {
    const path = request.url?.split('?')[0]
    if (path === '/api/v2/student/me/profile') return send(response, meProfile())
    if (path === '/api/v2/student/me/transcript/review') return send(response, { course_records: state.pending ? [courseRow] : [], terms: [{ id: TERM_ID, label: 'Fall 2025', year: 2025, season: 'fall', sequence: 1, institution_id: 'i' }], institutions: [{ id: 'i', name: 'Texas A&M University' }], pending_catalog_review: 0, excluded_by_repeat: [] })
    if (path === '/api/v2/student/me/transcript/upload' && request.method === 'POST') { state.pending = true; return send(response, TRANSCRIPT_UPLOAD_OK) }
    next()
  })
  const page = await (await startBrowser(t)).newPage()
  await page.goto(`${origin}/transcript-preview.html`)
  await page.getByRole('heading', { name: 'Add your transcript' }).waitFor()
  await page.locator('#transcript-file').setInputFiles(TRANSCRIPT_PDF)

  // CASE T6: no stage-driven delay in front of the review.
  const started = Date.now()
  await page.getByRole('button', { name: 'Upload transcript' }).click()
  await page.getByRole('heading', { name: 'Verify your academic record' }).waitFor()
  assert.ok(Date.now() - started < 2000)

  // CASE P9: no timer outlives the request.
  await page.waitForTimeout(1200)
  assert.equal(await page.locator('.dp-panel').count(), 0)
  assert.equal(await page.getByText('Reading your transcript…').count(), 0)
})

// ── PRESENTATION ───────────────────────────────────────────────────────────

test('processing panel: reduced motion, institution accent, and narrow layouts', { timeout: 45_000 }, async (t) => {
  const state = { release: null }
  const origin = await startServer(t, 'dp-presentation', (request, response, next) => {
    const path = request.url?.split('?')[0]
    if (path === '/api/v2/student/me/profile') return send(response, meProfile())
    if (path === '/api/v2/student/me/career/review') return send(response, EMPTY_CAREER)
    if (path === '/api/v2/student/me/resume/upload' && request.method === 'POST') {
      state.release = () => { send(response, RESUME_UPLOAD_OK) }
      return
    }
    next()
  })
  const browser = await startBrowser(t)

  async function openProcessing(page) {
    await page.goto(`${origin}/resume-recovery-preview.html`)
    await page.getByText('Add your resume').waitFor()
    await page.locator('#resume-file').setInputFiles(PDF)
    await page.getByRole('button', { name: 'Upload resume' }).click()
    await page.locator('.dp-panel').waitFor()
  }

  // ── Reduced motion. The rail and pulse go; the copy still advances, because
  //    the stages are driven by timers rather than by the animations.
  const reduced = await browser.newPage({ reducedMotion: 'reduce' })
  await openProcessing(reduced)
  await reduced.getByText('Uploading your resume…').waitFor()
  // The travelling segment is gone outright -- not frozen partway along, which
  // would read as a percentage. What is left is a uniform hairline divider.
  assert.equal(await reduced.locator('.dp-rail-run').isVisible().catch(() => false), false,
    'the travelling segment must not render under reduced motion')
  assert.equal(await reduced.locator('.dp-rail').evaluate((el) => getComputedStyle(el).height), '1px',
    'the rail must degrade to a hairline rule, not a filled bar')
  const markerAnimation = await reduced.locator('.dp-marker').evaluate((el) => getComputedStyle(el).animationName)
  assert.equal(markerAnimation, 'none', 'the marker must not pulse under reduced motion')
  // Nothing on the panel is animating at all.
  const animating = await reduced.locator('.dp-panel').evaluate((panel) =>
    [panel, ...panel.querySelectorAll('*')].filter((el) => getComputedStyle(el).animationName !== 'none').length)
  assert.equal(animating, 0, 'no element may animate under reduced motion')
  // The status still changes, which is the whole point.
  await reduced.getByText('Reading your resume…').waitFor({ timeout: 5000 })
  await reduced.getByText('You’ll review everything before it is saved to your profile.').waitFor()
  await reduced.close()

  // ── Full motion: the rail animates and the segment is genuinely moving.
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  await openProcessing(page)
  const railAnimation = await page.locator('.dp-rail-run').evaluate((el) => getComputedStyle(el).animationName)
  assert.equal(railAnimation, 'dp-rail-travel')

  // ── Institution accent comes from tokens, never a hard-coded hex. Applying a
  //    theme the way institutionTheme.ts does must recolour the rail.
  const accentOf = async (rgb) => page.evaluate((value) => {
    document.documentElement.style.setProperty('--accent-text-rgb', value)
    const el = document.querySelector('.dp-rail-run')
    return getComputedStyle(el).backgroundColor
  }, rgb)
  assert.equal(await accentOf('80 0 0'), 'rgb(80, 0, 0)', 'TAMU maroon must reach the rail')
  assert.equal(await accentOf('0 51 160'), 'rgb(0, 51, 160)', 'SMU blue must reach the rail')
  await page.evaluate(() => { document.documentElement.style.removeProperty('--accent-text-rgb') })

  // ── Responsive: no horizontal overflow, and a long filename truncates
  //    rather than widening the panel.
  for (const viewport of [{ width: 1280, height: 900 }, { width: 834, height: 1112 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await page.waitForTimeout(120)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
      `page overflowed at ${String(viewport.width)}px`)
    const fits = await page.locator('.dp-panel').evaluate((el) => el.scrollWidth <= el.clientWidth + 1)
    assert.equal(fits, true, `the processing panel overflowed at ${String(viewport.width)}px`)
  }

  // Stage text of very different lengths must not move the rail underneath it.
  const railTop = async () => page.locator('.dp-rail').evaluate((el) => Math.round(el.getBoundingClientRect().top))
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.getByText('Uploading your resume…').waitFor()
  const early = await railTop()
  await page.getByText('Extracting experience, projects, and certifications…').waitFor({ timeout: 8000 })
  assert.equal(await railTop(), early, 'the rail shifted when the stage copy changed')

  state.release()
})
