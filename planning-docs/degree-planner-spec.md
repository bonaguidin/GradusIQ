# Degree Planner — Pre-Build Specification

**Status:** DRAFT — awaiting Deepak's review before any build prompt is written.
**Feature working name:** Degree Planner (sits directly under Course Discovery)
**Active implementation branch:** `smu-catalog-prereq-and-group-id` (commits `6a3ad7a` through `1716847`), not yet merged or pushed.

---

## 1. What this feature actually is

Course Discovery today answers "what courses build the skills my target role needs" — role-driven, GAP-sourced, no awareness of degree requirements or scheduling constraints.

This feature adds a second, orthogonal layer underneath it:

- **Requirement skeleton** (new): what does this student's major actually require to graduate, and what's already satisfied by their transcript
- **Prerequisite-aware scheduling** (new): given what's left to satisfy, in what order *can* it be taken, and where does it fit against a per-term credit-hour load
- **Role-driven electives** (existing, reused): wherever the skeleton has open elective room, prefer GAP-recommended courses that also build target-role skills

The three layers are meant to cooperate, not run as separate systems. Course Discovery doesn't change — this feature wraps around it.

---

## 2. Confirmed scope decisions (from planning conversation — do not re-litigate)

| Decision | Answer |
|---|---|
| Planner type | Requirement-driven (real degree-completion plan), not role-driven-only |
| First school to build against | **SMU Computer Science, B.S.** — confirmed structured requirements data exists, matches existing Coursedog integration |
| TAMU | Parallel track, not a blocker — see §5 |
| Course-load constraint | Must respect prereqs AND a per-term credit-hour cap when placing recommended courses |
| Scheduling logic | Deterministic (topological sort + bin-packing), **not LLM-driven** — same rationale as the FIT/SHIFT grounding fix: a hallucinated prereq ordering is a worse failure mode than a hallucinated skill match |

---

## 3. Data sources — confirmed status

### 3.1 SMU degree requirements (confirmed live, this session)
- Source: `catalog.smu.edu/programs/CS-BS/requirements-*` — Coursedog-backed, same vendor as existing SMU course-catalog integration
- Shape: named requirement buckets (Lyle EDGE Curriculum, Mathematics and Science, Computer Science Core — 33 Credit Hours, Technical Electives — 9 Credit Hours, Engineering Leadership — 6 Credit Hours, Advanced Major Electives — 3-5 Credit Hours), each listing required or "choose N of" course groups
- **Resolved:** requirement groups reference courses via `courseGroupId` (e.g. `0045691`), which is present in every record the existing `courses/search` Coursedog endpoint already returns — it's just absent from `fetch_smu_catalog.py`'s `COLUMNS` list today and discarded, not missing from the source. Confirmed exact match against the requirements endpoint's course-reference IDs on 69 of 73 live CS-BS requirement references (94.5%); the remaining 4 are likely inactive/renumbered course records outside the script's current active-status filter — a minor residual gap, not a scheme mismatch. No new endpoint or auth needed — same `programs/search/$filters` and `courses/search/$filters` Coursedog "cm" surfaces, same unauthenticated Referer/Origin headers already in use.

### 3.2 TAMU degree requirements (confirmed live, this session)
- Source: `catalog.tamu.edu/undergraduate/.../bs/` — CourseLeaf platform (not Coursedog, not Acalog/DIGARC as initially assumed)
- Shape: server-rendered `<table class="sc_plangrid">` — semester-by-semester course codes, titles, credit hours, no separate API
- **Not yet built:** no ingestion exists for this today. Predictable URL pattern per program (`/undergraduate/<college>/<dept>/<program-slug>/`), plain scrape, no auth needed.

### 3.3 Prerequisite data (confirmed live, this session — this was the main open question)
- **Already exists, already populated, already stored, currently unused by any feature:**
  `course_catalog.prerequisites` (text, nullable), populated for both TAMU and SMU courses today.
- **TAMU origin:** CourseLeaf scrape (`data/catalog/scrape_approved_subjects.py` + `normalize_catalog.py`) — pulled from course description text, not the robots.txt-disallowed `/search/` path. Confirmed via live query against 5 CSCE courses (221, 312, 313, 314, 315) — all populated with real prerequisite chains.
- **SMU origin:** Coursedog's own structured `requisites` field is confirmed **empty on every sampled record** — a dead end. SMU's prereq text is instead parsed out of the course description blob via sentence-splitting (`split_description()`), matching sentences like "Prerequisite:", "Corequisite:", "Restricted to...".
- **Format (both schools):** free-text prose, human-readable course codes (e.g. "CSCE 221", "CEE 2321"), corequisite phrasing mixed into the same field rather than a separate column. Example:
  > `CSCE 221`: "Prerequisites: Grade C or better in CSCE 120 or CSCE 121; grade of C or better in CSCE 222/ECEN 222 or ECEN 222/CSCE 222, or concurrent enrollment."

  This single example contains a nested OR inside an AND, plus a concurrent-enrollment (corequisite) exception — representative of the real complexity, not a worst case.

### 3.4 Coverage breadth — checked, mixed result

Full-catalog audit (not just the 5 CSCE courses):

| Scope | Total | Populated | % Populated |
|---|---|---|---|
| SMU full catalog | 3,249 | 1,598 | 49.2% |
| TAMU CSCE only | 71 | 66 | 93.0% |
| TAMU full catalog | 2,565 | 2,312 | 90.1% |

**TAMU is solid.** 90% populated overall, 95%+ at the 300/400 level — the intro-course-gaps-are-expected pattern holds throughout.

**SMU's upper-level null rate is mostly genuine, confirmed via live spot-check.** Cross-referenced 10 null-prerequisite upper-level courses directly against SMU's live Coursedog feed (the same endpoint `fetch_smu_catalog.py` already calls) — stored `description` text matched the live source verbatim in every case, and `requisites` is empty at the source itself, not just downstream. Full breakdown across all 989 null upper-level rows:

