import assert from 'node:assert/strict'
import test from 'node:test'

import {
  INITIAL_CAREER_OPTIMIZATION_STATE,
  careerChangeSummary,
  careerChangeHeading,
  careerOptimizationCopy,
  compareCareerSchedules,
  completedCareerOptimizationState,
  courseTermMoves,
  graduationTimingImpact,
} from '../src/lib/careerSchedulePresentation.ts'

function schedule(entries) {
  const terms = new Map()
  for (const [term_key, requirement_group_id, course_code] of entries) {
    const courses = terms.get(term_key) ?? []
    courses.push({ course_code, requirement_group_id, credit_hours: 3, limitations: [] })
    terms.set(term_key, courses)
  }
  return {
    student_id: 'sid', program_id: 'pid', status: 'SCHEDULED', failure: null, unscheduled: [],
    terms: [...terms].map(([term_key, courses]) => ({ term_key, courses, total_credit_hours: courses.length * 3 })),
  }
}

function ranking(group = 'g1') {
  return {
    requirement_group_id: group,
    ranked_candidates: [{ candidate_id: `winner-${group}`, rank: 1, ranking_reason: `Reason for ${group}.`, skill_alignment_explanation: `Skills for ${group}.` }],
  }
}

function response(status) {
  const academic = schedule([['2026-Fall', 'g1', 'CS 1000']])
  return {
    feature: 'CAREER_OPTIMIZED_SCHEDULE', status, selection_basis: status === 'OPTIMIZED' || status === 'PARTIAL' ? 'CAREER_RANKED' : 'ACADEMIC_DEFAULT',
    target_role: 'Software Engineering Intern', fingerprint: null, generated_at: 'now', cache_status: 'MISS',
    academic_schedule: academic, optimized_schedule: academic, requirement_rankings: [], ranking_failures: [], ranking_prompt_version: '1', resolved_model: 'model', summary: null,
  }
}

test('identical schedules have no changes', () => {
  const academic = schedule([['2026-Fall', 'g1', 'CS 1000']])
  const result = compareCareerSchedules(academic, academic, [ranking()])
  assert.deepEqual(result.changes, [])
  assert.match(careerChangeSummary(result), /already matches/)
})

test('single replacement maps the validated winning explanation', () => {
  const result = compareCareerSchedules(
    schedule([['2026-Fall', 'g1', 'CS 1000']]),
    schedule([['2026-Fall', 'g1', 'CS 2000']]),
    [ranking()],
  )
  assert.equal(result.changedChoiceCount, 1)
  assert.deepEqual(result.changes[0].removedCourseCodes, ['CS 1000'])
  assert.deepEqual(result.changes[0].addedCourseCodes, ['CS 2000'])
  assert.deepEqual(result.changes[0].unchangedCourseCodes, [])
  assert.equal(careerChangeHeading(result.changes[0]), 'CS 1000 → CS 2000')
  assert.equal(result.changes[0].candidateId, 'winner-g1')
  assert.equal(result.changes[0].rankingReason, 'Reason for g1.')
  assert.equal(result.changes[0].skillAlignmentExplanation, 'Skills for g1.')
})

test('multi-course candidate change stays bundled as one requirement change', () => {
  const result = compareCareerSchedules(
    schedule([['2026-Fall', 'lab', 'PHYS 1105'], ['2026-Fall', 'lab', 'PHYS 1303']]),
    schedule([['2026-Fall', 'lab', 'BIOL 1101'], ['2026-Fall', 'lab', 'BIOL 1301']]),
    [ranking('lab')],
  )
  assert.equal(result.changedChoiceCount, 1)
  assert.deepEqual(result.changes[0].removedCourseCodes, ['PHYS 1105', 'PHYS 1303'])
  assert.deepEqual(result.changes[0].addedCourseCodes, ['BIOL 1101', 'BIOL 1301'])
})

