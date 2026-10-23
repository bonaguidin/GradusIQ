// Geometry for the GPA-by-term chart (GpaTrendChart) and the Overview
// sparkline. Pure so the scale and label rules are testable without a browser;
// gpaTrend.test.mjs pins them.
//
// Points, not bars: a bar has to start at zero, and on a 0-4 axis a 3.1 term
// and a 3.75 term look nearly the same. Points let the axis start near the
// student's lowest GPA so the swings show.

// Below this many terms a trend line says nothing; the page shows the numbers.
export const MIN_TREND_TERMS = 3

const STEP = 0.5
const LABEL_SPACE = 72

/** "2025-Fall" -> "Fall '25". Falls back to the key itself. */
export function shortTermLabel(termKey) {
  const match = /^(\d{4})-(.+)$/.exec(String(termKey ?? ''))
  if (!match) return String(termKey ?? '')
  const season = match[2].charAt(0).toUpperCase() + match[2].slice(1).toLowerCase()
  return `${season} '${match[1].slice(2)}`
}

/** Y domain in 0.5 steps: from just under the lowest value to at least 4.0. */
export function gpaDomain(values) {
  const finite = values.filter((v) => typeof v === 'number' && Number.isFinite(v))
  if (finite.length === 0) return { min: 0, max: 4 }
  const low = Math.min(...finite)
  const high = Math.max(...finite)
  const min = Math.max(0, Math.floor((low - 0.1) / STEP) * STEP)
  const max = Math.max(4, Math.ceil(high / STEP) * STEP)
  return { min, max }
}

/**
 * Layout for the full chart. Returns every coordinate the SVG needs so the
 * component only draws. Projected points (current grades) are drawn dashed and
 * hollow; `solidCount` is how many leading points are on a final record.
 */
export function gpaTrendLayout(points, { width, height, padLeft = 40, padRight = 24, padTop = 20, padBottom = 32 } = {}) {
  const values = points.flatMap((p) => [p.term_gpa, p.cumulative_gpa])
  const domain = gpaDomain(values)
  const plotW = width - padLeft - padRight
  const plotH = height - padTop - padBottom
  const x = (i) => (points.length <= 1 ? padLeft + plotW / 2 : padLeft + (plotW * i) / (points.length - 1))
  const y = (v) => padTop + plotH - ((v - domain.min) / (domain.max - domain.min)) * plotH

  const ticks = []
  for (let v = domain.min; v <= domain.max + 1e-9; v += STEP) ticks.push({ value: Math.round(v * 10) / 10, y: y(v) })

  // A term label needs about LABEL_SPACE px; on a narrow plot label every
  // Nth term, counting back from the latest so it is always labelled.
  const fit = Math.max(2, Math.floor(plotW / LABEL_SPACE))
  const labelEvery = Math.max(1, Math.ceil(points.length / fit))
  const placed = points.map((p, i) => ({
    ...p,
    x: x(i),
    termY: y(p.term_gpa),
    cumulativeY: typeof p.cumulative_gpa === 'number' ? y(p.cumulative_gpa) : null,
    axisLabel: i === points.length - 1 || (points.length - 1 - i) % labelEvery === 0 ? shortTermLabel(p.term_key) : null,
  }))
  const firstProjected = placed.findIndex((p) => p.projected)
  const solidCount = firstProjected === -1 ? placed.length : firstProjected

  return { domain, ticks, points: placed, solidCount, baselineY: padTop + plotH, plotLeft: padLeft, plotRight: width - padRight }
}

/** Polyline "x,y x,y" string over a slice of placed points. */
export function polylinePoints(placed, key) {
  return placed
    .filter((p) => typeof p[key] === 'number')
    .map((p) => `${p.x.toFixed(1)},${p[key].toFixed(1)}`)
    .join(' ')
}

/** Cumulative GPA path for the Overview sparkline. */
export function sparklinePoints(points, { width, height, pad = 3 }) {
  const series = points.filter((p) => typeof p.cumulative_gpa === 'number')
  if (series.length < 2) return { solid: '', projected: '', last: null }
  // The same GPA-scale domain as the full chart, not the series' own min and
  // max: stretching to the data would draw 3.50 -> 3.51 as a full-height swing.
  const { min: lo, max: hi } = gpaDomain(series.map((p) => p.cumulative_gpa))
  const span = hi - lo
  const coords = series.map((p, i) => ({
    x: pad + ((width - 2 * pad) * i) / (series.length - 1),
    y: pad + (height - 2 * pad) * (1 - (p.cumulative_gpa - lo) / span),
    projected: p.projected,
  }))
  const toStr = (list) => list.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')
  const firstProjected = coords.findIndex((c) => c.projected)
  const solidEnd = firstProjected === -1 ? coords.length : firstProjected
  return {
    solid: toStr(coords.slice(0, solidEnd)),
    projected: firstProjected > 0 ? toStr(coords.slice(firstProjected - 1)) : '',
    last: coords[solidEnd - 1] ?? null,
  }
}