| Bucket | Rate | What it means |
|---|---|---|
| Scraper gap | 0% | None found — fetch script isn't dropping anything the source has |
| Parser gap | ~4.9% (48 rows) | `split_description()`'s regex misses permission/approval phrasing not anchored to its trigger words ("prerequisite/corequisite/restricted to..."). Concentrated almost entirely in independent-study/special-topics course templates (CS 41xx-49xx, ARHS 4302, ENGR 3390/4390-family) — a small, repeated pattern, not scattered noise. |
| Genuine gap | ~95.1% (941 rows) | Upper-level humanities/social-science electives (Art History, World Languages, Political Science, History, Anthropology, Music) that legitimately carry no prerequisite in SMU's own catalog. STEM departments have very few nulls outside the one parser-gap template above. |

This removes the main risk to SMU-first sequencing (§5) — the null rate isn't hiding missing scraper data.

- **SMU internal-ID → course-code mapping** for the degree-requirements endpoint (§3.1 open gap above) — still unconfirmed.
- **Term-offering pattern** (fall-only / spring-only / alternating-year courses) — not investigated at all this round. A required course scheduled into a term it doesn't run in would silently produce a wrong plan.

---

## 4. The core engineering problem — prerequisite parsing

This is now the long pole, not data acquisition. `prerequisites` is unstructured prose with real logical complexity:

- **AND / OR nesting**: "Grade C or better in CSCE 120 or CSCE 121; grade of C or better in CSCE 222/ECEN 222..."
- **Cross-listed courses**: "CSCE 222/ECEN 222 or ECEN 222/CSCE 222" — same course, two department codes, redundantly listed both orders
- **Concurrent enrollment / corequisites** embedded in the same sentence, distinguished only by phrasing ("or concurrent enrollment") rather than a separate field
- **Grade minimums** ("Grade of C or better") — not currently modeled anywhere; the planner needs to at least be aware a grade floor exists, even if it doesn't enforce it in v1

**Recommendation:** treat this as its own parsing/normalization pass, run once per course record (not per-student, per-request) and cached — same "never call live per request" architecture principle already established for job-posting data in the backlog. Output should be a structured intermediate form (e.g. `{requires_all: [...], requires_any: [...], coreq_allowed: [...], grade_min: "C"}`) that the scheduler consumes, rather than re-parsing prose at scheduling time.

**Confirmed at full-catalog scale (not just CSCE):**
- **Field-overloading.** Both schools store non-prerequisite content in the same `prerequisites` column: SMU has ~20 rows that are pure program/major restrictions with no prereq logic at all ("Restricted to Lyle seniors.", "Restricted to NexPoint Tower Scholars."). TAMU departments outside CSCE frequently append unrelated trailing clauses ("also taught at Galveston and Qatar campuses.", "Replaces CHEM 323 in previous catalogs.") onto otherwise-real prereq text. **The parser needs a pre-filter/classification step before AND/OR tokenization** — not just a tokenizer.
- **CSCE was not representative of TAMU's format diversity.** CSCE consistently uses a `Prerequisite(s):` label with standard AND/OR/grade-threshold prose. Most other TAMU departments (STAT, ENGL, HIST, CHEM, MKTG, PHYS, ISTM, ...) drop the label entirely and store bare comma/semicolon-separated course lists or standalone eligibility text (e.g. "Junior or senior classification."). Parser rules need to handle labeled and unlabeled forms, not assume the CSCE pattern generalizes.
- **No scraper corruption found** at scale — zero HTML fragments, truncation, encoded-entity leaks, or placeholder values across all 1,598 populated SMU rows and 2,312 populated TAMU rows. Whatever's there is genuine prose, just format-inconsistent across departments.

This parser is worth its own audit-then-spec cycle before being built — it's a meaningfully hard NLP-adjacent problem and deserves the same scrutiny FIT/SHIFT got.

---

## 5. TAMU sequencing — SMU-first confirmed

SMU-first sequencing (§2) is confirmed, not just assumed. The upper-level prerequisite null rate that raised doubt in the prior revision of this spec (§3.4) turned out to be ~95% genuine (courses that legitimately have no prerequisite) and ~5% a narrow, mechanically fixable parser gap — not a scraper problem requiring re-work. Two small follow-ups are recommended before or alongside the requirement-skeleton build, not full blockers:

1. Extend `split_description()`'s `REQUISITE_SENTENCE` regex to catch permission/approval phrasing (e.g. "permission required", "instructor permission", "Dean's Office-approved") — fixes ~48 rows, concentrated in independent-study/special-topics templates.
2. The v1 scheduler should treat a genuinely-null `prerequisites` value as "no constraint" rather than an error or a blocking case — this is now confirmed to be the correct semantic for ~95% of null rows, not a workaround for a data gap.

TAMU requirement-skeleton ingestion remains a parallel/later track (§3.2), picked up once the prerequisite parser (§4) is stable, since it's the only school-specific piece left after that.

---

## 6. Recommended build sequence

