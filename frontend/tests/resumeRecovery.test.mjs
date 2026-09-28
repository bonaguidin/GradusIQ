import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { chromium } from 'playwright'
import { createServer } from 'vite'
import { meProfile } from './fixtures/meProfile.mjs'

const EMPTY = { career_profile: null, certifications: [], work_experience: [], projects: [] }
const PENDING = {
  career_profile: {
    id: 'cp-recovered', source: 'resume_parse', target_roles: ['Software Engineer'],
    interests: ['systems'], career_goals: null, geographic_preference: null,
    ai_anxiety_level: null, skills_technical: ['TypeScript'], skills_soft: [], ai_exposure: null,
  },
  certifications: [],
  work_experience: [{
    id: 'work-recovered', source: 'resume_parse', employer: 'Acme', role: 'Intern',
    duration: null, location: null, description: null, skills_gained: ['TypeScript'],
  }],
  projects: [],
}

function json(response, status = 200) {
  response.statusCode = status
  response.setHeader('content-type', 'application/json')
  response.end(JSON.stringify(status === 200 ? response.body : { detail: response.body }))
}

test('resume page recovers persisted review across load, error, confirmation, and upload', { timeout: 45_000 }, async (t) => {
  const state = { pending: true, failReview: false, reviewGets: 0, uploads: 0, confirms: 0, careerConfirmed: false, profileReads: 0 }
  const apiPlugin = {
    name: 'resume-recovery-test-api',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (path === '/api/v2/student/me/profile' && request.method === 'GET') {
          state.profileReads += 1
          response.body = meProfile({ career: state.careerConfirmed })
          json(response)
          return
        }
        if (path === '/api/v2/student/me/career/review' && request.method === 'GET') {
          state.reviewGets += 1
          response.body = state.failReview ? 'Could not load records for review.' : state.pending ? PENDING : EMPTY
          json(response, state.failReview ? 502 : 200)
          return
        }
        if (path === '/api/v2/student/me/career/confirm' && request.method === 'POST') {
          state.confirms += 1
          state.pending = false
          state.careerConfirmed = true
          response.body = {
            status: 'ok', scope: 'all_unconfirmed',
            confirmed: { career_profiles: 1, certifications: 0, work_experience: 1, projects: 0 },
            total_confirmed: 2,
          }
          json(response)
          return
        }
        if (path === '/api/v2/student/me/resume/upload' && request.method === 'POST') {
          state.uploads += 1
          state.pending = true
          response.body = {
            status: 'ok', extraction: { status: 'ok', page_count: 1 }, warnings: [], model: 'test',
            career_profile: { outcome: 'inserted' },
            written: {
              certifications: { inserted: 0, skipped_duplicate: 0 },
              work_experience: { inserted: 1, skipped_duplicate: 0 },
              projects: { inserted: 0, skipped_duplicate: 0 },
            },
          }
          json(response)
          return
        }
        next()
      })
    },
  }

  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-resume-recovery', import.meta.url)),
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const url = `http://127.0.0.1:${String(address.port)}/resume-recovery-preview.html`

  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()

  // CASE 1: pending review exists; upload never flashes before review.
  await page.goto(url)
  await page.getByRole('heading', { name: 'Here’s what we read.' }).waitFor()
  assert.equal(await page.getByText('Add your resume').count(), 0)
  assert.equal(state.reviewGets, 1, 'recovered sections must prevent CareerReview from issuing a duplicate GET')

  // CASE 3: a full reload recovers from backend state again.
  await page.reload()
  await page.getByRole('heading', { name: 'Here’s what we read.' }).waitFor()
  assert.equal(state.reviewGets, 2)

  // CASE R1: a confirmed backend success goes straight to the dashboard.
  const profileReadsBeforeConfirm = state.profileReads
  await page.getByRole('button', { name: 'Confirm all' }).click()
  await page.waitForFunction(() => location.hash === '#/dashboard')
  assert.equal(state.confirms, 1)

  // CASE R4: the dashboard says what happened, as an accessible status.
  const notice = page.locator('[role="status"] .dash-notice')
  await notice.waitFor()
  assert.equal(
    await notice.innerText().then((t) => t.includes('Resume saved — your career profile has been updated.')),
    true,
  )

  // CASES R2/R3: the terminal screen and its button are gone, not relocated.
  assert.equal(await page.getByText('Your profile has been saved').count(), 0)
  assert.equal(await page.getByRole('link', { name: 'Go to dashboard' }).count(), 0)
  assert.equal(await page.getByRole('button', { name: 'Go to dashboard' }).count(), 0)
  // The old copy asserted against here is doubly gone.
  assert.equal(await page.getByText('You can close this page.').count(), 0)

  // CASE R5: the canonical profile was re-read as part of the handover.
  assert.ok(state.profileReads > profileReadsBeforeConfirm, 'confirmation must refetch /me/profile')

  // CASE R6: the newly confirmed career data is on screen, not the pre-confirm
  // empty state -- which is what a stale profile would have rendered.
  await page.getByRole('button', { name: 'Career' }).click()
  // CareerProfile now lives under the Career Profile sidebar child.
  await page.getByRole('button', { name: 'Career Profile' }).click()
  // The redesigned Career section shows a target role in both the summary and
  // the direction list, so this names the one it means.
  await page.locator('.cp-roles li').getByText('Software Engineer').waitFor()
  assert.equal(await page.getByRole('link', { name: 'Upload resume' }).count(), 0)

  // The notice belongs to one transition: dismissible, and gone after a reload.
  await page.locator('.dash-notice-dismiss').click()
  assert.equal(await page.locator('.dash-notice').count(), 0)
  await page.reload()
  await page.getByRole('button', { name: 'Career' }).waitFor()
  assert.equal(await page.locator('.dash-notice').count(), 0)

  // CASE R10: the confirmed review does not come back.
  await page.goto(`${url}#/`)
  await page.getByText('Add your resume').waitFor()
  assert.equal(await page.getByRole('heading', { name: 'Here’s what we read.' }).count(), 0)

  // CASE 4: an API failure is not treated as empty; retry performs a new GET.
  state.failReview = true
  await page.reload()
  await page.getByText('Could not check your resume').waitFor()
  assert.equal(await page.getByText('Add your resume').count(), 0)
  state.failReview = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await page.getByText('Add your resume').waitFor()

  // CASE 6: no-pending upload still enters the existing CareerReview flow.
  await page.locator('#resume-file').setInputFiles({
    name: 'resume.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-test'),
  })
  await page.getByRole('button', { name: 'Upload resume' }).click()
  await page.getByRole('heading', { name: 'Here’s what we read.' }).waitFor()
  assert.equal(state.uploads, 1)
  assert.equal(await page.getByText('Add your resume').count(), 0)
})

