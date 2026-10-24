import { useEffect, useRef } from 'react';

/**
 * A change made outside the page that shows the data, e.g. a course planned
 * from the assistant chat while the planner is open. The page that owns the
 * data listens and reloads it; nothing else is shared.
 */
export type DataTopic = 'planned-courses' | 'canvas-calendar';

const EVENT = 'gradusiq:data-changed';

export function notifyDataChanged(topic: DataTopic): void {
  window.dispatchEvent(new CustomEvent<DataTopic>(EVENT, { detail: topic }));
}

/** Calls `onChange` whenever `topic` changes elsewhere in the app. */
export function useDataChanged(topic: DataTopic, onChange: () => void): void {
  const latest = useRef(onChange);
  useEffect(() => {
    latest.current = onChange;
  });
  useEffect(() => {
    const listener = (event: Event) => {
      if ((event as CustomEvent<DataTopic>).detail === topic) latest.current();
    };
    window.addEventListener(EVENT, listener);
    return () => window.removeEventListener(EVENT, listener);
  }, [topic]);
}
