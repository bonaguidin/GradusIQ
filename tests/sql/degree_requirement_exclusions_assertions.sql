\set ON_ERROR_STOP on

insert into institutions(id, name) values
  ('01000000-0000-0000-0000-000000000001', 'SMU');
insert into students(id, auth_user_id, name, expected_graduation) values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'One', 'Spring 2029'),
  ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', 'Two', 'Spring 2029');
insert into student_institutions(id, student_id, institution_id, relationship, catalog_year) values
  ('11000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '01000000-0000-0000-0000-000000000001', 'home', '2026-2027');
insert into programs(id, institution_id, catalog_year) values
  ('30000000-0000-0000-0000-000000000001', '01000000-0000-0000-0000-000000000001', '2026-2027'),
  ('30000000-0000-0000-0000-000000000002', '01000000-0000-0000-0000-000000000001', '2026-2027');
insert into requirement_groups(id, program_id, coursedog_rule_id, name) values
  ('40000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 'r1', 'R1'),
  ('40000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000001', 'r2', 'R2'),
  ('40000000-0000-0000-0000-000000000009', '30000000-0000-0000-0000-000000000002', 'r9', 'R9');

-- ── direct-table constraints and RLS ────────────────────────────────────────
set role service_role;
insert into degree_requirement_exclusions(student_id, program_id, requirement_group_id) values
  ('10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001'),
  ('10000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001');
reset role;

do $$ begin
  begin
    insert into degree_requirement_exclusions(student_id, program_id, requirement_group_id)
    values ('10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001');
    raise exception 'duplicate exclusion accepted';
  exception when unique_violation then null; end;
  begin
    insert into degree_requirement_exclusions(student_id, program_id, requirement_group_id)
    values ('10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000002', '40000000-0000-0000-0000-000000000001');
    raise exception 'cross-program requirement accepted';
  exception when foreign_key_violation then null; end;
end $$;

set role authenticated;
select set_config('request.jwt.claim.sub', '20000000-0000-0000-0000-000000000001', false);
do $$ begin
  if (select count(*) from degree_requirement_exclusions) <> 1 then
    raise exception 'owner SELECT leaked another student or hid own row';
  end if;
  begin
    insert into degree_requirement_exclusions(student_id, program_id, requirement_group_id)
    values ('10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000002');
    raise exception 'authenticated direct mutation accepted';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

set role anon;
do $$ begin
  begin perform count(*) from degree_requirement_exclusions;
    raise exception 'anonymous read accepted';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

set role service_role;
delete from degree_requirement_exclusions;
reset role;

-- ── RPC: happy path, idempotence, complete-set replace ──────────────────────
set role service_role;
do $$
declare
  v jsonb; s bigint; p bigint; i bigint;
  first_result jsonb; second_result jsonb;
  original_updated timestamptz;
begin
  v := get_degree_schedule_revisions('10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001');
  s := (v->>'student_revision')::bigint; p := (v->>'program_revision')::bigint; i := (v->>'institution_revision')::bigint;

  first_result := replace_degree_requirement_exclusions(
    '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', s, p, i,
    'sha256:' || repeat('a', 64),
    array['40000000-0000-0000-0000-000000000001']::uuid[]);
  if first_result->>'status' <> 'APPLIED' or (first_result->>'student_revision')::bigint <> s + 1 then
    raise exception 'first exclusion write did not apply exactly one revision';
  end if;
  if (select count(*) from degree_requirement_exclusions where student_id='10000000-0000-0000-0000-000000000001') <> 1 then
    raise exception 'exclusion row not written';
  end if;
  if not (first_result->'excluded_group_ids' ? '40000000-0000-0000-0000-000000000001') then
    raise exception 'excluded_group_ids missing from APPLIED result';
  end if;
  select updated_at into original_updated from degree_requirement_exclusions
  where student_id='10000000-0000-0000-0000-000000000001';

  -- Same set again, fresh expected revision -> UNCHANGED, no bump, no touch.
  second_result := replace_degree_requirement_exclusions(
    '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', s + 1, p, i,
    'sha256:' || repeat('b', 64),
    array['40000000-0000-0000-0000-000000000001']::uuid[]);
  if second_result->>'status' <> 'UNCHANGED' or (second_result->>'student_revision')::bigint <> s + 1 then
    raise exception 'idempotent exclusion write was not UNCHANGED';
  end if;
  if exists (select 1 from degree_requirement_exclusions
             where student_id='10000000-0000-0000-0000-000000000001' and updated_at <> original_updated) then
    raise exception 'idempotent write changed a timestamp';
  end if;

  -- Duplicate ids in the payload collapse to one row.
  first_result := replace_degree_requirement_exclusions(
    '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', s + 1, p, i,
    'sha256:' || repeat('c', 64),
    array['40000000-0000-0000-0000-000000000002','40000000-0000-0000-0000-000000000002']::uuid[]);
  s := (first_result->>'student_revision')::bigint;
  if first_result->>'status' <> 'APPLIED'
     or (select count(*) from degree_requirement_exclusions where student_id='10000000-0000-0000-0000-000000000001') <> 1
     or not exists (select 1 from degree_requirement_exclusions
                    where student_id='10000000-0000-0000-0000-000000000001'
                      and requirement_group_id='40000000-0000-0000-0000-000000000002') then
    raise exception 'complete-set replace / dedupe failed';
  end if;

  -- Empty set removes everything, then is idempotent.
  first_result := replace_degree_requirement_exclusions(
    '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', s, p, i,
    'sha256:' || repeat('d', 64), array[]::uuid[]);
  s := (first_result->>'student_revision')::bigint;
  if first_result->>'status' <> 'APPLIED'
     or (select count(*) from degree_requirement_exclusions where student_id='10000000-0000-0000-0000-000000000001') <> 0 then
    raise exception 'empty-set removal failed';
  end if;
  second_result := replace_degree_requirement_exclusions(
    '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', s, p, i,
    'sha256:' || repeat('e', 64), array[]::uuid[]);
  if second_result->>'status' <> 'UNCHANGED' then
    raise exception 'empty-set repeat was not UNCHANGED';
  end if;
end $$;
reset role;

-- ── RPC: CAS conflict rejects without writing ───────────────────────────────
set role service_role;
do $$
declare v jsonb; conflict jsonb; rows_before jsonb;
begin
  v := get_degree_schedule_revisions('10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001');
  select jsonb_agg(to_jsonb(s) order by requirement_group_id) into rows_before from degree_requirement_exclusions s;
  -- An unrelated academic mutation bumps the student revision after the snapshot.
  update students set expected_graduation='Fall 2029' where id='10000000-0000-0000-0000-000000000001';
  conflict := replace_degree_requirement_exclusions(
    '10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',
    (v->>'student_revision')::bigint,(v->>'program_revision')::bigint,(v->>'institution_revision')::bigint,
    'sha256:'||repeat('f',64), array['40000000-0000-0000-0000-000000000001']::uuid[]);
  if conflict->>'status' <> 'REVISION_CONFLICT' then raise exception 'stale CAS accepted'; end if;
  if (select jsonb_agg(to_jsonb(s) order by requirement_group_id) from degree_requirement_exclusions s) is distinct from rows_before then
    raise exception 'rejected CAS partially wrote';
  end if;
end $$;
reset role;

-- ── RPC: payload validation ────────────────────────────────────────────────
set role service_role;
do $$
declare v jsonb;
begin
  v := get_degree_schedule_revisions('10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001');
  begin
    perform replace_degree_requirement_exclusions(
      '10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',
      (v->>'student_revision')::bigint,(v->>'program_revision')::bigint,(v->>'institution_revision')::bigint,
      'sha256:'||repeat('1',64), array['40000000-0000-0000-0000-000000000009']::uuid[]);
    raise exception 'exclusion of a foreign-program requirement accepted';
  exception when foreign_key_violation then null; end;
  begin
    perform replace_degree_requirement_exclusions(
      '10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',
      (v->>'student_revision')::bigint,(v->>'program_revision')::bigint,(v->>'institution_revision')::bigint,
      'sha256:'||repeat('2',64), array['40000000-0000-0000-0000-000000000001', null]::uuid[]);
    raise exception 'null in the exclusion payload accepted';
  exception when check_violation then null; end;
end $$;
reset role;

-- ── RPC execute privileges ─────────────────────────────────────────────────
do $$ begin
  if has_function_privilege('anon','replace_degree_requirement_exclusions(uuid,uuid,bigint,bigint,bigint,text,uuid[])','EXECUTE') then
    raise exception 'anon can execute exclusion RPC'; end if;
  if has_function_privilege('authenticated','replace_degree_requirement_exclusions(uuid,uuid,bigint,bigint,bigint,text,uuid[])','EXECUTE') then
    raise exception 'authenticated can execute exclusion RPC'; end if;
  if not has_function_privilege('service_role','replace_degree_requirement_exclusions(uuid,uuid,bigint,bigint,bigint,text,uuid[])','EXECUTE') then
    raise exception 'service role cannot execute exclusion RPC'; end if;
end $$;
