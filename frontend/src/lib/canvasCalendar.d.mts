export const CANVAS_CALENDAR_URL: string;
export function canvasCalendarRefreshUrl(): string;

export interface CanvasCalendarEvent {
  uid: string;
  title: string;
  courseLabel: string | null;
  kind: 'assignment' | 'event';
  startsAt: string;
  allDay: boolean;
  likelyExam: boolean;
  url: string | null;
}

export type CanvasCalendarResult =
  | {
      ok: true;
      connected: boolean;
      canvasHost: string | null;
      syncedAt: string | null;
      lastError: string | null;
      events: CanvasCalendarEvent[];
    }
  | { ok: false; message: string };

export function normalizeCanvasCalendar(status: number, body: unknown): CanvasCalendarResult;
export function canvasCalendarPageUrl(canvasHost: string | null): string | null;
export function eventDayKey(event: CanvasCalendarEvent): string;
export function dayHeading(dayKey: string, now?: Date): string;
export function eventTimeLabel(event: CanvasCalendarEvent): string;
export function groupEventsByDay(events: CanvasCalendarEvent[]): { dayKey: string; events: CanvasCalendarEvent[] }[];
export function syncedLabel(syncedAt: string | null, now?: Date): string | null;
