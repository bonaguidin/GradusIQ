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
export function eventDayKey(event: CanvasCalendarEvent, timeZone?: string): string;
export function dayHeading(dayKey: string, now?: Date, timeZone?: string): string;
export function eventTimeLabel(event: CanvasCalendarEvent, timeZone?: string): string;
export function dueInstant(event: CanvasCalendarEvent, timeZone?: string): Date;
export function dueStamp(event: CanvasCalendarEvent, timeZone?: string): string;
export function relativeDue(due: Date, now?: Date): string;
export const DUE_SOON_MS: number;
export interface NextDue {
  event: CanvasCalendarEvent;
  dueAt: Date;
  moreAtSameTime: number;
  dueSoon: boolean;
}
export function pickNextDue(events: CanvasCalendarEvent[], now?: Date, timeZone?: string): NextDue | null;
export function cleanCourse<T extends string | null>(label: T): T;
export function cleanTitle(title: string): string;
export function groupEventsByDay(events: CanvasCalendarEvent[], timeZone?: string): { dayKey: string; events: CanvasCalendarEvent[] }[];
export function syncedLabel(syncedAt: string | null, now?: Date): string | null;
export const STALE_AFTER_MS: number;
export function staleNote(result: CanvasCalendarResult | null, now?: Date): string | null;
