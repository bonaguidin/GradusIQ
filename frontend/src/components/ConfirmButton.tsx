import { useCallback, useEffect, useRef, useState } from 'react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';

export type ConfirmStatus = 'idle' | 'loading' | 'success' | 'error';

/**
 * How long the check holds before the caller moves on. Long enough for the
 * check to draw and the slam to settle (index.css, "confirm animation"); the
 * review screens wait the same 650ms before leaving.
 */
export const CONFIRM_SUCCESS_HOLD_MS = 650;

/** The shake runs 400ms; the button returns to its label just after. */
const ERROR_SETTLE_MS = 500;

/**
 * Drives a ConfirmButton through one attempt.
 *
 * `succeed()` resolves once the check has had its moment, so a caller that
 * navigates or swaps the view on success awaits it first; otherwise the
 * animation is unmounted before anyone sees it. `fail()` shakes, then returns
 * to idle on its own, so the button is ready for another try without the
 * caller tracking a second flag.
 */
export function useConfirmStatus() {
  const [status, setStatus] = useState<ConfirmStatus>('idle');
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const start = useCallback(() => {
    window.clearTimeout(timer.current);
    setStatus('loading');
  }, []);

  const succeed = useCallback(
    () =>
      new Promise<void>((resolve) => {
        window.clearTimeout(timer.current);
        setStatus('success');
        timer.current = window.setTimeout(resolve, CONFIRM_SUCCESS_HOLD_MS);
      }),
    [],
  );

  const fail = useCallback(() => {
    window.clearTimeout(timer.current);
    setStatus('error');
    timer.current = window.setTimeout(() => setStatus('idle'), ERROR_SETTLE_MS);
  }, []);

  const reset = useCallback(() => {
    window.clearTimeout(timer.current);
    setStatus('idle');
  }, []);

  return { status, start, succeed, fail, reset };
}

export interface ConfirmButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  status: ConfirmStatus;
  /** The label for the current state. It stays the accessible name throughout. */
  children: ReactNode;
}

/**
 * A button that answers a big moment: a spinner while it works, a check that
 * draws in with a slam and ring on success, a cross and a shake on failure.
 *
 * Reserved for actions that change the student's record (confirm, upload,
 * connect, create account), not routine saves; on every button it would stop
 * meaning anything. It adds the animation on top of whatever look the caller's
 * className gives, so a .btn-primary keeps its size and a .rv-commit-button
 * keeps its own.
 *
 * The label is hidden visually while an icon shows, never removed, so a
 * screen reader still hears "Saving…" or "Saved".
 */
export function ConfirmButton({ status, className, children, disabled, type = 'button', ...rest }: ConfirmButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      className={`${className ?? ''} confirm-anim${status === 'idle' ? '' : ` is-${status}`}`.trim()}
      disabled={disabled || status === 'loading' || status === 'success'}
      aria-busy={status === 'loading' || undefined}
    >
      <span className="confirm-anim-label">{children}</span>
      <span className="confirm-anim-spinner" aria-hidden="true" />
      <svg className="confirm-anim-icon confirm-anim-check" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 13l4 4L19 7" />
      </svg>
      <svg className="confirm-anim-icon confirm-anim-cross" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6 6l12 12M18 6L6 18" />
      </svg>
      <span className="confirm-anim-ring" aria-hidden="true" />
    </button>
  );
}
