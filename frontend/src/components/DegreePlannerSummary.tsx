import type { DegreeScheduleResponse } from '../api/degreeSchedule.mjs';
import { nextPlannedTerm } from '../lib/degreeSchedulePresentation.mjs';

export function DegreePlannerSummary({
  institution,
  major,
  expectedGraduation,
  schedule,
}: {
  institution: string | null;
  major: string | null;
  expectedGraduation: string | null;
  schedule: DegreeScheduleResponse | null;
}) {
  const nextTerm = nextPlannedTerm(schedule);
  const scheduled = schedule && 'status' in schedule && schedule.status === 'SCHEDULED';

  return (
    <section className="card degree-planner-summary" aria-labelledby="degree-planner-title">
      <div>
        <span className="degree-planner-eyebrow">Degree Planner</span>
        <h2 id="degree-planner-title">{major || 'Your degree plan'}</h2>
        {institution && <p className="degree-planner-institution">{institution}</p>}
        <p className="degree-planner-status">
          {scheduled && expectedGraduation
            ? `On track through ${expectedGraduation}`
            : scheduled
              ? 'Your academic schedule is ready'
              : 'Preparing your academic plan…'}
        </p>
      </div>
      <dl className="degree-planner-summary-facts">
        <div>
          <dt>Next planned term</dt>
          <dd>{nextTerm ? `${nextTerm.displayName} · ${nextTerm.totalLabel}` : 'Not available yet'}</dd>
        </div>
      </dl>
    </section>
  );
}
