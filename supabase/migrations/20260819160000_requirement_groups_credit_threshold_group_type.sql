-- Adds a 6th requirement_groups.group_type value, 'enumerated_credit_
-- threshold', for groups derived from Coursedog's
-- completeVariableCoursesAndVariableCredits condition (e.g. SMU CS-BS's
-- "Content Area 4, Physics") -- a rule shape distinct from
-- 'enumerated_all' ("every option required") even though the ingestion
-- script currently maps both to the same group_type. See
-- planning-docs/degree-planner-spec.md §8.4/§9's "still unresolved at the
-- schema level" note and the requirement-satisfaction build task that
-- surfaced this: the satisfaction engine had no structural signal to tell
-- a genuine "all required" enumerated_all group (e.g. Computer Science
-- Core) apart from a credit-accumulation group with the same group_type
-- (Content Area 4, Physics), and was working around it with a hardcoded
-- coursedog_rule_id allowlist -- this migration removes the need for
-- that.
--
-- Not applied. DDL only.
--
-- ============================================================================
-- VERIFICATION (2026-08-19, read-only against the live linked database, run
-- immediately before writing this file -- same pattern as
-- 20260818130000_smu_requirement_skeleton.sql and
-- 20260819150000_requirement_groups_rule_source.sql)
-- ============================================================================
--
-- 1. requirement_groups_group_type_check's exact current definition,
--    confirmed live via direct Postgres connection (supabase db dump's
--    dry-run login role, `select conname, pg_get_constraintdef(oid) from
--    pg_constraint where conrelid = 'public.requirement_groups'::regclass
--    and contype = 'c'`), not assumed from reading
--    20260818130000_smu_requirement_skeleton.sql's CREATE TABLE:
--
--      CHECK ((group_type = ANY (ARRAY['enumerated_all'::text,
--        'enumerated_at_least_n'::text, 'compound_all'::text,
--        'compound_any'::text, 'freeform'::text])))
--
--    Matches the CREATE TABLE definition exactly -- no drift. This
--    migration's ALTER targets exactly this constraint by name
--    (requirement_groups_group_type_check).
--
-- 2. Live row count and group_type distribution (secret-key client, all 23
--    rows -- matches the count 20260819150000 backfilled), confirming
--    scope before altering anything:
--
--      enumerated_all           12
--      enumerated_at_least_n     5
--      compound_all              2
--      compound_any              2
--      freeform                  2
--      -----------------------------
--      total                    23
--
--    None already use 'enumerated_credit_threshold' (impossible -- the
--    value doesn't exist in the constraint yet -- but confirms no row
--    needs an unexpected backfill beyond the single planned UPDATE below).
--
-- 3. The one row this value is for, confirmed live by coursedog_rule_id
--    (the stable identity, same lookup key 20260819150000 itself
--    documents as canonical) rather than by name or id:
--
--      id: cb393105-c316-49bd-88c8-5905b29515f0
--      coursedog_rule_id: T6z1BLsv
--      name: Content Area 4, Physics
--      group_type: enumerated_all   (pre-migration; changed to
--        'enumerated_credit_threshold' by the follow-up data UPDATE, NOT
--        by this migration -- this file is schema-only)
--      credit_hours_required: 7
--      rule_source: coursedog
--
--    Exactly 1 row matches -- no other group in the live tree needs this
--    reclassification (confirmed against the full completeness audit in
--    §8.4: Content Area 4, Physics is the only completeVariableCourses
--    AndVariableCredits-derived group in SMU CS-BS's 23-group tree).
--
-- 4. RLS / anon-grant posture re-confirmed live, not assumed from the
--    prior migration's verification, since posture checks in this family
--    are per-migration, not inherited on faith:
--
--    a. anon-key SELECT on requirement_groups succeeds (1 sample row
--       returned) -- requirement_groups_read_public is live and in force.
--    b. anon-key UPDATE is rejected: 42501 "permission denied for table
--       requirement_groups" (Postgres GRANT-level error). Confirms
--       20260818130000's `revoke ... from anon;` is still in force. This
--       migration only alters a CHECK constraint -- no policy or grant
--       change needed or made here.
--
-- ============================================================================

alter table requirement_groups
  drop constraint requirement_groups_group_type_check;

alter table requirement_groups
  add constraint requirement_groups_group_type_check
    check (group_type in (
      'enumerated_all', 'enumerated_at_least_n',
      'compound_all', 'compound_any', 'freeform',
      'enumerated_credit_threshold'
    ));

comment on column requirement_groups.group_type is
  'Maps 1:1 to the source rule''s Coursedog `condition` field: '
  'completedAllOf -> enumerated_all, completedAtLeastXOf -> '
  'enumerated_at_least_n, allOf -> compound_all, anyOf -> compound_any, '
  'freeformText -> freeform, completeVariableCoursesAndVariableCredits -> '
  'enumerated_credit_threshold. See the requirement-skeleton migration''s '
  'file header for what each means; enumerated_credit_threshold groups '
  'additionally carry a real minCredits value in credit_hours_required '
  'that the satisfaction engine sums matched courses'' credit_hours '
  'against, rather than requiring every option completed.';
