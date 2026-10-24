import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

test('a proposed change runs only after Confirm, and the assistant hears about it', { timeout: 60_000 }, async (t) => {
  const { chromium } = await import('playwright')
  const { createServer } = await import('vite')
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-chat-proposals', import.meta.url)),
    logLevel: 'silent',
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

  const chatBodies = []
  await page.route('**/api/v2/student/me/chat', async (route) => {
    chatBodies.push(route.request().postDataJSON())
    const reply = chatBodies.length === 1
      ? {
          reply: 'You can confirm it below.',
          actions: [],
          proposals: [
            {
              id: 'p1',
              kind: 'add_planned_course',
              summary: 'Add CS 3353 (Data Structures) to your Spring 2027 plan',
              payload: { course_code: 'CS 3353', title: 'Data Structures', credit_hours: 3, catalog_course_id: 'c2', year: 2027, season: 'Spring' },
            },
            { id: 'p2', kind: 'refresh_canvas', summary: 'Refresh your Canvas calendar now', payload: {} },
          ],
        }
      : { reply: 'Great.', actions: [] }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(reply) })
  })
  const planned = []
  await page.route('**/api/v2/student/me/planned-courses', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    planned.push(route.request().postDataJSON())
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ planned_course: { kind: 'planned', id: 'pl-9', course_code: 'CS 3353' } }),
    })
  })

  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  await page.goto(`http://127.0.0.1:${String(address.port)}/authenticated-dashboard-preview.html?mode=complete&tour=done`)
  const inline = page.locator('.chat-panel--inline')
  await inline.getByLabel('Message GradusIQ').fill('Add CS 3353 to spring')
  await inline.getByLabel('Message GradusIQ').press('Enter')
  await inline.getByText('Add CS 3353 (Data Structures) to your Spring 2027 plan?').waitFor()

  // Nothing is sent until Confirm.
  assert.equal(planned.length, 0)
  const cards = inline.locator('.chat-proposal')
  assert.equal(await cards.count(), 2)
  await cards.nth(0).getByRole('button', { name: 'Confirm' }).click()
  await inline.getByText('Done. Added CS 3353 to your Spring 2027 plan.').waitFor()
  assert.deepEqual(planned, [{
    course_code: 'CS 3353', year: 2027, season: 'Spring', title: 'Data Structures', credit_hours: 3, catalog_course_id: 'c2',
  }])

  // "No thanks" hides the other card without calling anything.
  await inline.locator('.chat-proposal').nth(1).getByRole('button', { name: 'No thanks' }).click()
  assert.equal(await inline.locator('.chat-proposal').count(), 1)

  // The outcome survives a refresh and goes back to the assistant as history.
  await page.reload()
  await inline.getByText('Done. Added CS 3353 to your Spring 2027 plan.').waitFor()
  await inline.getByLabel('Message GradusIQ').fill('Thanks')
  await inline.getByLabel('Message GradusIQ').press('Enter')
  await inline.getByText('Great.').waitFor()
  assert.equal(
    chatBodies[1].history[1].content,
    'You can confirm it below.\n\n(The student confirmed: Add CS 3353 (Data Structures) to your Spring 2027 plan.)\n'
      + '(The student declined: Refresh your Canvas calendar now.)',
  )
})
