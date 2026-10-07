import { useEffect, useRef, useState } from 'react';
import type { ReviewCounters } from '../../lib/resumeApi.mjs';

export interface LedgerBarProps {
  counters: ReviewCounters;
  onJumpToGap(): void;
}

/**
 * A number that plays a short upward bump when its value changes.
 *
 * Keyed on the value itself rather than on render: re-rendering for an
 * unrelated reason must not animate, or the bump stops meaning "this just
 * changed" and becomes visual noise. prefers-reduced-motion is handled in CSS,
 * where the animation is simply not applied -- the number still updates.
 */
export function Counter({
  value,
  label,
  tone,
}: {
  value: number | string;
  label: string;
  tone?: 'gap';
}) {
  // Accepts a string so a formatted total (credits, "12.00") can bump the same
  // way a plain count does. The bump keys on inequality, which works for both.
  const [bump, setBump] = useState(false);
  const previous = useRef(value);

  useEffect(() => {
    if (previous.current === value) return;
    previous.current = value;
    setBump(true);
    const timer = window.setTimeout(() => setBump(false), 320);
    return () => window.clearTimeout(timer);
  }, [value]);

  return (
    <div className="rv-counter">
      <span
        className={[
          'rv-counter-value',
          tone === 'gap' ? 'rv-counter-value-gap' : '',
          bump ? 'rv-counter-bump' : '',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        {value}
      </span>
      <span className="rv-counter-label">{label}</span>
    </div>
  );
}

export function LedgerBar({ counters, onJumpToGap }: LedgerBarProps) {
  const { read, gaps, edited, filledRatio } = counters;
  const noGaps = gaps === 0;

  return (
    <div className="rv-ledger">
      <div className="rv-ledger-counts">
        <Counter value={read} label="read from resume" />
        <Counter value={gaps} label="not found" tone="gap" />
        <Counter value={edited} label="edited by you" />
      </div>

      <div className="rv-ledger-actions">
        <button
          type="button"
          className="rv-jump"
          onClick={onJumpToGap}
          disabled={noGaps}
          aria-label={noGaps ? 'Nothing missing' : `Jump to the next of ${String(gaps)} missing fields`}
        >
          {noGaps ? '✓ nothing missing' : '↓ next gap'}
        </button>
      </div>

      <div
        className="rv-progress"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(filledRatio * 100)}
        aria-label="Fields with a value"
      >
        <div className="rv-progress-fill" style={{ transform: `scaleX(${String(filledRatio)})` }} />
      </div>
    </div>
  );
}
