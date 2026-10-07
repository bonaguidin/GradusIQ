import { useEffect } from 'react';
import type { RefObject } from 'react';

/**
 * Moves focus to a submit-error message the moment it appears.
 *
 * Without this, a failed submit leaves focus wherever it already was
 * (usually the submit button) -- the error text is on the page and
 * correctly placed, but nothing points a screen reader or keyboard user
 * at it. The element `ref` points to must have `tabIndex={-1}` (focusable
 * programmatically, not via Tab) and `role="alert"` so its content is
 * announced the moment focus lands on it.
 *
 * Takes the error value itself, not a derived boolean, so that a second
 * failure with the exact same message still re-focuses it -- relies on
 * every caller clearing its error to null before a new submit attempt
 * (all of them already do), since React bails out of re-running this
 * effect if the value passed in is unchanged from last render.
 */
export function useErrorFocus(error: unknown, ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    if (error) ref.current?.focus();
  }, [error, ref]);
}
