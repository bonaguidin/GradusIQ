import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { planningRoutes } from './fixtures/planningRoutes.mjs'
import {
  REPORT_LIMITS,
  REPORT_URL,
  buildReportFormData,
  fitWithin,
  normalizeReportResponse,
  screenshotFits,
  validateReport,
} from '../src/lib/reportIssue.mjs'

const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

// ── pure helpers ─────────────────────────────────────────────────────────────

test('validateReport asks for a real description and a reply address', () => {
  assert.deepEqual(validateReport({ description: 'The GPA card is blank after upload.', email: 'a@b.edu' }), {})
  assert.ok(validateReport({ description: 'broken', email: 'a@b.edu' }).description)
  assert.ok(validateReport({ description: 'x'.repeat(REPORT_LIMITS.maxDescription + 1), email: 'a@b.edu' }).description)
  assert.ok(validateReport({ description: 'The GPA card is blank.', email: 'nope' }).email)
  assert.ok(validateReport({ description: 'The GPA card is blank.', email: '' }).email)
})

test('screenshotFits enforces count, per-image and total caps under the backend limits', () => {
  // The backend allows 1.5 MB each and 3.5 MB total (feedback/report.py);
  // the form must stay under both so it never sends what the server refuses.
  assert.ok(REPORT_LIMITS.maxScreenshotBytes < 1_500_000)
  assert.ok(REPORT_LIMITS.maxTotalBytes < 3_500_000)
  assert.equal(screenshotFits([], 500_000), 'ok')
  assert.equal(screenshotFits([1, 2, 3], 10), 'count')
  assert.equal(screenshotFits([], REPORT_LIMITS.maxScreenshotBytes + 1), 'size')
  assert.equal(screenshotFits([1_300_000, 1_300_000], 1_000_000), 'total')
})

test('fitWithin scales the longest side down and keeps the aspect ratio', () => {
  assert.deepEqual(fitWithin(800, 600), { width: 800, height: 600 })
  assert.deepEqual(fitWithin(3200, 1800), { width: 1600, height: 900 })
  assert.deepEqual(fitWithin(1000, 4000), { width: 400, height: 1600 })
})

test('buildReportFormData sends trimmed fields, the honeypot, and each screenshot', () => {
  const form = buildReportFormData(
    { kind: 'feature', description: '  Add dark mode please  ', email: ' a@b.edu ', name: ' ', page: 'Career', userAgent: 'UA' },
    [{ blob: new Blob(['x'], { type: 'image/png' }), name: 'screenshot-1.png' }],
  )
  assert.equal(form.get('kind'), 'feature')
  assert.equal(form.get('description'), 'Add dark mode please')
  assert.equal(form.get('email'), 'a@b.edu')
  assert.equal(form.get('name'), null)
  assert.equal(form.get('page'), 'Career')
  assert.equal(form.get('user_agent'), 'UA')
  assert.equal(form.get('website'), '')
  assert.equal(form.getAll('screenshots').length, 1)
})

test('normalizeReportResponse keeps the backend message for the cases it explains', () => {
  assert.deepEqual(normalizeReportResponse(200, { status: 'sent' }), { ok: true })
  assert.equal(normalizeReportResponse(429, { detail: 'Try again later.' }).message, 'Try again later.')
  assert.equal(normalizeReportResponse(503, { detail: 'Email us instead.' }).message, 'Email us instead.')
  assert.match(normalizeReportResponse(0, null).message, /connection/)
  assert.match(normalizeReportResponse(413, null).message, /too large/)
  assert.match(normalizeReportResponse(500, { detail: 'Traceback...' }).message, /Something went wrong/)
})

test('both dashboards put the bug icon right before the tour "?"', async () => {
  for (const path of ['pages/AuthenticatedDashboard.tsx', 'pages/DashboardPage.tsx']) {
    const page = await read(path)
    const header = page.slice(page.indexOf('<header className="topbar">'), page.indexOf('</header>'))
    assert.match(header, /<ReportIssueButton[\s\S]*?\/>\s*<button\s+type="button"\s+className="topbar-help"/, path)
  }
})

// ── in the browser ───────────────────────────────────────────────────────────

const PNG_1PX = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64',
)

