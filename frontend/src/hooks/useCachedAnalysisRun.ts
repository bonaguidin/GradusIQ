import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { getCachedAnalysis } from '../api/analysis';
import type { AnalysisRunState } from './useAnalysisRun';
import type { FeatureResult } from '../types/analysis';

export interface CachedAnalysisRun<TResult> {
  state: AnalysisRunState<TResult>;
  trigger: () => void;
  /**
   * True while a manual re-run is in flight AND there is already a 'done'
   * result on screen. The panel keeps showing the previous result during
   * this window instead of switching to the full loading view -- see
   * AnalysisPanel's `refreshing` prop.
   */
  refreshing: boolean;
  /**
   * Set when a re-run (triggered while a 'done' result was already showing)
   * fails. The previous result stays in `state`; this is rendered as a small
   * inline notice alongside it rather than replacing the panel with the
   * full failed-state view.
   */
  refreshError?: string;
  /**
   * Set by useSequencedAnalysisRuns when a sibling FIT/GAP/SHIFT run is
   * already live -- this hook never sets it itself. See AnalysisPanel's
   * blockedReason.
   */
  blockedReason?: string;
}

/**
 * GAP/FIT/SHIFT run state, backed by the persistent analysis cache instead of
 * always requiring a fresh live call.
 *
 * - Demo identity (`identity.slug` truthy): no cache read exists for a demo
 *   session (getCachedAnalysis requires an accessToken, which demo identities
 *   never have), so this leaves state at 'idle' same as a real student's
 *   cache miss. It used to call `trigger()` unconditionally on mount, which
 *   made all three of Career Intelligence's panels fire a live analysis call
 *   at once on every page load -- a burst the backend's free-tier memory
 *   limit couldn't always absorb. The "Run analysis" invitation now requires
 *   the same manual click a real student already gets.
 * - Real identity (`identity.slug` falsy): GET .../analysis-cache/{feature} is
 *   called on mount instead. A hit sets state straight to 'done' -- no live
 *   run, no loading flash. A miss (404) leaves state at 'idle', which renders
 *   the existing "Run analysis" invitation; this hook deliberately does NOT
 *   auto-trigger a live run for real students (GAP in particular can be slow
 *   enough that an unrequested background run on every login is the wrong
 *   default).
 *
 * The manual "Run analysis"/"Re-run analysis" button always calls `trigger`,
 * which live-runs `run()` regardless of identity. When a 'done' result is
 * already showing, `trigger` does not blank the panel: it flips `refreshing`
 * on instead of moving `state` back to 'loading', and swaps in the new result
 * (or records `refreshError`) only once the call settles.
 */
export function useCachedAnalysisRun<TData>(
  feature: 'gap' | 'fit' | 'shift',
  run: () => Promise<FeatureResult<TData>>,
): CachedAnalysisRun<FeatureResult<TData>> {
  const { slug, session } = useAuth();
  const accessToken = session?.access_token ?? null;

  type TResult = FeatureResult<TData>;
  const [state, setState] = useState<AnalysisRunState<TResult>>({ phase: 'idle' });
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | undefined>(undefined);

  // Read synchronously inside `trigger` without making `trigger` depend on
  // (and be re-created every time) `state` changes.
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const trigger = useCallback(() => {
    const hasResult = stateRef.current.phase === 'done';
    if (hasResult) {
      setRefreshing(true);
      setRefreshError(undefined);
    } else {
      setState({ phase: 'loading' });
    }
    run()
      .then((result) => {
        setRefreshing(false);
        setRefreshError(undefined);
        setState({ phase: 'done', result });
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Request failed.';
        if (stateRef.current.phase === 'done') {
          setRefreshing(false);
          setRefreshError(message);
        } else {
          setState({ phase: 'transport-error', message });
        }
      });
  }, [run]);

  // Mount-only: fires once per hook instance (per panel), not on every
  // identity/accessToken change -- matches every other one-shot mount effect
  // in this codebase's analysis panels (none of which re-fetch on re-render).
  const attemptedRef = useRef(false);
  useEffect(() => {
    if (attemptedRef.current) return;
    attemptedRef.current = true;

    if (slug || !accessToken) return;

    // No cancellation flag here: attemptedRef above already guarantees this
    // body runs at most once per hook instance, ever -- including under
    // StrictMode's development-only double-invoke (mount, cleanup, mount),
    // where attemptedRef's true value (set synchronously above, before
    // either invocation's cleanup runs) makes the second invocation a no-op.
    // A `cancelled` flag flipped by that synthetic cleanup would silently
    // drop the FIRST invocation's real fetch result instead -- the one
    // fetch this effect ever makes -- leaving state stuck at 'idle' even
    // after a real cached result comes back.
    getCachedAnalysis<TData>(feature, accessToken)
      .then((result) => {
        if (result === null) return;
        setState({ phase: 'done', result });
      })
      .catch(() => {
        // A transport failure reading the cache is not a run failure -- leave
        // state at 'idle' so the student still sees the normal invitation and
        // can trigger a live run themselves.
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally mount-only
  }, []);

  return { state, trigger, refreshing, refreshError };
}
