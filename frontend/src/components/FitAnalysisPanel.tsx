import { useAuth } from '../auth/useAuth';
import { analyzeFit } from '../api/analysis';
import { analysisFailureMessage, type AnalysisRunState } from '../hooks/useAnalysisRun';
import { useCachedAnalysisRun } from '../hooks/useCachedAnalysisRun';
import { hiringSignalLine } from '../lib/hiringSignalLine.mjs';
import type { FeatureResult, FitAnalysisData, FitLevel, FitRoleMatch } from '../types/analysis';
import { AnalysisPanel, type AnalysisPhase } from './AnalysisPanel';

export interface FitAnalysisRun {
  state: AnalysisRunState<FeatureResult<FitAnalysisData>>;
  trigger: () => void;
  /** From useCachedAnalysisRun -- see GapAnalysisRun. */
  refreshing?: boolean;
  refreshError?: string;
  /** From useSequencedAnalysisRuns -- see AnalysisPanel's blockedReason. */
  blockedReason?: string;
}

interface FitAnalysisPanelProps {
  /**
   * Lets a parent (the Career Snapshot sub-tab) share this exact run state
   * instead of each holding its own. Omitted by every other caller, which
   * keeps its own internal useAnalysisRun instance exactly as before.
   */
  run?: FitAnalysisRun;
}

// FIT role-fit panel — data shape is fit.py's output_contract (role_matches[],
// overall_fit_summary). Confirmed against real (non-mocked) DeepSeek R1 output —
// see frontend/src/types/analysis.ts.
export function FitAnalysisPanel({ run: externalRun }: FitAnalysisPanelProps = {}) {
  const { slug, session } = useAuth();
  const internalRun = useCachedAnalysisRun('fit', () =>
    analyzeFit({ slug, accessToken: session?.access_token ?? null }),
  );
  const { state, trigger, refreshing, refreshError, blockedReason } = externalRun ?? internalRun;

  const phase: AnalysisPhase =
    state.phase === 'idle'
      ? 'idle'
      : state.phase === 'loading'
        ? 'loading'
        : state.phase === 'transport-error'
          ? 'failed'
          : state.result.status === 'skipped'
            ? 'skipped'
            : state.result.status === 'failed'
              ? 'failed'
              : 'success';

  const missingFields = state.phase === 'done' ? state.result.missing_fields ?? [] : [];

  return (
    <AnalysisPanel
      title="Role Fit (FIT)"
      invitation="See how well your profile matches your target roles — a fit level per role, why it fits, and what's still missing."
      phase={phase}
      onRun={trigger}
      missingFields={missingFields}
      failureMessage={analysisFailureMessage(state)}
      refreshing={refreshing}
      refreshError={refreshError}
      blockedReason={blockedReason}
    >
      {state.phase === 'done' && state.result.status === 'success' && (
        <FitResult data={state.result.data} summary={state.result.summary} />
      )}
    </AnalysisPanel>
  );
}

export const FIT_LEVEL_LABEL: Record<FitLevel, string> = {
  high: 'High Fit',
  medium: 'Medium Fit',
  low: 'Low Fit',
};

function FitResult({ data, summary }: { data: FitAnalysisData; summary: string }) {
  // A "success" status is a contract, not a guarantee -- a response cut
  // short mid-OOM can still parse as JSON with a field missing.
  const roleMatches = data.role_matches ?? [];
  if (roleMatches.length === 0) {
    return <p className="empty-state">No role matches identified.</p>;
  }

  return (
    <div>
      <p className="gap-summary">{data.overall_fit_summary || summary}</p>

      <div className="theme-list">
        {roleMatches.map((match, idx) => (
          <RoleMatchCard key={idx} match={match} />
        ))}
      </div>
    </div>
  );
}

function RoleMatchCard({ match }: { match: FitRoleMatch }) {
  const supportingSignals = match.supporting_signals ?? [];
  const missingSignals = match.missing_signals ?? [];

  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">{match.role}</span>
        <span className={`fit-badge fit-badge--${match.fit_level}`}>
          {FIT_LEVEL_LABEL[match.fit_level]}
        </span>
      </div>
      <p className="theme-summary">{match.rationale}</p>
      <HiringSignalLine hiringSignal={match.hiring_signal} />

      <div className="gap-columns">
        <div>
          <div className="gap-column-title">Why this fits</div>
          {supportingSignals.length > 0 ? (
            <ul className="gap-list">
              {supportingSignals.map((signal, idx) => (
                <li key={idx} className="gap-list-item gap-list-item--strength">
                  {signal}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-state">None identified.</p>
          )}
        </div>

        <div>
          <div className="gap-column-title">What's missing</div>
          {missingSignals.length > 0 ? (
            <ul className="gap-list">
              {missingSignals.map((signal, idx) => (
                <li key={idx} className="gap-list-item gap-list-item--must">
                  {signal}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-state">None identified.</p>
          )}
        </div>
      </div>
    </div>
  );
}

// Renders fit.py's server-derived hiring_signal (coverage/employers/posting_count
// -- see fit.py's _hiring_signal_by_role). Absent entirely for cached/demo
// results that predate this field; render nothing rather than guess. The
// per-state decision lives in hiringSignalLine.mjs, tested independently of
// this component's JSX.
function HiringSignalLine({ hiringSignal }: { hiringSignal?: FitRoleMatch['hiring_signal'] }) {
  const line = hiringSignalLine(hiringSignal);
  if (!line) {
    return null;
  }
  return <p className={`hiring-signal hiring-signal--${line.variant}`}>{line.text}</p>;
}
