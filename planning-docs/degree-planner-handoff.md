# Degree Planner — Session Handoff

Generated 2026-08-19, from the tail end of a long working session. This file is meant to be pasted into a fresh Claude Code session with zero memory of that work — everything you need is below or in the spec it points to.

---

## a. Orientation

**Degree Planner** is a new feature sitting directly under **Course Discovery** in CareerOS. Course Discovery today answers "what courses build the skills my target role needs" — role-driven, no awareness of actual degree requirements. Degree Planner adds a requirement-driven layer underneath it: what does this student's major *actually* require to graduate, what's already satisfied by their transcript, and in what order can the rest be taken given prerequisites and a per-term credit-hour cap. The three layers (requirement skeleton, prereq-aware scheduling, role-driven electives) are meant to cooperate — Course Discovery itself doesn't change. First school being built against: **SMU Computer Science, B.S.** TAMU is a deliberate parallel/later track, not a blocker.

---

## b. Ground rules — not optional

- **Audit before code.** Always investigate read-only before proposing or making changes, especially anything touching the live database.
- **Never push.** Commits on the feature branch are fine; pushing is not, unless explicitly instructed.
- **Never apply a migration or run a `--write` data operation without explicit go-ahead** after reporting what it will do first.
- **If something unexpected turns up mid-task** — a bug, a scope mismatch, a blocker — **STOP and report.** Do not silently fix, work around, or proceed past it.
- **Live-verify assumptions against the actual database/API**, not documentation, prior sessions, or code comments. This project has repeatedly found reality diverging from assumptions — SMU's Coursedog `requisites` field turning out empty, `catalog_year` not existing where a prior task assumed it did, PostgREST's default 1000-row limit silently truncating an unpaginated query, an "unconditional" regex fix regressing a previously-correct case elsewhere in the catalog. Check the real thing.
- **`planning-docs/degree-planner-spec.md` is the persistent source of truth.** Read it first. Keep it updated as work progresses — that's how continuity survives across sessions. (See the state-drift note below — it's currently a bit behind reality, which is itself a live example of why this discipline matters.)
- **Feature branch discipline.** Everything stays on `smu-catalog-prereq-and-group-id` (or a clearly-named follow-on branch) off `dev`. Never commit directly to `dev`/`main`.

---

## c. What's done (verified against git log + live DB, not just the spec's prose)

Branch `smu-catalog-prereq-and-group-id`, 12 commits ahead of `dev` (`47f6083`..`09e0b21`), **not pushed**:

```
09e0b21 feat(students): convert Ethan Brooks fixture to SMU Computer Science
8f5c19a docs(degree-planner): §8.4 addendum on enumerated_all alternative-path ambiguity and Ethan Brooks decisions
b1adcca feat(students): add student_institutions.catalog_year (DDL only, not applied)
f4e8fbf fix(smu-catalog): handle completedAnyOf and completeVariableCoursesAndVariableCredits
a395ca0 chore(smu-catalog): re-fetch SMU catalog to backfill coursedog_group_id
4268d02 fix(smu-catalog): correct two split_description() bugs found in full-catalog live diffing
1716847 feat(course-discovery): add structured_prerequisite() parser for degree-planner scheduler
0f548c4 feat(smu-catalog): add fetch/import scripts for requirement-skeleton ingestion
7abb0e6 feat(smu-catalog): add requirement-skeleton schema (programs, requirement_groups)
e10b665 docs(degree-planner): resolve §8.3 open questions, add requirement-skeleton design addendum
59e34c4 feat(smu-catalog): capture Coursedog courseGroupId into course_catalog
6a3ad7a fix(smu-catalog): catch permission/approval phrasing in prerequisite split
```

**⚠️ State-drift note:** the spec (§6/§8) describes some of this as "not yet applied" or "pending" — that's now stale. Verified live via `supabase migration list`: **every migration through `20260819140000_student_institutions_catalog_year.sql` is applied to the linked database**, not just committed. Don't trust the spec's applied/not-applied language without re-checking; trust `supabase migration list` and a direct query.

