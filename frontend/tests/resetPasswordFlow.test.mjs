import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test, { after, before } from 'node:test'
import { readFile } from 'node:fs/promises'
import { chromium } from 'playwright'
import { createServer } from 'vite'

// Covers requestPasswordReset/confirmPasswordReset (via the harness's stubbed
// AuthContext, whose calls are recorded on document.body.dataset -- same
// convention as signupFlow.test.mjs) and both new pages' behavior: the
// request page must never reveal whether an email has an account, and the
// confirm page must gate on session state and never show a raw Supabase
// error string.

let server
let browser
let origin

before(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    logLevel: 'silent',
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-reset-password-test', import.meta.url)),
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

async function open(t, entry, mode) {
  const page = await browser.newPage()
  t.after(async () => page.close())
  await page.goto(`${origin}/reset-password-preview.html?entry=${entry}&mode=${mode}`)
  return page
}

test('request page: a resolved request shows the generic success message', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'request', 'success')
  await page.getByLabel('Email').fill('student@example.com')
  await page.getByRole('button', { name: 'Send reset link' }).click()

  await page.getByText('If an account exists for this email, a reset link has been sent.').waitFor()
  assert.equal(await page.evaluate(() => document.body.dataset.resetRequestCalls), '1')
  assert.equal(
    await page.evaluate(() => document.body.dataset.resetRequestEmail),
    'student@example.com',
  )
})

test('request page: a rejected request shows the SAME generic success message, never an error', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'request', 'error')
  await page.getByLabel('Email').fill('nobody@example.com')
  await page.getByRole('button', { name: 'Send reset link' }).click()

  // The whole enumeration-prevention point: success and failure render
  // identically from the student's side.
  await page.getByText('If an account exists for this email, a reset link has been sent.').waitFor()
  assert.equal(await page.getByRole('alert').count(), 0)
  assert.equal(await page.evaluate(() => document.body.dataset.resetRequestCalls), '1')
})

test('request page: links back to /login', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'request', 'success')
  await page.getByRole('link', { name: 'Back to sign in' }).waitFor()
})

test('confirm page: while sessionLoading, shows a spinner and no form', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'confirm', 'loading')
  await page.locator('.spinner').waitFor()
  assert.equal(await page.getByLabel('New password').count(), 0)
})

test('confirm page: no session renders the expired-link state, not the form', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'confirm', 'no-session')
  await page.getByText('This password reset link is invalid or has expired.').waitFor()
  await page.getByRole('link', { name: 'Request a new reset link' }).waitFor()
  assert.equal(await page.getByLabel('New password').count(), 0)
})

// The core regression test for the "any session passes" gap: a session that
// exists for a reason OTHER than opening a reset link (ordinary sign-in,
// another open tab, a token refresh) must not unlock the form. The gate is
// isPasswordRecovery, not merely session presence.
test('confirm page: a session that is not a recovery session renders the SAME expired-link state, not the form', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'confirm', 'signed-in')
  await page.getByText('This password reset link is invalid or has expired.').waitFor()
  await page.getByRole('link', { name: 'Request a new reset link' }).waitFor()
  assert.equal(await page.getByLabel('New password').count(), 0)
})

test('confirm page: mismatched passwords block submission before any call is made', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'confirm', 'success')
  await page.getByLabel('New password', { exact: true }).fill('a-strong-password')
  await page.getByLabel('Confirm new password').fill('a-different-password')
  await page.getByRole('button', { name: 'Update password' }).click()

  const alert = page.getByRole('alert')
  await alert.waitFor()
  assert.match(await alert.innerText(), /Passwords do not match/)
  assert.equal(await page.evaluate(() => document.body.dataset.resetConfirmCalls), undefined)
})

test('confirm page: a matching submission calls confirmPasswordReset and navigates to /login with a success note', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'confirm', 'success')
  await page.getByLabel('New password', { exact: true }).fill('a-strong-password')
  await page.getByLabel('Confirm new password').fill('a-strong-password')
  await page.getByRole('button', { name: 'Update password' }).click()

  await page.getByText('Password updated. Sign in with your new password.').waitFor()
  assert.equal(await page.evaluate(() => document.body.dataset.resetConfirmCalls), '1')
  assert.equal(
    await page.evaluate(() => document.body.dataset.resetConfirmPassword),
    'a-strong-password',
  )
})

test('confirm page: an expired/rejected reset shows a friendly message, never the raw Supabase error', { timeout: 45_000 }, async (t) => {
  const page = await open(t, 'confirm', 'error')
  await page.getByLabel('New password', { exact: true }).fill('a-strong-password')
  await page.getByLabel('Confirm new password').fill('a-strong-password')
  await page.getByRole('button', { name: 'Update password' }).click()

  const alert = page.getByRole('alert')
  await alert.waitFor()
  const text = await alert.innerText()
  assert.match(text, /reset link may have expired/)
  // The stub's raw error message must never leak to the page.
  assert.doesNotMatch(text, /Auth session missing/)
})

/** Source with comments removed, so a structural guard reads code and not prose. */
function codeOnly(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
}

test('AuthContext: requestPasswordReset and confirmPasswordReset mirror signInWithPassword\'s throw-on-error shape', async () => {
  const context = codeOnly(
    await readFile(new URL('../src/auth/AuthContext.tsx', import.meta.url), 'utf8'),
  )

  assert.match(context, /resetPasswordForEmail\(email/)
  assert.match(context, /redirectTo:\s*`\$\{window\.location\.origin\}\/reset-password\/confirm`/)
  assert.match(context, /updateUser\(\{\s*password:\s*newPassword\s*\}\)/)

  // Both new methods must throw the raw Supabase error, same as
  // signInWithPassword/signUpWithPassword -- no invented wrapper shape.
  const requestBody = context.slice(context.indexOf('const requestPasswordReset'))
  const confirmBody = context.slice(context.indexOf('const confirmPasswordReset'))
  assert.match(requestBody.slice(0, 400), /if \(error\) throw error;/)
  assert.match(confirmBody.slice(0, 400), /if \(error\) throw error;/)
})

test('AuthContext: isPasswordRecovery is set only from the PASSWORD_RECOVERY event, not from session presence', async () => {
  const context = codeOnly(
    await readFile(new URL('../src/auth/AuthContext.tsx', import.meta.url), 'utf8'),
  )

  assert.match(context, /setIsPasswordRecovery\(_event === 'PASSWORD_RECOVERY'\)/)

  // Guards against a regression back to gating on session alone: the confirm
  // page's decision must be sourced from useAuth(), not re-derived locally.
  const page = codeOnly(
    await readFile(new URL('../src/pages/ResetPasswordConfirmPage.tsx', import.meta.url), 'utf8'),
  )
  assert.match(page, /isPasswordRecovery/)
  assert.match(page, /if \(!session \|\| !isPasswordRecovery\)/)
})
