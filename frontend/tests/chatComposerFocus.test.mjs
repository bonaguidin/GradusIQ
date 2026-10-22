import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('the chat input stays enabled while a reply is pending so Enter keeps focus', async () => {
  const panel = await readFile(new URL('../src/components/ChatPanel.tsx', import.meta.url), 'utf8')
  const input = panel.match(/<input\s+ref=\{inputRef\}[\s\S]*?\/>/)
  assert.ok(input, 'chat input carries the focus ref')
  assert.match(input[0], /disabled=\{!canSend\}/)
  assert.doesNotMatch(input[0], /disabled=\{sending/)
  assert.match(panel, /if \(!trimmed \|\| sending \|\| !canSend\) return;/)
  assert.match(panel, /inputRef\.current\?\.focus\(\);\s*void submit\(s\);/)
})

test('pressing Enter with text while a reply is pending says why nothing was sent, then clears', { timeout: 45_000 }, async (t) => {
  const { fileURLToPath } = await import('node:url')
  const { chromium } = await import('playwright')
  const { createServer } = await import('vite')
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-chat-pending', import.meta.url)),
    logLevel: 'silent',
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()

  const requests = []
  let release
  const gate = new Promise((resolve) => { release = resolve })
  await page.route('**/api/v2/student/me/chat', async (route) => {
    requests.push(route.request().postDataJSON().message)
    await gate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ reply: 'Here you go.' }) })
  })

  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  await page.goto(`http://127.0.0.1:${String(address.port)}/authenticated-dashboard-preview.html?mode=complete`)
  const input = page.getByLabel('Message GradusIQ')
  await input.waitFor()

  await input.fill('First question')
  await input.press('Enter')
  await page.locator('.chat-typing').waitFor()

  // Second message while the first is pending: nothing is sent, and it says why.
  await input.fill('Second question')
  await input.press('Enter')
  await page.getByRole('status').filter({ hasText: 'Still answering your last message' }).waitFor()
  assert.deepEqual(requests, ['First question'])
  assert.equal(await input.inputValue(), 'Second question')
  assert.equal(await input.evaluate((node) => node === document.activeElement), true)

  // The reply landing clears the notice for good.
  release()
  await page.getByText('Here you go.').waitFor()
  assert.equal(await page.getByText('Still answering your last message').count(), 0)
  assert.equal(await input.inputValue(), 'Second question')
})
