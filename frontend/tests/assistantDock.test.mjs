import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

test('the assistant panel opens on other pages and keeps one conversation', { timeout: 60_000 }, async (t) => {
  const { chromium } = await import('playwright')
  const { createServer } = await import('vite')
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-assistant-dock', import.meta.url)),
    logLevel: 'silent',
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()

  const bodies = []
  await page.route('**/api/v2/student/me/chat', async (route) => {
    bodies.push(route.request().postDataJSON())
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ reply: 'Your GPA is **3.42**.\n\n- Keep CS 3341\n- Retake MATH 2339' }),
    })
  })

  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const base = `http://127.0.0.1:${String(address.port)}/authenticated-dashboard-preview.html?mode=complete&tour=done`

  // tour=done gives the preview a signed-in user id, which keys the saved
  // conversation. Overview already has the chat inline, so no launcher there.
  await page.goto(base)
  await page.getByLabel('Message GradusIQ').waitFor()
  assert.equal(await page.locator('.assistant-launcher').count(), 0)

  // On Academic the launcher opens the panel, and the message names the page.
  await page.goto(`${base}&section=academic&academic=gpa-calculator`)
  const launcher = page.locator('.assistant-launcher')
  await launcher.waitFor()
  await launcher.click()
  const dock = page.locator('.assistant-dock')
  const input = dock.getByLabel('Message GradusIQ')
  assert.equal(await input.evaluate((node) => node === document.activeElement), true)
  await input.fill('How is my GPA?')
  await input.press('Enter')
  await dock.locator('strong', { hasText: '3.42' }).waitFor()
  assert.equal(await dock.locator('.chat-msg--assistant li').count(), 2)
  assert.equal(bodies[0].page, 'academic/gpa-calculator')

  // A refresh keeps the conversation and the panel can be closed with Escape.
  await page.reload()
  await page.locator('.assistant-launcher').click()
  await dock.getByText('How is my GPA?').waitFor()
  await page.keyboard.press('Escape')
  await page.locator('.assistant-launcher').waitFor()
  assert.equal(await dock.count(), 0)
  assert.equal(await page.locator('.assistant-launcher').evaluate((node) => node === document.activeElement), true)

  // Back on Overview the same conversation is in the inline chat.
  await page.goto(base)
  await page.locator('.chat-panel--inline').getByText('How is my GPA?').waitFor()

  // New chat clears it everywhere.
  await page.locator('.chat-panel--inline').getByRole('button', { name: 'New chat' }).click()
  assert.equal(await page.locator('.chat-msg').count(), 0)
})
