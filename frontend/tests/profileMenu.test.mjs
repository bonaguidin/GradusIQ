import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import test, { after, before } from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'

let server
let browser
let origin

before(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-profile-menu', import.meta.url)),
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

test('the profile menu is a plain disclosure: expanded state, normal links, Escape returns focus, outside click closes', { timeout: 45_000 }, async () => {
  const page = await browser.newPage()
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete`)
  await page.locator('.rail').waitFor()

  const trigger = page.locator('.rail-identity-button')
  assert.equal(await trigger.getAttribute('aria-expanded'), 'false')
  assert.equal(await trigger.getAttribute('aria-haspopup'), null)
  assert.equal(await page.locator('#rail-profile-menu').count(), 0)

  await trigger.click()
  assert.equal(await trigger.getAttribute('aria-expanded'), 'true')
  const panel = page.locator('#rail-profile-menu')
  await panel.waitFor()
  // No ARIA menu semantics: nothing promises arrow-key behaviour it lacks.
  assert.equal(await page.locator('[role="menu"], [role="menuitem"]').count(), 0)
  assert.deepEqual(
    await panel.locator('a, button').allInnerTexts(),
    ['Career Profile', 'Update transcript', 'Update resume', 'Log out'],
  )

  // Escape closes it and puts focus back on the trigger, even from inside.
  await panel.locator('a').first().focus()
  await page.keyboard.press('Escape')
  await panel.waitFor({ state: 'detached' })
  assert.equal(await trigger.getAttribute('aria-expanded'), 'false')
  assert.equal(await page.evaluate(() => document.activeElement?.className), 'rail-identity-button')

  // A click outside closes it too.
  await trigger.click()
  await panel.waitFor()
  await page.locator('.topbar-title').click()
  await panel.waitFor({ state: 'detached' })
  await page.close()
})

test('the profile menu takes its shadow from the card token, not a raw color', async () => {
  const css = await readFile(new URL('../src/index.css', import.meta.url), 'utf8')
  const start = css.indexOf('.rail-profile-menu {')
  const block = css.slice(start, css.indexOf('}', start))
  assert.match(block, /box-shadow: var\(--shadow-card\);/)
  assert.doesNotMatch(block, /rgba?\(/)
})
