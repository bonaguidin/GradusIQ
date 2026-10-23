import assert from 'node:assert/strict'
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
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-password-input', import.meta.url)),
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

test('the password toggle reveals and hides the value, and reports its state once', { timeout: 45_000 }, async () => {
  const page = await browser.newPage()
  await page.goto(`${origin}/signup-preview.html?mode=confirm`)
  const field = page.locator('#signup-password')
  await field.waitFor()
  const toggle = page.getByRole('button', { name: 'Show password' })
  await field.fill('a-strong-password')

  assert.equal(await field.getAttribute('type'), 'password')
  assert.equal(await toggle.getAttribute('aria-pressed'), 'false')
  assert.equal(await toggle.getAttribute('aria-controls'), 'signup-password')

  await toggle.click()
  assert.equal(await field.getAttribute('type'), 'text')
  assert.equal(await field.inputValue(), 'a-strong-password')
  // One constant name plus aria-pressed: the state is not also in the label.
  assert.equal(await toggle.getAttribute('aria-label'), 'Show password')
  assert.equal(await toggle.getAttribute('aria-pressed'), 'true')

  await toggle.click()
  assert.equal(await field.getAttribute('type'), 'password')
  assert.equal(await toggle.getAttribute('aria-pressed'), 'false')
  await page.close()
})

test('the password toggle is reachable by keyboard and shows a focus ring', { timeout: 45_000 }, async () => {
  const page = await browser.newPage()
  await page.goto(`${origin}/signup-preview.html?mode=confirm`)
  const field = page.locator('#signup-password')
  await field.waitFor()
  await field.focus()
  await page.keyboard.press('Tab')
  const toggle = page.getByRole('button', { name: 'Show password' })
  assert.equal(await toggle.evaluate((node) => node === document.activeElement), true)
  const outline = await toggle.evaluate((node) => getComputedStyle(node).outlineStyle)
  assert.notEqual(outline, 'none')

  await page.keyboard.press('Space')
  assert.equal(await field.getAttribute('type'), 'text')
  await page.close()
})
