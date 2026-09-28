import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test, { after, before } from 'node:test'
import { readFile } from 'node:fs/promises'
import { chromium } from 'playwright'
import { createServer } from 'vite'

// The reported production bug: with the project's "Confirm email" setting OFF
// (mailer_autoconfirm true, read live from /auth/v1/settings), signUp() confirms
// the address inline and returns a session -- and the form still rendered
// "Check your email" for a link that is never sent. These cover both settings,
// because the setting is a per-project toggle and either value must work.

const TAMU_ID = '75d68331-91d2-47e8-9671-2a3b065955d0'

// One server and one browser for the whole file. Standing up four of each
// concurrently with the other suites' servers starved this file badly enough to
// time out a 30s locator wait, and nothing here needs isolation beyond a fresh
// page per test -- the harness's state lives in the page, not the server.
let server
let browser
let origin

before(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    logLevel: 'silent',
    // Private dep-optimization cache. Test files run in parallel, and every
    // Vite dev server on this root otherwise writes the same
    // node_modules/.vite -- concurrent optimizer runs clobber each other's
    // cache, which stalls whichever server is mid-request behind a re-optimize
    // and times out locator waits in a DIFFERENT suite. Isolating it keeps this
    // file from contributing to that.
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-signup-test', import.meta.url)),
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  origin = `http://127.0.0.1:${String(address.port)}`
  browser = await chromium.launch()
})

after(async () => {
  await browser?.close()
  await server?.close()
})

/** A fresh page against the harness, with signUp() stubbed per `mode`. */
async function open(t, mode) {
  const page = await browser.newPage()
  t.after(async () => page.close())
  await page.goto(`${origin}/signup-preview.html?mode=${mode}`)
  await page.getByRole('button', { name: 'Create account' }).waitFor()
  return page
}

/** Fill every required field with a valid, of-age submission. */
async function fillForm(page, email = 'newstudent@example.com') {
  await page.getByLabel('Full name').fill('Deepak Murali')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('a-strong-password')
  await page.getByLabel('Date of birth').fill('2000-04-12')
  await page.getByLabel('Institution').selectOption(TAMU_ID)
}

test('confirmation disabled: a signup that returns a session goes to the dashboard, not check-your-email', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'session')
  await fillForm(page)
  await page.getByRole('button', { name: 'Create account' }).click()

  // The whole bug in one assertion.
  await page.getByRole('heading', { name: 'Dashboard reached' }).waitFor()
  assert.equal(await page.getByText('Check your email').count(), 0)
  assert.equal(await page.getByText(/We sent a confirmation link/).count(), 0)

  // Exactly one signup call: no retry loop, and no second attempt from a
  // re-render. StrictMode double-invokes effects, so a page that drove signup
  // from an effect rather than the submit handler would show 2 here.
  assert.equal(await page.evaluate(() => document.body.dataset.signupCalls), '1')
})

test('confirmation enabled: a signup with no session still shows check-your-email and does not navigate', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'confirmation')
  await fillForm(page, 'pending@example.com')
  await page.getByRole('button', { name: 'Create account' }).click()

  await page.getByText('Check your email').waitFor()
  await page.getByText(/We sent a confirmation link/).waitFor()
  // The address is echoed back so the student can spot a typo.
  await page.getByText('pending@example.com').waitFor()

  // Never the dashboard: there is no session, so there is nothing to render it
  // with and provisioning must not be attempted.
  assert.equal(await page.getByRole('heading', { name: 'Dashboard reached' }).count(), 0)
  assert.equal(await page.evaluate(() => document.body.dataset.signupCalls), '1')
})

test('a rejected signup shows the error, with no confirmation screen and no navigation', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'error')
  await fillForm(page)
  await page.getByRole('button', { name: 'Create account' }).click()

  const alert = page.getByRole('alert')
  await alert.waitFor()
  assert.match(await alert.innerText(), /Password is too weak/)

  assert.equal(await page.getByText('Check your email').count(), 0)
  assert.equal(await page.getByRole('heading', { name: 'Dashboard reached' }).count(), 0)

  // The form stays usable: the button must not be stuck mid-submit.
  const button = page.getByRole('button', { name: 'Create account' })
  assert.equal(await button.isDisabled(), false)
})

test('the institution the student picked survives into the metadata provisioning reads back', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'session')
  await fillForm(page)
  await page.getByRole('button', { name: 'Create account' }).click()
  await page.getByRole('heading', { name: 'Dashboard reached' }).waitFor()

  // student_institutions needs a real institution_id and students.name is NOT
  // NULL, so a form-to-metadata mistake here produces a half-provisioned
  // account rather than a visible failure. This is the production TAMU case.
  const metadata = JSON.parse(await page.evaluate(() => document.body.dataset.signupMetadata))
  assert.deepEqual(metadata, {
    name: 'Deepak Murali',
    institution_id: TAMU_ID,
    date_of_birth: '2000-04-12',
  })
  assert.equal(await page.evaluate(() => document.body.dataset.signupEmail), 'newstudent@example.com')
})

/** Source with comments removed, so a structural guard reads code and not prose. */
function codeOnly(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
}

test('the signup page never provisions: AuthContext stays the single provisioning path', async () => {
  // A structural guard, not a behavioural one. The double-provisioning failure
  // this prevents is invisible in the browser -- both writers are idempotent
  // against the unique constraints, so the damage is a race and duplicated
  // network work, not a duplicate row. The only durable check is that the page
  // has no provisioning code at all.
  const page = codeOnly(
    await readFile(new URL('../src/pages/SignUpPage.tsx', import.meta.url), 'utf8'),
  )

  assert.equal(page.includes('studentAccount'), false, 'SignUpPage must not touch the provisioning module')
  assert.equal(page.includes('resolveStudentAccount'), false, 'SignUpPage must not resolve accounts itself')
  assert.equal(page.includes("from('students')"), false, 'SignUpPage must not write student rows')
  assert.equal(page.includes('supabase'), false, 'SignUpPage must reach auth only through useAuth')

  // And the provisioning entry point has exactly one caller: the AuthContext
  // effect keyed on the signed-in user id.
  const context = codeOnly(
    await readFile(new URL('../src/auth/AuthContext.tsx', import.meta.url), 'utf8'),
  )
  const callSites = context.split('resolveStudentAccountOnce(').length - 1
  assert.equal(callSites, 1, 'provisioning must be invoked from exactly one place')
})
