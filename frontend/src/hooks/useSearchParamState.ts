import { useCallback } from 'react';
import { useUrlParams } from './useUrlParams';

/**
 * Syncs one piece of state to a single URL query parameter -- the common
 * case where a page only ever changes one key per interaction (a single set
 * of tabs, a filter). A drop-in replacement for useState's tuple shape, but
 * backed by the URL instead of a component-local value, so it survives a
 * refresh and can be shared as a link.
 *
 * Built on useUrlParams(); see its doc comment for the fallback behavior on
 * an unknown/stale param and the history-replace rule this inherits. If a
 * handler needs to change MORE THAN ONE param at once (e.g. switching
 * sections while also resetting a sub-tab to its default), reach for
 * useUrlParams() directly instead of calling two of these in the same
 * handler -- two independent instances of this hook each resolve their
 * update against the same pre-handler snapshot, so the second call's write
 * would silently overwrite the first's instead of combining with it.
 */
export function useSearchParamState<T extends string>(
  key: string,
  defaultValue: T,
  allowedValues: readonly T[],
): [T, (value: T) => void] {
  const { getParam, setParams } = useUrlParams();
  const value = getParam(key, defaultValue, allowedValues);
  const setValue = useCallback(
    (next: T) => setParams({ [key]: next === defaultValue ? null : next }),
    [key, defaultValue, setParams],
  );
  return [value, setValue];
}
