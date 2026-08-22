create extension if not exists pgcrypto;
create role authenticated;
create role anon;

create table institutions (
  id uuid primary key default gen_random_uuid(),
  name text not null
);

create table programs (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references institutions (id),
  coursedog_program_id text not null,
  program_group_id text not null,
  code text not null,
  name text not null,
  degree_designation text null,
  catalog_year text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (institution_id, coursedog_program_id)
);

create table requirement_groups (
  id uuid primary key default gen_random_uuid(),
  program_id uuid not null references programs (id),
  catalog_year text not null,
  coursedog_rule_id text not null,
  parent_group_id uuid null references requirement_groups (id),
  name text not null,
  group_type text not null,
  n_required int null,
  credit_hours_required int null,
  notes_html text null,
  requires_manual_definition boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (program_id, coursedog_rule_id),
  constraint requirement_groups_group_type_check
    check (group_type in (
      'enumerated_all', 'enumerated_at_least_n',
      'compound_all', 'compound_any', 'freeform'
    )),
  constraint requirement_groups_n_required_matches_type
    check (
      (group_type = 'enumerated_at_least_n' and n_required is not null)
      or (group_type != 'enumerated_at_least_n' and n_required is null)
    ),
  constraint requirement_groups_n_required_positive
    check (n_required is null or n_required > 0),
  constraint requirement_groups_credit_hours_non_negative
    check (credit_hours_required is null or credit_hours_required >= 0)
);

alter table programs enable row level security;
alter table requirement_groups enable row level security;

create policy programs_read_public
  on programs for select
  to anon, authenticated
  using (true);

create policy requirement_groups_read_public
  on requirement_groups for select
  to anon, authenticated
  using (true);

grant usage on schema public to authenticated, anon;
grant select on all tables in schema public to authenticated, anon;
revoke insert, update, delete, truncate on requirement_groups from anon;
