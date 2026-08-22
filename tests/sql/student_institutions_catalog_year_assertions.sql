\set ON_ERROR_STOP on

-- 1. Column shape: text, nullable, matching course_catalog.catalog_year /
--    programs.catalog_year / requirement_groups.catalog_year in type.
do $$
declare
  col_type text;
  col_nullable text;
begin
  select data_type, is_nullable into col_type, col_nullable
  from information_schema.columns
  where table_name = 'student_institutions' and column_name = 'catalog_year';

  if col_type is null then
    raise exception 'student_institutions.catalog_year does not exist';
  end if;
  if col_type <> 'text' then
    raise exception 'catalog_year type is %, expected text', col_type;
  end if;
  if col_nullable <> 'YES' then
    raise exception 'catalog_year is NOT NULL, expected nullable';
  end if;
end $$;

-- 2. Nullable in practice: a row with no catalog_year still inserts.
do $$ begin
  insert into student_institutions (id, student_id, institution_id, relationship)
  values ('80000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001',
          '90000000-0000-0000-0000-000000000001', 'transfer');
  if exists (
    select 1 from student_institutions
    where id = '80000000-0000-0000-0000-000000000001' and catalog_year is not null
  ) then
    raise exception 'catalog_year should default to null when omitted';
  end if;
end $$;

-- 3. Round-trips a real value in the documented format.
do $$ begin
  update student_institutions
  set catalog_year = '2026-2027'
  where id = '80000000-0000-0000-0000-000000000001';
  if (select catalog_year from student_institutions
      where id = '80000000-0000-0000-0000-000000000001') <> '2026-2027' then
    raise exception 'catalog_year did not round-trip';
  end if;
end $$;

-- 4. The pre-existing partial unique index (one 'home' row per student) still
--    enforces after the ALTER -- confirms the migration did not disturb it.
do $$ begin
  begin
    insert into student_institutions (student_id, institution_id, relationship, catalog_year)
    values ('10000000-0000-0000-0000-000000000001', '90000000-0000-0000-0000-000000000001',
            'home', '2027-2028');
    raise exception 'second home row for the same student was accepted';
  exception when unique_violation then null;
  end;
end $$;

-- 5. RLS still owner-scoped with the new column present: authenticated user
--    A sees only their own row (including its catalog_year), not student B's.
set role authenticated;
select set_config('request.jwt.claim.sub', '20000000-0000-0000-0000-000000000001', false);
do $$ begin
  if (select count(*) from student_institutions) <> 2 then
    raise exception 'student A should see exactly their own 2 rows, saw %',
      (select count(*) from student_institutions);
  end if;
  if exists (select 1 from student_institutions where student_id = '10000000-0000-0000-0000-000000000002') then
    raise exception 'student A can see student B''s row -- RLS leak';
  end if;
  if (select catalog_year from student_institutions where relationship = 'home') <> '2026-2027' then
    raise exception 'own catalog_year value not visible or wrong';
  end if;
end $$;
reset role;

-- 6. anon: no rows visible, INSERT rejected -- same posture as before this
--    migration (RLS policies do not enumerate columns).
set role anon;
do $$ begin
  if (select count(*) from student_institutions) <> 0 then
    raise exception 'anon should see 0 rows, saw %', (select count(*) from student_institutions);
  end if;
  begin
    insert into student_institutions (student_id, institution_id, relationship, catalog_year)
    values ('10000000-0000-0000-0000-000000000001', '90000000-0000-0000-0000-000000000001',
            'prior', '2020-2021');
    raise exception 'anon insert was accepted';
  exception when insufficient_privilege then null;
  end;
end $$;
reset role;
