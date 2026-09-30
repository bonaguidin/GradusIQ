import assert from 'node:assert/strict'
import test from 'node:test'

import { pressGeometry } from '../src/lib/pressGeometry.mjs'

const RECT = { left: 100, top: 50, width: 120, height: 40 }
const CORNERS = [[0, 0], [RECT.width, 0], [0, RECT.height], [RECT.width, RECT.height]]

test('keyboard activation has no position, so the effect starts centred', () => {
  const g = pressGeometry(RECT, null)
  assert.equal(g.x, 60)
  assert.equal(g.y, 20)
  assert.equal(g.reach, Math.hypot(60, 20))
})

test('entering at a corner has to travel the full diagonal', () => {
  const g = pressGeometry(RECT, { x: 100, y: 50 })
  assert.equal(g.x, 0)
  assert.equal(g.y, 0)
  assert.equal(g.reach, Math.hypot(120, 40))
})

test('leave coordinates just outside the control are pulled back onto its edge', () => {
  const g = pressGeometry(RECT, { x: 95, y: 200 })
  assert.equal(g.x, 0)
  assert.equal(g.y, 40)
})

test('reach covers every corner from any origin, so the fill never leaves a gap', () => {
  for (const [px, py] of [[0, 0], [37, 12], [120, 40], [60, 20], [119, 1]]) {
    const g = pressGeometry(RECT, { x: RECT.left + px, y: RECT.top + py })
    for (const [cx, cy] of CORNERS) {
      assert.ok(Math.hypot(cx - g.x, cy - g.y) <= g.reach + 1e-9, `corner ${cx},${cy} from ${px},${py}`)
    }
  }
})

test('a collapsed control produces zeros, not NaN', () => {
  assert.deepEqual(pressGeometry({ left: 0, top: 0, width: 0, height: 0 }, null), { x: 0, y: 0, reach: 0 })
})
