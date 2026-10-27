import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  CANVAS_CALENDAR_URL,
  canvasCalendarPageUrl,
  canvasCalendarRefreshUrl,
  cleanCourse,
  cleanTitle,
  dayHeading,
  dueInstant,
  dueStamp,
  eventDayKey,
  groupEventsByDay,
  normalizeCanvasCalendar,
  pickNextDue,
  relativeDue,
  staleNote,
  syncedLabel,
} from '../src/lib/canvasCalendar.mjs'

const raw = (overrides = {}) => ({
  uid: 'event-assignment-1',
  title: 'Homework 4',
  course_label: 'MATH 151',
  kind: 'assignment',
  starts_at: '2026-10-15T04:59:00Z',
  all_day: false,
  likely_exam: false,
  url: 'https://canvas.tamu.edu/courses/1/assignments/1',
  ...overrides,
})

test('routes', () => {
  assert.equal(CANVAS_CALENDAR_URL, '/api/v2/student/me/canvas-calendar')
  assert.equal(canvasCalendarRefreshUrl(), '/api/v2/student/me/canvas-calendar/refresh')
  assert.equal(canvasCalendarPageUrl('canvas.tamu.edu'), 'https://canvas.tamu.edu/calendar')
  assert.equal(canvasCalendarPageUrl(null), null)
})

test('normalizes a connected payload and drops malformed events', () => {
  const result = normalizeCanvasCalendar(200, {
    connected: true,
    canvas_host: 'canvas.tamu.edu',
    synced_at: '2026-10-13T15:00:00Z',
    last_error: null,
    events: [raw(), { title: 'no uid' }, raw({ uid: 'e2', url: 'javascript:alert(1)', likely_exam: true })],
  })
  assert.equal(result.ok, true)
  assert.equal(result.connected, true)
  assert.equal(result.events.length, 2)
  assert.equal(result.events[0].courseLabel, 'MATH 151')
  assert.equal(result.events[1].url, null)
  assert.equal(result.events[1].likelyExam, true)
})

test('surfaces the backend message on a rejected link', () => {
  const result = normalizeCanvasCalendar(422, {
    detail: { error: 'invalid_feed_url', message: "That link isn't from canvas.tamu.edu." },
  })
  assert.deepEqual(result, { ok: false, message: "That link isn't from canvas.tamu.edu." })
  assert.equal(normalizeCanvasCalendar(0, null).ok, false)
})

test('all-day dates are never shifted through UTC', () => {
  const event = normalizeCanvasCalendar(200, { connected: true, events: [raw({ starts_at: '2026-10-20', all_day: true })] }).events[0]
  assert.equal(eventDayKey(event), '2026-10-20')
})

test('groups by day in order', () => {
  const { events } = normalizeCanvasCalendar(200, {
    connected: true,
    events: [
      raw({ uid: 'a', starts_at: '2026-10-22', all_day: true }),
      raw({ uid: 'b', starts_at: '2026-10-20', all_day: true }),
      raw({ uid: 'c', starts_at: '2026-10-20', all_day: true }),
    ],
  })
  const groups = groupEventsByDay(events)
  assert.deepEqual(groups.map((g) => g.dayKey), ['2026-10-20', '2026-10-22'])
  assert.deepEqual(groups[0].events.map((e) => e.uid), ['b', 'c'])
})

test('day headings and sync labels', () => {
  const now = new Date(2026, 9, 13, 10, 0)
  assert.equal(dayHeading('2026-10-13', now), 'Today')
  assert.equal(dayHeading('2026-10-14', now), 'Tomorrow')
  assert.notEqual(dayHeading('2026-10-20', now), 'Today')
  assert.equal(syncedLabel(null, now), null)
  assert.equal(syncedLabel(new Date(now.getTime() - 5 * 60000).toISOString(), now), 'Synced 5 min ago')
  assert.equal(syncedLabel(new Date(now.getTime() - 3 * 3600000).toISOString(), now), 'Synced 3 hrs ago')
})

