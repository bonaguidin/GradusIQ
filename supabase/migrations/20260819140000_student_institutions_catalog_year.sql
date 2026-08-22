-- Adds student_institutions.catalog_year, the field the requirement-
-- satisfaction engine will use to pick which requirement_groups snapshot
-- governs a given student's institution relationship.
--
-- Not applied. DDL only. No backfill, no application code change --
-- populating this column for real students is separate, later work (the
-- entering-term derivation via academic_terms noted in
-- planning-docs/degree-planner-spec.md §8.3 is still not built).
--
-- ============================================================================
-- VERIFICATION (2026-08-19, read-only against the live linked database, run
-- immediately before writing this file -- same pattern as
-- 20260804155924_course_catalog.sql, 20260817230000_course_catalog_
-- coursedog_group_id.sql, and 20260818130000_smu_requirement_skeleton.sql)
-- ============================================================================
--
-- 1. student_institutions.catalog_year does not already exist:
--      secret-key `select catalog_year from student_institutions limit 1`
--      -> 42703 "column student_institutions.catalog_year does not exist".
--
-- 2. RLS posture -- checked live for THIS table specifically, not assumed
--    from the course_catalog/reference-table precedent, because
--    student_institutions is student data, not public reference data, and
--    its posture is genuinely different:
--
--    a. anon-key SELECT on student_institutions returns 0 rows (silent
--       RLS filtering, not a grant-level error) -- there is no public-read
--       policy on this table at all, unlike course_catalog's
--       course_catalog_read_public. Confirmed against real data:
--       secret-key (service role, bypasses RLS) SELECT count on the same
--       table is 27.
--    b. anon-key INSERT is rejected: 42501 "new row violates row-level
--       security policy for table student_institutions" -- a DIFFERENT
--       failure mode than course_catalog's INSERT rejection (which is
--       42501 "permission denied for table course_catalog", a Postgres
--       GRANT-level error). This table was deliberately left OUT of
--       20260801175516_revoke_anon_writes_on_reference_tables.sql's REVOKE
--       ("the eight student tables keep their grants; they are protected
--       by owner-scoped RLS policies ... rather than by grant removal") --
--       anon still holds the raw INSERT grant here, and it is
--       student_institutions_owner_all's `with check` clause (not a
--       REVOKE) doing the rejecting.
--
--    Net result for this migration: RLS is enabled on student_institutions
--    with exactly one policy, student_institutions_owner_all (`for all`,
--    to authenticated, scoped via `exists (select 1 from students where
--    students.id = student_institutions.student_id and
--    students.auth_user_id = auth.uid())` on both USING and WITH CHECK --
--    20260728000103_institution_grading_schema.sql). Postgres RLS policies
--    do not enumerate columns, so a new column is automatically covered by
--    this existing policy -- confirmed live behaviorally above, not just
--    read from the migration source. No policy change is needed or made
--    here.
--
-- ============================================================================
-- WHY THIS COLUMN, AND WHY ON student_institutions RATHER THAN students
-- ============================================================================
--
-- catalog_year answers "which version of THIS institution's degree
-- requirements governs this student" -- a property of one specific
-- institution relationship, not the student globally. student_institutions
-- already models more than one relationship per student
-- (relationship in ('home', 'transfer', 'dual_enrollment', 'prior'), with a
-- PARTIAL unique index enforcing only one 'home' row, not a global
-- one-row-per-student constraint) -- a transfer or dual-enrollment student
-- could legitimately need two different catalog_year values, one per
-- institution relationship. students has no way to represent that; this
-- table does, structurally, today. See planning-docs/degree-planner-spec.md
-- §8.4 for the full resolution.
--
-- ============================================================================
-- WHY text, WHY 'YYYY-YYYY', WHY NOT AN FK
-- ============================================================================
--
-- Matches course_catalog.catalog_year and programs.catalog_year /
-- requirement_groups.catalog_year exactly, in name, type, and format --
-- same precedent those three already share (course_catalog: §3.1 /
-- 20260804155924; programs & requirement_groups: §8.2 / 20260818130000).
--
-- Deliberately a plain validated string, not a foreign key to any versioned
-- table. Same reasoning 20260812143000_profile_completion_field_formats.sql
-- already established for students.expected_graduation: an FK to a seeded,
-- date-range-limited table (there, academic_term_dates, seeded 2026-2027
-- only) cannot represent an answer years outside that seeded window --
-- exactly the shape a catalog_year for a student admitted in a past or
-- future year would need. A validated string can.
--
-- No CHECK constraint is added on the format here. course_catalog.
-- catalog_year and programs/requirement_groups.catalog_year carry none
-- either (all three are `text not null` with no format regex) -- adding one
-- only on this table would be a new, unprecedented restriction on a field
-- this migration otherwise mirrors exactly. Revisit only if all four
-- catalog_year columns are constrained together, not this one alone.
--
-- ============================================================================

alter table student_institutions
  add column catalog_year text null;

comment on column student_institutions.catalog_year is
  'Which catalog year''s degree requirements govern this institution '
  'relationship, e.g. "2026-2027" -- matches course_catalog.catalog_year / '
  'programs.catalog_year / requirement_groups.catalog_year in format. '
  'Null until populated: no backfill or write path exists yet (see '
  'planning-docs/degree-planner-spec.md §8.3/§8.4 for the entering-term '
  'derivation this is meant to eventually support). Lives here rather than '
  'on students because a transfer or dual-enrollment student can have more '
  'than one institution relationship, each potentially needing its own '
  'catalog year.';
