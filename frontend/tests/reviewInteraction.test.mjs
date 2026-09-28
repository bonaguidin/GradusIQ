import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { chromium } from 'playwright'
import { createServer } from 'vite'

test('resume review interaction and responsive behavior', { timeout: 30_000 }, async (t) => {
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-review-interaction', import.meta.url)),
    logLevel: 'silent',
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())

  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')

  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
  await page.goto(`http://127.0.0.1:${String(address.port)}/review-preview.html`)
  await page.locator('.rv-card').first().waitFor()
  await page.evaluate(() => {
    document.documentElement.style.setProperty('--accent-rgb', '80 0 0')
    document.documentElement.style.setProperty('--accent-text-rgb', '68 0 0')
  })

  const counters = page.locator('.rv-counter-value')
  assert.deepEqual(await counters.allTextContents(), ['17', '9', '0'])
  assert.equal(await page.locator('.rv-progress').getAttribute('aria-valuenow'), '65')

  // Click-to-edit, Enter-to-save, persisted edited provenance, and save flash.
  const experience = page.locator('.rv-card', { hasText: 'NVIDIA' })
  const employer = experience.locator('.rv-field-button').first()
  await employer.click()
  const editor = experience.locator('.rv-input').first()
  assert.equal(await editor.evaluate((node) => document.activeElement === node), true)
  await editor.fill('Nvidia Corporation')
  await editor.press('Enter')
  await page.waitForTimeout(180)
  assert.equal(await experience.locator('.rv-glyph-edited').count(), 1)
  assert.equal(
    await experience.locator('.rv-glyph-edited').evaluate((node) => getComputedStyle(node).color),
    'rgb(68, 0, 0)',
  )
  assert.deepEqual(await counters.allTextContents(), ['16', '9', '1'])
  assert.equal(await experience.locator('.rv-field-flash').count(), 1)

  // Escape restores the pre-edit value and performs no PATCH/provenance change.
  const role = experience.locator('.rv-field-button').nth(1)
  const roleBefore = (await role.textContent())?.trim()
  await role.click()
  await experience.locator('.rv-input').first().fill('Wrong value')
  await experience.locator('.rv-input').first().press('Escape')
  assert.equal((await role.textContent())?.trim(), roleBefore)
  assert.deepEqual(await counters.allTextContents(), ['16', '9', '1'])

  // A gap pill is keyboard reachable and promotes directly into a focused editor.
  const firstGap = page.locator('[data-gap-pill]').first()
  const restingGapBackground = await firstGap.evaluate((node) => getComputedStyle(node).backgroundColor)
  await firstGap.hover()
  assert.notEqual(
    await firstGap.evaluate((node) => getComputedStyle(node).backgroundColor),
    restingGapBackground,
  )
  await firstGap.focus()
  assert.equal(await firstGap.evaluate((node) => document.activeElement === node), true)
  assert.equal(await firstGap.evaluate((node) => getComputedStyle(node).outlineStyle), 'solid')
  await firstGap.press('Enter')
  const promoted = page.locator('.rv-input').first()
  assert.equal(await promoted.evaluate((node) => document.activeElement === node), true)
  await promoted.press('Escape')

  // Jump finds and focuses the next remaining gap.
  await page.locator('.rv-jump').click()
  await page.waitForTimeout(380)
  assert.equal(
    await page.evaluate(() => document.activeElement?.hasAttribute('data-gap-pill')),
    true,
  )

  // Commit state and its disabled/success transition use the same live counters.
  assert.match(await page.locator('.rv-commit-status').innerText(), /9 fields stay empty/)
  assert.equal(
    await page.locator('.rv-commit-status').evaluate((node) => getComputedStyle(node).color),
    'rgb(68, 0, 0)',
  )
  await page.locator('.rv-commit-button').click()
  assert.equal(await page.locator('.rv-commit-button').isDisabled(), true)

  // Mobile layout stacks field values and makes the commit action full width.
  await page.setViewportSize({ width: 390, height: 844 })
  const mobileLayout = await page.locator('.rv-commit-inner').evaluate((node) => ({
    direction: getComputedStyle(node).flexDirection,
    buttonWidth: getComputedStyle(node.querySelector('.rv-commit-button')).width,
  }))
  assert.equal(mobileLayout.direction, 'column')
  assert.notEqual(mobileLayout.buttonWidth, 'auto')
})
