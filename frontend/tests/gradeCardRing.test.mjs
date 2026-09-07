import test from 'node:test'
import assert from 'node:assert/strict'

import { arcPath, circlePath, gradeColorKey, buildGradeCardModel, hoveredCenter } from '../src/lib/gradeCardRing.mjs'

// --- fixtures: shaped exactly like GET /syllabus-grade-profiles entries -------------

const category = (name, weight_percent, effective_score = null, status = null) => ({
  name,
  source_type: 'category',
  weight_percent,
  effective_score,
  status,
})

const readyProfile = (over = {}) => ({
  id: 'p1',
  course_code: 'PHYS 207',
  term: 'Fall 2026',
  review_state: 'confirmed',
  calculator_ready: true,
  current_grade: null,
  current_letter_grade: null,
  components: [],
  ...over,
})

// --- geometry ----------------------------------------------------------------------

test('segment sweep is proportional to weight_percent, in component order, from 12 o\'clock', () => {
  const model = buildGradeCardModel(
    readyProfile({
      components: [category('Midterm', 30), category('Final', 50), category('Quizzes', 20)],
    }),
    { gapDeg: 0 },
  )
  assert.equal(model.kind, 'ring')
  const spans = model.segments.map((s) => s.endAngle - s.startAngle)
  assert.deepEqual(spans.map((d) => Math.round(d)), [108, 180, 72]) // 30/50/20 % of 360
  // first segment starts at the top; segments are contiguous with gapDeg: 0
  assert.equal(model.segments[0].startAngle, -90)
  assert.equal(Math.round(model.segments[0].endAngle), Math.round(model.segments[1].startAngle))
  assert.equal(Math.round(model.segments[2].endAngle), -90 + 360)
})

test('gapDeg opens a gap between segments without moving their centres', () => {
  const withGap = buildGradeCardModel(
    readyProfile({ components: [category('A', 50), category('B', 50)] }),
    { gapDeg: 4 },
  )
  const [a, b] = withGap.segments
  assert.ok(a.startAngle > -90, 'first segment padded in from the start')
  assert.ok(b.startAngle - a.endAngle > 3.9, 'a visible gap sits between the two arcs')
  assert.equal(a.midAngle, -90 + 90) // centre of a 0-180 sweep is unmoved by symmetric padding
})

test('a thin sliver is not merged or padded away', () => {
  const model = buildGradeCardModel(
    readyProfile({ components: [category('Tiny', 1), category('Rest', 99)] }),
    { gapDeg: 8 },
  )
  const sliver = model.segments[0]
  assert.equal(model.segments.length, 2)
  assert.ok(sliver.endAngle > sliver.startAngle, 'sliver keeps a positive, non-inverted arc')
  assert.ok(sliver.endAngle - sliver.startAngle <= 3.6) // ~1% of 360, minus its own capped pad
})

test('every weighted component segments (category or assessment); only null-weight ones are skipped', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 88,
      current_letter_grade: 'B',
      components: [
        category('Homework', 40, 90, 'completed'),
        { name: 'Final Project', source_type: 'assessment', weight_percent: 60, effective_score: 85, status: 'completed' },
        { name: 'No weight', source_type: 'category', weight_percent: null, effective_score: null, status: null },
      ],
    }),
  )
  const realSegments = model.segments.filter((s) => !s.isShortfall)
  assert.deepEqual(
    realSegments.map((s) => s.name),
    ['Homework', 'Final Project'],
  )
  assert.equal(model.totalSegmentWeight, 100)
  assert.equal(model.weightSumOff, false)
})

