// Pure view-model for the grade-calculator course cards: a square card whose
// ring is segmented by category weight and filled by score, in one colour per
// card keyed to the letter grade. No React, no DOM -- GradeCard.tsx renders
// what buildGradeCardModel returns, and gradeCardRing.test.mjs drives this
// straight from fixture list-payloads.
//
// Everything comes from one already-fetched list entry
// (SyllabusProfileSummary): current_letter_grade + components[] were added to
// GET /syllabus-grade-profiles in PR #83. No extra fetch.

const RING_CENTER = 50; // viewBox is 0 0 100 100
const RING_RADIUS = 42;
const START_ANGLE = -90; // 12 o'clock; SVG y-down so increasing angle = clockwise
// Wide enough that adjacent same-score segments read as separate now that the
// tracks are butt-capped (a round cap used to visually fill a ~3deg gap).
const DEFAULT_GAP_DEG = 6;
// Category weights within +/- this of 100 are treated as a clean 100 -- neither
// a shortfall segment nor an over-100 note.
const WEIGHT_SUM_TOLERANCE = 1;

const LETTER_TO_COLOR_KEY = { A: 'a', B: 'b', C: 'c', D: 'd', F: 'f' };

function clamp(n, lo, hi) {
  return Math.max(lo, Math.min(hi, n));
}

