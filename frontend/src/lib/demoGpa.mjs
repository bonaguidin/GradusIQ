// The demo GPA Calculator's figures. Demo personas carry an official GPA but
// no completed coursework behind it, so Projected GPA had nothing to move.
// To respond the way a real student's would, the demo assumes a typical
// completed load for the persona's class year behind that official GPA, then
// folds in grades entered this term by the rules of
// GradusIQ_career/academics/gpa.py's 'projected' scope: in-progress courses
// whose grade maps to points and counts toward GPA, weighted by credit hours,
// exam credit excluded, rounded to two places. Demo only -- real accounts are
// computed server-side. demoGpa.test.mjs pins it.

export const ASSUMED_COMPLETED_HOURS = { freshman: 15, sophomore: 45, junior: 75, senior: 105 };

export function demoCompletedHours(classification, recordedCompletedHours = 0) {
  const assumed = ASSUMED_COMPLETED_HOURS[(classification ?? '').trim().toLowerCase()] ?? 0;
  return Math.max(assumed, recordedCompletedHours);
}

function countingPoints(letter, grades) {
  if (!letter) return null;
  const row = grades.find((grade) => grade.letter === letter);
  return row && row.counts_toward_gpa && typeof row.points === 'number' ? row.points : null;
}

export function demoGpaSummary({ officialGpa, classification, courses, grades }) {
  const recorded = courses
    .filter((course) => course.status === 'completed')
    .reduce((sum, course) => sum + Number(course.credit_hours), 0);
  const completedHours = demoCompletedHours(classification, recorded);

  let points = officialGpa === null ? 0 : officialGpa * completedHours;
  let hours = officialGpa === null ? 0 : completedHours;
  let graded = 0;
  for (const course of courses) {
    if (course.status !== 'in_progress' || course.credit_type === 'exam') continue;
    const value = countingPoints(course.letter_grade, grades);
    if (value === null) continue;
    points += value * Number(course.credit_hours);
    hours += Number(course.credit_hours);
    graded += 1;
  }

  return {
    // Nothing entered: exactly the official figure, with no float drift.
    projectedGpa: graded === 0 || hours === 0 ? officialGpa : Math.round((points / hours) * 100) / 100,
    earnedHours: completedHours,
    inProgressWithCurrentGradeCount: graded,
  };
}
