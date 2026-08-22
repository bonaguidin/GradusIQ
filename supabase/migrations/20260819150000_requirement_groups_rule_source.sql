-- Adds requirement_groups.rule_source, distinguishing rows imported
-- verbatim from a real Coursedog rule ('coursedog', the default -- covers
-- all 11 pre-existing top-level/leaf rows plus the "Mathematics and
-- Science" parent row itself, which keeps its real coursedog_rule_id
-- "JVDU4qJ2") from rows this project synthesizes by hand where Coursedog's
-- own rule structure doesn't carry the distinction needed (e.g. the
-- upcoming Calculus Sequence / Calculus I & II / Consolidated Calculus /
-- Linear Algebra / Discrete Computational Structures / Statistical Methods
-- split -- see planning-docs/degree-planner-spec.md §8.4).
--
-- Not applied. DDL only.
--
-- ============================================================================
-- VERIFICATION (2026-08-19, read-only against the live linked database, run
-- immediately before writing this file -- same pattern as
-- 20260804155924_course_catalog.sql, 20260817230000_course_catalog_
-- coursedog_group_id.sql, 20260818130000_smu_requirement_skeleton.sql, and
-- 20260819140000_student_institutions_catalog_year.sql)
-- ============================================================================
--
-- 1. requirement_groups.rule_source does not already exist:
--      secret-key `select rule_source from requirement_groups limit 1`
--      -> 42703 "column requirement_groups.rule_source does not exist".
--
-- 2. Backfill-safe default -- confirmed against the real row count, not
--    assumed: requirement_groups currently holds exactly 17 rows (secret-
--    key `select id from requirement_groups`, counted). All 17 are
--    genuine Coursedog-sourced rows (verbatim rule/subRule imports) --
--    none need an explicit UPDATE. `default 'coursedog'` on the ALTER
--    backfills all 17 automatically; no separate UPDATE statement is
--    needed or included.
--
-- 3. RLS posture -- checked live for THIS table specifically, not assumed
--    from the student_institutions precedent, because requirement_groups
--    is public reference data (published SMU catalog data), not owner-
--    scoped student data -- its posture is genuinely different from that
--    migration's:
--
--    a. anon-key SELECT on requirement_groups succeeds (1 sample row
--       returned) -- requirement_groups_read_public (20260818130000) is
--       live and in force, a permissive `for select ... using (true)`
--       policy. Postgres RLS policies do not enumerate columns, so the
--       new rule_source column is automatically covered by this existing
--       policy once added -- no policy change needed or made here.
--    b. anon-key INSERT is rejected: 42501 "permission denied for table
--       requirement_groups" (Postgres GRANT-level error, same failure
--       mode as course_catalog's -- NOT an RLS-policy rejection like
--       student_institutions'). Confirms 20260818130000's
--       `revoke insert, update, delete, truncate on requirement_groups
--       from anon;` is still in force. This migration adds a column, not
--       a policy or grant -- that revoke needs no change and none is made.
--
-- ============================================================================

alter table requirement_groups
  add column rule_source text not null default 'coursedog'
  constraint requirement_groups_rule_source_check
    check (rule_source in ('coursedog', 'manual'));

comment on column requirement_groups.rule_source is
  '''coursedog'' (default): row is a verbatim import of one real Coursedog '
  'rule or subRule, keyed by a real coursedog_rule_id. ''manual'': row was '
  'synthesized by this project to correct a modeling gap Coursedog''s own '
  'payload didn''t structurally distinguish (e.g. splitting one flat '
  '''all required'' rule into true alternative sub-paths) -- its '
  'coursedog_rule_id is a synthetic, traceable-but-non-native value, not a '
  'real Coursedog id. See planning-docs/degree-planner-spec.md §8.4.';
