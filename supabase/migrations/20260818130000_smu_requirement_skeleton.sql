-- SMU CS-BS requirement-skeleton ingestion: programs, requirement_groups,
-- requirement_group_options, requirement_group_option_courses.
--
-- Not applied. DDL only. Written from planning-docs/degree-planner-spec.md
-- §8.2 (revised) and §8.3 (both open items resolved this session against
-- live data).
--
-- Scope: SMU CS-BS's top-level "Requirements for the Major" group only
-- (Coursedog requirementLevel "programRequirements"). Specialization/track
-- subplans (requirementLevel "subplan") are out of scope -- see the build
-- prompt this migration accompanies.
--
-- ============================================================================
-- VERIFICATION (2026-08-18, read-only against the live linked database, run
-- immediately before finalizing this file -- same pattern as
-- 20260804155924_course_catalog.sql and
-- 20260817230000_course_catalog_coursedog_group_id.sql)
-- ============================================================================
--
-- 1. None of the 4 new tables already exist (secret-key client, each a
--    separate `select * limit 1`):
--
--      programs                            -> PGRST205 "Could not find the
--        table 'public.programs' in the schema cache" (hint suggested the
--        unrelated 'public.projects' -- confirms no name collision, not a
--        near-miss)
--      requirement_groups                  -> PGRST205, same shape, no hint
--      requirement_group_options           -> PGRST205, hint suggested
--        'public.student_institutions' (irrelevant, confirms no collision)
--      requirement_group_option_courses    -> PGRST205, hint suggested
--        'public.resume_reconciliation_items' (irrelevant, confirms no
--        collision)
--
--    All 4 raised identically to the "no such table" case
--    20260804155924_course_catalog.sql documented for course_catalog itself.
--
-- 2. institutions -- the FK target for programs.institution_id -- is valid
--    and holds exactly the 2 rows this migration's downstream import script
--    expects (secret-key SELECT id, name):
--
--      75d68331-91d2-47e8-9671-2a3b065955d0  Texas A&M University
--      6b180bbf-66d7-4aef-b8c6-2ae534c78e9a  Southern Methodist University
--
--    import_requirement_groups.py's resolve_institution() looks up "Southern
--    Methodist University" by exact name match -- confirmed present, and
--    confirmed unambiguous (exactly one row with that name).
--
-- 3. RLS / anon-grant posture this migration's policies below are modeled
--    on -- re-confirmed live against course_catalog and institutions rather
--    than assumed from reading the code:
--
--    a. anon-key SELECT on institutions succeeds (2 rows returned) --
--       institutions_read_public policy is live and in force.
--    b. anon-key SELECT on course_catalog succeeds (3 sample rows
--       returned) -- course_catalog_read_public policy is live and in
--       force, confirming the exact policy shape this migration's four new
--       policies (<table>_read_public, to anon+authenticated, using (true))
--       are copied from.
--    c. anon-key INSERT on course_catalog is rejected:
--       42501 "permission denied for table course_catalog" (Postgres
--       privilege error, not an RLS-silent-empty-result) -- confirms
--       20260801175516_revoke_anon_writes_on_reference_tables.sql's REVOKE
--       is still in force for course_catalog specifically.
--    d. anon-key INSERT on institutions is rejected the same way: 42501
--       "permission denied for table institutions".
--
--    Together, (c) and (d) confirm the anon-default-grant issue
--    20260801175516 fixed has NOT crept back in on the existing reference
--    tables this migration's tables are modeled after. This migration's own
--    `revoke insert, update, delete, truncate on <table> from anon;`
--    statements (§5 below) apply that same fix proactively to the 4 new
--    tables at creation time, rather than needing a follow-up revoke
--    migration the way course_catalog originally did.
--
-- ============================================================================

-- ============================================================================
-- DATA SHAPE BACKING THE DESIGN (confirmed live, this session, via
-- programs/search/$filters against southernmethodist_peoplesoft_direct,
-- program code "CS-BS", _id "CS-BS-2026-05-21" as of this fetch):
--
--   - requisites.requisitesSimple is an array of "group" objects, each with
--     requirementLevel "subplan" (tracks) or "programRequirements" (the one
--     major-requirements group this migration imports).
--   - The programRequirements-level "Requirements for the Major
--     (95-99 Credit Hours)" group has 7 rules, each one `condition`:
--       completedAllOf       -> all listed courses required
--                                (Mathematics and Science, Computer Science
--                                Core)
--       completedAtLeastXOf  -> choose N of the listed courses, N in a
--                                sibling `restriction` field
--                                (Engineering Leadership, restriction: 2)
--       freeformText         -> no structured course criteria at all; the
--                                entire constraint is prose in `notes`
--                                (Technical Electives, Advanced Major
--                                Electives)
--       allOf / anyOf        -> compound: a `subRules[]` array of further
--                                rule objects instead of a flat `value`
--                                (Lyle EDGE Curriculum; a lab-science-
--                                sequence choice)
--   - Enumerated rules' course references sit in value.values[], each entry
--     `{value: [coursedogGroupId, ...], logic: "and"|"or"}` -- an "and"
--     pair is a co-requisite bundle (e.g. lecture+lab) counted as one
--     option, not two alternatives.
--   - coursedog_group_id values here are the same 7-digit-string IDs
--     already flowing into course_catalog.coursedog_group_id
--     (20260817230000_course_catalog_coursedog_group_id.sql) -- confirmed
--     matching format ("0045691"-style).
--   - ~5% of a program's course references are expected not to resolve
--     against course_catalog.coursedog_group_id (inactive/renumbered
--     courses, per the prior full-catalog audit referenced in the spec)
--     -- hence coursedog_group_id is nullable here with a sibling
--     unresolved_course_ref, not a NOT NULL foreign key.
-- ============================================================================


