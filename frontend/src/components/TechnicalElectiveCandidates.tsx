import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '../auth/useAuth';
import {
  fetchTechnicalElectiveCandidates,
  isSkippedTechnicalElectives,
  type TechnicalElectiveCandidate,
  type TechnicalElectiveEligibility,
} from '../api/technicalElectives';
import { useAnalysisRun } from '../hooks/useAnalysisRun';

const LABEL: Record<TechnicalElectiveEligibility, string> = {
  READY: 'Ready',
  PREREQUISITES_PLANNED: 'Prerequisites planned',
  PREREQUISITES_MISSING: 'Prerequisites missing',
};

function creditLabel(course: TechnicalElectiveCandidate) {
  return course.credit_min === course.credit_max
    ? `${course.credit_min} credits`
    : `${course.credit_min}–${course.credit_max} credits`;
}

export function TechnicalElectiveCandidates({ requirementGroupId }: { requirementGroupId: string }) {
  const { session } = useAuth();
  const [expanded, setExpanded] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const load = useCallback(
    () => fetchTechnicalElectiveCandidates(session?.access_token ?? ''),
    [session?.access_token],
  );
  const { state, trigger } = useAnalysisRun(load);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    trigger();
  }, [trigger]);

  const result = state.phase === 'done' && !isSkippedTechnicalElectives(state.result)
    ? state.result
    : null;
  if (result && result.requirement_group_id !== requirementGroupId) return null;

  return (
    <div className="technical-elective-options">
      <button
        type="button"
        className="btn btn-ghost btn-sm technical-elective-options-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? 'Hide course options' : 'View course options'}
      </button>

      {expanded && (
        <div className="technical-elective-options-body">
          <p className="technical-elective-disclaimer">
            Provisional CS 3000+ options only. Adviser approval is required, and courses in your chosen track cannot count.
          </p>
          {state.phase === 'loading' && <p role="status">Loading course options…</p>}
          {state.phase === 'transport-error' && (
            <div className="analysis-failed technical-elective-local-error">
              <p>{state.message}</p>
              <button type="button" className="btn btn-ghost btn-sm" onClick={trigger}>Try again</button>
            </div>
          )}
          {state.phase === 'done' && isSkippedTechnicalElectives(state.result) && (
            <p>{state.result.summary}</p>
          )}
          {result && (
            <>
              <ul className="technical-elective-list">
                {(showAll ? result.candidates : result.candidates.slice(0, 6)).map((course) => (
                  <li key={course.course_code} className="technical-elective-course">
                    <div>
                      <strong>{course.course_code}</strong> · {course.title}
                      <span className="technical-elective-credits">{creditLabel(course)}</span>
                    </div>
                    <span className={`technical-elective-state technical-elective-state--${course.eligibility.toLowerCase()}`}>
                      {LABEL[course.eligibility]}
                    </span>
                    {course.planned_prerequisite_codes.length > 0 && (
                      <p>Planned prerequisites: {course.planned_prerequisite_codes.join(', ')}</p>
                    )}
                    {course.missing_prerequisite_options.length > 0 && (
                      <p>Missing: {course.missing_prerequisite_options.map((values) => values.join(' or ')).join('; ')}</p>
                    )}
                  </li>
                ))}
              </ul>
              {result.candidates.length === 0 && (
                <p>No courses could be verified automatically from the current catalog rules. An adviser can still help select an eligible Technical Elective.</p>
              )}
              {result.candidates.length > 6 && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowAll((value) => !value)}>
                  {showAll ? 'Show fewer' : `View all ${result.candidates.length} options`}
                </button>
              )}
              <p className="technical-elective-cross-department">
                Other departments may be approved as exceptions; ask your adviser about those options.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
