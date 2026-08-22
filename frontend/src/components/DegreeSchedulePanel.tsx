import { Fragment, useCallback, useEffect } from 'react';
import { fetchDegreeSchedule, isSkippedDegreeSchedule, type DegreeScheduleResponse } from '../api/degreeSchedule';
import { useAuth } from '../auth/useAuth';
import { useAnalysisRun } from '../hooks/useAnalysisRun';
import {
  DEFERRED_REASON_DESCRIPTION,
  DEFERRED_REASON_LABEL,
  degreeScheduleContentState,
} from '../lib/degreeSchedulePresentation';
import { CareerOptimizationPanel } from './CareerOptimizationPanel';
import { DegreeScheduleTerms } from './DegreeScheduleTerms';

export function DegreeSchedulePanel({
  targetRole,
  onResult,
}: {
  targetRole?: string;
  onResult?: (result: DegreeScheduleResponse) => void;
}) {
  const { session } = useAuth();
  const accessToken = session?.access_token ?? '';
  const load = useCallback(() => fetchDegreeSchedule(accessToken), [accessToken]);
  const { state, trigger } = useAnalysisRun(load);

  useEffect(() => { trigger(); }, [trigger]);

  useEffect(() => {
    if (state.phase === 'done') onResult?.(state.result);
  }, [onResult, state]);

  const skipped = state.phase === 'done' && isSkippedDegreeSchedule(state.result) ? state.result : null;
  const schedule = state.phase === 'done' && !isSkippedDegreeSchedule(state.result) ? state.result : null;
  const contentState = state.phase === 'done' ? degreeScheduleContentState(state.result) : null;
  const infeasible = contentState === 'infeasible';
  const deferred = schedule?.status === 'SCHEDULED' ? schedule.unscheduled : [];

  return (
    <Fragment>
      <section className="card degree-schedule-panel" aria-labelledby="degree-schedule-title">
      <div className="editable-section-header">
        <div>
          <h3 id="degree-schedule-title" className="editable-section-title">Degree Schedule</h3>
          <p className="degree-schedule-subtitle">Your prerequisite-aware academic schedule for requirements with a fixed course path.</p>
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={trigger}
          disabled={state.phase === 'loading'}
          aria-busy={state.phase === 'loading'}
        >
          {state.phase === 'loading' ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {state.phase === 'idle' && <p className="analysis-empty">Preparing your degree schedule…</p>}

      {state.phase === 'loading' && (
        <div className="analysis-loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <p>Retrieving your degree schedule…</p>
        </div>
      )}

      {state.phase === 'transport-error' && (
        <div className="analysis-failed">
          <p>{state.message}</p>
        </div>
      )}

      {skipped && (
        <div className="analysis-skipped">
          <p>{skipped.summary}</p>
        </div>
      )}

      {infeasible && (
        <div className="analysis-failed degree-schedule-infeasible">
          <strong>Schedule needs attention</strong>
          <p>{schedule?.failure?.safe_message ?? 'The remaining courses could not be scheduled safely.'}</p>
        </div>
      )}

      {schedule?.status === 'SCHEDULED' && (
        <>
          <p className="degree-schedule-partial-note">
            Your academic schedule is shown below. Requirements that still need adviser input are listed separately.
          </p>

          {contentState === 'empty' ? (
            <p className="empty-state">No deterministic courses currently need scheduling.</p>
          ) : (
            <DegreeScheduleTerms terms={schedule.terms} ariaLabel="Academic degree schedule" />
          )}

          <section className="degree-schedule-deferred" aria-labelledby="degree-schedule-deferred-title">
            <h4 id="degree-schedule-deferred-title">Requirements not scheduled yet</h4>
            {deferred.length === 0 ? (
              <p className="empty-state">No requirements are waiting on course selection or adviser review.</p>
            ) : (
              <ul>
                {deferred.map((requirement) => (
                  <li key={requirement.requirement_group_id}>
                    <div>
                      <strong>{requirement.name}</strong>
                      <span className={`degree-schedule-reason degree-schedule-reason--${requirement.reason.toLowerCase().replace(/_/g, '-')}`}>
                        {DEFERRED_REASON_LABEL[requirement.reason]}
                      </span>
                    </div>
                    <p>{DEFERRED_REASON_DESCRIPTION[requirement.reason]}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
      </section>
      {schedule?.status === 'SCHEDULED' && (
        <CareerOptimizationPanel accessToken={accessToken} academicSchedule={schedule} confirmedTargetRole={targetRole} />
      )}
    </Fragment>
  );
}
