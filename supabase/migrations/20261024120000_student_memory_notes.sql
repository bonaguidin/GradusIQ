-- Assistant memory notes: short facts a student asked the GradusIQ assistant
-- to remember ("Aiming for remote software roles"), sent into every future
-- chat so the assistant grows with them without keeping whole conversations.
--
-- See GradusIQ_career/ai/chat_memory.py. A note is only ever written by the
-- student's own click (the assistant proposes, the student saves), and the
-- student can see and delete every note in Career Profile. Conversations
-- themselves are still not stored server-side.
--
-- Owner-only under RLS, like canvas_calendar_feeds. Team members with
-- dashboard or service-role access can still read the table: not reading
-- student notes is a team policy, not something RLS enforces.

create table student_memory_notes (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students (id) on delete cascade,
  note text not null check (char_length(note) between 1 and 200),
  created_at timestamptz not null default now()
);

create index student_memory_notes_student_id_created_at_idx
  on student_memory_notes (student_id, created_at);

comment on table student_memory_notes is
  'Short facts a student chose to have the GradusIQ assistant remember. '
  'Written only by the student''s own click; deletable by the student.';

alter table student_memory_notes enable row level security;

create policy student_memory_notes_owner_all
  on student_memory_notes for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = student_memory_notes.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = student_memory_notes.student_id
        and students.auth_user_id = auth.uid()
    )
  );

grant select, insert, delete on student_memory_notes to authenticated;
revoke all on student_memory_notes from anon;
