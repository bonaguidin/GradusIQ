import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { demoCompletedHours, demoGpaSummary } from '../src/lib/demoGpa.mjs'

// TAMU's scale as the demo fixtures carry it: no plus/minus, W excluded.
const TAMU = [
  { letter: 'A', points: 4, counts_toward_gpa: true },
  { letter: 'B', points: 3, counts_toward_gpa: true },
  { letter: 'C', points: 2, counts_toward_gpa: true },
  { letter: 'D', points: 1, counts_toward_gpa: true },
  { letter: 'F', points: 0, counts_toward_gpa: true },
  { letter: 'W', points: null, counts_toward_gpa: false },
]
const course = (letter_grade, credit_hours = 3, extra = {}) => ({ status: 'in_progress', credit_hours, letter_grade, credit_type: 'institutional', ...extra })
const jordan = (courses) => demoGpaSummary({ officialGpa: 3, classification: 'Freshman', courses, grades: TAMU })

test('with nothing entered, projected is exactly the official GPA', () => {
  const s = jordan([course(null), course(null)])
  assert.equal(s.projectedGpa, 3)
  assert.equal(s.inProgressWithCurrentGradeCount, 0)
})

test('entered grades blend into the official GPA over a class-year load', () => {
  assert.equal(jordan([course('A')]).projectedGpa, 3.17) // (3*15 + 4*3) / 18
  assert.equal(jordan([course('A'), course('B')]).projectedGpa, 3.14) // (45+12+9) / 21
  assert.equal(jordan([course('A'), course('B'), course('F', 4)]).projectedGpa, 2.64) // 66 / 25
  assert.equal(jordan([course('A'), course('B')]).inProgressWithCurrentGradeCount, 2)
})

test('grades that do not count, exam credit and other statuses stay out, as in gpa.py', () => {
  assert.equal(jordan([course('W')]).projectedGpa, 3)
  assert.equal(jordan([course('A', 3, { credit_type: 'exam' })]).projectedGpa, 3)
  assert.equal(jordan([course('A', 3, { status: 'dropped' })]).projectedGpa, 3)
  assert.equal(jordan([course('Z')]).projectedGpa, 3, 'an unmapped letter counts for nothing')
})

test('earned hours come from the class year, or recorded completed hours when there are more', () => {
  assert.equal(demoCompletedHours('Sophomore'), 45)
  assert.equal(demoCompletedHours(' senior '), 105)
  assert.equal(demoCompletedHours('Sophomore', 60), 60)
  assert.equal(demoCompletedHours(null), 0)
  assert.equal(jordan([]).earnedHours, 15)
})

test('a persona with no official GPA projects from this term alone, and shows none until a grade is in', () => {
  const s = (courses) => demoGpaSummary({ officialGpa: null, classification: 'Freshman', courses, grades: TAMU })
  assert.equal(s([course(null)]).projectedGpa, null)
  assert.equal(s([course('A'), course('C')]).projectedGpa, 3)
})

test('the demo dashboard feeds the GPA Calculator from the live course records', async () => {
  const page = await readFile(new URL('../src/pages/DashboardPage.tsx', import.meta.url), 'utf8')
  assert.match(page, /demoGpaSummary\(\{[\s\S]*?courses: demoCourseRecords,[\s\S]*?buildDemoGradingSchema\(/)
  assert.match(page, /\[baseDashboard, demoCourseRecords/)
})