test('a slow confirm dims the resume review too, identically to transcript', { timeout: 30_000 }, async (t) => {
  // The overlay lives in the shared CommitBar precisely so the two flows
  // cannot diverge here. This asserts the resume side actually receives it,
  // rather than trusting that sharing a component is enough.
  const apiPlugin = {
    name: 'resume-slow-confirm-api',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (path === '/api/v2/student/me/profile' && request.method === 'GET') {
          response.body = meProfile({ career: true })
          json(response)
          return
        }
        if (path === '/api/v2/student/me/career/review' && request.method === 'GET') {
          response.body = PENDING
          json(response)
          return
        }
        if (path === '/api/v2/student/me/career/confirm' && request.method === 'POST') {
          setTimeout(() => {
            response.body = {
              status: 'ok', scope: 'all_unconfirmed',
              confirmed: { career_profiles: 1, certifications: 0, work_experience: 1, projects: 0 },
              total_confirmed: 2,
            }
            json(response)
          }, 1500)
          return
        }
        next()
      })
    },
  }

  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-resume-recovery', import.meta.url)),
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

  await page.goto(`http://127.0.0.1:${String(address.port)}/resume-recovery-preview.html`)
  await page.getByRole('button', { name: 'Confirm all' }).click()

  await page.getByText('Saving your record').waitFor()
  await page.getByText('This can take up to a minute if the server is waking up.').waitFor()
  assert.equal(await page.locator('.rv-confirming').count(), 1)

  const button = page.getByRole('button', { name: 'Saving…' })
  await button.waitFor()
  assert.equal(await button.isDisabled(), true)
  assert.equal(await page.getByRole('alert').count(), 0)

  // It stays up THROUGH the handover and is gone once the dashboard replaced it.
  await page.waitForFunction(() => location.hash === '#/dashboard')
  assert.equal(await page.locator('.rv-confirming').count(), 0)
  await page.locator('.dash-notice').waitFor()
})

test('resume confirm failures stay on the review screen and stay retryable', { timeout: 45_000 }, async (t) => {
  // CASE R7 (500) and CASE R8 (a confirm that never completes -- aborted at the
  // network layer rather than waiting out the real 60s CONFIRM_TIMEOUT_MS; both
  // reach the same `ok: false` branch, and resumeApi.test.mjs pins the timeout
  // status mapping itself).
  const apiPlugin = {
    name: 'resume-confirm-failure-api',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (path === '/api/v2/student/me/profile' && request.method === 'GET') {
          response.body = meProfile()
          json(response)
          return
        }
        if (path === '/api/v2/student/me/career/review' && request.method === 'GET') {
          response.body = PENDING
          json(response)
          return
        }
        if (path === '/api/v2/student/me/career/confirm' && request.method === 'POST') {
          response.body = 'Your records could not be confirmed.'
          json(response, 500)
          return
        }
        next()
      })
    },
  }

  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-resume-failures', import.meta.url)),
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
  await page.goto(`http://127.0.0.1:${String(address.port)}/resume-recovery-preview.html`)

  // CASE R7: API failure.
  await page.getByRole('button', { name: 'Confirm all' }).click()
  await page.getByText('Your records could not be confirmed.').waitFor()
  assert.equal(await page.evaluate(() => location.hash), '')
  await page.getByRole('heading', { name: 'Here’s what we read.' }).waitFor()
  assert.equal(await page.locator('.dash-notice').count(), 0)
  assert.equal(await page.locator('.rv-confirming').count(), 0)
  assert.equal(await page.getByRole('button', { name: 'Confirm all' }).isEnabled(), true)

  // CASE R8: a confirm that never completes.
  //
  // Waits on the SETTLED outcome, never on the intermediate "Saving…" label. An
  // aborted request can resolve inside a single render, so that label is not
  // guaranteed to be observable -- waiting for it is a race that hangs for the
  // full locator timeout when it loses. What matters here is where the student
  // ends up, and that is deterministic.
  await page.route('**/api/v2/student/me/career/confirm', (route) => route.abort('timedout'))
  await page.getByRole('button', { name: 'Confirm all' }).click()
  await page.getByText('Could not confirm your records (status 0).').waitFor()
  assert.equal(await page.evaluate(() => location.hash), '')
  await page.getByRole('heading', { name: 'Here’s what we read.' }).waitFor()
  assert.equal(await page.locator('.dash-notice').count(), 0)
  assert.equal(await page.locator('.rv-confirming').count(), 0)
  assert.equal(await page.getByRole('button', { name: 'Confirm all' }).isEnabled(), true)
})