test('same course in another term is a term movement, not a replacement', () => {
  const result = compareCareerSchedules(
    schedule([['2026-Fall', 'g1', 'CS 1000']]),
    schedule([['2027-Spring', 'g1', 'CS 1000']]),
    [ranking()],
  )
  assert.deepEqual(result.changes[0].addedCourseCodes, [])
  assert.deepEqual(result.changes[0].removedCourseCodes, [])
  assert.deepEqual(result.changes[0].movedCourseCodes, ['CS 1000'])
  assert.deepEqual(courseTermMoves(result.changes[0]), [{ courseCode: 'CS 1000', fromTermKey: '2026-Fall', toTermKey: '2027-Spring' }])
  assert.equal(careerChangeHeading(result.changes[0]), 'CS 1000 rescheduled')
})

test('unchanged courses remain visible inside an atomic multi-course path', () => {
  const result = compareCareerSchedules(
    schedule([['2026-Fall', 'lab', 'BIOL 1101'], ['2027-Spring', 'lab', 'BIOL 1102']]),
    schedule([['2026-Fall', 'lab', 'CHEM 1117'], ['2027-Spring', 'lab', 'BIOL 1102']]),
    [ranking('lab')],
  )
  assert.deepEqual(result.changes[0].removedCourseCodes, ['BIOL 1101'])
  assert.deepEqual(result.changes[0].addedCourseCodes, ['CHEM 1117'])
  assert.deepEqual(result.changes[0].unchangedCourseCodes, ['BIOL 1102'])
})

test('graduation timing compares the final supported schedule terms', () => {
  const academic = schedule([['2026-Fall', 'g1', 'CS 1000'], ['2027-Spring', 'g2', 'CS 2000']])
  assert.equal(graduationTimingImpact(academic, academic), 'Graduation timing did not change.')
  assert.equal(
    graduationTimingImpact(academic, schedule([['2026-Fall', 'g1', 'CS 1000'], ['2027-Fall', 'g2', 'CS 2000']])),
    'The final planned term changed from Spring 2027 to Fall 2027.',
  )
})

test('multiple changes retain stable first-appearance ordering', () => {
  const result = compareCareerSchedules(
    schedule([['2026-Fall', 'z-group', 'CS 1000'], ['2026-Fall', 'a-group', 'CS 2000']]),
    schedule([['2026-Fall', 'z-group', 'CS 3000'], ['2026-Fall', 'a-group', 'CS 4000']]),
    [ranking('a-group'), ranking('z-group')],
  )
  assert.deepEqual(result.changes.map((change) => change.requirementGroupId), ['z-group', 'a-group'])
  assert.equal(careerChangeSummary(result), '2 degree choices changed for career alignment.')
})

test('missing ranking provenance never invents an explanation', () => {
  const result = compareCareerSchedules(
    schedule([['2026-Fall', 'g1', 'CS 1000']]),
    schedule([['2026-Fall', 'g1', 'CS 2000']]),
    [],
  )
  assert.equal(result.changes[0].careerRanked, false)
  assert.equal(result.changes[0].rankingReason, null)
  assert.equal(result.changes[0].skillAlignmentExplanation, null)
})

test('partial changes are career-labelled only for successfully ranked groups', () => {
  const result = compareCareerSchedules(
    schedule([['2026-Fall', 'ranked', 'CS 1000'], ['2026-Fall', 'fallback', 'CS 2000']]),
    schedule([['2026-Fall', 'ranked', 'CS 3000'], ['2026-Fall', 'fallback', 'CS 4000']]),
    [ranking('ranked')],
  )
  assert.deepEqual(result.changes.map((change) => change.careerRanked), [true, false])
  assert.match(careerOptimizationCopy('PARTIAL', null).message, /academic schedule/)
})

test('fallback and skipped copy preserve academic authority and backend skipped reason', () => {
  assert.match(careerOptimizationCopy('FALLBACK', null).message, /unchanged/)
  assert.equal(careerOptimizationCopy('SKIPPED', 'Choose a confirmed role.').message, 'Choose a confirmed role.')
})

test('state begins idle and completed preview selection follows response semantics', () => {
  assert.deepEqual(INITIAL_CAREER_OPTIMIZATION_STATE, { phase: 'idle' })
  assert.equal(completedCareerOptimizationState(response('OPTIMIZED')).view, 'optimized')
  assert.equal(completedCareerOptimizationState(response('PARTIAL')).view, 'optimized')
  assert.equal(completedCareerOptimizationState(response('FALLBACK')).view, 'academic')
  assert.equal(completedCareerOptimizationState(response('SKIPPED')).view, 'academic')
})
