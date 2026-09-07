-- Backfills TAMU academic_term_dates for Fall 2025 and Spring 2026.
--
-- Additive to 20260811120000_academic_term_dates.sql, which seeded only the
-- 2026-2027 academic year and said so explicitly: "NOT SEEDED: Fall 2025 and
-- Spring 2026, which two live academic_terms rows reference. They predate this
-- calendar PDF and are outside the 2026-2027 scope."
--
-- WHY THESE TWO TERMS NEED DATES NOW
-- ============================================================================
-- Those two academic_terms rows carry a student's first-year coursework but
-- have no (institution_id, year, season) match in academic_term_dates, so
-- build_terms_view emits them with start_date/end_date = null. The year-view
-- Course Discovery cards run that through termStatus() (frontend
-- termPlanning.mjs): no dates -> 'unknown' -> semesterState() collapses
-- 'unknown' to 'future' -> the "future" branch renders `courses: []` and never
-- reads course_records for that term. Result: a first-year term the student
-- has completed coursework in shows "No courses confirmed yet." / "Not
-- scheduled", with the coursework only reachable through the separate
-- requirement-decision path. Seeding the dates lets both terms resolve to
-- 'past', so the term cards read course_records like every other past term.
--
-- Upcoming-term detection is unaffected: it only ever looks forward from
-- today, and both of these terms ended well in the past.
--
-- SOURCE
-- ============================================================================
-- Texas A&M University Office of the Registrar official academic calendars:
--   https://registrar.tamu.edu/academic-calendar/fall-2025.html
--   https://registrar.tamu.edu/academic-calendar/spring-2026.html
-- Read live 2026-09-02, hence source_last_checked. source = 'registrar_published',
-- matching the 2026-2027 rows transcribed from TAMU's own published calendar.
--
-- DATE CONVENTION -- identical to 20260811120000's, which is consistent across
-- all four of its seeded terms:
--   start_date = first day of classes
--     (academic_term_dates.start_date column comment: "First day of classes.
--      Chosen over the registration-opens or move-in date because 'has the
--      term started?' is what the upcoming-term detection asks.")
--   end_date = last day of final examinations, NOT the last day of classes
--     (column comment: "Last day of final examinations, not the last day of
--      classes. The term is not over while exams are still being written, and
--      grades ... do not exist until after them.")
--
-- VALUES BEHIND EACH ROW (from the registrar calendars above):
--
--   Fall 2025
--     First day of classes ................ August 25, 2025    -> start 2025-08-25
--     Last day of classes ................. December 8, 2025
--     Final examinations end .............. December 16, 2025  -> end   2025-12-16
--
--   Spring 2026
--     First day of classes ................ January 12, 2026   -> start 2026-01-12
--     Last day of classes ................. April 28, 2026
--     Final examinations end .............. May 5, 2026        -> end   2026-05-05
--
-- year is the CALENDAR year of the term (2025 for Fall 2025, 2026 for Spring
-- 2026), matching academic_terms.year and terms.parse_term_label -- the same
-- key the 2026-2027 rows use (Fall 2026 -> 2026, Spring 2027 -> 2027).
--
-- No ON CONFLICT clause, matching 20260811120000's plain insert: these
-- (Texas A&M University, 2025, 'Fall') and (..., 2026, 'Spring') rows do not
-- exist -- the unique (institution_id, year, season) constraint is the guard
-- if that assumption is ever wrong.

insert into academic_term_dates
  (institution_id, year, season, label, start_date, end_date, source, source_last_checked)
select
  institutions.id, v.year, v.season, v.label, v.start_date, v.end_date,
  'registrar_published', date '2026-09-02'
from institutions
cross join (values
  (2025, 'Fall',   'Fall 2025',   date '2025-08-25', date '2025-12-16'),
  (2026, 'Spring', 'Spring 2026', date '2026-01-12', date '2026-05-05')
) as v(year, season, label, start_date, end_date)
where institutions.name = 'Texas A&M University';
