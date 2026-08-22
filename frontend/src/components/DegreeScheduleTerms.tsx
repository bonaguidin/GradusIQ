import type { TermPlan } from '../api/degreeSchedule';
import { formatCredits, termPresentation } from '../lib/degreeSchedulePresentation';

export function DegreeScheduleTerms({ terms, ariaLabel }: { terms: TermPlan[]; ariaLabel: string }) {
  const presented = termPresentation(terms);
  if (presented.length === 0) return <p className="empty-state">No courses currently need scheduling.</p>;
  return (
    <div className="degree-schedule-terms" aria-label={ariaLabel}>
      {presented.map((term) => (
        <section className="degree-schedule-term" key={term.term_key}>
          <div className="degree-schedule-term-header">
            <h4>{term.displayName}</h4>
            <span>{term.totalLabel}</span>
          </div>
          <ul className="degree-schedule-courses">
            {term.courses.map((course) => (
              <li key={`${term.term_key}-${course.course_code}`}>
                <div className="degree-schedule-course-row">
                  <strong>{course.course_code}</strong>
                  <span>{formatCredits(course.credit_hours)}</span>
                </div>
                {course.limitations.length > 0 && (
                  <ul className="degree-schedule-limitations" aria-label={`${course.course_code} scheduling limitations`}>
                    {course.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