1. **Regex extension (small, immediate)** — extend `split_description()`'s `REQUISITE_SENTENCE` pattern to catch permission/approval phrasing per §5. ~48-row fix, no schema change, no new data source. **Landed:** branch `smu-catalog-prereq-and-group-id`, commit `6a3ad7a`, 14 new tests, full suite (1396 tests) passing.
2. **SMU requirement-ID resolution — complete.** `courseGroupId` flows from Coursedog's `courses/search` response through `build_course()` → `import_catalog.py`'s `to_row()` → stored as `course_catalog.coursedog_group_id` (migration `20260817230000_course_catalog_coursedog_group_id.sql`). The ID→course-code join and requirement-skeleton ingestion logic are now written too: the schema (§8.2) and the fetch/import scripts that join against this column are implemented, tested (49 new tests passed, full suite 1445 passed, 0 regressions), and committed (`7abb0e6`, `0f548c4`) on branch `smu-catalog-prereq-and-group-id`. Not yet applied/run live — see §8.2's status note.
3. **Prerequisite parser — implemented.** `structured_prerequisite()` (commit `1716847`) is a richer AND/OR/grade-minimum/corequisite/restriction parser, added alongside — not replacing — the existing conservative `prerequisite_requirement()`/`evaluate_prerequisites()`. Tested against real prerequisite text pulled from `data/catalog/engineering/*.json` and `data/catalog/smu/lyle.json`.
4. **Requirement-skeleton ingestion (SMU CS-BS) — complete, live in production.** `fetch_smu_requirements.py --write` and `import_requirement_groups.py --write` both ran successfully. Live state (current, post-restructure): 1 program row, **23** requirement_groups (17 at initial ingestion — including 2 group_types added after the initial migration, `enumerated_at_least_n` for `completedAnyOf` and a `minCredits`-based variant of `enumerated_all` for `completeVariableCoursesAndVariableCredits`, both mapped without schema changes — later restructured to 23 via commit `cba3dd4`'s Mathematics and Science alternative-path fix, §8.4), 58 requirement_group_options, 67 requirement_group_option_courses (65 resolved against `course_catalog.coursedog_group_id`, 2 flagged via `unresolved_course_ref` per the §8.3 decision, not dropped — option/course counts unchanged by the restructure). Post-write verification confirmed every row against the pre-write dry-run prediction, RLS intact, zero side effects on `course_catalog`/`institutions`. Commits spanning this work: `6a3ad7a` through `cba3dd4`, branch `smu-catalog-prereq-and-group-id`, not yet merged or pushed.

   **Known v1 simplification, not an oversight:** for `completeVariableCoursesAndVariableCredits` rules, only `minCredits` is captured into `credit_hours_required` — `maxCredits` is intentionally discarded (single-int column, one live example to generalize from: Content Area 4, Physics, `minCredits=7`/`maxCredits=8`). Revisit if the scheduler ever needs to represent a credit range rather than one required value.
5. **Requirement-satisfaction engine** — deterministic, rule-based (not LLM): map transcript against requirement buckets, produce a gap list of what's unsatisfied.
6. **Scheduler** — topological sort of remaining requirements using parsed prereq data (step 3), packed into terms bounded by a credit-hour cap (default: standard full-time load, e.g. 15, unless a better signal exists in the student's own course-load history).
7. **Elective slotting** — wherever the scheduler has open elective room, prefer GAP-recommended, target-role-relevant courses (reuses existing Course Discovery logic).
8. **UI** — 4-year term-by-term view, placed under Course Discovery per the original screenshot.

TAMU requirement-skeleton ingestion (§5) can be picked up in parallel once step 3 (parser) is stable, since it's the only school-specific piece left.

---

## 7. Explicitly out of scope for this spec

- Term-offering-pattern data (fall/spring/alternating-year) — flagged as a real risk in §3.4 but not solved here; needs its own investigation before the scheduler can be trusted for courses with irregular offering patterns
- Grade-minimum enforcement — parser should capture it (§4) but scheduler doesn't need to enforce it in v1
- TAMU requirement-skeleton scraper build (§5) — sequenced after SMU, not designed in this document
- Any UI/visual design work — this spec is data + logic only

---

## 8. Requirement-skeleton ingestion — design addendum

**Status:** DRAFT design, not yet a build prompt. Flagging open questions before committing to a schema.

### 8.1 Two different requirement-group shapes — must both be supported

SMU's CS-BS requirements (§3.1) contain two structurally different kinds of requirement group, confirmed from the live `requirements-krhha` page **and, this session, from the raw Coursedog `programs/search/$filters` response itself** (program `_id=CS-BS-2026-05-21`, queried live via the same unauthenticated Referer/Origin pattern as the courses endpoint):

- **Enumerated list**: a fixed, finite set of course options. Coursedog encodes this as `condition: "completedAllOf"` (all listed courses required) or `condition: "completedAtLeastXOf"` (choose N of the listed courses, N given by a sibling `restriction` field) on the rule object. The courses live in `value.values[]`, each entry an array of one or more `coursedog_group_id`s plus a `logic` of `"and"`/`"or"` — an `"and"` pair is a co-requisite bundle counted as one option (e.g. a lecture+lab pairing), not two alternatives.
- **Filter rule** (e.g. Technical Electives, 9 Credit Hours — "Nine credit hours of CS courses at the 3000 level or above as approved by adviser"): **confirmed not to be a structured filter object.** Coursedog encodes this as `condition: "freeformText"`, where `value` is just a generic label string (`"Complete the following:"`) and the entire actual constraint — department, level threshold, adviser-approval clause — lives only as prose inside the rule's `notes` field (HTML). No department code, no level-number field, nothing machine-parseable exists anywhere in the payload for this shape. See §8.3 for the full confirmation.

**Also found this session, not anticipated in the original draft: a third shape — compound/nested groups.** Two of CS-BS's seven major-requirement rules (`Lyle EDGE Curriculum`; a "Two Courses" rule choosing one lab-science sequence out of several) use `condition: "allOf"` / `"anyOf"` with a `subRules[]` array in place of a flat `value` — each sub-rule is itself a full rule object (enumerated, freeform, or further nested). This isn't an edge case in some other program; it's present in CS-BS's own major requirements, so ingestion can't skip it.

The requirement-skeleton schema must model all three shapes, or ingestion will either crash or silently store some groups as empty enumerated lists.

### 8.2 Revised schema shape (draft, not final — supersedes the original draft)

Revised per §8.3's filter-rule-shape findings: the original draft's `filter_department` / `filter_level_min` columns assumed a structured filter source that turned out not to exist, and the original draft had no shape for compound/nested groups.

    requirement_groups:
      - id
      - program_id (SMU CS-BS specifically for v1)
      - catalog_year: text, not null — mirrors course_catalog.catalog_year's existing precedent (§3.1: stored per-row, not in a separate version table). Pins this row to one snapshot ("2026-2027" for v1); a future re-scrape writes new rows under a new catalog_year rather than requiring a schema change. No cross-year coexistence or per-student catalog-year matching in v1 — see §8.3.
      - coursedog_rule_id: text — the source rule/group's own `id` field (e.g. "AjzAZTn4"), for traceability and idempotent re-import
      - parent_group_id: nullable self-reference — populated only for a subRule of a compound group
      - name: text (e.g. "Technical Electives (9 Credit Hours)")
      - group_type: enum('enumerated_all', 'enumerated_at_least_n', 'compound_all', 'compound_any', 'freeform') — maps 1:1 to Coursedog's `condition` field (completedAllOf, completedAtLeastXOf, allOf, anyOf, freeformText)
      - n_required: int, null unless group_type = 'enumerated_at_least_n' (value is Coursedog's `restriction` field)
      - credit_hours_required: int, null if not parseable from the group name's "(N Credit Hours)" suffix
      - notes_html: text, null if the source rule has no notes — captured whenever present, not just for freeform groups, since enumerated groups can carry qualifying prose too (e.g. Mathematics and Science's "one 3000-level or higher MATH or STAT course" note sits alongside an already-enumerated values[] list)
      - requires_manual_definition: boolean, default false, true when group_type = 'freeform' — tells the requirement-satisfaction engine (§6 step 5, not yet built) to treat this group as un-checkable against a transcript in v1 and surface it to the student as "ask your adviser," rather than silently marking it satisfied or unsatisfied

    requirement_group_options (only for group_type in ('enumerated_all', 'enumerated_at_least_n')):
      - id
      - requirement_group_id
      - option_index: int — position in the source values[] array
      - logic: enum('and', 'or') — mirrors that value entry's own `logic` field; 'and' means every course under this option_index must be completed together (e.g. lecture+lab), not that any one alone satisfies the option

    requirement_group_option_courses:
      - requirement_group_option_id
      - coursedog_group_id (joins to course_catalog.coursedog_group_id, per §3.1's confirmed join key)

**Implemented and verified — not yet applied.** Migration `20260818130000_smu_requirement_skeleton.sql` (commit `7abb0e6`) creates the 4 tables described above, matches this schema (with one addition: `requirement_group_option_courses` carries a sibling `unresolved_course_ref` column alongside `coursedog_group_id`, with a CHECK constraint enforcing exactly one is set — the concrete implementation of §8.3's unresolved-course-ID decision). RLS matches `course_catalog`'s precedent exactly (anon+authenticated SELECT only, explicit revoke on insert/update/delete/truncate). A full live VERIFICATION block (table-collision check, institutions FK validity, anon-grant re-confirmation) is included in the migration file itself, dated and with actual query results — not applied to any database yet.

### 8.3 Open questions for next session

**Unresolved course IDs — decided.** When a requirement group's course reference doesn't resolve against `coursedog_group_id` (~5% rate, likely inactive/renumbered courses per the prior audit), ingestion flags it (e.g. a nullable `unresolved_course_ref` field, surfaced in UI/logs) and continues importing the rest of the program's requirements. Does not fail the whole import.

**Corequisite satisfaction — decided.** "Concurrent enrollment allowed" counts a requirement group as satisfied once the student is enrolled in the course, not only once completed with a grade — matches how registration itself treats it. The requirement-satisfaction engine should check enrollment status, not just completed/graded transcript entries.

**Catalog-year scoping — resolved.** No demo student record (`data/students/*.json`) or production schema table (`students`, `student_institutions`, `academic_terms` — `supabase/migrations/20260728000103_institution_grading_schema.sql`) carries an explicit `catalog_year` / `admit_term` / `entry_term` field. Checked all five demo students (Jordan Reyes, Ethan Brooks, Marcus Webb, Priya Nair, Sofia Ramirez) and the production `students`/`student_institutions`/`academic_terms` DDL directly — neither has one. It's derivable in principle: `academic_terms` stores one row per student per term (`year`, `season`, `sequence`, where `sequence = 1` is the student's own first term at that institution), which combined with `data/reference/smu_term_dates.json`'s term-date table gives an entering term a future feature could map to a catalog year — but that derivation logic doesn't exist yet and is out of scope for this build.

Resolution follows the project's own existing precedent rather than inventing a new one: `course_catalog.catalog_year` is already stored per-row instead of in a separate version table (§3.1). `requirement_groups` gets the same treatment (§8.2) — a per-row `catalog_year`, populated with the single current snapshot ("2026-2027", matching `course_catalog`) for v1. This future-proofs the column for a later re-scrape without a schema migration, but v1 does not implement per-student catalog-year matching: the requirement-satisfaction engine (§6 step 5) matches every student against the one current `requirement_groups` snapshot, same as course matching already implicitly does today. Per-student catalog-year resolution via `academic_terms` is a real follow-up, not a v1 blocker.

*Separate finding surfaced by this check, flagged for Deepak rather than decided here:* none of the five demo/test students attend SMU or major in Computer Science — all five are TAMU students (Business Administration, Computer Engineering-intended, Psychology, Aerospace Engineering, Biology). There is currently no fixture student to run the SMU CS-BS requirement-satisfaction engine against end-to-end once it's built. Doesn't block the migration/ingestion work itself (program data, not student data), but worth a decision before step 5 in §6 — either add a sixth demo student or re-profile one of the five as an SMU CS major.

**Filter-rule shape — resolved.** Pulled the live CS-BS payload from Coursedog's `programs/search/$filters` endpoint this session (program `_id=CS-BS-2026-05-21` — the exact ID from the original audit's example, confirmed live via a filtered query on `_id`; same unauthenticated Referer/Origin pattern as §3.1, executed via Chrome's page context so the request carried the site's own headers, robots.txt on catalog.smu.edu not applicable to this XHR-origin request). Findings, superseding the "likely encodes this differently... needs confirmation" language in the original §8.1:

- Filter-rule groups (Technical Electives; Advanced Major Electives — 2 of CS-BS's 7 major-requirement rules) use `condition: "freeformText"`, with no department/level fields anywhere in the payload — the entire constraint is prose in `notes`. The original draft's `filter_department`/`filter_level_min` columns have no source to populate from and are dropped in the revised §8.2.
- Enumerated groups use `condition: "completedAllOf"` (all required) or `"completedAtLeastXOf"` (choose N, N in a `restriction` field) — confirmed against Computer Science Core (11 courses, completedAllOf) and Engineering Leadership (6 courses, choose 2, completedAtLeastXOf/restriction:2), alongside the already-audited "Required Courses" example.
- A third shape not anticipated in the original draft: compound groups (`condition: "allOf"`/`"anyOf"` wrapping a `subRules[]` array of further rule objects), used by 2 of CS-BS's 7 major-requirement rules (Lyle EDGE Curriculum; the lab-science-sequence choice). The revised §8.2 supports this via `parent_group_id` self-reference — not optional, since it's present in CS-BS's own major requirements, not just some other program.

§8.2 has been revised to match all three shapes. Still a draft for the build prompt to implement, not a migration that's been written.

---

## 8.4 Satisfaction-engine scoping decisions

Resolved during initial scoping of the requirement-satisfaction engine (the next phase after requirement-skeleton ingestion, §6 steps 1-4, which are complete).

**In-progress courses count as satisfied.** For gap-list/progress display purposes, a course with `course_records.status = 'in_progress'` counts the same as `'completed'` toward requirement-group satisfaction — shows realistic "on track" progress rather than only crediting finished coursework. This is distinct from the §8.3 corequisite-satisfaction decision, which was specifically about whether concurrent enrollment unblocks registration for a dependent course; this decision is about the degree-completion gap list itself.

**Catalog-year scoping: real field, not a hardcoded assumption.** Only one SMU CS-BS requirement version exists in `programs`/`requirement_groups` today (`CS-BS-2026-05-21`), but a real `catalog_year` field will be added to student profiles now rather than deferring.

**Resolved: `student_institutions`, not `students`.** The schema already models multiple institution relationships per student (`relationship in ('home', 'transfer', 'dual_enrollment', 'prior')`, partial unique index on one 'home' row only, not global one-row-per-student) — catalog_year is a property of one specific institution relationship, not the student globally, and a transfer/dual-enrollment student could legitimately need two different values. Column: `catalog_year text null`, matching `course_catalog.catalog_year` and `programs`/`requirement_groups.catalog_year` exactly in name, type, and format ('YYYY-YYYY'). Deliberately a plain string, not an FK to any versioned table — same reasoning `20260812143000_profile_completion_field_formats.sql` already established for `expected_graduation` (a seeded date-range table can't represent answers years out). Not yet built — see §6 for the migration task.

**No demo student fits SMU CS-BS today — Ethan Brooks will be converted.** Audit findings: none of the 5 canonical demo students are SMU-affiliated; 2 blank SMU test accounts exist in production (Ty Langston, Noah Test) but have zero course_records and no profile data, offering no real shortcut over building from scratch. Decision: convert Ethan Brooks (previously TAMU, General Engineering → Computer Engineering-intended, the closest thematic fit) to SMU, Computer Science. This requires rewriting his institution affiliation, major fields, and course_records entirely — his existing TAMU coursework (CHEM 107, CHEM 117, ENGL 104, ENGR 102, KINE 199, MATH 151, all in_progress) does not carry over, since none are SMU courses. Full scope of what needs auditing/changing to be determined before this conversion is built.

**Key mechanical finding, not yet a decision — flagging for the build task:** `course_records.catalog_course_id` (the FK meant to link a transcript row to `course_catalog`) is 0% populated across all demo data. The satisfaction engine must join on `course_records.course_code` (text) against `course_catalog.code` instead, then pivot to `course_catalog.coursedog_group_id` to reach `requirement_group_option_courses`. This works for SMU (code format matches) but can never work for TAMU, since TAMU has no `coursedog_group_id` populated anywhere — a TAMU transcript structurally cannot exercise this join path, which is part of why an SMU demo student is required, not just convenient.

**Resolved: full completeness audit of the original 17 SMU CS-BS requirement groups against real credit-hour arithmetic.** 2 groups needed genuine engine-level special-case satisfaction logic, not flat enumerated_all/enumerated_at_least_n semantics — the other 15 checked out cleanly (exact credit-sum matches, correctly-modeled choose-N structures, or catalog-prose-confirmed all-required sequences):

1. **Content Area 4, Physics** — credit-threshold-range semantics. The 3 options (PHYS 1303+1105, PHYS 1304+1106, PHYS 3305) don't fit "all required" (sums to 11, not 7) or "pick exactly one" (max single option is 4 credits, well under the 7-8 required) — the actual rule is "accumulate credits from chosen options until within minCredits/maxCredits (7-8)," confirmed by both the raw Coursedog condition (completeVariableCoursesAndVariableCredits, already captured with minCredits=7 per §8.4's earlier maxCredits-discarded note) and the public catalog page's own prose ("Complete course(s) and earn 7 - 8 credit(s) from the following"). The satisfaction engine needs to be aware of this condition type and sum credits across a student's chosen/completed options rather than checking flat all-or-nothing completion. **Still unresolved at the schema level** — Ethan Brooks hasn't touched this group, so §9's hand-trace could only pose it as a hypothetical; exact gap-list display format ("not satisfied" vs. "4 of 7-8 credits" vs. something else) remains an open decision, see §9.

2. **Mathematics and Science** — alternative-path OR logic. MATH 1337+1338 (Calc I+II) and MATH 1340 (Consolidated Calculus) are alternatives to each other, not 3 independently-required courses — confirmed via a free-text `notes` field in the raw Coursedog payload ("(Math 1337 & Math 1338) or Math 1340"), the only source with this signal anywhere. **Now fixed at the data level** (commit `cba3dd4`, superseding the "has NOT been fixed" language this paragraph originally carried): the flat `enumerated_all` group was restructured into a `compound_any` "Calculus Sequence" group with two `enumerated_all` children — "Calculus I & II" (MATH 1337+1338) and "Consolidated Calculus" (MATH 1340) — `rule_source = 'manual'` on both, since the split has no single Coursedog rule ID backing it. Live-verified against Ethan Brooks' transcript in §9: his MATH 1337 (completed) + MATH 1338 (in_progress) resolve onto the same "Calculus I & II" option, correctly satisfying that one child without touching the Consolidated Calculus alternative. This is the reason the live group count moved from 17 to 23 (Mathematics and Science's restructure added 6 rows in place of the original 1: the group itself plus Calculus Sequence, its 2 children, Linear Algebra, Discrete Computational Structures, and Statistical Methods, each broken out as its own row). Since the `notes`-field signal was confirmed non-generalizable (13 of the original 17 groups had no notes field at all), this was a one-off manual fix for this one group, not a mechanism applied elsewhere.

All other 15 of the original 17 groups (including the 2 originally-suspected-and-now-cleared cases, Interdisciplinary Projects and the Biology/Chemistry sequences) are correctly modeled as-is — no manual annotation table needed for them.

**Separately, a smaller, non-blocking data-accuracy gap** (same root-cause class as Physics's minCredits/maxCredits truncation, not a satisfaction-logic bug — these groups are still correctly marked satisfied either way): Leadership and Mentoring and Experiential Learning both store `credit_hours_required` as a flat 1 (parsed from a name-suffix range, "1-3 Credit Hours"), which understates earned credit when a student satisfies the requirement via the 3-credit option rather than the 1-credit one. Worth fixing alongside Physics's min/max handling later; not a blocker for satisfaction-engine design.

**Decided: Ethan Brooks conversion — Sophomore, transcript approved.** Classification: Sophomore (not Freshman) — enables a completed+in_progress mix, the only demo student across all 5 with any 'completed' course_records rows once built. expected_graduation stays 'Spring 2029' — unchanged, still narratively consistent under a Fall 2025 SMU start. catalog_year = '2026-2027' (matches the only ingested CS-BS requirement version). Proposed 8-course transcript (4 completed, 4 in_progress, touching 5 of the (then-)17 requirement groups with realistic partial signal) approved as drafted. career_profiles narrative rewrite (career_goals, target_roles, interests, skills_technical, geographic_preference) still pending — full current field values need to be pulled before drafting replacements, to avoid overwriting content that isn't actually stale.

---

## 9. Requirement-satisfaction engine — design decisions

Resolved via a hand-trace against Ethan Brooks' real transcript and the
live 23-group tree (all 8 of his course_records rows join cleanly:
course_records.course_code → course_catalog.code → coursedog_group_id →
requirement_group_option_courses, confirmed end to end, zero unmatched).

**Hand-trace correction — Interdisciplinary Projects.** The original
hand-trace called this group "Satisfied (ENGR 2101 completed)." That was
wrong. Interdisciplinary Projects is enumerated_all with 3 required
options — ENGR 2101, 3101, 4101, a project sequence spanning sophomore,
junior, and senior year — not a choose-one group. Ethan Brooks has only
completed ENGR 2101, so the correct status is IN_PROGRESS (1 of 3
required options satisfied), confirmed by the built evaluator. This is
the first concrete case where the automated engine caught a manual
hand-trace error rather than the other way around — worth keeping as
documented evidence of why the engine exists, not just silently
correcting the number.

**Unified three-state status model, applied to every group in the tree
(leaf and compound alike):**
- `SATISFIED` — leaf: a matching course exists in course_records
  (completed or in_progress, per §8.4's in-progress-counts decision) and
  counts_toward_credit = true (see below). compound_all: every child
  SATISFIED. compound_any: at least one child SATISFIED. Credit-threshold
  groups (completeVariableCoursesAndVariableCredits-derived, e.g. Content
  Area 4 Physics): accumulated credits from matched courses ≥
  minCredits.
- `IN_PROGRESS` — compound_all/compound_any: at least one child has any
  matched course but the group isn't SATISFIED. Credit-threshold: 0 <
  accumulated credits < minCredits. **Leaf groups use this same
  three-state model, not a restricted SATISFIED/NOT_STARTED-only
  subset** — an earlier draft of this section claimed leaves had no
  IN_PROGRESS state of their own, which was a spec error, not a code
  error, caught when the built engine correctly evaluated Computer
  Science Core as IN_PROGRESS at 3-of-11 matched options. The
  in-progress/completed distinction at the individual course_records row
  level is still collapsed into "counts as satisfied" per §8.4 — that
  part holds — but the group's own status is computed with the full
  three-state model like every other node in the tree.
- `NOT_STARTED` — no matched course anywhere in the subtree.
- `MANUAL_REVIEW` — groups with requires_manual_definition = true
  (Technical Electives, Advanced Major Electives). No structured course
  list exists to check against; matches this column's own documented
  intent ("surface to student as 'ask your adviser'"). Never computed as
  SATISFIED/IN_PROGRESS/NOT_STARTED.

Credit-threshold and compound groups also carry an optional detail
string for display (e.g. "4 of 7 credits", "2 of 6 children satisfied")
— not yet specified in exact format, left to the build task.

**course_records field usage, confirmed:** counts_toward_credit must be
checked before crediting a course toward any requirement — a course
explicitly marked false shouldn't satisfy a group. counts_toward_gpa and
excluded_from_gpa_by are GPA-calculation concerns only and are NOT
consulted by the satisfaction engine — flagging explicitly since both
sets of fields live on the same table and could otherwise be conflated.

**Known limitations, accepted, not fixed:**
- Engineering Leadership's 2 unresolved_course_ref entries (raw
  Coursedog IDs 0220321/0248931, no course_code) can never be matched
  against a transcript — this group can show at most 4/6 available
  options until/unless those IDs are manually resolved. Documented
  limitation per the ingestion migration's own comment, not a blocker.
- Mathematics and Science's stored credit_hours_required (24) still
  doesn't reconcile against its children's actual credits — a
  pre-existing, separately-flagged gap (§8.4), not addressed by this
  design.

**Not yet designed:** the actual query/algorithm structure that computes
this tree bottom-up for a given student, and the API/output shape a
future scheduler or UI would consume. This section defines the
semantics; implementation is the next task.

---

## 9.1 Requirement-satisfaction engine — architecture

Investigated and proposed against real conventions already in this
codebase (course_discovery/ module shape, build_student_intelligence_
profile's flat-fetch-then-Python-tree pattern, StrictModel/Enum output
convention, fixture-based pure-function testing). Full proposal on
branch smu-catalog-prereq-and-group-id session notes; summary below.

**Module placement:** GradusIQ_career/course_discovery/, following the
existing models.py / prerequisites.py / service.py split. Named
"requirement-satisfaction" or "degree-audit" — explicitly NOT "gap" or
"fit," both already taken by unrelated AI-feature runners
(features/gap.py, features/fit.py).

**Query strategy:** flat fetch (requirement_groups, requirement_group_
options, requirement_group_option_courses, course_records — 4-5 queries,
no recursion at the DB level), tree assembled in Python via parent_
group_id, mirroring build_student_intelligence_profile's exact pattern.
Justified by data size (23 groups / 58 options / 67 course refs for one
program) and by avoiding rpc()-based raw SQL, which would break this
codebase's RLS-scoped-client convention.

**Output shape:** RequirementGroupStatus enum (SATISFIED/IN_PROGRESS/
NOT_STARTED/MANUAL_REVIEW, per §9's semantics) and a recursive
RequirementGroupResult StrictModel (id, coursedog_rule_id, name,
group_type, status, detail, matched_course_codes, children), wrapped in
RequirementSatisfactionResult (student_id, program_id, top-level groups
only). matched_course_codes is populated on LEAF groups only — compound
nodes (compound_all/compound_any) leave it empty and rely on consumers
walking into children for traceability, never aggregating child course
codes upward. This is an explicit rule, not an implementation detail
left to chance.

**Split for testability:** a pure evaluate_requirement_tree() function
(no Client parameter, hand-built dict fixtures, zero I/O) does all real
logic; a thin fetch_requirement_tree(client, ...) stays untested-by-unit-
test, same treatment as profile_builder.py's raw fetches.

**Required test coverage before this ships (explicitly called out, not
just "add tests"):**
1. Ethan Brooks' real hand-traced tree (§9's audit) as a ground-truth
   integration-style fixture — the evaluator must reproduce every status
   in that trace exactly.
2. A hand-built credit-threshold case (Content Area 4 Physics or
   equivalent) — this group is untouched in all real demo data, so its
   SATISFIED/IN_PROGRESS/NOT_STARTED boundary logic has never been
   exercised against anything, real or hypothetical, until this test
   exists.
3. A hand-built option-level `or`-logic case (Statistical Methods'
   CS 4340 | STAT 4340 | OREM 3340 cross-listing, or equivalent) —
   confirms matching any one of an "or" option's course IDs satisfies
   that option, not all of them.

**Built and tested** — GradusIQ_career/course_discovery/
requirement_satisfaction.py (pure evaluator) and GradusIQ_career/
requirement_satisfaction_fetch.py (thin fetch function, placed outside
course_discovery/ per that module's own no-Supabase-access rule,
matching profile_builder.py's existing placement precedent). 14 tests
including a real live-pulled Ethan Brooks fixture, credit-threshold
boundary cases, and cross-listed or-logic cases, per this section's
required coverage above. Credit-threshold groups are identified via a
dedicated group_type value (enumerated_credit_threshold), not a
hardcoded ID allowlist — added by migration
20260819160000_requirement_groups_credit_threshold_group_type.sql
(applied live; the single live Content Area 4, Physics row migrated from
enumerated_all to enumerated_credit_threshold, and
fetch_smu_requirements.py's CONDITION_TO_GROUP_TYPE updated so a future
re-ingestion maps completeVariableCoursesAndVariableCredits correctly
without a manual fix). Not yet wired into an API endpoint or UI.

---

## 10. Scheduler — scoping decisions

Scoped via a hand-trace against Ethan Brooks' real remaining
requirements (13 leaf groups still open, per the live requirement-
satisfaction endpoint), the same grounding approach used for the
satisfaction engine.

**Findings:** his remaining requirements split into 3 single-course
fills, one no-choice 8-course chain (Computer Science Core, with real
prereq ordering: CS 2341 → CS 3341 → {CS 3353, CS 5330, CS 5343, CS
5344} → CS 5328 → CS 5351), 5 groups requiring genuine course selection
(Advanced/Domain-Specific AI, Experiential Learning, Statistical
Methods, the lab-science content-area choice, Engineering Leadership),
and 2 freeform groups (Technical Electives, Advanced Major Electives)
that are un-schedulable until an adviser names actual courses.

**Decided: v1 scope is ordering only, selection deferred.** The
scheduler handles topological ordering and credit-hour bin-packing for
groups with a single obvious candidate or a fixed no-choice chain. The
5 groups requiring genuine selection among options are deferred to a
later phase — building selection logic now would sit on top of §9's
still-open credit-threshold/compound-any display semantics, risking
rework. This still covers the majority of Ethan's real remaining courses
by count.

**Known bug, deferred (not a v1 blocker):** structured_prerequisite()
doesn't parse "prerequisite or corequisite" / "corequisite" phrasing
into coreq_allowed — it lands in requires_all as an ordinary
prerequisite. On real SMU data this creates an actual cycle (BIOL 1301
requires BIOL 1101 requires BIOL 1301), which would break a naive
topological sort. This only affects the Biology/Chemistry lab-science
content-area choice — one of the 5 deferred selection groups — so it is
NOT a v1 blocker, but must be fixed before Phase 2 (selection logic)
is built.

**Fixed for v1: "X or equivalent" parser gap.** 4 of 5 needs-review
prerequisite strings shared one common boilerplate pattern
("C-/better in COURSE or equivalent" / "... or permission of
instructor") that the parser conservatively refused rather than guessed
at. This blocked CS 2341, which gates half of CS Core's remaining
no-choice chain — squarely in v1 scope. See build task for the fix.

**Term-offering data: confirmed absent, accepted as a documented v1
simplification.** Re-checked directly (not just re-citing the original
§3.4/§7 flag) — no field or table anywhere carries term-offering
patterns; only 2 phrase-based hits exist in the entire SMU corpus,
neither relevant to Ethan's candidates. v1 assumes every course is
offered every long term. Known risk, not uniform: CS 5391/5394
(independent study, arranged per-student) and CS 5325 (a specialized
5000-level elective, plausibly once-a-year) are the two candidates most
likely to violate this assumption among his real remaining courses.

**No existing TermPlanner class or per-term credit-hour cap exists** —
searched directly, not found under that name. Reusable: academic_terms/
academic_term_dates + planning/term_view.py's term-identity/upcoming-term
logic, transcript/terms.py's SEASON_ORDER vocabulary,
planning/planned.py's add_planned/ensure_term_row for attaching courses
to future terms. Credit-hour bin-packing is new logic — nothing to
reuse for the cap itself (planned.py's MAX_CREDIT_HOURS=99.99 is a
single-course sanity ceiling, not a registration-load cap).

---

## 10.1 Scheduler — architecture

Investigated and proposed against real conventions already in this
codebase — specifically GradusIQ_career/action_planning/query.py's
dependency_order() (Kahn's algorithm, lexicographic tie-break,
cycle-detection-first, PlanFailure fail-closed envelope,
unconstrained/limitations-never-silent output) — mirrored exactly rather
than reinvented, same discipline the satisfaction engine used matching
course_discovery/'s existing shape.

**Module placement:** GradusIQ_career/course_discovery/scheduler.py, a
pure function (no Client, hand-built fixtures, zero I/O) consuming
already-computed RequirementGroupResult + StructuredPrerequisite + term
data.

**v1 scope, corrected from §10's original framing:** every LEAF group
that is no-choice (single obvious course, or a fixed multi-course chain
with no selection among alternatives) — not limited to the two buckets
named in §10's scoping pass. This includes Interdisciplinary Projects'
remaining ENGR 3101/ENGR 4101 (missed in the original scoping - a real
oversight, not an intentional exclusion) alongside the 3 single fills
and Computer Science Core's 8-course chain. The 5 groups requiring
genuine selection among options, plus the 2 freeform groups, remain
deferred per §10.

**Decisions:**
- **OR-clause prerequisites** (e.g. CS 5330's (CS 2341 or CS 2353)):
  drop the edge, record as a limitation, matching action_planning's
  documented policy exactly — never synthesize a hard edge that would
  silently convert OR into AND.
- **In-progress counts as satisfied** for prerequisite-clearing purposes
  (not just satisfaction-engine display), consistent with §8.4 — a
  future term's prerequisite check treats an in-progress course as
  cleared, since it resolves before any later term begins.
- **Credit-hour cap: hardcoded 15 for v1**, not adaptive to student
  history. Revisit only if a real case demonstrates 15 produces a bad
  plan.
- **Over-constrained detection is in scope for v1** — if remaining
  no-choice credit hours can't fit before expected_graduation given the
  cap and term horizon, the scheduler flags this via the same
  fail-closed status/failure pattern used elsewhere, not silently.

**Output shape:** ScheduledCourse (course_code, credit_hours,
requirement_group_id for traceability, limitations), TermPlan (term_key,
courses, total_credit_hours), UnscheduledRequirement
(requirement_group_id, name, reason: SELECTION_DEFERRED |
FREEFORM_MANUAL_REVIEW), wrapped in ScheduleResult (student_id,
program_id, terms, unscheduled, status: SCHEDULED|ERROR, failure:
PlanFailure | None — reused directly from action_planning).

**Worked example (Ethan Brooks, corrected 13-course v1 scope, 15-credit
cap, starting 2026-Fall):** built and tested —
GradusIQ_career/course_discovery/scheduler.py, real prerequisite text
pulled live from data/catalog/smu/*.json, checked into
tests/fixtures/ethan_brooks_scheduler_input.json and
tests/test_scheduler.py. Real computed result, 5 terms, comfortably
inside the 6-term horizon to Spring 2029, recomputed after the
bare-comma-as-OR parsing fix below landed:

| Term | Courses | Credits |
|---|---|---|
| 2026-Fall | CS 2341, CS 2353, ENGR 2112, ENGR 3101, ENGR 4101, MATH 3304 | 12 |
| 2027-Spring | CS 3341, CS 3353 | 6 |
| 2027-Fall | CS 5330, CS 5343, CS 5344 | 9 |
| 2028-Spring | CS 5328 | 3 |
| 2028-Fall | CS 5351 | 3 |

**Data-quality gap found and fixed this session:**
structured_prerequisite() used to merge a comma-only course list with no
"and"/"or" connector into one OR-set PrerequisiteClause even when the
source text was actually an AND-list. CS 3353's real text is "C- or
better in CS 2341, CS 2353." (no connector at all) and CS 5330's is
"..., CS 2341, CS 2353, and CS 3341." (an Oxford-comma AND-list) — both
are genuine AND requirements, not real "or" alternatives. Scoped
corpus-wide before fixing (230 real courses affected, 158 SMU + 72 TAMU,
of which 203 were unambiguous and 27 were a genuinely separate,
deliberately-untouched ambiguous case — a comma list ending in a trailing
"or equivalent"/"or permission of instructor" governing the WHOLE list,
e.g. ASCE 3310's "..., ASCE 3330, or permission of instructor", a real
6-way OR, correctly left alone). Fixed in
GradusIQ_career/course_discovery/prerequisites.py's new
_clauses_for_codes()/_identity_groups() helpers, applied at both
collection points (the top-level fallback and the _AND_SPLIT sub-clause
loop — CS 5320 confirmed both needed it, since its literal "and" only
appears before the third item, leaving the earlier bare-comma pair
merged under the old code at the sub-clause level). Slash-joined
cross-listed identities (e.g. "CEE 2310/ME 2310", "CS 4340/OREM 3340/
STAT 4340") are collapsed to one identity before the AND-split decision,
so a genuine cross-listed pair is never shattered into two independently-
required courses — the confirmed main regression risk, built in from the
start. 29 tests in tests/test_structured_prerequisite.py (8 new), full
suite 1506 passed, no regressions.

Effect on the worked example above: CS 3353 now lands strictly after CS
2341/CS 2353 (2027-Spring, not 2026-Fall alongside them), and CS 5330
carries a real edge on all three of CS 2341/CS 2353/CS 3341 rather than a
dropped-and-flagged OR-set — no `limitations` remain on any of the 13
courses. The "CS 5330's (CS 2341 or CS 2353)" example originally named in
this section's OR-clause decision was never actually a real "or" in the
source catalog text; the OR-clause-drop-and-flag decision itself is still
correct and necessary in general (a real OR does exist elsewhere, e.g.
Statistical Methods' CS 4340/STAT 4340/OREM 3340 and the 27-item ambiguous
bucket left untouched by this fix), but that specific illustrative case
was mischaracterized. CS 5328's "Corequisite: CS 5330" — the same
deferred corequisite-parsing gap already flagged for the BIOL
content-area case — is still not fixed (out of scope for this fix, which
targeted the bare-comma-as-OR bug specifically); it still produces an
overly conservative but safe "CS 5330 strictly before CS 5328" edge
instead of allowing the same term.

Also confirmed via this real fixture: **in-progress-counts-as-cleared**
correctly lets CS 2341 (whose only real prerequisite, CS 1342, is
in-progress) and MATH 3304 (whose OR-clause is trivially met by
already-in-progress MATH 1338) both land in the very first term, matching
the decision above.
