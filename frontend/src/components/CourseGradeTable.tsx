import type { Course, Enrollment } from '../types/student';
import { formatFixed } from '../lib/format.mjs';

interface CourseGradeTableProps {
  courses: Course[];
  enrollments: Enrollment[];
}

function gradeClass(grade: string | null): string {
  if (!grade) return '';
  const upper = grade.toUpperCase();
  if (upper.startsWith('A')) return 'grade-a';
  if (upper.startsWith('B')) return 'grade-b';
  if (upper.startsWith('C')) return 'grade-c';
  return 'grade-df';
}

export function CourseGradeTable({ courses, enrollments }: CourseGradeTableProps) {
  const enrollmentByCourseId = new Map<number, Enrollment>();
  for (const enroll of enrollments) {
    enrollmentByCourseId.set(enroll.course_id, enroll);
  }

  if (!courses || courses.length === 0) {
    return <p className="empty-state">No course data available.</p>;
  }

  return (
    <div className="table-wrapper">
      <table className="grade-table">
        <thead>
          <tr>
            <th scope="col">Course Code</th>
            <th scope="col">Course Name</th>
            <th scope="col">Grade</th>
            <th scope="col">Score</th>
          </tr>
        </thead>
        <tbody>
          {courses.map((course) => {
            const enroll = enrollmentByCourseId.get(course.id);
            const grade = enroll?.grades?.current_grade ?? null;
            const score = enroll?.grades?.current_score ?? null;
            return (
              <tr key={course.id}>
                <td>
                  <code className="course-code">{course.course_code}</code>
                </td>
                <td>{course.name}</td>
                <td>
                  {grade ? (
                    <span className={`grade-pill ${gradeClass(grade)}`}>{grade}</span>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </td>
                <td>
                  {score !== null ? (
                    <span>{formatFixed(score, 1)}%</span>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
