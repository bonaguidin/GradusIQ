import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test, { after, before } from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'

// The reported bug: the tour reopened on every sign-in after it was finished,
// because completion lived only in one browser's localStorage. Each test below
// gets a fresh browser context (empty localStorage), which is exactly the
// "new browser / new device / new deploy URL" case that used to re-trigger it.

let server
let browser
let origin

before(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-onboarding-tour', import.meta.url)),
    logLevel: 'silent',
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  origin = `http://127.0.0.1:${String(server.httpServer.address().port)}`
  browser = await chromium.launch()
})

after(async () => {
  await browser?.close()
  await server?.close()
})

// The preview hands the dashboard a session through AuthContext, but the
// real Supabase client (which makes the metadata write) reads its own session
// from storage. Seed one under the client's key for the placeholder project
// "example" so updateUser() sends its request, then stub that request and
// record each metadata write.
async function openPreview(tour, { seenInBrowser = false } = {}) {
  const context = await browser.newContext()
  await context.addInitScript((seen) => {
    const now = Math.floor(Date.now() / 1000)
    localStorage.setItem('sb-example-auth-token', JSON.stringify({
      access_token: 'real-access-token', refresh_token: 'refresh', token_type: 'bearer',
      expires_in: 3600, expires_at: now + 3600,
      user: { id: 'user-real', aud: 'authenticated', user_metadata: {} },
    }))
    if (seen) localStorage.setItem('gradusiq_tour_seen_user-real', '1')
  }, seenInBrowser)
  const page = await context.newPage()
  const writes = []
  await page.route('**/auth/v1/user**', async (route) => {
    const body = route.request().postDataJSON()
    writes.push(body?.data ?? null)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 'user-real', aud: 'authenticated', user_metadata: body?.data ?? {} }),
    })
  })
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete&tour=${tour}`)
  await page.locator('.rail').waitFor()
  return { context, page, writes }
}

const tourDialog = (page) => page.getByRole('dialog', { name: /./ }).filter({ has: page.locator('.tour-eyebrow') })

test('a new account sees the tour once, and skipping it saves completion to the account', { timeout: 30_000 }, async () => {
  const { context, page, writes } = await openPreview('new')
  await tourDialog(page).waitFor()
  await page.getByRole('button', { name: 'Skip tour' }).click()
  await tourDialog(page).waitFor({ state: 'detached' })
  await page.waitForTimeout(200)
  assert.equal(writes.length, 1)
  assert.match(writes[0].onboarding_tour_completed_at, /^\d{4}-\d{2}-\d{2}T/)

  // Same browser, next sign-in: stays closed.
  await page.reload()
  await page.locator('.rail').waitFor()
  await page.waitForTimeout(300)
  assert.equal(await tourDialog(page).count(), 0)
  await context.close()
})

test('an account that finished the tour elsewhere does not see it in a fresh browser', { timeout: 30_000 }, async () => {
  const { context, page, writes } = await openPreview('done')
  await page.waitForTimeout(300)
  assert.equal(await tourDialog(page).count(), 0)
  assert.equal(writes.length, 0)

  // The "?" button still replays it, and closing a replay writes nothing new.
  await page.getByRole('button', { name: 'Replay the new-user tour' }).click()
  await tourDialog(page).waitFor()
  await page.keyboard.press('Escape')
  await tourDialog(page).waitFor({ state: 'detached' })
  await page.waitForTimeout(200)
  assert.equal(writes.length, 0)
  await context.close()
})

test('a browser that finished the tour before this fix copies it up to the account', { timeout: 30_000 }, async () => {
  const { context, page, writes } = await openPreview('new', { seenInBrowser: true })
  await page.waitForTimeout(300)
  assert.equal(await tourDialog(page).count(), 0)
  assert.equal(writes.length, 1)
  assert.ok(writes[0].onboarding_tour_completed_at)
  await context.close()
})