function trim(n) {
  // keep SVG path data short and stable across platforms
  return Number(n.toFixed(3));
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

function polar(cx, cy, r, angleDeg) {
  const a = (angleDeg * Math.PI) / 180;
  return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
}

/**
 * A stroked arc (not a wedge) from startAngle to endAngle, degrees, drawn
 * clockwise for a positive sweep. 0deg = 3 o'clock.
 */
export function arcPath(cx, cy, r, startAngle, endAngle) {
  const start = polar(cx, cy, r, startAngle);
  const end = polar(cx, cy, r, endAngle);
  const sweep = endAngle - startAngle;
  const largeArc = Math.abs(sweep) > 180 ? 1 : 0;
  const clockwiseFlag = sweep >= 0 ? 1 : 0;
  return `M ${trim(start.x)} ${trim(start.y)} A ${trim(r)} ${trim(r)} 0 ${largeArc} ${clockwiseFlag} ${trim(end.x)} ${trim(end.y)}`;
}

/**
 * A full-circle stroke path (two 180deg arcs) -- SVG cannot draw a 360deg arc
 * in one `A` command. Used for the categoryless card's single ring and for a
 * 100%-filled arc.
 */
export function circlePath(cx, cy, r) {
  return `${arcPath(cx, cy, r, -90, 90)} ${arcPath(cx, cy, r, 90, 270)}`;
}

function fillArc(fraction, startAngle, radius) {
  if (fraction <= 0) return null;
  if (fraction >= 0.999) return circlePath(RING_CENTER, RING_CENTER, radius);
  return arcPath(RING_CENTER, RING_CENTER, radius, startAngle, startAngle + fraction * 360);
}

/**
 * Map a letter grade to the card's single colour key. Keys on the first
 * character so "A-" / "B+" still resolve. Anything outside A-F (or a null
 * letter) returns null -> the card renders neutral, percentage only.
 */
export function gradeColorKey(letter) {
  if (letter == null) return null;
  const head = String(letter).trim().toUpperCase().charAt(0);
  return LETTER_TO_COLOR_KEY[head] ?? null;
}

function courseLabelOf(profile) {
  return profile.course_code || 'Untitled course';
}

function aria(text) {
  return text.replace(/\s+/g, ' ').trim();
}

// Shared centre text: a letter grade (with the percentage below it) when the
// scale placed the score, the bare percentage when it did not, and a dash when
// there is no score at all -- never "0%".
function centreText({ hasGrades, usableLetter, pct }) {
  if (!hasGrades) return { centerPrimary: '—', centerSecondary: null };
  if (usableLetter != null) {
    return { centerPrimary: usableLetter, centerSecondary: pct != null ? `${pct}%` : null };
  }
  return { centerPrimary: pct != null ? `${pct}%` : '—', centerSecondary: null };
}

function buildAriaLabel({ courseLabel, term, letter, pct, segments, categoryless, shortfallPercent, overagePercent }) {
  const parts = [`${courseLabel}${term ? `, ${term}` : ''}.`];

  if (letter != null && pct != null) parts.push(`Current grade ${letter}, ${pct}%.`);
  else if (pct != null) parts.push(`Current grade ${pct}%.`);
  else parts.push('No grade entered yet.');

  if (categoryless) {
    parts.push('Graded by individual assessments, not weighted categories.');
    return aria(parts.join(' '));
  }

  if (segments.length === 0) {
    parts.push('No breakdown available yet.');
    return aria(parts.join(' '));
  }

  for (const s of segments) {
    if (s.isShortfall) continue;
    parts.push(
      s.graded
        ? `${s.name}: weight ${s.weightPercent}%, score ${s.score}%.`
        : `${s.name}: weight ${s.weightPercent}%, not yet graded.`,
    );
  }
  if (shortfallPercent != null) {
    parts.push(
      `${shortfallPercent}% of the course weight is not accounted for by any component (the syllabus breakdown may be incomplete).`,
    );
  }
  if (overagePercent != null) {
    parts.push(`Component weights add up to ${round2(100 + overagePercent)}%, more than 100%.`);
  }
  return aria(parts.join(' '));
}

/**
 * @param {object} profile  one SyllabusProfileSummary from the list call
 * @param {object} [opts]    { gapDeg, radius, startAngle } geometry overrides
 * @returns {object} a discriminated view-model:
 *   { kind: 'setup', courseLabel, term, ariaLabel }
 *   { kind: 'categoryless', courseLabel, term, letter, colorKey, percentText,
 *     centerPrimary, centerSecondary, trackPath, fillPath|null, ariaLabel }
 *   { kind: 'ring', courseLabel, term, letter, colorKey, percentText,
 *     centerPrimary, centerSecondary, hasGrades, segments[], totalSegmentWeight,
 *     weightSumOff, weightShortfallPercent|null, weightOveragePercent|null, ariaLabel }
 *
 * A ring segment: { name, weightPercent, score|null, status|null, graded,
 *   isShortfall, fillFraction, startAngle, endAngle, midAngle, trackPath, fillPath|null }
 *   - graded=false, isShortfall=false -> ungraded component, track only
 *   - graded=true, fillFraction=0     -> a real scored zero (track only, counted)
 *   - isShortfall=true                -> course weight not accounted for by any
 *     component; a distinct hatched track, never fillable, not hoverable
 *
 * Every component with a numeric weight_percent is a segment -- weighted
 * categories and the individual assessments of a decomposed category alike.
 * Segment weights that fall short of 100 get a trailing shortfall segment so
 * the ring still closes; weights that exceed 100 are scaled to fit the circle
 * (proportions preserved) and noted in the aria-label. Same arc formula for
 * both: sweep = weight / max(100, sum) * 360.
 */
export function buildGradeCardModel(profile, opts = {}) {
  const gapDeg = opts.gapDeg ?? DEFAULT_GAP_DEG;
  const radius = opts.radius ?? RING_RADIUS;
  const startAngle = opts.startAngle ?? START_ANGLE;

  const courseLabel = courseLabelOf(profile);
  const term = profile.term || null;

  if (!profile.calculator_ready) {
    return {
      kind: 'setup',
      courseLabel,
      term,
      ariaLabel: aria(`${courseLabel}${term ? `, ${term}` : ''}. Grading model not set up yet. Open to finish setup.`),
    };
  }

  const allComponents = Array.isArray(profile.components) ? profile.components : [];

  // Every component carrying a real weight becomes a ring segment: weighted
  // categories AND the individual assessments of a decomposed category, which
  // the syllabus calculator returns with source_type 'assessment'.
  const segmentComponents = allComponents.filter((c) => c && typeof c.weight_percent === 'number');
  // The categoryless (single full-circle arc) branch is for points-based
  // syllabi. It keys on the absence of any *category-typed* component, NOT on
  // segmentComponents.length: a points course puts a numeric weight_percent on
  // every assessment, so a length check would send it down the segmented-ring
  // path -- and its weights can legitimately sum to under 100 (the calculator's
  // _build_points_components drops assessments whose possible_points is
  // unknown), painting a bogus "not accounted for" shortfall. Do not
  // "simplify" this to a segment-count test.
  const categoryTypedComponents = segmentComponents.filter((c) => c.source_type === 'category');

  const letterRaw = profile.current_letter_grade ?? null;
  const colorKey = gradeColorKey(letterRaw);
  const usableLetter = colorKey != null ? letterRaw : null;
  const pct = typeof profile.current_grade === 'number' ? profile.current_grade : null;

  // Points-based syllabus: components are all assessments, no weighted
  // categories. One full-circle arc filled to the overall percentage, same
  // grade-colour keying, letter + percentage in the centre. No segments.
  if (categoryTypedComponents.length === 0 && allComponents.length > 0) {
    const hasGrades = pct != null;
    const { centerPrimary, centerSecondary } = centreText({ hasGrades, usableLetter, pct });
    return {
      kind: 'categoryless',
      courseLabel,
      term,
      letter: usableLetter,
      colorKey,
      percentText: pct != null ? `${pct}%` : null,
      centerPrimary,
      centerSecondary,
      trackPath: circlePath(RING_CENTER, RING_CENTER, radius),
      fillPath: pct != null ? fillArc(clamp(pct / 100, 0, 1), startAngle, radius) : null,
      ariaLabel: buildAriaLabel({ courseLabel, term, letter: usableLetter, pct, segments: [], categoryless: true }),
    };
  }

  const rawTotal = round2(segmentComponents.reduce((sum, c) => sum + c.weight_percent, 0));
  const shortfall =
    segmentComponents.length > 0 && rawTotal < 100 - WEIGHT_SUM_TOLERANCE ? round2(100 - rawTotal) : 0;
  const overage =
    segmentComponents.length > 0 && rawTotal > 100 + WEIGHT_SUM_TOLERANCE ? round2(rawTotal - 100) : 0;
  // Arcs always sum to exactly 360: shortfall tops the total back up to 100;
  // an over-100 total becomes its own basis so proportions still fit the circle.
  const basis = Math.max(100, rawTotal);

  const entries = segmentComponents.map((c) => ({ component: c, weightPercent: c.weight_percent }));
  if (shortfall > 0) entries.push({ isShortfall: true, weightPercent: shortfall });

  let cursor = startAngle;
  const segments = entries.map((entry) => {
    const sweep = (entry.weightPercent / basis) * 360;
    // A segment narrower than the inter-segment gap keeps its full arc,
    // unpadded -- thin slivers render as-is, never merged or shrunk to
    // nothing. Wider segments give up gapDeg/2 at each end for the gap.
    const pad = sweep <= gapDeg ? 0 : gapDeg / 2;
    const segStart = cursor + pad;
    const segEnd = cursor + sweep - pad;
    cursor += sweep;

    const base = {
      startAngle: segStart,
      endAngle: segEnd,
      midAngle: (segStart + segEnd) / 2,
      trackPath: arcPath(RING_CENTER, RING_CENTER, radius, segStart, segEnd),
    };

    if (entry.isShortfall) {
      return {
        ...base,
        name: 'Unassigned weight',
        weightPercent: entry.weightPercent,
        score: null,
        status: null,
        graded: false,
        isShortfall: true,
        fillFraction: 0,
        fillPath: null, // a shortfall can never be filled -- it is missing weight, not missing work
      };
    }

    const c = entry.component;
    const graded = c.status != null && typeof c.effective_score === 'number';
    const fillFraction = graded ? clamp(c.effective_score / 100, 0, 1) : 0;
    const fillEnd = segStart + (segEnd - segStart) * fillFraction;
    return {
      ...base,
      name: c.name,
      weightPercent: c.weight_percent,
      score: graded ? c.effective_score : null,
      status: c.status ?? null,
      graded,
      isShortfall: false,
      fillFraction,
      fillPath: graded && fillFraction > 0 ? arcPath(RING_CENTER, RING_CENTER, radius, segStart, fillEnd) : null,
    };
  });

  const hasGrades = segments.some((s) => s.graded) || pct != null;
  const { centerPrimary, centerSecondary } = centreText({ hasGrades, usableLetter, pct });

  return {
    kind: 'ring',
    courseLabel,
    term,
    letter: usableLetter,
    colorKey,
    percentText: pct != null ? `${pct}%` : null,
    centerPrimary,
    centerSecondary,
    hasGrades,
    segments,
    totalSegmentWeight: rawTotal,
    weightSumOff: shortfall > 0 || overage > 0,
    weightShortfallPercent: shortfall > 0 ? shortfall : null,
    weightOveragePercent: overage > 0 ? overage : null,
    ariaLabel: buildAriaLabel({
      courseLabel,
      term,
      letter: usableLetter,
      pct,
      segments,
      categoryless: false,
      shortfallPercent: shortfall > 0 ? shortfall : null,
      overagePercent: overage > 0 ? overage : null,
    }),
  };
}

/**
 * The center text while a segment is hovered (desktop, pointer: fine only).
 * Returns { primary, secondary } — the category's score over its name, or a
 * dash for an ungraded / shortfall segment. Callers fall back to
 * model.centerPrimary/Secondary when nothing is hovered.
 */
export function hoveredCenter(segment) {
  if (!segment) return null;
  return {
    primary: segment.graded ? `${segment.score}%` : '—',
    secondary: segment.name,
  };
}
