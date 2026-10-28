import { useEffect, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { fetchCanvasCalendar } from '../api/canvasCalendar';
import { useDataChanged } from '../lib/dataChanged';
import type { CanvasCalendarResult } from '../lib/canvasCalendar.mjs';

export interface CanvasCalendarStore {
  /** Null until the first answer arrives. */
  state: CanvasCalendarResult | null;
  setState: Dispatch<SetStateAction<CanvasCalendarResult | null>>;
}

/**
 * The student's Canvas calendar, fetched once per dashboard session.
 *
 * Called by the dashboard shell and handed down, so the overview's next-due
 * alert and the Academic "Coming up in Canvas" card read one answer instead
 * of each asking the backend (a read that can make the server fetch from
 * Canvas) on every tab change. The card writes connect, refresh and
 * disconnect results back through `setState`; a refresh from the assistant
 * chat arrives as the 'canvas-calendar' data-changed event.
 *
 * `enabled` is false for demo identities (no session token, no feed) and for
 * students with no confirmed courses (the card is not shown to them).
 */
export function useCanvasCalendar(accessToken: string | null, enabled: boolean): CanvasCalendarStore {
  const [state, setState] = useState<CanvasCalendarResult | null>(null);
  const active = enabled && accessToken !== null;

  useEffect(() => {
    if (!active || accessToken === null) return undefined;
    let live = true;
    void fetchCanvasCalendar(accessToken).then((result) => {
      if (live) setState(result);
    });
    return () => {
      live = false;
    };
  }, [active, accessToken]);

  useDataChanged('canvas-calendar', () => {
    if (!active || accessToken === null) return;
    void fetchCanvasCalendar(accessToken).then((result) => {
      if (result.ok) setState(result);
    });
  });

  return { state, setState };
}