test('the report pop-up validates, attaches a screenshot and sends it with the session', { timeout: 45_000 }, async (t) => {
  const planning = planningRoutes({ terms: [] })
  const reports = []
  let nextStatus = 503
  const json = (response, status, body) => {
    response.statusCode = status
    response.setHeader('content-type', 'application/json')
    response.end(JSON.stringify(body))
  }
  const apiPlugin = {
    name: 'report-issue-api',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0]
        if (planning.handle(path, request.method, request, response)) return undefined
        if (path === '/api/v2/student/me/requirement-satisfaction') return json(response, 404, { detail: 'Not found.' })
        if (path?.startsWith('/api/v2/student/me/analysis-cache/')) return json(response, 404, { detail: 'Not found.' })
        if (path === REPORT_URL && request.method === 'POST') {
          const chunks = []
          request.on('data', (chunk) => chunks.push(chunk))
          request.on('end', () => {
            reports.push({
              authorization: request.headers.authorization,
              contentType: request.headers['content-type'],
              body: Buffer.concat(chunks).toString('latin1'),
            })
            if (nextStatus === 200) json(response, 200, { status: 'sent' })
            else json(response, nextStatus, { detail: "Reports aren't set up yet. Please email gradus@gradusiq.com instead." })
          })
          return undefined
        }
        next()
      })
    },
  }
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-report-issue', import.meta.url)),
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()
  await page.goto(`http://127.0.0.1:${address.port}/authenticated-dashboard-preview.html?mode=complete`)

  const trigger = page.getByRole('button', { name: 'Report a bug or suggest a feature' })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: 'Report a bug or suggest a feature' })
  await dialog.waitFor()
  // The open dialog must not push the two topbar icons apart.
  const bugBox = await trigger.boundingBox()
  const helpBox = await page.getByRole('button', { name: 'Replay the new-user tour' }).boundingBox()
  assert.ok(helpBox.x - (bugBox.x + bugBox.width) < 16, 'bug icon sits right beside the "?"')
  // Prefilled from the student profile.
  assert.equal(await dialog.getByLabel('Name optional').inputValue(), 'Alex Morgan')

  // Empty submit: field errors, nothing sent.
  await dialog.getByRole('button', { name: 'Send report' }).click()
  await dialog.getByText('Tell us a little more so we can act on it.').waitFor()
  await dialog.getByText('Enter an email we can reply to.').waitFor()
  assert.equal(reports.length, 0)

  await dialog.getByText('I have an idea').click()
  assert.equal(await dialog.getByRole('radio', { name: 'I have an idea' }).isChecked(), true)
  await dialog.getByLabel('What would you like to see?').fill('A dark mode for late-night planning.')
  await dialog.getByLabel('Email').fill('alex@example.edu')
  await dialog.locator('input[type="file"]').setInputFiles({ name: 'shot.png', mimeType: 'image/png', buffer: PNG_1PX })
  await dialog.getByRole('img', { name: 'Screenshot 1' }).waitFor()

  // A backend failure keeps the form and shows its message.
  await dialog.getByRole('button', { name: 'Send report' }).click()
  await dialog.getByRole('alert').getByText(/gradus@gradusiq\.com/).waitFor()
  assert.equal(reports.length, 1)

  nextStatus = 200
  await dialog.getByRole('button', { name: 'Send report' }).click()
  await page.getByRole('dialog', { name: 'Thanks, it’s on its way' }).waitFor()
  const sent = reports[1]
  assert.equal(sent.authorization, 'Bearer real-access-token')
  assert.match(sent.contentType, /^multipart\/form-data; boundary=/)
  assert.match(sent.body, /name="kind"\r\n\r\nfeature\r\n/)
  assert.match(sent.body, /name="description"\r\n\r\nA dark mode for late-night planning\.\r\n/)
  assert.match(sent.body, /name="email"\r\n\r\nalex@example\.edu\r\n/)
  assert.match(sent.body, /name="name"\r\n\r\nAlex Morgan\r\n/)
  assert.match(sent.body, /name="page"\r\n\r\nOverview \(\/authenticated-dashboard-preview\.html\)\r\n/)
  assert.match(sent.body, /name="website"\r\n\r\n\r\n/)
  assert.match(sent.body, /name="screenshots"; filename="screenshot-1\.png"\r\nContent-Type: image\/png/)

  // Done closes it and hands focus back to the bug icon.
  await page.getByRole('button', { name: 'Done' }).click()
  await page.getByRole('dialog').waitFor({ state: 'detached' })
  assert.equal(await trigger.evaluate((node) => node === document.activeElement), true)

  // Escape closes a fresh one too.
  await trigger.click()
  await dialog.waitFor()
  await page.keyboard.press('Escape')
  await page.getByRole('dialog').waitFor({ state: 'detached' })

  // Phone width: a bottom sheet with no sideways scroll.
  await page.setViewportSize({ width: 375, height: 740 })
  await trigger.click()
  await dialog.waitFor()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  assert.ok(overflow <= 0, `horizontal overflow ${overflow}px`)
  await page.locator('.report-dialog').evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)))
  const box = await page.locator('.report-dialog').boundingBox()
  assert.ok(box && Math.round(box.y + box.height) === 740, 'sheet sits on the bottom edge')
})
