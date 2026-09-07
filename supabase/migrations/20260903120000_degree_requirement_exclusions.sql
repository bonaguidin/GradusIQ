-- Student-chosen exclusions of otherwise no-choice Degree Schedule requirements.
--
-- Parallel to degree_requirement_selections (20260824120000), which owns
-- choice-shaped LOCKED selections. This table owns the opposite intent: a
-- single-mandatory requirement group the student has deliberately removed from
-- their plan. An excluded group stops being auto-scheduled and instead surfaces
-- as an EXCLUDED decision needing review (see
-- course_discovery/requirement_selection.py). Every read/write path must still
-- reconstruct current requirement-tree evidence and validate the complete
-- schedule before trusting a row here -- a row is student intent, never proof
-- the requirement stopped applying.
--
-- Deliberately carries no candidate_id / course_codes: a single-mandatory group
-- has no real alternative, so restoring it is a one-click "add it back", not a
-- re-choose. The requirement_group_id is the whole payload.
--
-- The requirement_groups_id_program_id_key unique constraint this table's
-- composite foreign key needs already exists -- 20260824120000 added it for
-- degree_requirement_selections' identical FK, and that migration always runs
-- first. It is referenced here, never re-added.

create table degree_requirement_exclusions (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students (id) on delete cascade,
  program_id uuid not null references programs (id) on delete cascade,
  requirement_group_id uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (requirement_group_id, program_id)
    references requirement_groups (id, program_id) on delete cascade,
  unique (student_id, program_id, requirement_group_id)
);

comment on table degree_requirement_exclusions is
  'One row per requirement group the student has set aside from their Degree '
  'Schedule. Intent/provenance only; the reconstructed requirement tree stays '
  'the authority for whether the requirement still applies.';

create index degree_requirement_exclusions_student_program_idx
  on degree_requirement_exclusions (student_id, program_id);

alter table degree_requirement_exclusions enable row level security;

-- Students may inspect their own exclusions but cannot bypass the backend's
-- schedule-version and revision checks by writing directly.
create policy degree_requirement_exclusions_owner_select
  on degree_requirement_exclusions for select
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = degree_requirement_exclusions.student_id
        and students.auth_user_id = auth.uid()
    )
  );

revoke all on degree_requirement_exclusions from anon;
revoke insert, update, delete, truncate on degree_requirement_exclusions from authenticated;
grant select on degree_requirement_exclusions to authenticated;
grant all on degree_requirement_exclusions to service_role;

-- Same monotonic student-revision bump the selections table gets, and the same
-- app.degree_schedule_revision_bump_suppressed guard (checked inside
-- degree_schedule_bump_student_revision itself) so a future combined
-- selection+exclusion write can suppress the row trigger and bump exactly once.
create trigger degree_schedule_exclusions_revision
after insert or update or delete on degree_requirement_exclusions
for each row execute function degree_schedule_bump_student_revision();

-- Service-role-only atomic complete-set replacement, structurally mirroring
-- replace_degree_requirement_selections. Python validates schedule semantics
-- (reconstruct + schedule_version CAS) before calling; this function proves the
-- database-backed validation inputs did not move between reconstruction and the
-- write, then replaces the whole exclusion set.
create or replace function replace_degree_requirement_exclusions(
  p_student_id uuid,
  p_program_id uuid,
  p_expected_student_revision bigint,
  p_expected_program_revision bigint,
  p_expected_institution_revision bigint,
  p_schedule_version text,
  p_excluded_group_ids uuid[]
) returns jsonb
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  v_institution_id uuid;
  v_student_revision bigint;
  v_program_revision bigint;
  v_institution_revision bigint;
  v_current uuid[];
  v_desired uuid[];
