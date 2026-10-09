import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

export type UrlParamUpdates = Record<string, string | null>;

/**
 * One shared read/write surface over the page's query-string state, so every
 * tab/filter that wants a place in the URL goes through a single
 * useSearchParams() instance instead of each grabbing its own.
 *
 * That sharing matters for correctness, not just tidiness: useSearchParams()
 * memoizes its snapshot once per render, and setSearchParams's
 * functional-update form resolves against THAT snapshot, not whatever the
 * URL becomes a moment later. Two independent useSearchParams() instances
 * calling setSearchParams back-to-back in the same handler (e.g. switching
 * the top-level section AND resetting a sub-tab to its default) would each
 * build their new URL from the same stale snapshot -- the second call's URL
 * silently overwrites the first's change instead of merging with it, because
 * neither call knows about the other. Routing every multi-key update through
 * one setParams call sidesteps that: it's a single setSearchParams call,
 * built from one snapshot, applying every change at once.
 *
 * getParam falls back to defaultValue whenever a param is missing or holds a
 * value outside allowedValues (a stale link, a typo, an old bookmark) --
 * never throws, never renders a blank state for a bad param.
 *
 * setParams always updates history with "replace," never "push": a tab or
 * filter is not a separate page, and a user hitting Back should land on the
 * previous *page*, not replay every tab they clicked through. Pass `null`
 * for a key to remove it from the URL entirely -- the convention here is to
 * do that whenever a value equals its own default, so a page in its default
 * state has a clean URL (plain /dashboard, not
 * /dashboard?section=overview&academic=overview).
 */
export function useUrlParams() {
  const [searchParams, setSearchParams] = useSearchParams();

  const getParam = useCallback(
    <T extends string>(key: string, defaultValue: T, allowedValues: readonly T[]): T => {
      const raw = searchParams.get(key);
      return raw && (allowedValues as readonly string[]).includes(raw) ? (raw as T) : defaultValue;
    },
    [searchParams],
  );

  const setParams = useCallback(
    (updates: UrlParamUpdates) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(updates)) {
            if (value === null) next.delete(key);
            else next.set(key, value);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  return { getParam, setParams };
}
