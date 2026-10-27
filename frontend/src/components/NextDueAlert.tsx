import { useEffect, useMemo, useState } from 'react';
import type { MouseEvent } from 'react';
import {
  cleanCourse,
  cleanTitle,
  dueStamp,
  pickNextDue,
  relativeDue,
  staleNote,
} from '../lib/canvasCalendar.mjs';
import type { CanvasCalendarResult } from '../lib/canvasCalendar.mjs';

// Re-pick this often so a tab left open never shows an item that has passed,
// and "in 25 minutes" keeps counting down.
const TICK_MS = 30_000;

/**
 * The Overview's one-line "Next due" alert: the student's earliest upcoming
 * Canvas item, linking to the "Coming up in Canvas" card on the Academic page.
 *
 * It says nothing when it has nothing true to say: a demo or no-courses
 * identity, no connected feed, an error with nothing cached, or nothing
 * upcoming all render null rather than a placeholder (the card is where
 * connecting happens). Cached events with a failed or old sync still show,
 * with a quiet "Synced N hrs ago" beside them.
 *
 * Not dismissible: it is derived from the calendar and changes by itself as
 * due dates pass. Within 24 hours of the due time it adds a heavier border,
 * a clock icon and the words "Due soon" -- a cue that does not rely on color.
 *
 * Times come from the shared formatters in lib/canvasCalendar.mjs, in the
 * viewer's own time zone, exactly as the card shows them. There is no new
 * live region: the alert is part of the page, not an announcement.
 */
export function NextDueAlert({
  result,
  enabled,
  onOpen,
}: {
  result: CanvasCalendarResult | null;
  enabled: boolean;
  onOpen: () => void;
}) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (!enabled) return undefined;
    const tick = () => setNow(new Date());
    const timer = window.setInterval(tick, TICK_MS);
    document.addEventListener('visibilitychange', tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [enabled]);

  const events = result && result.ok && result.connected ? result.events : null;
  const pick = useMemo(() => (events ? pickNextDue(events, now) : null), [events, now]);
  if (!enabled || !pick) return null;

  const { event, dueAt, moreAtSameTime, dueSoon } = pick;
  const title = cleanTitle(event.title);
  const course = cleanCourse(event.courseLabel);
  const stamp = dueStamp(event);
  const relative = relativeDue(dueAt, now);
  const note = staleNote(result, now);

  const linkName = [
    `Next due: ${title}`,
    course,
    `due ${stamp}`,
    relative,
    dueSoon ? 'due soon' : null,
    event.likelyExam ? 'likely exam' : null,
    moreAtSameTime > 0 ? `${moreAtSameTime} more due at the same time` : null,
  ].filter(Boolean).join(', ') + '. Go to Coming up in Canvas';

  function handleClick(e: MouseEvent<HTMLAnchorElement>) {
    // A modified click (new tab) uses the href; a plain click stays in the app.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    onOpen();
  }

  return (
    <section className="next-due" aria-label="Next due" data-due-soon={dueSoon ? 'true' : undefined}>
      <div className="next-due-inner">
        <a className="next-due-link" href="?section=academic" aria-label={linkName} onClick={handleClick}>
          <svg className="next-due-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {dueSoon
              ? <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2" />
              : <path d="M7 3v3M17 3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" />}
          </svg>
          <span className="next-due-text">
            <span className="next-due-label">Next due:</span>{' '}
            <strong title={event.title}>{title}</strong>
            {course && <span className="next-due-course" title={event.courseLabel ?? undefined}>, {course}</span>}
            {', '}
            <time dateTime={dueAt.toISOString()}>{stamp}</time>
            <span className="next-due-relative"> ({relative})</span>
          </span>
          {dueSoon && <span className="next-due-badge next-due-badge--soon">Due soon</span>}
          {event.likelyExam && <span className="next-due-badge">Likely exam</span>}
          {moreAtSameTime > 0 && <span className="next-due-more">+{moreAtSameTime} more due then</span>}
          {note && <span className="next-due-sync">{note}</span>}
        </a>
      </div>
    </section>
  );
}
