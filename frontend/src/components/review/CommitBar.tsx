import { useEffect, useRef, useState } from 'react';
import type { ReviewCounters } from '../../lib/resumeApi.mjs';
import { ConfirmingOverlay } from './ConfirmingOverlay';

export interface CommitBarProps {
  counters: ReviewCounters;
  confirming: boolean;
  justSaved: boolean;
  error: string | null;
  onConfirm(): void;
  /**
   * A state the student cannot act on, rather than a failed action.
   *
   * Distinct from `error` because the remedy is different: an error invites
   * another attempt, this does not. When set, the confirm button is disabled --
   * leaving it live beside "verification pending" would invite clicking a
   * button that cannot succeed. Resume passes nothing and is unaffected.
   */
  blocked?: string | null;
  /** Replaces the derived status line for surfaces counting something else. */
  statusOverride?: string;
  /** Replaces the "Confirm all" idle label. */
  confirmLabel?: string;
}

/**
 * Fixed bottom bar: what confirming will actually do, and the button that does it.
 *
 * The status line takes the SAME `counters` object the ledger renders, rather
 * than recomputing from sections/drafts. Two independent counts of the same
 * thing drift the moment one call site changes, and the failure mode here is a
 * bar that promises "3 fields will stay empty" above a ledger reading 4 --
 * which would make the student distrust both numbers.
 *
 * Also renders ConfirmingOverlay while `confirming` is true. That lives here,
 * not in the two review screens, because this is the only component both flows
 * share -- putting it here is what makes it impossible to fix the in-flight
 * feedback for one flow and forget the other.
 */
export function CommitBar({
  counters,
  confirming,
  justSaved,
  error,
  onConfirm,
  blocked = null,
  statusOverride,
  confirmLabel = 'Confirm all',
}: CommitBarProps) {
  const { gaps, total, edited } = counters;

  // A brief, one-shot flourish on the button itself right as a confirm
  // attempt concludes in error -- distinct from `error`, which stays set
  // (and keeps rendering as the status line above) long after this settles.
  // Keyed on confirming's own true -> false transition, not on the error
  // string's identity, so a second attempt failing with the exact same
  // message still replays it.
  const [justFailed, setJustFailed] = useState(false);
  const wasConfirming = useRef(confirming);
  useEffect(() => {
    if (wasConfirming.current && !confirming && error) {
      setJustFailed(true);
      const timer = window.setTimeout(() => setJustFailed(false), 500);
      wasConfirming.current = confirming;
      return () => window.clearTimeout(timer);
    }
    wasConfirming.current = confirming;
    return undefined;
  }, [confirming, error]);

  const status =
    statusOverride ??
    (gaps > 0
      ? `Confirming now saves ${String(total - gaps)} of ${String(total)} fields. ${String(gaps)} ${
          gaps === 1 ? 'field stays' : 'fields stay'
        } empty.`
      : `All ${String(total)} fields have a value${
          edited > 0 ? `, ${String(edited)} corrected by you` : ''
        }.`);

  return (
    <>
      <ConfirmingOverlay confirming={confirming} />
      <div className="rv-commit">
        <div className="rv-commit-inner">
          <p className="rv-commit-status">
            {blocked ? (
              <span className="rv-commit-blocked" role="status">
                {blocked}
              </span>
            ) : error ? (
              <span className="rv-commit-error" role="alert">{error}</span>
            ) : (
              status
            )}
          </p>
          <button
            type="button"
            className={`rv-commit-button${confirming ? ' is-loading' : ''}${justSaved ? ' is-success' : ''}${justFailed ? ' is-error' : ''}`}
            onClick={onConfirm}
            disabled={confirming || justSaved || blocked !== null}
          >
            {/* Text stays the real content (and the button's accessible name)
                in every state -- is-loading/is-success/is-error only hide it
                visually, replacing it with the spinner/check/cross below, so
                a screen reader still hears "Saving…"/"Saved ✓" exactly as it
                did before this existed. */}
            <span className="rv-commit-label">
              {justSaved
                ? 'Saved ✓'
                : confirming
                  ? 'Saving…'
                  : blocked
                    ? 'Verification pending'
                    : confirmLabel}
            </span>
            <span className="rv-commit-spinner" aria-hidden="true" />
            <svg className="rv-commit-icon rv-commit-check" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M5 13l4 4L19 7" />
            </svg>
            <svg className="rv-commit-icon rv-commit-cross" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
            <span className="rv-commit-ring" aria-hidden="true" />
          </button>
        </div>
      </div>
    </>
  );
}