test('the dashboard mounts the panel only for a real session', async () => {
  const dashboard = await readFile(new URL('../src/pages/AuthenticatedDashboard.tsx', import.meta.url), 'utf8')
  assert.match(dashboard, /\{accessToken && <CanvasCalendarPanel accessToken=\{accessToken\} calendar=\{canvasCalendar\} \/>\}/)
  assert.match(dashboard, /useCanvasCalendar\(accessToken, /)
})

// ── next-due selection and the shared formatter ─────────────────────────────

const CHI = 'America/Chicago'
const NY = 'America/New_York'
const ev = (overrides = {}) =>
  normalizeCanvasCalendar(200, { connected: true, events: [raw(overrides)] }).events[0]

test('pickNextDue: an empty list has no pick', () => {
  assert.equal(pickNextDue([], new Date('2026-10-27T15:00:00Z'), CHI), null)
})

test('pickNextDue: the earliest item at or after now wins, whatever the feed order', () => {
  const now = new Date('2026-10-27T15:00:00Z')
  const pick = pickNextDue(
    [ev({ uid: 'late', starts_at: '2026-10-30T20:55:00Z' }), ev({ uid: 'soon', starts_at: '2026-10-29T20:55:00Z' })],
    now,
    CHI,
  )
  assert.equal(pick.event.uid, 'soon')
  assert.equal(pick.moreAtSameTime, 0)
  assert.equal(pick.dueSoon, false)
})

test('pickNextDue: an item due earlier today that has passed is skipped, one due exactly now is kept', () => {
  const now = new Date('2026-10-27T15:00:00Z')
  const events = [
    ev({ uid: 'passed', starts_at: '2026-10-27T14:59:00Z' }),
    ev({ uid: 'exact', starts_at: '2026-10-27T15:00:00Z' }),
    ev({ uid: 'later', starts_at: '2026-10-27T22:00:00Z' }),
  ]
  assert.equal(pickNextDue(events, now, CHI).event.uid, 'exact')
  assert.equal(pickNextDue(events.slice(0, 1), now, CHI), null)
})

test('pickNextDue: all-day items are due at 23:59 on their date in the viewer zone', () => {
  const allDay = ev({ uid: 'proposal', starts_at: '2026-10-27', all_day: true })
  // 23:59 CDT on Oct 27 is 04:59Z on Oct 28.
  assert.equal(dueInstant(allDay, CHI).toISOString(), '2026-10-28T04:59:00.000Z')
  // Still upcoming at 10 PM local, gone after midnight.
  assert.equal(pickNextDue([allDay], new Date('2026-10-28T03:00:00Z'), CHI).event.uid, 'proposal')
  assert.equal(pickNextDue([allDay], new Date('2026-10-28T05:00:00Z'), CHI), null)
  // Same date in another zone is a different instant: the zone is the viewer's.
  assert.equal(dueInstant(allDay, NY).toISOString(), '2026-10-28T03:59:00.000Z')
})

test('pickNextDue: an all-day item due today beats a timed item due tomorrow, and loses to one due tonight', () => {
  const now = new Date('2026-10-27T15:00:00Z')
  const allDay = ev({ uid: 'allday', starts_at: '2026-10-27', all_day: true })
  const tomorrow = ev({ uid: 'tomorrow', starts_at: '2026-10-28T15:00:00Z' })
  const tonight = ev({ uid: 'tonight', starts_at: '2026-10-28T02:00:00Z' })
  assert.equal(pickNextDue([tomorrow, allDay], now, CHI).event.uid, 'allday')
  assert.equal(pickNextDue([allDay, tonight], now, CHI).event.uid, 'tonight')
})

test('pickNextDue: ties keep feed order and count the others at that moment', () => {
  const now = new Date('2026-10-27T15:00:00Z')
  const pick = pickNextDue(
    [
      ev({ uid: 'a', starts_at: '2026-10-28T04:59:00Z' }),
      ev({ uid: 'b', starts_at: '2026-10-28T04:59:00Z' }),
      ev({ uid: 'c', starts_at: '2026-10-28T04:59:00Z' }),
      ev({ uid: 'd', starts_at: '2026-10-29T04:59:00Z' }),
    ],
    now,
    CHI,
  )
  assert.equal(pick.event.uid, 'a')
  assert.equal(pick.moreAtSameTime, 2)
})

test('pickNextDue: due within 24 hours is flagged, and the line is exactly 24h', () => {
  const now = new Date('2026-10-27T15:00:00Z')
  assert.equal(pickNextDue([ev({ starts_at: '2026-10-28T15:00:00Z' })], now, CHI).dueSoon, true)
  assert.equal(pickNextDue([ev({ starts_at: '2026-10-28T15:00:01Z' })], now, CHI).dueSoon, false)
})

test('pickNextDue: exam flag survives on the pick', () => {
  const now = new Date('2026-10-27T15:00:00Z')
  assert.equal(pickNextDue([ev({ likely_exam: true, starts_at: '2026-10-28T20:00:00Z' })], now, CHI).event.likelyExam, true)
})

test('relativeDue reads minutes, hours and days between instants', () => {
  const now = new Date('2026-10-27T15:00:00Z')
  const at = (ms) => new Date(now.getTime() + ms)
  assert.equal(relativeDue(at(0), now), 'now')
  assert.equal(relativeDue(at(59 * 1000), now), 'now')
  assert.equal(relativeDue(at(60 * 1000), now), 'in 1 minute')
  assert.equal(relativeDue(at(25 * 60000), now), 'in 25 minutes')
  assert.equal(relativeDue(at(3600000), now), 'in 1 hour')
  assert.equal(relativeDue(at(23.9 * 3600000), now), 'in 23 hours')
  assert.equal(relativeDue(at(25 * 3600000), now), 'in 1 day')
  assert.equal(relativeDue(at(50 * 3600000), now), 'in 2 days')
})

test('DST: spring forward shortens the night, and the pick and wording follow instants', () => {
  // Chicago springs forward 2026-03-08 02:00 -> 03:00. 10 PM Sat CST to 10 AM Sun CDT is 11 real hours.
  const now = new Date('2026-03-08T04:00:00Z') // Sat Mar 7, 10:00 PM CST
  const due = ev({ uid: 'sun', starts_at: '2026-03-08T15:00:00Z' }) // Sun Mar 8, 10:00 AM CDT
  const pick = pickNextDue([due], now, CHI)
  assert.equal(relativeDue(pick.dueAt, now), 'in 11 hours')
  assert.match(dueStamp(due, CHI), /Mar 8/)
  assert.match(dueStamp(due, CHI), /10:00\s?AM/)
  // An all-day item on the transition date is 23:59 CDT (UTC-5), not CST.
  const allDay = ev({ starts_at: '2026-03-08', all_day: true })
  assert.equal(dueInstant(allDay, CHI).toISOString(), '2026-03-09T04:59:00.000Z')
  // And on the fall-back date, 23:59 CST (UTC-6).
  const fall = ev({ starts_at: '2026-11-01', all_day: true })
  assert.equal(dueInstant(fall, CHI).toISOString(), '2026-11-02T05:59:00.000Z')
})

test('one formatter feeds the card and the alert: same zone, same day key and time text', () => {
  const late = ev({ starts_at: '2026-10-29T04:59:00Z' }) // 11:59 PM Oct 28 in Chicago
  assert.equal(eventDayKey(late, CHI), '2026-10-28')
  assert.equal(eventDayKey(late, 'Asia/Tokyo'), '2026-10-29')
  assert.match(dueStamp(late, CHI), /Oct 28/)
  assert.match(dueStamp(late, CHI), /11:59\s?PM/)
  assert.equal(dueStamp(ev({ starts_at: '2026-10-29', all_day: true }), CHI).endsWith('end of day'), true)
})

test('staleNote: quiet for a fresh sync, a note for a failed or old one', () => {
  const now = new Date('2026-10-27T15:00:00Z')
  const base = { ok: true, connected: true, canvasHost: null, events: [] }
  const hoursAgo = (h) => new Date(now.getTime() - h * 3600000).toISOString()
  assert.equal(staleNote({ ...base, syncedAt: hoursAgo(1), lastError: null }, now), null)
  assert.equal(staleNote({ ...base, syncedAt: hoursAgo(7), lastError: null }, now), 'Synced 7 hrs ago')
  assert.equal(staleNote({ ...base, syncedAt: hoursAgo(1), lastError: 'Canvas is down' }, now), 'Synced 1 hr ago')
  assert.equal(staleNote({ ok: false, message: 'x' }, now), null)
  assert.equal(staleNote(null, now), null)
})

test('cleanCourse: strips a trailing colon, a section list, and nothing else', () => {
  assert.equal(cleanCourse('CSCE 222 504:'), 'CSCE 222 504')
  assert.equal(cleanCourse('FSTC-300:599,M99,NUTR-300:599'), 'FSTC-300')
  assert.equal(cleanCourse('ECEN-248:531,532,533,534,535,536'), 'ECEN-248')
  assert.equal(cleanCourse('ENGR-217:201,202,203,…,PHYS-217:201,…'), 'ENGR-217')
  // Anything else is returned unchanged.
  assert.equal(cleanCourse('MATH 151-501: Engineering Mathematics I'), 'MATH 151-501: Engineering Mathematics I')
  assert.equal(cleanCourse('ENGR 102'), 'ENGR 102')
  assert.equal(cleanCourse('Study Skills Workshop'), 'Study Skills Workshop')
  assert.equal(cleanCourse(null), null)
})

test('cleanTitle: drops only a trailing parenthetical that holds a -DUPn marker', () => {
  assert.equal(cleanTitle('Post-Lab 8 Electronic Submission (ECEN-248-536-DUP1)'), 'Post-Lab 8 Electronic Submission')
  assert.equal(cleanTitle('Lab 4 Submission (PHYS-217-508-DUP1)'), 'Lab 4 Submission')
  assert.equal(cleanTitle('Homework Assignment #4'), 'Homework Assignment #4')
  assert.equal(cleanTitle('Quiz 2 (chapters 3-4)'), 'Quiz 2 (chapters 3-4)')
  assert.equal(cleanTitle('(PHYS-217-508-DUP1)'), '(PHYS-217-508-DUP1)')
})
