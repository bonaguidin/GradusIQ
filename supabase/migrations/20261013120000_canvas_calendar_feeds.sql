-- Canvas calendar feeds: one row per student holding their Canvas iCal feed
-- URL and the last parsed snapshot of its events.
--
-- See GradusIQ_career/canvas/calendar_feed.py. The feed is the student's own
-- "Calendar Feed" link from Canvas, which needs no developer key or school
-- approval. It carries due dates and calendar events, not grades.
--
-- feed_url is a bearer secret (anyone holding it can read that calendar), so
-- this table is owner-only under RLS and the API never returns the URL after
-- it is saved.
--
-- Also sets SMU's canvas_host, which was seeded null in
-- 20260728000103_institution_grading_schema.sql. The feed validator only
-- accepts links from the student's institution's canvas_host or an
-- instructure.com subdomain, so without it SMU links would be rejected.

create table canvas_calendar_feeds (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null unique references students (id) on delete cascade,
  feed_url text not null check (feed_url ~ '^https://[^/]+/feeds/calendars/user_[A-Za-z0-9]+\.ics$'),
  feed_host text not null,
  events jsonb not null default '[]'::jsonb check (jsonb_typeof(events) = 'array'),
  synced_at timestamptz null,
  last_error text null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table canvas_calendar_feeds is
  'A student''s Canvas calendar feed URL and the last parsed snapshot of its '
  'events (assignment due dates, calendar events). Not grades: those need the '
  'Canvas API, which needs per-school approval.';

comment on column canvas_calendar_feeds.events is
  'Parsed snapshot, replaced wholesale on every successful sync. Bounded to '
  'the near past and the coming months by calendar_feed.keep_for_storage.';

comment on column canvas_calendar_feeds.last_error is
  'Student-facing message from the most recent failed sync, null once a sync '
  'succeeds. A failed sync keeps the previous events.';

alter table canvas_calendar_feeds enable row level security;

create policy canvas_calendar_feeds_owner_all
  on canvas_calendar_feeds for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = canvas_calendar_feeds.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = canvas_calendar_feeds.student_id
        and students.auth_user_id = auth.uid()
    )
  );

grant select, insert, update, delete on canvas_calendar_feeds to authenticated;
revoke all on canvas_calendar_feeds from anon;

update institutions
set canvas_host = 'canvas.smu.edu'
where name = 'Southern Methodist University'
  and canvas_host is null;
