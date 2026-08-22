\set ON_ERROR_STOP on

-- 1. Column shape: text, NOT NULL, default 'coursedog'.
do $$
declare
  col_type text;
  col_nullable text;
  col_default text;
begin
  select data_type, is_nullable, column_default
  into col_type, col_nullable, col_default
  from information_schema.columns
  where table_name = 'requirement_groups' and column_name = 'rule_source';

  if col_type is null then
    raise exception 'requirement_groups.rule_source does not exist';
  end if;
  if col_type <> 'text' then
    raise exception 'rule_source type is %, expected text', col_type;
  end if;
  if col_nullable <> 'NO' then
    raise exception 'rule_source is nullable, expected NOT NULL';
  end if;
  if col_default is distinct from '''coursedog''::text' then
    raise exception 'rule_source default is %, expected ''coursedog''', col_default;
  end if;
end $$;

-- 2. Backfill behavior: a row inserted with no explicit rule_source (the
--    shape every one of the 17 pre-existing live rows will take when this
--    ALTER runs against them) defaults to 'coursedog', not null and not an
--    error.
do $$ begin
  insert into requirement_groups
    (id, program_id, catalog_year, coursedog_rule_id, name, group_type)
  values
    ('a0000000-0000-0000-0000-000000000001', '90000000-0000-0000-0000-000000000010',
     '2026-2027', 'JVDU4qJ2', 'Mathematics and Science', 'compound_all');

  if (select rule_source from requirement_groups
      where id = 'a0000000-0000-0000-0000-000000000001') <> 'coursedog' then
    raise exception 'pre-existing-shaped row did not default to ''coursedog''';
  end if;
end $$;

-- 3. A manually-synthesized child row round-trips rule_source = 'manual'.
do $$ begin
  insert into requirement_groups
    (id, program_id, catalog_year, coursedog_rule_id, parent_group_id, name,
     group_type, rule_source)
  values
    ('a0000000-0000-0000-0000-000000000002', '90000000-0000-0000-0000-000000000010',
     '2026-2027', 'JVDU4qJ2-calc-alt', 'a0000000-0000-0000-0000-000000000001',
     'Calculus Sequence', 'compound_any', 'manual');

  if (select rule_source from requirement_groups
      where id = 'a0000000-0000-0000-0000-000000000002') <> 'manual' then
    raise exception 'explicit ''manual'' value did not round-trip';
  end if;
end $$;

-- 4. The check constraint rejects any value outside ('coursedog', 'manual').
do $$ begin
  begin
    insert into requirement_groups
      (id, program_id, catalog_year, coursedog_rule_id, name, group_type, rule_source)
    values
      ('a0000000-0000-0000-0000-000000000003', '90000000-0000-0000-0000-000000000010',
       '2026-2027', 'bogus-rule', 'Bogus', 'freeform', 'llm-generated');
    raise exception 'invalid rule_source value was accepted';
  exception when check_violation then null;
  end;
end $$;

-- 5. Pre-existing constraints (group_type check, n_required-matches-type
--    check) still enforce after the ALTER -- confirms this migration didn't
--    disturb them.
do $$ begin
  begin
    insert into requirement_groups
      (id, program_id, catalog_year, coursedog_rule_id, name, group_type)
    values
      ('a0000000-0000-0000-0000-000000000004', '90000000-0000-0000-0000-000000000010',
       '2026-2027', 'bad-type', 'Bad', 'not_a_real_type');
    raise exception 'invalid group_type was accepted';
  exception when check_violation then null;
  end;
end $$;

-- 6. RLS unaffected: anon SELECT still succeeds and returns the new column;
--    anon INSERT is still rejected the same way as before this migration
--    (a GRANT-level permission-denied error, not an RLS policy rejection --
--    requirement_groups has no write policy at all, matching the reference-
--    table posture this table was modeled on).
set role anon;
do $$ begin
  if (select count(*) from requirement_groups) <> 2 then
    raise exception 'anon should see the 2 rows inserted above, saw %',
      (select count(*) from requirement_groups);
  end if;
  if (select rule_source from requirement_groups
      where id = 'a0000000-0000-0000-0000-000000000002') <> 'manual' then
    raise exception 'anon cannot read rule_source (new column not covered by existing policy)';
  end if;
end $$;
reset role;

set role anon;
do $$ begin
  begin
    insert into requirement_groups
      (program_id, catalog_year, coursedog_rule_id, name, group_type)
    values
      ('90000000-0000-0000-0000-000000000010', '2026-2027', 'anon-attempt', 'x', 'freeform');
    raise exception 'anon insert was accepted';
  exception when insufficient_privilege then null;
  end;
end $$;
reset role;