test('a decomposed category (Homework category + three assessment components) renders 4 segments, no shortfall', () => {
  const model = buildGradeCardModel(
    readyProfile({
      course_code: 'CSCE 222',
      current_grade: 94,
      current_letter_grade: 'A',
      components: [
        category('Homework assignment', 35, 100, 'completed'),
        { name: 'midterm I', source_type: 'assessment', weight_percent: 15, effective_score: 80, status: 'completed' },
        { name: 'midterm II', source_type: 'assessment', weight_percent: 15, effective_score: 80, status: 'completed' },
        { name: 'final exam', source_type: 'assessment', weight_percent: 35, effective_score: 100, status: 'completed' },
      ],
    }),
  )
  assert.equal(model.kind, 'ring')
  assert.deepEqual(
    model.segments.map((s) => s.name),
    ['Homework assignment', 'midterm I', 'midterm II', 'final exam'],
  )
  assert.equal(model.totalSegmentWeight, 100)
  assert.equal(model.weightSumOff, false)
  assert.equal(model.weightShortfallPercent, null)
  assert.ok(model.segments.every((s) => !s.isShortfall))
  for (const name of ['Homework assignment', 'midterm I', 'midterm II', 'final exam']) {
    assert.match(model.ariaLabel, new RegExp(`${name}: weight \\d+%, score \\d+%\\.`))
  }
})

test('arcPath emits a stroke arc (M then A) with the large-arc flag past 180 degrees', () => {
  const small = arcPath(50, 50, 42, -90, 0)
  assert.match(small, /^M [\d.-]+ [\d.-]+ A 42 42 0 0 1 [\d.-]+ [\d.-]+$/)
  const big = arcPath(50, 50, 42, -90, 180)
  assert.match(big, / A 42 42 0 1 1 /)
})

// --- ungraded vs a real scored zero ----------------------------------------------

test('an ungraded category renders track-only: graded false, no fill path', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 90,
      current_letter_grade: 'A',
      components: [category('Graded', 50, 90, 'completed'), category('Ungraded', 50, null, null)],
    }),
  )
  const ungraded = model.segments.find((s) => s.name === 'Ungraded')
  assert.equal(ungraded.graded, false)
  assert.equal(ungraded.score, null)
  assert.equal(ungraded.status, null)
  assert.equal(ungraded.fillPath, null)
  assert.equal(ungraded.fillFraction, 0)
})

test('a scored zero is distinct from ungraded: graded true, fillFraction 0, still no fill path', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 45,
      current_letter_grade: 'F',
      components: [category('Bombed', 50, 0, 'completed'), category('Ungraded', 50, null, null)],
    }),
  )
  const zero = model.segments.find((s) => s.name === 'Bombed')
  assert.equal(zero.graded, true)
  assert.equal(zero.score, 0)
  assert.equal(zero.status, 'completed')
  assert.equal(zero.fillFraction, 0)
  assert.equal(zero.fillPath, null) // 0% fill draws nothing, but it is a graded segment
  // and the two are genuinely different in the model
  const ungraded = model.segments.find((s) => s.name === 'Ungraded')
  assert.notEqual(zero.graded, ungraded.graded)
})

test('a graded segment fills score/100 of its own arc, not of the whole ring', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 80,
      current_letter_grade: 'B',
      components: [category('Half', 40, 50, 'completed')],
    }),
    { gapDeg: 0 },
  )
  const seg = model.segments[0]
  const arcSpan = seg.endAngle - seg.startAngle
  assert.equal(seg.fillFraction, 0.5)
  assert.ok(seg.fillPath, 'a >0% fill draws a path')
  // fill end angle is halfway along the segment's 144deg sweep
  const fillEndFromPath = Number(seg.fillPath.split(' A ')[0].split(' ').slice(-2, -1))
  assert.ok(Number.isFinite(fillEndFromPath))
  assert.equal(Math.round(arcSpan), 144)
})

// --- colour key -----------------------------------------------------------------

