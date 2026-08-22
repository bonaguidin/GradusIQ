import { useCallback, useEffect, useRef } from 'react';
import { useAuth } from '../auth/useAuth';
import {
  fetchRequirementSatisfaction,
  isSkippedRequirementSatisfaction,
  type RequirementSatisfactionResponse,
} from '../api/requirementSatisfaction';
import { useAnalysisRun } from '../hooks/useAnalysisRun';
import { RequirementGroupNode } from './RequirementGroupNode';

// Sits directly under CourseDiscoveryPanel in the same Course Discovery
// sub-tab (see AuthenticatedDashboard.tsx) rather than a separate tab --
// requirement progress is read alongside course recommendations, not
// navigated to separately. Same useAnalysisRun/AnalysisPanel shell
// CourseDiscoveryPanel uses, so both panels behave identically on load,
// re-run, and error.
export function RequirementSatisfactionPanel({
  onResult,
}: {
  onResult?: (result: RequirementSatisfactionResponse) => void;
}) {
  const { session } = useAuth();
  const load = useCallback(
    () => fetchRequirementSatisfaction(session?.access_token ?? ''),
    [session?.access_token],
  );
  const { state, trigger } = useAnalysisRun(load);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    trigger();
  }, [trigger]);

  useEffect(() => {
    if (state.phase === 'done') onResult?.(state.result);
  }, [onResult, state]);

  const skipped = state.phase === 'done' && isSkippedRequirementSatisfaction(state.result)
    ? state.result
    : null;

  return (
    <section className="card requirement-satisfaction-panel" aria-labelledby="degree-requirements-title">
      <div className="editable-section-header">
        <div>
          <h3 id="degree-requirements-title" className="editable-section-title">Degree Requirements</h3>
          <p className="requirement-satisfaction-subtitle">Completed and in-progress coursework counted toward your degree.</p>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={trigger} disabled={state.phase === 'loading'} aria-busy={state.phase === 'loading'}>
          {state.phase === 'loading' ? 'Checking…' : 'Refresh degree progress'}
        </button>
      </div>

      {(state.phase === 'idle' || state.phase === 'loading') && (
        <div className="analysis-loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <p>Checking degree requirements…</p>
        </div>
      )}

      {state.phase === 'transport-error' && (
        <div className="analysis-failed"><p>{state.message}</p></div>
      )}

      {skipped && <div className="analysis-skipped"><p>{skipped.summary}</p></div>}

      {state.phase === 'done' && !isSkippedRequirementSatisfaction(state.result) && (
        state.result.groups.length > 0 ? (
          <ul className="requirement-tree">
            {state.result.groups.map((group) => (
              <RequirementGroupNode key={group.id} group={group} />
            ))}
          </ul>
        ) : (
          <p className="empty-state">No requirement groups are on record for your program yet.</p>
        )
      )}
    </section>
  );
}
