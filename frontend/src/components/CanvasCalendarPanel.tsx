import { useState } from 'react';
import type { FormEvent } from 'react';
import { connectCanvasCalendar, disconnectCanvasCalendar, fetchCanvasCalendar } from '../api/canvasCalendar';
import type { CanvasCalendarStore } from '../hooks/useCanvasCalendar';
import { ConfirmButton, useConfirmStatus } from './ConfirmButton';
import {
  canvasCalendarPageUrl,
  cleanCourse,
  cleanTitle,
  dayHeading,
  eventTimeLabel,
  groupEventsByDay,
  syncedLabel,
} from '../lib/canvasCalendar.mjs';
import { SkeletonRows } from './Skeleton';
import { EmptyState } from './EmptyState';

/**
 * Upcoming due dates and exams from the student's Canvas calendar feed.
 *
 * Not connected: three steps and one paste box. The feed link is the one
 * Canvas source that needs no school approval, so this is the whole "connect"
 * flow. Connected: the next three weeks grouped by day, with exams flagged.
 * "Likely exam" is a title match on the backend, so it is worded as a guess.
 */
export function CanvasCalendarPanel({ accessToken, calendar }: { accessToken: string; calendar: CanvasCalendarStore }) {
  const { state, setState } = calendar;
  const [feedUrl, setFeedUrl] = useState('');
  const [busy, setBusy] = useState<'connect' | 'refresh' | 'disconnect' | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const confirm = useConfirmStatus();

  async function handleConnect(event: FormEvent) {
    event.preventDefault();
    if (!feedUrl.trim()) {
      setFormError('Paste the Calendar Feed link from Canvas.');
      confirm.fail();
      return;
    }
    setBusy('connect');
    setFormError(null);
    confirm.start();
    const result = await connectCanvasCalendar(accessToken, feedUrl.trim());
    if (result.ok) {
      // The connected view replaces this form, so the check plays first.
      await confirm.succeed();
      setBusy(null);
      setFeedUrl('');
      setState(result);
      confirm.reset();
    } else {
      setBusy(null);
      confirm.fail();
      setFormError(result.message);
    }
  }

  async function handleRefresh() {
    setBusy('refresh');
    const result = await fetchCanvasCalendar(accessToken, true);
    setBusy(null);
    if (result.ok) setState(result);
  }

  async function handleDisconnect() {
    setBusy('disconnect');
    const result = await disconnectCanvasCalendar(accessToken);
    setBusy(null);
    if (result.ok) setState((prev) => ({ ...result, canvasHost: prev?.ok ? prev.canvasHost : null }));
  }

  if (state === null) {
    return (
      <section className="academic-overview-canvas-calendar">
        <h3 className="term-courses-heading">Coming up in Canvas</h3>
        <SkeletonRows label="Loading your Canvas calendar…" />
      </section>
    );
  }

  if (!state.ok) {
    return (
      <section className="academic-overview-canvas-calendar">
        <h3 className="term-courses-heading">Coming up in Canvas</h3>
        <p className="empty-state">{state.message}</p>
      </section>
    );
  }

  if (!state.connected) {
    const calendarPage = canvasCalendarPageUrl(state.canvasHost);
    return (
      <section className="academic-overview-canvas-calendar">
        <h3 className="term-courses-heading">Coming up in Canvas</h3>
        <p className="canvas-calendar-intro">
          Connect your Canvas calendar to see every due date and exam across your courses in one place.
        </p>
        <ol className="canvas-calendar-steps">
          <li>
            {calendarPage
              ? <a href={calendarPage} target="_blank" rel="noreferrer">Open your Canvas calendar</a>
              : 'Open Calendar in Canvas'}
          </li>
          <li>Click <strong>Calendar Feed</strong> at the bottom right and copy the link</li>
          <li>Paste it here</li>
        </ol>
        <form className="canvas-calendar-form" onSubmit={handleConnect}>
          <input
            className="form-input"
            type="url"
            inputMode="url"
            placeholder="https://…/feeds/calendars/user_….ics"
            aria-label="Canvas calendar feed link"
            value={feedUrl}
            onChange={(e) => setFeedUrl(e.target.value)}
            disabled={busy !== null}
          />
          <ConfirmButton type="submit" className="btn btn-primary btn-sm" status={confirm.status} disabled={busy !== null}>
            {confirm.status === 'success' ? 'Connected' : busy === 'connect' ? 'Connecting…' : 'Connect'}
          </ConfirmButton>
        </form>
        {formError && <p className="login-error" role="alert">{formError}</p>}
        <p className="canvas-calendar-note">
          Read-only. This shares due dates and events, not grades. You can disconnect any time.
        </p>
      </section>
    );
  }

  const groups = groupEventsByDay(state.events);
  const synced = syncedLabel(state.syncedAt);
  return (
    <section className="academic-overview-canvas-calendar">
      <h3 className="term-courses-heading">Coming up in Canvas</h3>
      {state.lastError && <p className="canvas-calendar-warning" role="status">{state.lastError}</p>}
      {groups.length === 0 ? (
        <EmptyState icon="calendar">Nothing due in the next three weeks.</EmptyState>
      ) : (
        <div className="canvas-calendar-days">
          {groups.map((group) => (
            <div className="canvas-calendar-day" key={group.dayKey}>
              <h4>{dayHeading(group.dayKey)}</h4>
              <ul>
                {group.events.map((item) => (
                  <li key={item.uid} className={item.likelyExam ? 'canvas-calendar-item is-exam' : 'canvas-calendar-item'}>
                    <span className="canvas-calendar-time">{eventTimeLabel(item)}</span>
                    <span className="canvas-calendar-title">
                      {item.url
                        ? <a href={item.url} target="_blank" rel="noreferrer" title={item.title}>{cleanTitle(item.title)}</a>
                        : <span title={item.title}>{cleanTitle(item.title)}</span>}
                      {item.courseLabel && <small title={item.courseLabel}>{cleanCourse(item.courseLabel)}</small>}
                    </span>
                    {item.likelyExam && <span className="canvas-calendar-badge">Likely exam</span>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      <div className="canvas-calendar-footer">
        {synced && <span>{synced}</span>}
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { void handleRefresh(); }} disabled={busy !== null}>
          {busy === 'refresh' ? 'Refreshing…' : 'Refresh'}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { void handleDisconnect(); }} disabled={busy !== null}>
          Disconnect
        </button>
      </div>
    </section>
  );
}