-- ============================================================================
-- 1. programs
-- ============================================================================

create table programs (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references institutions (id),
  -- Coursedog's own program identity fields. _id embeds an effective-date
  -- suffix that changes when SMU republishes the program (e.g.
  -- "CS-BS-2026-05-21"); program_group_id is the stable identity across
  -- those republications (e.g. "CS-BS") -- confirmed both present and
  -- distinct on the live CS-BS record this session.
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

comment on table programs is
  'A specific published version of a degree program (e.g. SMU CS-BS as '
  'published 2026-05-21). One row per Coursedog program record actually '
  'imported, not a general program catalog -- v1 only imports SMU CS-BS. '
  'catalog_year is stored per-row rather than in a separate version table, '
  'matching course_catalog''s existing precedent (20260804155924).';

comment on column programs.coursedog_program_id is
  'Coursedog''s versioned _id, e.g. "CS-BS-2026-05-21". Changes when the '
  'program is republished; program_group_id is the stable key across that.';

comment on column programs.program_group_id is
  'Coursedog''s programGroupId, e.g. "CS-BS". Stable across catalog-year '
  'republications of the same program -- the fetch script resolves a '
  'program to import by (institution, code, status=Active) rather than by '
  'a hardcoded coursedog_program_id, so this is what a future re-import '
  'keys off of to detect "same program, new version" vs. "different '
  'program".';


-- ============================================================================
-- 2. requirement_groups
-- ============================================================================

create table requirement_groups (
  id uuid primary key default gen_random_uuid(),
  program_id uuid not null references programs (id),
  -- Per-row, not a separate version table -- same reasoning as
  -- course_catalog.catalog_year and programs.catalog_year above. Pins this
  -- row to one snapshot; a future re-scrape writes new rows under a new
  -- catalog_year rather than requiring a migration. No per-student
  -- catalog-year matching in v1 (see spec §8.3) -- the requirement-
  -- satisfaction engine, not yet built, matches every student against the
  -- one current snapshot.
  catalog_year text not null,
  -- The source rule/group's own `id` field (e.g. "AjzAZTn4"), for
  -- traceability and idempotent re-import.
  coursedog_rule_id text not null,
  -- Populated only for a subRule of a compound group (group_type
  -- 'compound_all'/'compound_any' on the parent row).
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
  -- n_required is Coursedog's `restriction` field and only means something
  -- for a "choose N of" rule; required exactly then, forbidden otherwise so
  -- a bug in the importer can't silently attach a stray N to the wrong
  -- group type.
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

comment on table requirement_groups is
  'One row per requirement rule under a program''s top-level major-'
  'requirements group (Coursedog requirementLevel "programRequirements"). '
  'A compound rule (allOf/anyOf) gets its own row with no options, plus '
  'one child row per subRule via parent_group_id -- see group_type.';

comment on column requirement_groups.group_type is
  'Maps 1:1 to the source rule''s Coursedog `condition` field: '
  'completedAllOf -> enumerated_all, completedAtLeastXOf -> '
  'enumerated_at_least_n, allOf -> compound_all, anyOf -> compound_any, '
  'freeformText -> freeform. See the file header for what each means.';

comment on column requirement_groups.n_required is
  'Coursedog''s `restriction` field: how many of the enumerated options '
  'must be completed. Only set when group_type = ''enumerated_at_least_n''.';

comment on column requirement_groups.notes_html is
  'The source rule''s `notes` field, verbatim (HTML). Captured whenever '
  'present, not only for freeform groups -- some enumerated groups carry '
  'qualifying prose alongside an already-enumerated option list (e.g. '
  '"one 3000-level or higher MATH or STAT course").';

comment on column requirement_groups.requires_manual_definition is
  'True when group_type = ''freeform'': there is no structured course '
  'criteria to check a transcript against, only prose in notes_html (e.g. '
  '"9 credit hours of CS courses at the 3000 level or above as approved '
  'by adviser"). The requirement-satisfaction engine (not yet built) '
  'should surface these to the student as "ask your adviser" rather than '
  'silently marking them satisfied or unsatisfied.';


-- ============================================================================
-- 3. requirement_group_options
-- ============================================================================

create table requirement_group_options (
  id uuid primary key default gen_random_uuid(),
  requirement_group_id uuid not null references requirement_groups (id) on delete cascade,
  -- Position in the source value.values[] array. Preserves declared order;
  -- not otherwise meaningful (no ordering semantics in the source data).
  option_index int not null,
  logic text not null,
  unique (requirement_group_id, option_index),
  constraint requirement_group_options_logic_check
    check (logic in ('and', 'or'))
);

comment on table requirement_group_options is
  'Only populated for requirement_groups rows with group_type '
  '''enumerated_all'' or ''enumerated_at_least_n''. One row per entry in '
  'the source value.values[] array.';

comment on column requirement_group_options.logic is
  'Mirrors that value entry''s own `logic` field. ''and'' means every '
  'course under this option_index (see requirement_group_option_courses) '
  'must be completed together to satisfy this one option -- e.g. a '
  'lecture+lab pairing -- not that any single one of them alone suffices.';


-- ============================================================================
-- 4. requirement_group_option_courses
-- ============================================================================

create table requirement_group_option_courses (
  id uuid primary key default gen_random_uuid(),
  requirement_group_option_id uuid not null references requirement_group_options (id) on delete cascade,
  -- Joins to course_catalog.coursedog_group_id (application-level join, not
  -- a foreign key -- see below). Null when the source ID didn't resolve.
  coursedog_group_id text null,
  -- Populated only when coursedog_group_id above is null: the raw,
  -- unresolved source ID, so the gap is visible in the data rather than a
  -- silently dropped row. Per spec §8.3's already-decided "unresolved
  -- course IDs" item: ingestion flags and continues, does not fail the
  -- whole import.
  unresolved_course_ref text null,
  constraint requirement_group_option_courses_exactly_one_ref
    check (
      (coursedog_group_id is not null and unresolved_course_ref is null)
      or (coursedog_group_id is null and unresolved_course_ref is not null)
    )
);

comment on table requirement_group_option_courses is
  'One row per course ID inside one requirement_group_options entry. No '
  'foreign key to course_catalog: coursedog_group_id is deliberately an '
  'application-level join key, the same way course_catalog itself carries '
  'coursedog_group_id with no reverse constraint -- roughly 5% of a '
  'program''s course references are expected not to resolve (inactive or '
  'renumbered courses per the prior full-catalog audit), and a hard FK '
  'would fail the whole import on those instead of the intended "flag and '
  'continue" behavior.';


-- ============================================================================
-- 5. Row level security
-- ============================================================================

-- Same posture as course_catalog / institutions / grade_point_map: RLS
-- enabled, one permissive SELECT policy for anon + authenticated, no write
-- policy for any role (PostgreSQL default-denies INSERT/UPDATE/DELETE with
-- no permissive policy). Writes happen only through the import script
-- running under the service/secret key, which bypasses RLS. Anon read is
-- intentional and matches course_catalog: this is published SMU catalog
-- data, not student data -- there is no student_id column anywhere in this
-- migration.
--
-- UNVERIFIED against the live database this session (no credentials
-- available) -- unlike 20260804155924_course_catalog.sql, which confirmed
-- this exact policy shape live before writing it. Re-confirm the
-- anon-write-grant situation (20260801175516_revoke_anon_writes_on_reference_tables.sql)
-- still holds for newly created tables before relying on the revoke below
-- being redundant vs. necessary.

alter table programs enable row level security;
alter table requirement_groups enable row level security;
alter table requirement_group_options enable row level security;
alter table requirement_group_option_courses enable row level security;

create policy programs_read_public
  on programs for select
  to anon, authenticated
  using (true);

create policy requirement_groups_read_public
  on requirement_groups for select
  to anon, authenticated
  using (true);

create policy requirement_group_options_read_public
  on requirement_group_options for select
  to anon, authenticated
  using (true);

create policy requirement_group_option_courses_read_public
  on requirement_group_option_courses for select
  to anon, authenticated
  using (true);

revoke insert, update, delete, truncate on programs from anon;
revoke insert, update, delete, truncate on requirement_groups from anon;
revoke insert, update, delete, truncate on requirement_group_options from anon;
revoke insert, update, delete, truncate on requirement_group_option_courses from anon;


-- ============================================================================
-- 6. Indexes
-- ============================================================================

-- Sizing note: one program (SMU CS-BS) imports on the order of a dozen
-- requirement_groups rows and well under a hundred option/course rows
-- total. These indexes declare the access pattern correctly; none of them
-- matter for performance at this size.

create index requirement_groups_program_id_idx
  on requirement_groups (program_id);

create index requirement_groups_parent_group_id_idx
  on requirement_groups (parent_group_id)
  where parent_group_id is not null;

create index requirement_group_options_group_id_idx
  on requirement_group_options (requirement_group_id);

create index requirement_group_option_courses_option_id_idx
  on requirement_group_option_courses (requirement_group_option_id);

-- Lookup path the requirement-satisfaction engine (not yet built) will
-- need: "which requirement groups does completing course X count toward".
create index requirement_group_option_courses_coursedog_group_id_idx
  on requirement_group_option_courses (coursedog_group_id)
  where coursedog_group_id is not null;
