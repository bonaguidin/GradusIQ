// Pure helpers for the Canvas calendar feed panel. The backend route is
// GradusIQ_career/api.py's /api/v2/student/me/canvas-calendar; the feed URL a
// student pastes is never echoed back, only the host it came from.
// canvasCalendar.test.mjs pins these.

export const CANVAS_CALENDAR_URL = '/api/v2/student/me/canvas-calendar'
export const canvasCalendarRefreshUrl = () => `${CANVAS_CALENDAR_URL}?refresh=true`

function asEvent(raw) {
  if (!raw || typeof raw !== 'object') return null
  const { uid, title, starts_at: startsAt } = raw
  if (typeof uid !== 'string' || typeof title !== 'string' || typeof startsAt !== 'string') return null
  return {
    uid,
    title,
    courseLabel: typeof raw.course_label === 'string' ? raw.course_label : null,
    kind: raw.kind === 'assignment' ? 'assignment' : 'event',
    startsAt,
    allDay: raw.all_day === true,
    likelyExam: raw.likely_exam === true,
    url: typeof raw.url === 'string' && raw.url.startsWith('https://') ? raw.url : null,
  }
}

function detailMessage(body, fallback) {
  const detail = body && typeof body === 'object' ? body.detail : null
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message
  if (typeof detail === 'string') return detail
  return fallback
}

export function normalizeCanvasCalendar(status, body) {
  if (status === 200 && body && typeof body === 'object') {
    const events = Array.isArray(body.events) ? body.events.map(asEvent).filter(Boolean) : []
    return {
      ok: true,
      connected: body.connected === true,
      canvasHost: typeof body.canvas_host === 'string' ? body.canvas_host : null,
      syncedAt: typeof body.synced_at === 'string' ? body.synced_at : null,
      lastError: typeof body.last_error === 'string' ? body.last_error : null,
      events,
    }
  }
  if (status === 0) return { ok: false, message: 'Could not reach GradusIQ. Check your connection and try again.' }
  return { ok: false, message: detailMessage(body, 'Could not load your Canvas calendar.') }
}

// Where the student finds their feed link. Canvas puts "Calendar Feed" at the
// bottom right of /calendar on every instance.
export function canvasCalendarPageUrl(canvasHost) {
  return canvasHost ? `https://${canvasHost}/calendar` : null
}

function localDayKey(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

// All-day items carry a bare YYYY-MM-DD with no zone; it is already the day
// the student sees in Canvas and must not be shifted through UTC.
export function eventDayKey(event) {
  return event.allDay ? event.startsAt.slice(0, 10) : localDayKey(new Date(event.startsAt))
}

export function dayHeading(dayKey, now = new Date()) {
  const today = localDayKey(now)
  const tomorrowDate = new Date(now)
  tomorrowDate.setDate(now.getDate() + 1)
  if (dayKey === today) return 'Today'
  if (dayKey === localDayKey(tomorrowDate)) return 'Tomorrow'
  const [y, m, d] = dayKey.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

export function eventTimeLabel(event) {
  if (event.allDay) return 'All day'
  return new Date(event.startsAt).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

// Days in order, events within a day in the order the backend sent them
// (already chronological, all-day items last).
export function groupEventsByDay(events) {
  const groups = []
  const byKey = new Map()
  for (const event of events) {
    const key = eventDayKey(event)
    let group = byKey.get(key)
    if (!group) {
      group = { dayKey: key, events: [] }
      byKey.set(key, group)
      groups.push(group)
    }
    group.events.push(event)
  }
  return groups.sort((a, b) => (a.dayKey < b.dayKey ? -1 : a.dayKey > b.dayKey ? 1 : 0))
}

export function syncedLabel(syncedAt, now = new Date()) {
  if (!syncedAt) return null
  const minutes = Math.max(0, Math.round((now.getTime() - new Date(syncedAt).getTime()) / 60000))
  if (Number.isNaN(minutes)) return null
  if (minutes < 1) return 'Synced just now'
  if (minutes < 60) return `Synced ${minutes} min ago`
  const hours = Math.round(minutes / 60)
  return `Synced ${hours} hr${hours === 1 ? '' : 's'} ago`
}
