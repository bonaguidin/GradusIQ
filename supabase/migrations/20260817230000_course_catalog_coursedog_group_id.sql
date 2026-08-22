-- Adds course_catalog.coursedog_group_id, a nullable passthrough of
-- Coursedog's internal course-group ID for SMU rows.
--
-- Not applied. DDL only. No import script change beyond capturing the
-- already-fetched value; no ID->course-code join logic yet -- that is a
-- separate, later change.
--
-- ============================================================================
-- WHY THIS COLUMN EXISTS
-- ============================================================================
--
-- SMU's degree-requirements payload (the Coursedog "cm" programs/search
-- endpoint, catalog.smu.edu/programs/CS-BS/requirements-*) references its
-- required courses by an internal ID like "0045691", not by course code.
-- The SMU requirement-ID resolution audit confirmed that ID is
-- `courseGroupId` on the courses/search endpoint's raw response -- present
-- on every record `fetch_smu_catalog.py` already fetches, byte-for-byte
-- identical to the requirements payload's course references (confirmed on
-- 69 of 73 live CS-BS requirement IDs; the remaining 4 fell outside the
-- fetch script's active-status filter, a residual gap unrelated to the ID
-- scheme itself).
--
-- Storing it here is what lets the requirement-skeleton ingestion (planned,
-- not built in this change) join a program's required-course IDs straight
-- against course_catalog instead of re-deriving or hand-mapping them.
--
-- ============================================================================
-- WHY NULLABLE, NO CONSTRAINT
-- ============================================================================
--
-- TAMU's catalog comes from CourseLeaf HTML, not Coursedog -- it has no
-- courseGroupId at all, and every TAMU row will carry this column as null
-- indefinitely. That is expected, not a data-quality gap: this column is an
-- SMU/Coursedog-specific passthrough, not a general course identifier. No
-- uniqueness constraint is added either -- the ID->code join is future work
-- for the next change, and adding a constraint ahead of that join being
-- written would be speculative.
--
-- ============================================================================
-- RLS: NO POLICY CHANGE NEEDED
-- ============================================================================
--
-- course_catalog's RLS is table-level (course_catalog_read_public, added in
-- 20260804155924_course_catalog.sql: one permissive SELECT policy for anon +
-- authenticated, USING (true)), not column-level. Postgres RLS policies do
-- not enumerate columns, so a new column is covered by the existing policy
-- automatically -- exactly how catalog_course_id was added to course_records
-- in that same migration with no companion policy change. No new policy is
-- added here for the same reason.
--
-- Writes still happen only through the import script running under the
-- secret key (service role, bypasses RLS), matching every other column on
-- this table -- see the REVOKE in 20260804155924_course_catalog.sql, which
-- already covers this column since it targets the whole table.
--
-- ============================================================================

alter table course_catalog
  add column coursedog_group_id text null;

comment on column course_catalog.coursedog_group_id is
  'Coursedog''s internal course-group ID (e.g. "0045691"), passed through '
  'unchanged from the courses/search Coursedog endpoint. SMU only -- always '
  'null for TAMU, which is CourseLeaf-sourced and has no Coursedog ID at '
  'all. Exists so the SMU degree-requirements payload (which references '
  'required courses by this same ID, not by course code) can eventually be '
  'joined against this table; that join is not implemented yet.';
