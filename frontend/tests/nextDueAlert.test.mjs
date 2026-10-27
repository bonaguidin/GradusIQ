import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { planningRoutes } from './fixtures/planningRoutes.mjs'

// The Overview's "Next due" alert, driven through the real
// AuthenticatedDashboard in the preview harness. The Canvas calendar route is
// stubbed with page.route so each case sets its own payload. The clock is
// frozen at Tue 2026-10-27 10:00 AM in America/Chicago (15:00Z) and the
// browser is pinned to that zone and en-US, so the viewer-zone text is exact.

const NOW = new Date('2026-10-27T15:00:00Z')
const CALENDAR = '**/api/v2/student/me/canvas-calendar'

const item = (overrides = {}) => ({
  uid: 'event-assignment-1',
  title: 'Homework Assignment #4',
  course_label: 'CSCE 222 504:',
  kind: 'assignment',
  starts_at: '2026-10-29T20:55:00Z', // Thu Oct 29, 3:55 PM CDT
  ends_at: null,
  all_day: false,
  likely_exam: false,
  url: 'https://canvas.tamu.edu/courses/1/assignments/1',
  ...overrides,
})
const connected = (events, extra = {}) => ({
  connected: true,
  canvas_host: 'canvas.tamu.edu',
  feed_host: 'canvas.tamu.edu',
  synced_at: '2026-10-27T14:50:00Z',
  last_error: null,
  events,
  ...extra,
})