begin
  if p_schedule_version !~ '^sha256:[0-9a-f]{64}$' then
    raise exception using errcode = '23514', message = 'invalid schedule version';
  end if;
  if p_excluded_group_ids is null then
    raise exception using errcode = '22023', message = 'excluded group ids must not be null';
  end if;
  if array_position(p_excluded_group_ids, null) is not null then
    raise exception using errcode = '23514', message = 'excluded group ids must not contain null';
  end if;
  select institution_id into v_institution_id from public.programs where id = p_program_id;
  if v_institution_id is null or not exists (select 1 from public.students where id = p_student_id) then
    raise exception using errcode = '23503', message = 'student or program does not exist';
  end if;

  perform public.get_degree_schedule_revisions(p_student_id, p_program_id);
  select revision into v_student_revision from public.degree_schedule_student_revisions
    where student_id = p_student_id and program_id = p_program_id for update;
  select revision into v_program_revision from public.degree_schedule_program_revisions
    where program_id = p_program_id for update;
  select revision into v_institution_revision from public.degree_schedule_institution_revisions
    where institution_id = v_institution_id for update;

  if v_student_revision <> p_expected_student_revision
     or v_program_revision <> p_expected_program_revision
     or v_institution_revision <> p_expected_institution_revision then
    return jsonb_build_object(
      'status', 'REVISION_CONFLICT',
      'student_revision', v_student_revision,
      'program_revision', v_program_revision,
      'institution_revision', v_institution_revision
    );
  end if;

  if exists (
    select 1 from unnest(p_excluded_group_ids) as x(requirement_group_id)
    left join public.requirement_groups g
      on g.id = x.requirement_group_id and g.program_id = p_program_id
    where g.id is null
  ) then
    raise exception using errcode = '23503', message = 'requirement does not belong to program';
  end if;

  select coalesce(array_agg(requirement_group_id order by requirement_group_id), array[]::uuid[])
  into v_current
  from public.degree_requirement_exclusions
  where student_id = p_student_id and program_id = p_program_id;

  select coalesce(array_agg(distinct gid order by gid), array[]::uuid[])
  into v_desired
  from unnest(p_excluded_group_ids) as gid;

  if v_current = v_desired then
    return jsonb_build_object(
      'status', 'UNCHANGED',
      'student_revision', v_student_revision,
      'program_revision', v_program_revision,
      'institution_revision', v_institution_revision,
      'excluded_group_ids', to_jsonb(v_current)
    );
  end if;

  perform set_config('app.degree_schedule_revision_bump_suppressed', 'on', true);
  delete from public.degree_requirement_exclusions s
  where s.student_id = p_student_id and s.program_id = p_program_id
    and not (s.requirement_group_id = any (p_excluded_group_ids));
  insert into public.degree_requirement_exclusions(student_id, program_id, requirement_group_id)
  select p_student_id, p_program_id, gid
  from (select distinct unnest(p_excluded_group_ids) as gid) d
  on conflict (student_id, program_id, requirement_group_id) do nothing;
  perform set_config('app.degree_schedule_revision_bump_suppressed', 'off', true);

  update public.degree_schedule_student_revisions
  set revision = revision + 1, updated_at = clock_timestamp()
  where student_id = p_student_id and program_id = p_program_id
  returning revision into v_student_revision;

  select coalesce(array_agg(requirement_group_id order by requirement_group_id), array[]::uuid[])
  into v_current
  from public.degree_requirement_exclusions
  where student_id = p_student_id and program_id = p_program_id;
  return jsonb_build_object(
    'status', 'APPLIED',
    'student_revision', v_student_revision,
    'program_revision', v_program_revision,
    'institution_revision', v_institution_revision,
    'excluded_group_ids', to_jsonb(v_current)
  );
end $$;

revoke all on function replace_degree_requirement_exclusions(uuid, uuid, bigint, bigint, bigint, text, uuid[])
  from public, anon, authenticated;
grant execute on function replace_degree_requirement_exclusions(uuid, uuid, bigint, bigint, bigint, text, uuid[])
  to service_role;

comment on function replace_degree_requirement_exclusions(uuid, uuid, bigint, bigint, bigint, text, uuid[])
is 'Service-role-only atomic complete-set replacement of a student''s Degree '
   'Schedule requirement exclusions. Python must reconstruct and validate the '
   'schedule_version before calling.';