test('gradeColorKey maps A-F (and their +/- variants) and nothing else', () => {
  assert.equal(gradeColorKey('A'), 'a')
  assert.equal(gradeColorKey('A-'), 'a')
  assert.equal(gradeColorKey('B+'), 'b')
  assert.equal(gradeColorKey('C'), 'c')
  assert.equal(gradeColorKey('D'), 'd')
  assert.equal(gradeColorKey('F'), 'f')
  assert.equal(gradeColorKey('P'), null)
  assert.equal(gradeColorKey('W'), null)
  assert.equal(gradeColorKey(null), null)
  assert.equal(gradeColorKey(undefined), null)
})

// --- states -------------------------------------------------------------------

test('not calculator_ready -> setup model, no ring', () => {
  const model = buildGradeCardModel(readyProfile({ calculator_ready: false, components: [] }))
  assert.equal(model.kind, 'setup')
  assert.equal(model.segments, undefined)
  assert.match(model.ariaLabel, /not set up yet/i)
  assert.match(model.ariaLabel, /^PHYS 207, Fall 2026\./)
})

test('ready but no components / no grades -> empty ring, centre is a dash not 0%', () => {
  const model = buildGradeCardModel(readyProfile({ components: [] }))
  assert.equal(model.kind, 'ring')
  assert.deepEqual(model.segments, [])
  assert.equal(model.hasGrades, false)
  assert.equal(model.centerPrimary, '—')
  assert.equal(model.centerSecondary, null)
})

test('ready with category tracks but no scores entered -> tracks only, dash centre', () => {
  const model = buildGradeCardModel(
    readyProfile({ components: [category('Midterm', 50), category('Final', 50)] }),
  )
  assert.equal(model.segments.length, 2)
  assert.ok(model.segments.every((s) => s.graded === false && s.fillPath === null))
  assert.equal(model.hasGrades, false)
  assert.equal(model.centerPrimary, '—')
})

test('current_letter_grade null but a percentage exists -> percentage alone, neutral, no colour key', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 63.5,
      current_letter_grade: null, // score fell in a gap in the scale
      components: [category('Midterm', 100, 63.5, 'completed')],
    }),
  )
  assert.equal(model.kind, 'ring')
  assert.equal(model.letter, null)
  assert.equal(model.colorKey, null)
  assert.equal(model.centerPrimary, '63.5%')
  assert.equal(model.centerSecondary, null)
})

test('an unrecognised letter is treated as no letter (neutral, percentage only)', () => {
  const model = buildGradeCardModel(
    readyProfile({ current_grade: 72, current_letter_grade: 'S', components: [category('M', 100, 72, 'completed')] }),
  )
  assert.equal(model.letter, null)
  assert.equal(model.colorKey, null)
  assert.equal(model.centerPrimary, '72%')
})

test('letter + percentage present -> letter is the centre, percentage below, colour key set', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 91,
      current_letter_grade: 'A',
      components: [category('M', 30, 90, 'completed'), category('F', 40, 92, 'completed'), category('P', 30, 91, 'completed')],
    }),
  )
  assert.equal(model.colorKey, 'a')
  assert.equal(model.centerPrimary, 'A')
  assert.equal(model.centerSecondary, '91%')
})

test('points-based syllabus (no weighted categories) -> one full-circle arc filled to the overall percentage', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 84,
      current_letter_grade: 'B',
      components: [
        { name: 'Exam 1', source_type: 'assessment', weight_percent: 25, effective_score: 80, status: 'completed' },
        { name: 'Exam 2', source_type: 'assessment', weight_percent: 25, effective_score: 88, status: 'completed' },
      ],
    }),
  )
  assert.equal(model.kind, 'categoryless')
  assert.equal(model.segments, undefined)
  // one full-circle track, and a fill that exists (84% -> a partial arc)
  assert.equal(model.trackPath, circlePath(50, 50, 42))
  assert.ok(model.fillPath && model.fillPath !== model.trackPath)
  assert.equal(model.colorKey, 'b')
  assert.equal(model.centerPrimary, 'B')
  assert.equal(model.centerSecondary, '84%')
})

