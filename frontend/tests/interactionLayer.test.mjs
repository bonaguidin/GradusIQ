import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import test from 'node:test'

const SRC = new URL('../src/', import.meta.url)
const LAYER = new URL('interaction.css', SRC)

const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')

test('every entry that loads index.css loads the interaction layer after it', async () => {
  const files = (await readdir(SRC)).filter((f) => f.endsWith('.tsx'))
  let entries = 0
  for (const file of files) {
    const text = await readFile(new URL(file, SRC), 'utf8')
    const base = text.indexOf("import './index.css'")
    if (base < 0) continue
    entries += 1
    assert.ok(text.indexOf("import './interaction.ts'") > base, `${file} must import ./interaction.ts after ./index.css`)
  }
  assert.ok(entries >= 7, `expected the app and its preview harnesses, found ${entries}`)
})

test('the timing set is defined once and nothing else in the layer uses a raw duration', async () => {
  const css = stripComments(await readFile(LAYER, 'utf8'))
  const root = css.match(/:root\s*\{[^}]*\}/)
  assert.ok(root, 'timing tokens live in a :root block')
  for (const token of ['--t-press', '--t-quick', '--t-move', '--t-settle', '--t-fill', '--t-data', '--ease-out', '--ease-spring']) {
    assert.match(root[0], new RegExp(`${token}:`))
  }
  assert.doesNotMatch(css.replace(root[0], ''), /\b\d*\.?\d+m?s\b/)
})

test('the layer has no colour literals, so institution theming still drives it', async () => {
  const css = stripComments(await readFile(LAYER, 'utf8'))
  assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b/i)
  assert.doesNotMatch(css, /\b(rgba?|hsla?)\(\s*\d/)
  assert.doesNotMatch(css, /\b(white|black)\b/)
})

test('buttons give under the pointer, and the movement is removed for reduced motion', async () => {
  const css = stripComments(await readFile(LAYER, 'utf8'))
  assert.match(css, /\.btn:active:not\(:disabled\)/)
  const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))
  assert.match(reduced, /transform:\s*none/)
  assert.match(reduced, /::after\s*\{\s*display:\s*none/)
})

test('the liquid fill never targets a bare ghost button, which may carry the pencil icon on ::before', async () => {
  const css = stripComments(await readFile(LAYER, 'utf8'))
  const selectors = [...css.matchAll(/([^{}]+)\{/g)].flatMap((m) => m[1].split(',')).map((s) => s.trim())
  const ghostBefore = selectors.filter((s) => s.includes('.btn-ghost') && s.includes('::before'))
  assert.ok(ghostBefore.length > 0)
  for (const selector of ghostBefore) {
    assert.match(selector, /\.analysis-panel > \.editable-section-header/)
  }
})

test('btn-secondary has a rule, so it never falls back to the native button look', async () => {
  const css = await readFile(new URL('index.css', SRC), 'utf8')
  assert.match(css, /\.btn-secondary\s*\{[^}]*background:\s*var\(--surface\)/)
})
