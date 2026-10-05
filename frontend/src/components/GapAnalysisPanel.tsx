import { useAuth } from '../auth/useAuth';
import { analyzeGap } from '../api/analysis';
import { analysisFailureMessage, type AnalysisRunState } from '../hooks/useAnalysisRun';
import { useCachedAnalysisRun } from '../hooks/useCachedAnalysisRun';
import type { FeatureResult, GapAnalysisData, GapMustHaveGap } from '../types/analysis';
import { AnalysisPanel, type AnalysisPhase } from './AnalysisPanel';
import { AnimatedNumber } from './AnimatedNumber';

export interface GapAnalysisRun {
  state: AnalysisRunState<FeatureResult<GapAnalysisData>>;
  trigger: () => void;
  /**
   * From useCachedAnalysisRun -- absent when a caller still constructs this
   * shape by hand (e.g. an internal fallback instance), in which case the
   * panel behaves exactly as it did before these existed.
   */
  refreshing?: boolean;
  refreshError?: string;
  /** From useSequencedAnalysisRuns -- see AnalysisPanel's blockedReason. */
  blockedReason?: string;
}

interface GapAnalysisPanelProps {
  /**
   * Lets a parent (the Career Snapshot sub-tab) share this exact run state
   * instead of each holding its own — so a GAP run triggered from Snapshot
   * shows up on the Readiness sub-tab and vice versa. Omitted by every other
   * caller, which keeps its own internal useAnalysisRun instance exactly as
   * before.
   */
  run?: GapAnalysisRun;
}

// GAP readiness panel — data shape is gap.py's output_contract (readiness_score,
// strengths, must_have_gaps, nice_to_have_gaps, recommended_next_steps).
// PROVISIONAL: unvalidated against a real (non-mocked) model response — see
// frontend/src/types/analysis.ts.
export function GapAnalysisPanel({ run: externalRun }: GapAnalysisPanelProps = {}) {
  const { slug, session } = useAuth();
  const internalRun = useCachedAnalysisRun('gap', () =>
    analyzeGap({ slug, accessToken: session?.access_token ?? null }),
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
      title="Readiness Check (GAP)"
      invitation="Run a readiness check against your target roles — see your GAP score, what's missing, and what to do next."
      phase={phase}
      onRun={trigger}
      missingFields={missingFields}
      failureMessage={analysisFailureMessage(state)}
      refreshing={refreshing}
      refreshError={refreshError}
      blockedReason={blockedReason}
    >
      {state.phase === 'done' && state.result.status === 'success' && (
        <GapResult data={state.result.data} summary={state.result.summary} />
      )}
    </AnalysisPanel>
  );
}

// must_have_gaps items carry why_it_matters; nice_to_have_gaps carry
// why_it_helps — the same shape covers both, only one field is ever present.
function GapItemDetail({ item }: { item: GapMustHaveGap }) {
  const why = item.why_it_matters ?? item.why_it_helps;
  return (
    <>
      <div className="gap-item-title">{item.gap}</div>
      {why && <p className="gap-item-why">{why}</p>}
      <p className="gap-item-action">{item.how_to_close}</p>
    </>
  );
}

function GapResult({ data, summary }: { data: GapAnalysisData; summary: string }) {
  return (
    <div>
      <div className="gap-score-row">
        <span className="gap-score-value"><AnimatedNumber value={data.readiness_score} decimals={0} /></span>
        <span className="gap-score-max">/ 10</span>
        <span className="gap-score-label">Readiness</span>
      </div>

      <p className="gap-summary">{summary}</p>

      <div className="gap-columns">
        <div>
          <div className="gap-column-title">Must-Have Gaps</div>
          {data.must_have_gaps.length > 0 ? (
            <ul className="gap-list">
              {data.must_have_gaps.map((item, idx) => (
                <li key={idx} className="gap-list-item gap-list-item--must">
                  <GapItemDetail item={item} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-state">None identified.</p>
          )}
        </div>

        <div>
          <div className="gap-column-title">Nice-to-Have Gaps</div>
          {data.nice_to_have_gaps.length > 0 ? (
            <ul className="gap-list">
              {data.nice_to_have_gaps.map((item, idx) => (
                <li key={idx} className="gap-list-item gap-list-item--nice">
                  <GapItemDetail item={item} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-state">None identified.</p>
          )}
        </div>
      </div>

      {data.strengths.length > 0 && (
        <div className="gap-section">
          <div className="gap-column-title">Strengths</div>
          <ul className="gap-list">
            {data.strengths.map((strength, idx) => (
              <li key={idx} className="gap-list-item gap-list-item--strength">
                {strength}
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.recommended_next_steps.length > 0 && (
        <div>
          <div className="gap-column-title">Recommended Next Steps</div>
          <ol className="gap-steps">
            {data.recommended_next_steps.map((step, idx) => (
              <li key={idx}>{step}</li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