test('categoryless at 100% draws a full-circle fill; with no score, no fill and a dash centre', () => {
  const full = buildGradeCardModel(
    readyProfile({
      current_grade: 100,
      current_letter_grade: 'A',
      components: [{ name: 'Exam', source_type: 'assessment', weight_percent: 100, effective_score: 100, status: 'completed' }],
    }),
  )
  assert.equal(full.fillPath, circlePath(50, 50, 42))

  const none = buildGradeCardModel(
    readyProfile({
      current_grade: null,
      current_letter_grade: null,
      components: [{ name: 'Exam', source_type: 'assessment', weight_percent: 100, effective_score: null, status: null }],
    }),
  )
  assert.equal(none.kind, 'categoryless')
  assert.equal(none.fillPath, null)
  assert.equal(none.centerPrimary, '—')
})

test('categoryless aria-label says the course is graded by individual assessments', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 84,
      current_letter_grade: 'B',
      components: [{ name: 'Exam 1', source_type: 'assessment', weight_percent: 100, effective_score: 84, status: 'completed' }],
    }),
  )
  assert.match(model.ariaLabel, /PHYS 207, Fall 2026\. Current grade B, 84%\./)
  assert.match(model.ariaLabel, /Graded by individual assessments, not weighted categories\./)
})

// --- weight-sum guard: shortfall + overage --------------------------------------

test('category weights summing to ~100 do not trip weightSumOff and add no shortfall segment', () => {
  const model = buildGradeCardModel(
    readyProfile({ components: [category('A', 33.34), category('B', 33.33), category('C', 33.33)] }),
  )
  assert.equal(model.totalSegmentWeight, 100)
  assert.equal(model.weightSumOff, false)
  assert.equal(model.weightShortfallPercent, null)
  assert.equal(model.weightOveragePercent, null)
  assert.ok(model.segments.every((s) => !s.isShortfall))
})

test('a sub-100 weight sum renders a distinct, unfillable shortfall segment that closes the ring', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 62,
      current_letter_grade: 'D',
      components: [category('A', 30, 80, 'completed'), category('B', 40, 55, 'completed')],
    }),
    { gapDeg: 0 },
  )
  assert.equal(model.totalSegmentWeight, 70)
  assert.equal(model.weightSumOff, true)
  assert.equal(model.weightShortfallPercent, 30)
  assert.equal(model.weightOveragePercent, null)

  const shortfall = model.segments.filter((s) => s.isShortfall)
  assert.equal(shortfall.length, 1)
  assert.equal(shortfall[0].weightPercent, 30)
  assert.equal(shortfall[0].graded, false)
  assert.equal(shortfall[0].fillPath, null)
  assert.equal(shortfall[0].status, null)
  // it is last, and the arcs still close the full circle
  assert.equal(model.segments.at(-1).isShortfall, true)
  const sweep = model.segments.reduce((t, s) => t + (s.endAngle - s.startAngle), 0)
  assert.equal(Math.round(sweep), 360)
  // 30% of the circle == 108deg for the shortfall arc
  assert.equal(Math.round(shortfall[0].endAngle - shortfall[0].startAngle), 108)
})

test('the shortfall segment is not the same as an ungraded category segment', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 40,
      current_letter_grade: 'F',
      components: [category('Graded', 30, 80, 'completed'), category('Ungraded', 40, null, null)],
    }),
  )
  const ungraded = model.segments.find((s) => s.name === 'Ungraded')
  const shortfall = model.segments.find((s) => s.isShortfall)
  assert.equal(ungraded.isShortfall, false)
  assert.equal(ungraded.graded, false)
  assert.equal(shortfall.isShortfall, true)
  assert.equal(shortfall.name, 'Unassigned weight')
  assert.equal(shortfall.weightPercent, 30) // 100 - (30 + 40)
})

