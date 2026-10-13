import type { ReactNode } from 'react';

export type StatusTone = 'ready' | 'partial' | 'minimal' | 'neutral';

/**
 * A stat tile whose value is a word, not a figure (Profile Status, Standing).
 * The word sits in a small status pill instead of the big mono number slot,
 * so it doesn't read as a number and doesn't set the row's height.
 */
export function StatusStat({ label, tone = 'neutral', children }: { label: string; tone?: StatusTone; children: ReactNode }) {
  return (
    <div className="overview-stat overview-stat--status">
      <span className={`overview-stat-status overview-stat-status--${tone}`}>
        <span className="overview-stat-status-dot" aria-hidden="true" />
        <span className="readiness-state">{children}</span>
      </span>
      <span className="overview-stat-label">{label}</span>
    </div>
  );
}
