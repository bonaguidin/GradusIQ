import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  CANVAS_CALENDAR_URL,
  canvasCalendarPageUrl,
  canvasCalendarRefreshUrl,
  dayHeading,
  eventDayKey,
  groupEventsByDay,
  normalizeCanvasCalendar,
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
  assert.match(dashboard, /\{accessToken && <CanvasCalendarPanel accessToken=\{accessToken\} \/>\}/)
})
