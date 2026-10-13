import { CANVAS_CALENDAR_URL, canvasCalendarRefreshUrl, normalizeCanvasCalendar } from '../lib/canvasCalendar.mjs';
import type { CanvasCalendarResult } from '../lib/canvasCalendar.mjs';

/**
 * Same shape as api/planning.ts's send. The connect and refresh calls fetch
 * from Canvas server-side, so they can take a few seconds, but none of them
 * runs AI work.
 */
async function send(url: string, init: RequestInit): Promise<{ status: number; body: unknown }> {
  try {
    const response = await fetch(url, init);
    let body: unknown = null;
    try { body = await response.json(); } catch { /* normalizers accept null */ }
    return { status: response.status, body };
  } catch {
    return { status: 0, body: null };
  }
}

const auth = (token: string) => ({ Accept: 'application/json', Authorization: `Bearer ${token}` });

export async function fetchCanvasCalendar(token: string, refresh = false): Promise<CanvasCalendarResult> {
  const { status, body } = await send(
    refresh ? canvasCalendarRefreshUrl() : CANVAS_CALENDAR_URL,
    { method: refresh ? 'POST' : 'GET', headers: auth(token) },
  );
  return normalizeCanvasCalendar(status, body);
}

export async function connectCanvasCalendar(token: string, feedUrl: string): Promise<CanvasCalendarResult> {
  const { status, body } = await send(CANVAS_CALENDAR_URL, {
    method: 'PUT',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify({ feed_url: feedUrl }),
  });
  return normalizeCanvasCalendar(status, body);
}

export async function disconnectCanvasCalendar(token: string): Promise<CanvasCalendarResult> {
  const { status, body } = await send(CANVAS_CALENDAR_URL, { method: 'DELETE', headers: auth(token) });
  return normalizeCanvasCalendar(status, body);
}