The full data foundation is live and working:

- **Prerequisite data confirmed and cleaned.** `course_catalog.prerequisites` populated for both schools; SMU's is parsed out of course descriptions (`split_description()`, `data/catalog/fetch_smu_catalog.py` + `normalize_catalog.py`), not from Coursedog's own `requisites` field (confirmed empty on every record). Two real parsing bugs found and fixed via full-catalog live diffing (commit `4268d02`) — an abbreviation false-sentence-boundary bug and a single-sentence-duplication bug — plus an abbreviation-list regression caught and fixed within the same commit before it shipped.
- **SMU catalog backfilled.** All 3,249 SMU `course_catalog` rows carry `coursedog_group_id` (commit `a395ca0`, live-verified diff against a DB snapshot before writing).
- **SMU CS-BS requirement skeleton — live in production.** 4 new tables (`programs`, `requirement_groups`, `requirement_group_options`, `requirement_group_option_courses`, migration `20260818130000`), populated: 1 program row, **17 requirement_groups**, 58 options, 67 option-courses (65 resolved against `coursedog_group_id`, 2 flagged via `unresolved_course_ref`, not dropped). Two additional Coursedog rule conditions (`completedAnyOf`, `completeVariableCoursesAndVariableCredits`) found and mapped without schema changes (commit `f4e8fbf`) — that's what took the group count from 13 to the full 17.
- **`structured_prerequisite()` parser built** (commit `1716847`, `course_discovery/prerequisites.py`) — a richer AND/OR/grade-minimum/corequisite/restriction parser, added *alongside* the existing conservative `prerequisite_requirement()`, not replacing it.
- **`student_institutions.catalog_year` added and applied** (migration `20260819140000`, commit `b1adcca`) — `text null`, matches `course_catalog`/`programs`/`requirement_groups.catalog_year` in name/type/format. Chosen over `students.catalog_year` because the schema already supports multiple institution relationships per student.
- **One demo student converted for end-to-end testing: Ethan Brooks → SMU Computer Science, Sophomore** (commit `09e0b21`, production DB + local fixture both updated). Academic side only, and it's real: `students`, `student_institutions` (institution + `catalog_year='2026-2027'`), `academic_terms` (Fall 2025 + Spring 2026), and `course_records` (8 real SMU courses, 4 completed + 4 in-progress, touching 5 of the 17 requirement groups) are all live. **`career_profiles` narrative (career_goals, target_roles, interests, skills_technical, geographic_preference) is deliberately NOT rewritten** — still describes his old TAMU/Computer-Engineering profile. No replacement content has been drafted or approved. Don't invent it; it needs a real content-drafting pass. Same for the local fixture's `assignments`/`submissions`/`examTopicTags`/`career` block.

---

## d. What's not started

The actual feature logic doesn't exist yet: **requirement-satisfaction engine, scheduler, elective slotting, UI** (spec §6 steps 5-8). Everything done so far is data foundation — schema, ingestion, one testable demo student. No code reads `requirement_groups` to produce a gap list or a term-by-term plan yet.

Known open design questions the satisfaction engine will need to resolve (see spec §8.3/§8.4 for full reasoning):
- In-progress courses count as satisfied (decided).
- Corequisite = satisfied once enrolled, not just completed (decided).
- Join path is `course_records.course_code` (text) → `course_catalog.code` → `coursedog_group_id`, **not** `course_records.catalog_course_id` (that FK is 0% populated across all demo data). Works for SMU, structurally can't work for TAMU (no `coursedog_group_id` there).
- **Unresolved: whether some `enumerated_all` requirement groups actually encode "pick one of these alternative paths" rather than "all of these are required."** This is the subject of the next task below.

---

## e. Immediate next task — run this verbatim

