// Pure helpers for the Canvas calendar feed panel. The backend route is
// GradusIQ_career/api.py's /api/v2/student/me/canvas-calendar; the feed URL a
// student pastes is never echoed back, only the host it came from.
// canvasCalendar.test.mjs pins these.

export const CANVAS_CALENDAR_URL = '/api/v2/student/me/canvas-calendar'
export const canvasCalendarRefreshUrl = () => `${CANVAS_CALENDAR_URL}/refresh`

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

// Every date and time below is shown in the viewer's own time zone (the
// browser's), through the functions in this block, so the Coming up card and
// the overview's next-due alert can never disagree. `timeZone` is an optional
// IANA name for tests; production callers leave it undefined.

function dayKeyInZone(date, timeZone) {
  // en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}

function zoneOffsetMs(ms, timeZone) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', {
      timeZone,
      hourCycle: 'h23',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
    })
      .formatToParts(new Date(ms))
      .map((part) => [part.type, part.value]),
  )
  const wall = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute, +parts.second)
  return wall - Math.floor(ms / 1000) * 1000
}

// The instant at which a wall clock in `timeZone` reads y-m-d h:min.
function wallToInstant(y, m, d, h, min, timeZone) {
  if (!timeZone) return new Date(y, m - 1, d, h, min)
  const guess = Date.UTC(y, m - 1, d, h, min)
  const first = guess - zoneOffsetMs(guess, timeZone)
  const second = guess - zoneOffsetMs(first, timeZone)
  return new Date(second)
}

// All-day items carry a bare YYYY-MM-DD with no zone; it is already the day
// the student sees in Canvas and must not be shifted through UTC.
export function eventDayKey(event, timeZone) {
  return event.allDay ? event.startsAt.slice(0, 10) : dayKeyInZone(new Date(event.startsAt), timeZone)
}

export function dayHeading(dayKey, now = new Date(), timeZone) {
  const today = dayKeyInZone(now, timeZone)
  const tomorrow = dayKeyInZone(new Date(now.getTime() + 24 * 3600 * 1000), timeZone)
  if (dayKey === today) return 'Today'
  if (dayKey === tomorrow) return 'Tomorrow'
  const [y, m, d] = dayKey.split('-').map(Number)
  // Noon UTC keeps the weekday right whatever the viewer's zone.
  return new Date(Date.UTC(y, m - 1, d, 12)).toLocaleDateString(undefined, {
    timeZone: 'UTC',
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
}

export function eventTimeLabel(event, timeZone) {
  if (event.allDay) return 'All day'
  return new Date(event.startsAt).toLocaleTimeString(undefined, { timeZone, hour: 'numeric', minute: '2-digit' })
}

// When an item is due. A timed item is its instant; an all-day item is due
// at 23:59 on its date in the viewer's zone ("by end of day").
export function dueInstant(event, timeZone) {
  if (!event.allDay) return new Date(event.startsAt)
  const [y, m, d] = event.startsAt.slice(0, 10).split('-').map(Number)
  return wallToInstant(y, m, d, 23, 59, timeZone)
}

// "Thu, Oct 29, 3:55 PM"; an all-day item reads "Thu, Oct 29, end of day".
export function dueStamp(event, timeZone) {
  const due = dueInstant(event, timeZone)
  const day = due.toLocaleDateString(undefined, { timeZone, weekday: 'short', month: 'short', day: 'numeric' })
  const time = event.allDay
    ? 'end of day'
    : due.toLocaleTimeString(undefined, { timeZone, hour: 'numeric', minute: '2-digit' })
  return `${day}, ${time}`
}

// "in 25 minutes", "in 3 hours", "in 2 days". Measured between instants, so
// a daylight-saving change between now and the due time cannot skew it.
export function relativeDue(due, now = new Date()) {
  const minutes = Math.floor((due.getTime() - now.getTime()) / 60000)
  if (minutes < 1) return 'now'
  if (minutes < 60) return `in ${minutes} minute${minutes === 1 ? '' : 's'}`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `in ${hours} hour${hours === 1 ? '' : 's'}`
  const days = Math.floor(hours / 24)
  return `in ${days} day${days === 1 ? '' : 's'}`
}

export const DUE_SOON_MS = 24 * 3600 * 1000

// The earliest item due at or after `now`, comparing instants. Ties on the
// exact due time keep feed order; `moreAtSameTime` counts the others due at
// that same moment. Null when nothing is upcoming.
export function pickNextDue(events, now = new Date(), timeZone) {
  let best = null
  let more = 0
  for (const event of events) {
    const due = dueInstant(event, timeZone)
    const ms = due.getTime()
    if (Number.isNaN(ms) || ms < now.getTime()) continue
    if (best === null || ms < best.ms) {
      best = { event, due, ms }
      more = 0
    } else if (ms === best.ms) {
      more += 1
    }
  }
  if (best === null) return null
  return {
    event: best.event,
    dueAt: best.due,
    moreAtSameTime: more,
    dueSoon: best.ms - now.getTime() <= DUE_SOON_MS,
  }
}

// Canvas course names arrive as typed by the school. Only three shapes are
// rewritten, and anything else comes back unchanged. The raw text stays on
// the element as a title attribute.
//   "CSCE 222 504:"                       -> "CSCE 222 504"
//   "ECEN-248:531,532,533"                -> "ECEN-248"
//   "FSTC-300:599,M99,NUTR-300:599"       -> "FSTC-300"
const SECTION_LIST_RE = /^([A-Za-z]{2,6}[- ]?\d{3}[A-Za-z]?):\S*\d\S*(?:,\s*\S+)*$/
export function cleanCourse(label) {
  if (typeof label !== 'string') return label
  const trailing = label.replace(/\s*:\s*$/, '')
  const list = SECTION_LIST_RE.exec(trailing)
  return list ? list[1] : trailing
}

// "Lab 4 Submission (PHYS-217-508-DUP1)" -> "Lab 4 Submission": the trailing
// parenthetical is only removed when it contains a -DUPn marker.
const DUP_SUFFIX_RE = /\s*\([^()]*-DUP\d+[^()]*\)\s*$/i
export function cleanTitle(title) {
  if (typeof title !== 'string') return title
  return title.replace(DUP_SUFFIX_RE, '') || title
}

// Days in order, events within a day in the order the backend sent them
// (already chronological, all-day items last).
export function groupEventsByDay(events, timeZone) {
  const groups = []
  const byKey = new Map()
  for (const event of events) {
    const key = eventDayKey(event, timeZone)
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

// Cached events with a failed or old sync still deserve the alert, with this
// quiet note beside it. Null when the data is fresh.
export const STALE_AFTER_MS = 6 * 3600 * 1000
export function staleNote(result, now = new Date()) {
  if (!result || !result.ok) return null
  const age = result.syncedAt ? now.getTime() - new Date(result.syncedAt).getTime() : Infinity
  return result.lastError || age > STALE_AFTER_MS ? syncedLabel(result.syncedAt, now) : null
}
