import { useEffect, useState } from 'react';
import type { CachedAnalysisRun } from './useCachedAnalysisRun';

type Feature = 'fit' | 'gap' | 'shift';

const FEATURE_LABEL: Record<Feature, string> = {
  fit: 'Role Fit',
  gap: 'Readiness',
  shift: 'Trend Guidance',
};

function isLive<T>(run: CachedAnalysisRun<T>): boolean {
  return run.state.phase === 'loading' || run.refreshing === true;
}

/**
 * Gates FIT/GAP/SHIFT to one live analysis call at a time.
 *
 * Career Intelligence renders all three panels together against a backend
 * that runs on a free, memory-constrained tier. Three live calls at once --
 * automatic on mount, or three quick clicks -- have pushed it over its
 * memory limit and gotten it OOM-killed mid-response. Each returned run's
 * `trigger` is a no-op while a sibling is live, and `blockedReason` names
 * which one to wait for, so the disabled button isn't left unexplained.
 */
export function useSequencedAnalysisRuns<TFit, TGap, TShift>(runs: {
  fit: CachedAnalysisRun<TFit>;
  gap: CachedAnalysisRun<TGap>;
  shift: CachedAnalysisRun<TShift>;
}): {
  fit: CachedAnalysisRun<TFit>;
  gap: CachedAnalysisRun<TGap>;
  shift: CachedAnalysisRun<TShift>;
} {
  const [running, setRunning] = useState<Feature | null>(null);
  // Checked per-field rather than by indexing `runs` with `running` --
  // TypeScript can't narrow a union of three unrelated generic types through
  // a dynamic key, since each of TFit/TGap/TShift "could be instantiated
  // with an arbitrary type which could be unrelated to" the others.
  const liveFeature: Feature | null =
    running === 'fit' && isLive(runs.fit)
      ? 'fit'
      : running === 'gap' && isLive(runs.gap)
        ? 'gap'
        : running === 'shift' && isLive(runs.shift)
          ? 'shift'
          : null;

  // The run holding the lock settled -- release it so the next click on any
  // panel can go through. liveFeature is derived straight from runs' state
  // above rather than taking runs itself as a dependency, since runs is a
  // fresh object every render.
  useEffect(() => {
    if (running !== null && liveFeature === null) setRunning(null);
  }, [running, liveFeature]);

  function gate<T>(feature: Feature, run: CachedAnalysisRun<T>): CachedAnalysisRun<T> {
    const blockedBy = liveFeature !== null && liveFeature !== feature ? FEATURE_LABEL[liveFeature] : null;
    return {
      ...run,
      trigger: () => {
        if (blockedBy) return;
        setRunning(feature);
        run.trigger();
      },
      blockedReason:
        blockedBy === null
          ? undefined
          : `Waiting for ${blockedBy} to finish — these run one at a time to stay within the server's memory limit.`,
    };
  }

  return {
    fit: gate('fit', runs.fit),
    gap: gate('gap', runs.gap),
    shift: gate('shift', runs.shift),
  };
}