```
AUDIT TASK — read-only. No commits, no writes.

GOAL
Determine whether SMU's raw Coursedog requisites payload contains any
signal distinguishing 'genuinely all required' enumerated_all groups from
'alternative paths listed together as if all required' — before the
requirement-satisfaction engine's design has to guess at this. Example:
CS-BS's 'Mathematics and Science' group lists MATH 1337+1338 (standard
Calc I+II) AND MATH 1340 (Consolidated Calculus, a one-course alternative
to the same material) as if all three were independently required — very
likely SMU's own payload encoding 'pick your path,' not a parser bug, but
unconfirmed.

STEPS
1. Pull the raw, unprocessed requisites JSON for CS-BS's 'Mathematics and
   Science' group directly from Coursedog (same live source
   fetch_smu_requirements.py reads from) — look for any field beyond
   value.condition/value.values[] that might carry this distinction.
2. Check whether this pattern is isolated to Math & Science or appears
   elsewhere in CS-BS's 17 groups ('Interdisciplinary Projects' is a
   second suspected case per the spec — check that one too, and scan the
   rest).
3. Check whether course_catalog or any other existing data source has a
   cross-listing/equivalency concept already (e.g. TAMU's CSCE 222/ECEN
   222-style cross-listings) that could be reused rather than needing new
   modeling.
4. If no distinguishing signal exists anywhere in the source data, report
   that clearly — it means this needs a manual per-group
   annotation/override, not cleverer parsing.

DELIVERABLE
- Raw payload for Math & Science and Interdisciplinary Projects, in full
- Whether a structural signal exists to auto-distinguish real requirements
  from listed-alternatives
- How many of the 17 groups are affected, if more than these 2
- One-line verdict: solvable via better parsing, or needs manual
  per-group annotation
```

*(Note for whoever picks this up: this exact audit was completed once already, near the end of the session this handoff was generated from. Its findings should already be reflected in `planning-docs/degree-planner-spec.md` §8.4 by the time you read this — check there first. If the spec doesn't yet reflect it, either the spec update didn't happen or something changed; re-run the audit rather than assume.)*

---

## f. Where to go for more depth

`planning-docs/degree-planner-spec.md` §8 has the full schema and decision history — §8.1-8.3 for the requirement-skeleton design (three group shapes, the revised schema, resolved open questions), §8.4 for satisfaction-engine scoping decisions made so far. Read it before starting anything nontrivial; this handoff is a summary, not a replacement.
---

## g. Phase 4C1 update (2026-08-20)

The explicit backend career-optimization preview is implemented at
`POST /api/v2/student/me/schedule/career-optimize`. The existing GET schedule
uses a shared provider-free academic reconstruction helper and remains wholly
model/cache independent. The POST accepts only optional `target_role` and
`force_refresh`, reconstructs all academic authority server-side, and returns
academic plus optimized schedules with ranking/failure provenance.

Caching is process-local (15-minute TTL, 128 entries), exact-fingerprint, and
OPTIMIZED-only. Identical in-flight requests share one ranking batch;
`force_refresh` bypasses completed cache reuse but still joins the same active
fingerprint computation.

---

## h. Phase 4C2 update (2026-08-20)

Ethan's approved Career Optimize inputs were narrowly reconciled in the local
fixture and production `career_profiles`: target roles now contain only
Software Engineering Intern, while technical skills contain Python basics,
technical writing, and Excel basics. Soft skills, source, confirmation time,
and all unrelated career fields were verified unchanged. His canonical live
profile resolves the single role and derives eight trusted local career needs
without a model call.

The frontend opt-in preview is implemented under Degree Schedule. The normal
mount path still calls only `GET /schedule`; `POST /schedule/career-optimize`
exists solely in the Career Optimization button handler. The academic schedule
remains visible through loading, skipped, fallback, and transport-error states.
Successful and partial results show requirement-grouped course deltas with only
validated backend explanations, plus a non-persisted academic/optimized term
toggle and a separate force-refresh action. No accept/save path exists.
