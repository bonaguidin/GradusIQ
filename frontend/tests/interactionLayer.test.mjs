import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import test from 'node:test'

const SRC = new URL('../src/', import.meta.url)
const LAYER = new URL('interaction.css', SRC)

const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')

// Split a selector list on top-level commas only -- :is(a, b) is one selector.
function splitSelectors(prelude) {
  const out = []
  let depth = 0
  let current = ''
  for (const ch of prelude) {
    if (ch === '(') depth += 1
    if (ch === ')') depth -= 1
    if (ch === ',' && depth === 0) { out.push(current.trim()); current = '' } else current += ch
  }
  out.push(current.trim())
  return out
}

const selectorsOf = (css) => [...css.matchAll(/([^{}]+)\{/g)].flatMap(([, prelude]) => splitSelectors(prelude))

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
  assert.doesNotMatch(css, /\b(white|black)\b(?!-)/) // not white-space
})

test('buttons give under the pointer, and the movement is removed for reduced motion', async () => {
  const css = stripComments(await readFile(LAYER, 'utf8'))
  assert.match(css, /\.btn:active:not\(:disabled\)/)
  const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))
  assert.match(reduced, /transform:\s*none/)
  assert.match(reduced, /::after\s*\{\s*display:\s*none/)
})

test('the liquid fill always excludes the pencil-icon edit button, which draws its icon on ::before', async () => {
  const css = stripComments(await readFile(LAYER, 'utf8'))
  const ghostBefore = selectorsOf(css).filter((s) => s.includes('.btn-ghost') && s.includes('::before'))
  assert.ok(ghostBefore.length > 0)
  for (const selector of ghostBefore) {
    assert.match(selector, /\.btn-ghost:not\(:where\([^)]*\.cp-detail[^]*:only-child\)\)/, selector)
  }
})

test('outline buttons fill solid with their own colour, and invert text only for hover-capable pointers', async () => {
  const css = stripComments(await readFile(LAYER, 'utf8'))
  assert.match(css, /\.btn-ghost:not\(:where\([^{]*\{\s*--press-fill:\s*rgb\(var\(--accent-rgb\)\);/)
  assert.match(css, /\.btn-danger-ghost\s*\{\s*--press-fill:\s*rgb\(var\(--error-rgb\)\);/)
  // A tap on touch leaves :hover applied with no fill underneath, so inverted
  // text anywhere outside the hover query would be light on a light ground.
  const hoverQuery = css.indexOf('@media (hover: hover) and (pointer: fine)')
  const reducedQuery = css.indexOf('@media (prefers-reduced-motion: reduce)')
  for (const inverted of [/color:\s*rgb\(var\(--on-accent-rgb\)\)/g, /color:\s*var\(--neutral-on-accent\)/g]) {
    for (const m of css.matchAll(inverted)) {
      assert.ok(m.index > hoverQuery && m.index < reducedQuery, `inverted text at ${m.index} must sit inside the hover query`)
    }
  }
})

test('the layer never wins a layout decision: structural rules carry no specificity', async () => {
  // A component that pins its button (position: absolute in a card corner)
  // must keep its layout. Equal specificity would hand the win to whichever
  // stylesheet loads last, which is this one in production.
  const css = stripComments(await readFile(LAYER, 'utf8'))
  const LAYOUT = /(^|;|\s)(position|overflow|isolation|display|float|margin[a-z-]*|width|height|inset|top|right|bottom|left)\s*:/
  let checked = 0
  for (const [, prelude, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!LAYOUT.test(body)) continue
    for (const selector of splitSelectors(prelude)) {
      if (/::(before|after)$/.test(selector)) continue // the layer's own boxes
      checked += 1
      assert.match(selector, /^:where\(/, `${selector} sets layout, so it must sit inside :where()`)
    }
  }
  assert.ok(checked > 0)
})

test('Skip keeps dark text over its neutral fill, whatever order the stylesheets load in', async () => {
  const css = stripComments(await readFile(LAYER, 'utf8'))
  const hover = css.slice(css.indexOf('@media (hover: hover) and (pointer: fine)'), css.indexOf('@media (prefers-reduced-motion: reduce)'))
  const skip = hover.match(/button\.tour-skip:hover:not\(:disabled\)\s*\{([^}]*)\}/)
  assert.ok(skip, 'Skip states its own hover text colour inside the hover query')
  assert.match(skip[1], /color:\s*var\(--ink\)/)
})

test('every button size is driven by the one --btn-scale token', async () => {
  const css = stripComments(await readFile(new URL('index.css', SRC), 'utf8'))
  assert.match(css, /--btn-scale:\s*1\.15;/)
  for (const selector of ['.btn', '.btn-sm', '.rv-commit-button']) {
    const escaped = selector.replace('.', '\\.')
    const rule = css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`))
    assert.ok(rule, `${selector} rule exists`)
    assert.match(rule[1], /font-size:\s*calc\([^;]*var\(--btn-scale\)\)/, `${selector} font-size scales`)
    assert.match(rule[1], /padding:\s*calc\([^;]*var\(--btn-scale\)\)/, `${selector} padding scales`)
  }
})

test('btn-secondary has a rule, so it never falls back to the native button look', async () => {
  const css = await readFile(new URL('index.css', SRC), 'utf8')
  assert.match(css, /\.btn-secondary\s*\{[^}]*background:\s*var\(--surface\)/)
})