test('next-due alert: selection, cues, hidden states, and the click through to the Canvas card', { timeout: 120_000 }, async (t) => {
  const planning = planningRoutes()
  const apiPlugin = {
    name: 'next-due-api',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/requirement-satisfaction' || path?.startsWith('/api/v2/student/me/analysis-cache/')) {
          response.setHeader('content-type', 'application/json')
          response.statusCode = 404
          response.end(JSON.stringify({ detail: 'Not found.' }))
          return undefined
        }
        next()
      })
    },
  }
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-next-due', import.meta.url)),
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const origin = `http://127.0.0.1:${String(address.port)}`
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const context = await browser.newContext({ timezoneId: 'America/Chicago', locale: 'en-US', viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  await page.clock.setFixedTime(NOW)
  await page.route('**/rest/v1/institutions*', (route) =>
    route.fulfill({ status: 200, headers: { 'content-type': 'application/vnd.pgrst.object+json' }, body: 'null' }))

  let reply = { status: 200, body: connected([item()]) }
  let calendarRequests = 0
  await page.route(CALENDAR, (route) => {
    calendarRequests += 1
    return route.fulfill({ status: reply.status, headers: { 'content-type': 'application/json' }, body: JSON.stringify(reply.body) })
  })

  async function openOverview(next) {
    reply = next
    calendarRequests = 0
    // The calendar answer has arrived (or failed) before we assert absence.
    const answered = page.waitForResponse((r) => r.url().includes('/canvas-calendar'))
    await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete`)
    await page.getByRole('heading', { name: 'Alex Morgan' }).waitFor()
    await answered
    await page.waitForTimeout(300)
  }
  const alert = () => page.getByRole('region', { name: 'Next due' })

  // CASE 1: connected, one upcoming item, two days out.
  await openOverview({ status: 200, body: connected([item()]) })
  await alert().waitFor()
  const text = (await alert().innerText()).replace(/\s+/g, ' ')
  assert.match(text, /Next due: Homework Assignment #4, CSCE 222 504, Thu, Oct 29, 3:55 PM \(in 2 days\)/)
  assert.doesNotMatch(text, /Due soon/)
  assert.equal(await alert().getAttribute('data-due-soon'), null)
  assert.equal(await alert().locator('time').getAttribute('datetime'), '2026-10-29T20:55:00.000Z')
  const link = alert().getByRole('link')
  assert.match(await link.getAttribute('aria-label'), /^Next due: Homework Assignment #4, CSCE 222 504, due Thu, Oct 29, 3:55 PM, in 2 days\. Go to Coming up in Canvas$/)
  assert.equal(await alert().locator('[role="status"], [aria-live]').count(), 0, 'no new live region')
  // Order: name header, alert, chat, stat tiles.
  const order = await page.evaluate(() => {
    const top = (sel) => document.querySelector(sel)?.getBoundingClientRect().top ?? -1
    return [top('.overview-header'), top('.next-due'), top('.chat-panel'), top('.overview-stats')]
  })
  assert.ok(order.every((v) => v >= 0) && order.every((v, i) => i === 0 || v > order[i - 1]), `layout order ${order.join(',')}`)
  // One request feeds the alert and, when it opens, the card. (React.StrictMode
  // in the harness runs the mount effect twice, so a dev load shows two.)
  const afterLoad = calendarRequests
  assert.ok(afterLoad >= 1 && afterLoad <= 2, `calendar requests on load: ${afterLoad}`)

  // CASE 2: click lands on the Academic page's Coming up in Canvas card, without re-requesting.
  await link.click()
  await page.waitForURL(/section=academic/)
  const card = page.locator('.academic-overview-canvas-calendar')
  await card.waitFor()
  await card.getByRole('heading', { name: 'Coming up in Canvas' }).waitFor()
  await page.waitForFunction(() => {
    const el = document.querySelector('.academic-overview-canvas-calendar')
    if (!el) return false
    const box = el.getBoundingClientRect()
    return box.top < window.innerHeight && box.bottom > 0
  })
  assert.equal(calendarRequests, afterLoad, 'opening the card makes no new request')
  // The card shows the same cleaned label and time, with the raw text kept as a title.
  const row = card.locator('.canvas-calendar-item').first()
  assert.equal((await row.locator('.canvas-calendar-time').innerText()).trim(), '3:55 PM')
  assert.equal(await row.locator('small').innerText(), 'CSCE 222 504')
  assert.equal(await row.locator('small').getAttribute('title'), 'CSCE 222 504:')

  // CASE 3: due within 24 hours gets the stronger cue and the words, not just color.
  await openOverview({ status: 200, body: connected([item({ starts_at: '2026-10-27T20:00:00Z' })]) })
  await alert().waitFor()
  assert.equal(await alert().getAttribute('data-due-soon'), 'true')
  await alert().getByText('Due soon').waitFor()
  assert.match((await alert().innerText()).replace(/\s+/g, ' '), /\(in 5 hours\)/)
  assert.equal(await alert().locator('a').evaluate((el) => getComputedStyle(el).borderTopWidth), '2px')

  // CASE 4: a tie names the others; an exam is tagged; a long label is cleaned with the raw text kept.
  await openOverview({
    status: 200,
    body: connected([
      item({ uid: 'a', title: 'Post-Lab 8 Electronic Submission (ECEN-248-536-DUP1)', course_label: 'ECEN-248:531,532,533,534,535,536', likely_exam: true }),
      item({ uid: 'b', title: 'Lab 4 Submission (PHYS-217-508-DUP1)', course_label: 'PHYS-217:501,502' }),
      item({ uid: 'c', title: 'Another one' }),
    ]),
  })
  await alert().waitFor()
  const tie = (await alert().innerText()).replace(/\s+/g, ' ')
  assert.match(tie, /Next due: Post-Lab 8 Electronic Submission, ECEN-248, /)
  assert.doesNotMatch(tie, /DUP1|531/)
  assert.match(tie, /Likely exam/)
  assert.match(tie, /\+2 more due then/)
  assert.equal(await alert().locator('strong').getAttribute('title'), 'Post-Lab 8 Electronic Submission (ECEN-248-536-DUP1)')

  // CASE 5: stale or failed sync with cached events still shows, with a quiet note.
  await openOverview({ status: 200, body: connected([item()], { synced_at: '2026-10-27T05:00:00Z', last_error: 'Canvas returned an error (500). Try again shortly.' }) })
  await alert().waitFor()
  await alert().getByText('Synced 10 hrs ago').waitFor()

  // CASE 6: nothing to say, nothing rendered.
  for (const [label, next] of [
    ['not connected', { status: 200, body: { connected: false, canvas_host: 'canvas.tamu.edu', events: [] } }],
    ['connected but empty', { status: 200, body: connected([]) }],
    ['only an item that has already passed', { status: 200, body: connected([item({ starts_at: '2026-10-27T14:00:00Z' })]) }],
    ['request failed', { status: 502, body: { detail: 'Could not load your Canvas calendar.' } }],
  ]) {
    await openOverview(next)
    assert.equal(await page.locator('.next-due').count(), 0, label)
    assert.equal(await page.getByRole('heading', { name: 'Alex Morgan' }).count(), 1, `${label}: the overview itself still renders`)
  }
})
