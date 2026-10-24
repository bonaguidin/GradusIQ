import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

test('assistant action buttons open the page and keep the chat beside it', { timeout: 60_000 }, async (t) => {
  const { chromium } = await import('playwright')
  const { createServer } = await import('vite')
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-chat-actions', import.meta.url)),
    logLevel: 'silent',
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

  const bodies = []
  await page.route('**/api/v2/student/me/chat', async (route) => {
    bodies.push(route.request().postDataJSON())
    const reply = bodies.length === 1
      ? { reply: 'Your GPA is 3.42.', actions: ['gpa-calculator', 'made-up', 'report-issue'] }
      : { reply: 'Sure.', actions: [] }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(reply) })
  })

  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const base = `http://127.0.0.1:${String(address.port)}/authenticated-dashboard-preview.html?mode=complete&tour=done`

  await page.goto(base)
  const inline = page.locator('.chat-panel--inline')
  await inline.getByLabel('Message GradusIQ').fill('What is my GPA?')
  await inline.getByLabel('Message GradusIQ').press('Enter')
  await inline.getByText('Your GPA is 3.42.').waitFor()

  // Unknown ids never become buttons.
  const buttons = inline.locator('.chat-action')
  assert.deepEqual(await buttons.allTextContents(), ['Open GPA Calculator', 'Report a bug'])

  // The button goes to the page, keeps the preview fixture, and the same
  // conversation is open in the side panel.
  await inline.getByRole('button', { name: 'Open GPA Calculator' }).click()
  await page.waitForURL(/section=academic/)
  const url = new URL(page.url())
  assert.equal(url.searchParams.get('academic'), 'gpa-calculator')
  assert.equal(url.searchParams.get('mode'), 'complete')
  const dock = page.locator('.assistant-dock')
  await dock.getByText('Your GPA is 3.42.').waitFor()

  // Buttons survive a refresh, and are never sent back to the server.
  await page.reload()
  await page.locator('.assistant-launcher').click()
  await dock.getByRole('button', { name: 'Report a bug' }).waitFor()
  await dock.getByLabel('Message GradusIQ').fill('Thanks')
  await dock.getByLabel('Message GradusIQ').press('Enter')
  await dock.getByText('Sure.').waitFor()
  assert.deepEqual(bodies[1].history[1], { role: 'assistant', content: 'Your GPA is 3.42.' })

  // "Report a bug" opens the same pop-up as the topbar bug icon.
  await dock.getByRole('button', { name: 'Report a bug' }).click()
  await page.getByRole('dialog').waitFor()
})
