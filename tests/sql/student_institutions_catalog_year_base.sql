create extension if not exists pgcrypto;
create schema auth;
create role authenticated;
create role anon;

create function auth.uid() returns uuid
language sql stable
as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;

create table institutions (
  id uuid primary key default gen_random_uuid(),
  name text not null
);

create table students (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid not null unique,
  name text not null
);

create table student_institutions (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students(id),
  institution_id uuid not null references institutions(id),
  relationship text not null check (relationship in ('home', 'transfer', 'dual_enrollment', 'prior')),
  created_at timestamptz not null default now()
);

create unique index student_institutions_one_home_per_student
  on student_institutions (student_id)
  where relationship = 'home';

alter table students enable row level security;
alter table student_institutions enable row level security;

create policy students_owner_all
  on students for all
  to authenticated
  using (auth.uid() = auth_user_id)
  with check (auth.uid() = auth_user_id);

create policy student_institutions_owner_all
  on student_institutions for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = student_institutions.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = student_institutions.student_id
        and students.auth_user_id = auth.uid()
    )
  );

grant usage on schema public, auth to authenticated, anon;
grant select, insert, update, delete on all tables in schema public to authenticated, anon;