test('sub-100 aria-label states that course weight is unaccounted for, distinct from "not yet graded"', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 62,
      current_letter_grade: 'D',
      components: [category('A', 30, 80, 'completed'), category('B', 40, null, null)],
    }),
  )
  assert.match(model.ariaLabel, /A: weight 30%, score 80%\./)
  assert.match(model.ariaLabel, /B: weight 40%, not yet graded\./)
  assert.match(model.ariaLabel, /30% of the course weight is not accounted for by any component/)
  assert.doesNotMatch(model.ariaLabel, /Unassigned weight: weight/) // the shortfall is not listed as a component line
})

test('an over-100 weight sum scales the segments to fit the circle and says so in the aria-label', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 88,
      current_letter_grade: 'B',
      components: [category('A', 70, 90, 'completed'), category('B', 60, 85, 'completed')],
    }),
    { gapDeg: 0 },
  )
  assert.equal(model.totalSegmentWeight, 130)
  assert.equal(model.weightSumOff, true)
  assert.equal(model.weightOveragePercent, 30)
  assert.equal(model.weightShortfallPercent, null)
  // no shortfall segment; the two real segments fill exactly the circle,
  // in their original 70:60 proportion
  assert.ok(model.segments.every((s) => !s.isShortfall))
  const [a, b] = model.segments
  const spanA = a.endAngle - a.startAngle
  const spanB = b.endAngle - b.startAngle
  assert.equal(Math.round(spanA + spanB), 360)
  assert.ok(Math.abs(spanA / spanB - 70 / 60) < 0.001)
  assert.match(model.ariaLabel, /Component weights add up to 130%, more than 100%\./)
})

// --- aria-label carries the whole breakdown ---------------------------------------

test('aria-label carries course, term, letter, percentage, and every category with weight + score', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 85,
      current_letter_grade: 'B',
      components: [
        category('Midterm', 30, 90, 'completed'),
        category('Final', 40, null, null),
        category('Project', 30, 0, 'completed'),
      ],
    }),
  )
  const label = model.ariaLabel
  assert.match(label, /PHYS 207, Fall 2026\./)
  assert.match(label, /Current grade B, 85%\./)
  assert.match(label, /Midterm: weight 30%, score 90%\./)
  assert.match(label, /Final: weight 40%, not yet graded\./)
  assert.match(label, /Project: weight 30%, score 0%\./)
})

test('aria-label without a letter still states the percentage', () => {
  const model = buildGradeCardModel(
    readyProfile({ current_grade: 63.5, current_letter_grade: null, components: [category('M', 100, 63.5, 'completed')] }),
  )
  assert.match(model.ariaLabel, /Current grade 63\.5%\./)
  assert.doesNotMatch(model.ariaLabel, /grade null/)
})

test('aria-label for an unscored ready course says so', () => {
  const model = buildGradeCardModel(readyProfile({ components: [category('M', 100)] }))
  assert.match(model.ariaLabel, /No grade entered yet\./)
  assert.match(model.ariaLabel, /M: weight 100%, not yet graded\./)
})

test('aria-label for the categoryless case explains the assessment-based grading', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 84,
      current_letter_grade: 'B',
      components: [{ name: 'Exam 1', source_type: 'assessment', weight_percent: 100, effective_score: 84, status: 'completed' }],
    }),
  )
  assert.match(model.ariaLabel, /individual assessments, not weighted categories/)
})

// --- hovered centre helper --------------------------------------------------------

test('hoveredCenter swaps the centre to a category score over its name; ungraded shows a dash', () => {
  const model = buildGradeCardModel(
    readyProfile({
      current_grade: 90,
      current_letter_grade: 'A',
      components: [category('Midterm', 50, 88, 'completed'), category('Final', 50, null, null)],
    }),
  )
  assert.deepEqual(hoveredCenter(model.segments[0]), { primary: '88%', secondary: 'Midterm' })
  assert.deepEqual(hoveredCenter(model.segments[1]), { primary: '—', secondary: 'Final' })
  assert.equal(hoveredCenter(null), null)
})
