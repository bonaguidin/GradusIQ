import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

test('the assistant offers to remember, saves only on click, and notes can be forgotten', { timeout: 60_000 }, async (t) => {
  const { chromium } = await import('playwright')
  const { createServer } = await import('vite')
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-chat-memory', import.meta.url)),
    logLevel: 'silent',
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

  const notes = []
  const saves = []
  const deletes = []
  await page.route('**/api/v2/student/me/chat', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ reply: 'Remote roles are common in software.', actions: [], remember: 'Aiming for remote roles' }),
    }),
  )
  await page.route('**/api/v2/student/me/memory**', async (route) => {
    const request = route.request()
    if (request.method() === 'POST') {
      const { note } = request.postDataJSON()
      saves.push(note)
      notes.push({ id: '11111111-2222-3333-4444-555555555555', note })
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ note: notes.at(-1) }) })
    }
    if (request.method() === 'DELETE') {
      deletes.push(new URL(request.url()).pathname.split('/').pop())
      notes.length = 0
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ available: true, notes, max_notes: 20 }),
    })
  })

  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const base = `http://127.0.0.1:${String(address.port)}/authenticated-dashboard-preview.html?mode=complete&tour=done`

  await page.goto(base)
  const inline = page.locator('.chat-panel--inline')
  await inline.getByLabel('Message GradusIQ').fill('I want to work remotely')
  await inline.getByLabel('Message GradusIQ').press('Enter')
  await inline.getByText('Remember this for future chats?').waitFor()
  assert.deepEqual(saves, [], 'nothing is saved before the click')

  await inline.getByRole('button', { name: 'Remember', exact: true }).click()
  await inline.getByText('Saved to memory:').waitFor()
  assert.deepEqual(saves, ['Aiming for remote roles'])

  // The saved state survives a refresh, so the offer is not made twice.
  await page.reload()
  await inline.getByText('Saved to memory:').waitFor()
  assert.equal(await inline.getByRole('button', { name: 'Remember', exact: true }).count(), 0)

  // Manage opens Career Profile, where the note can be forgotten.
  await inline.getByRole('button', { name: 'Manage' }).click()
  await page.waitForURL(/career=profile/)
  // The chat closes so it does not cover the list.
  assert.equal(await page.locator('.assistant-dock').count(), 0)
  const panel = page.locator('.memory-notes')
  await panel.getByText('Aiming for remote roles').waitFor()
  await panel.getByRole('button', { name: 'Forget: Aiming for remote roles' }).click()
  await panel.getByText('Nothing yet.').waitFor()
  assert.deepEqual(deletes, ['11111111-2222-3333-4444-555555555555'])
})

test('no memory section and no offer card before the notes table exists', { timeout: 60_000 }, async (t) => {
  const { chromium } = await import('playwright')
  const { createServer } = await import('vite')
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-chat-memory-off', import.meta.url)),
    logLevel: 'silent',
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  let memoryReads = 0
  await page.route('**/api/v2/student/me/memory**', (route) => {
    memoryReads += 1
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ available: false, notes: [], max_notes: 20 }) })
  })
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  await page.goto(`http://127.0.0.1:${String(address.port)}/authenticated-dashboard-preview.html?mode=complete&tour=done&section=career&career=profile`)
  await page.getByRole('heading', { name: 'Career Profile' }).waitFor()
  await page.waitForTimeout(300)
  assert.ok(memoryReads >= 1)
  assert.equal(await page.locator('.memory-notes').count(), 0)
})
