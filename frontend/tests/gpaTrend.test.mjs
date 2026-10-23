import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { MIN_TREND_TERMS, gpaDomain, gpaTrendLayout, shortTermLabel, sparklinePoints } from '../src/lib/gpaTrend.mjs'

const point = (key, termGpa, cumulative, projected = false) => ({
  term_id: key, term_key: key, label: key, term_gpa: termGpa, cumulative_gpa: cumulative, gpa_hours: 15, projected,
})

const HISTORY = [
  point('2024-Fall', 3.4, 3.4),
  point('2025-Spring', 3.1, 3.25),
  point('2025-Fall', 3.75, 3.42),
  point('2026-Fall', 3.85, 3.54, true),
]

test('short term labels', () => {
  assert.equal(shortTermLabel('2025-Fall'), "Fall '25")
  assert.equal(shortTermLabel('2026-summer'), "Summer '26")
  assert.equal(shortTermLabel('odd'), 'odd')
})

test('the GPA axis starts near the lowest value instead of at zero, and reaches 4.0', () => {
  assert.deepEqual(gpaDomain([3.1, 3.85]), { min: 3, max: 4 })
  assert.deepEqual(gpaDomain([2.45, 3.2]), { min: 2, max: 4 })
  assert.deepEqual(gpaDomain([4.0]), { min: 3.5, max: 4 })
  assert.deepEqual(gpaDomain([]), { min: 0, max: 4 })
})

test('layout marks where the projected (current-grades) segment starts', () => {
  const layout = gpaTrendLayout(HISTORY, { width: 640, height: 240 })
  assert.equal(layout.solidCount, 3)
  assert.deepEqual(layout.ticks.map((t) => t.value), [3, 3.5, 4])
  // Higher GPA sits higher on screen.
  assert.ok(layout.points[2].termY < layout.points[1].termY)
  assert.equal(layout.points[0].x, 40)
  assert.equal(layout.points[3].x, 616)
})

test('narrow plots thin the term labels but always label the latest term', () => {
  const many = Array.from({ length: 10 }, (_, i) => point(`${2020 + i}-Fall`, 3.5, 3.5))
  const wide = gpaTrendLayout(many, { width: 900, height: 240 })
  assert.ok(wide.points.every((p) => p.axisLabel))
  const narrow = gpaTrendLayout(many, { width: 340, height: 240 })
  const labelled = narrow.points.filter((p) => p.axisLabel)
  assert.ok(labelled.length < many.length)
  assert.equal(narrow.points.at(-1).axisLabel, "Fall '29")
})

test('the sparkline does not stretch a 3.50 to 3.51 change into a full-height swing', () => {
  const height = 28
  const pad = 3
  const line = sparklinePoints(
    [point('2025-Spring', 3.5, 3.5), point('2025-Fall', 3.51, 3.51), point('2026-Spring', 3.51, 3.51)],
    { width: 96, height, pad },
  )
  const ys = line.solid.split(' ').map((pair) => Number(pair.split(',')[1]))
  const swing = Math.abs(ys[0] - ys[1])
  // The drawable height is height - 2*pad = 22px across a 3.0-4.0 domain, so
  // a 0.01 move is ~0.22px; the old min-max scaling drew it as the full 22px.
  assert.ok(swing < 0.5, `swing was ${swing}px`)
  assert.equal(ys[1], ys[2])
})

test('the sparkline stays inside its box and keeps rising values rising', () => {
  const line = sparklinePoints([point('a', 2.4, 2.4), point('b', 3.0, 2.7), point('c', 3.9, 3.2)], { width: 96, height: 28, pad: 3 })
  const ys = line.solid.split(' ').map((pair) => Number(pair.split(',')[1]))
  assert.ok(ys.every((y) => y >= 3 && y <= 25))
  assert.ok(ys[0] > ys[1] && ys[1] > ys[2])
})

test('the sparkline splits off the projected tail', () => {
  const line = sparklinePoints(HISTORY, { width: 96, height: 28 })
  assert.equal(line.solid.split(' ').length, 3)
  assert.equal(line.projected.split(' ').length, 2)
  assert.ok(line.last)
  assert.equal(MIN_TREND_TERMS, 3)
})

test('GPA chart on the GPA Calculator, sparkline on Overview', { timeout: 45_000 }, async (t) => {
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-gpa-trend', import.meta.url)),
    logLevel: 'silent',
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const origin = `http://127.0.0.1:${String(address.port)}`
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()

  // Overview: the sparkline sits in the GPA tile and opens the GPA Calculator.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete&gpaHistory=1`)
  const spark = page.getByRole('button', { name: 'See GPA by term' })
  await spark.waitFor()
  await spark.click()
  await page.getByRole('heading', { name: 'GPA Calculator' }).waitFor()

  // GPA Calculator: one point per term, the latest projected from current grades.
  const chart = page.getByRole('region', { name: 'GPA by term' })
  await chart.waitFor()
  assert.equal(await chart.locator('.gpa-trend-point').count(), 5)
  assert.equal(await chart.locator('.gpa-trend-point--projected').count(), 1)
  await chart.getByText('Projected (current grades)').waitFor()

  // Hover shows the term's figures; clicking opens that term in the tabs below.
  const fall25 = chart.getByRole('button', { name: /^Fall 2025: term GPA 3\.75, cumulative 3\.42/ })
  await fall25.hover()
  await chart.getByRole('status').getByText('Fall 2025').waitFor()
  await fall25.click()
  assert.equal(new URL(page.url()).searchParams.get('term'), '2025-Fall')

  // Too little history: no chart, no sparkline, a one-line note instead.
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete&section=academic&academic=gpa-calculator`)
  await page.getByText(/Your GPA chart appears once you have 3 terms/).waitFor()
  assert.equal(await page.locator('.gpa-trend-point').count(), 0)
  await page.goto(`${origin}/authenticated-dashboard-preview.html?mode=complete`)
  await page.locator('.overview-stat').first().waitFor()
  assert.equal(await page.getByRole('button', { name: 'See GPA by term' }).count(), 0)
})

test('the chart is a labelled group, so its focusable points are exposed, and a focused point shows the focus ring', { timeout: 45_000 }, async (t) => {
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-gpa-trend', import.meta.url)),
    logLevel: 'silent',
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage()
  await page.goto(`http://127.0.0.1:${String(address.port)}/authenticated-dashboard-preview.html?mode=complete&gpaHistory=1&section=academic&academic=gpa-calculator`)

  const group = page.getByRole('group', { name: 'Term and cumulative GPA for 5 terms' })
  await group.waitFor()
  assert.equal(await page.locator('svg.gpa-trend-svg[role="img"]').count(), 0)
  // role="img" would make these presentational; as a group they stay buttons.
  assert.equal(await group.getByRole('button').count(), 5)

  // Keyboard focus draws a real outline, not just a thicker dot.
  await page.keyboard.press('Tab')
  await group.getByRole('button').first().focus({ timeout: 5000 })
  await page.keyboard.press('Shift+Tab')
  await page.keyboard.press('Tab')
  const outline = await page.evaluate(() => {
    const style = getComputedStyle(document.activeElement)
    return { style: style.outlineStyle, width: style.outlineWidth }
  })
  assert.notEqual(outline.style, 'none')
  assert.notEqual(outline.width, '0px')
})
