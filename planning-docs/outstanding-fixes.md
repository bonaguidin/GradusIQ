# GradusIQ — Improvements Backlog

_Running list: bugs, gaps, and feature ideas. Update as items close._

---

## 🔴 Blocking / real students affected

- [ ] **GAP's synchronous execution risks exceeding Vercel's function timeout for real students.** Audited 2026-08-17. The full chain (`api.py:analyze_gap` → `_run_protected_feature` → `GapRunner.run` → `role_requirements_for` → `role_research_agent.get_role_requirements` → `CareerFeatureRunner.run`'s DeepSeek R1 synthesis call) is entirely synchronous — no async/await anywhere in the path, one request thread blocks start to finish. Two costs stack: (1) the DeepSeek R1 synthesis call itself, documented in code as routinely 100–200s+ (`ai/openrouter_client.py:16-20`), timeout set to 300s specifically to accommodate it; (2) `role_requirements_for` (`gap.py:188-201`) loops over uncovered target roles **sequentially**, each uncovered role bounded by a 90s wall-clock budget (`role_research_agent.py:115`, `_TIME_BUDGET_SECONDS`). `frontend/vercel.json` caps `api/proxy.mjs` at `maxDuration: 300` — a single uncovered target role plus the DeepSeek call can already approach or exceed that ceiling; a student with several uncovered roles exceeds it outright. (Re-auditing prior numbers: the previously-cited "111–215s" and "~40s per role" figures aren't directly sourced in code — the actual documented figures are "100–200s+" for DeepSeek and a 90s budget cap per uncovered role, which is worse than "~40s" implied.) Whether the linked Vercel project is actually on a plan permitting >300s (Pro/Enterprise with Fluid Compute go up to 800s; Hobby caps at 60s) is not determinable from the repo — needs checking in the Vercel dashboard/CLI, not assumed.

  This is now a **hard blocker for extending auto-run analysis to real student accounts**, not just a nice-to-have. `useCachedAnalysisRun` (`frontend/src/hooks/useCachedAnalysisRun.ts:26-49`) already deliberately withholds auto-run for real students specifically because of this risk (comment: "GAP in particular can be slow enough that an unrequested background run on every login is the wrong default") — real students currently only get GAP via a manual "Run analysis" click, which still hits this same unbounded synchronous path and can time out under the student's nose.

  Three fix directions were scoped, none implemented yet:
  - **(a) Decouple into a background job, client polls/receives an event.** Correct long-term fix, but no queue/worker infrastructure exists in the stack today — Vercel functions are themselves bounded by the same `maxDuration`, so this needs a separate worker process (or a Postgres-as-queue + cron-triggered worker) outside the request/response cycle. The per-student `student_analysis_cache` table (`api.py:1005-1025`) could plausibly grow a status column to support this, but it's a real infra lift, not a config change.
  - **(b) More aggressive cross-student role-research caching.** Partially moot: `role_research_cache.json` is **already** a shared/global cache keyed by role name only (not per-student), so repeat lookups across students already skip the 90s research path. It has no TTL (`data/.cache/role_research_cache.json`, flagged separately below under Job posting data). But this only ever addresses the role-research half of the cost — it does nothing for the dominant 100–200s+ DeepSeek synthesis call, which runs regardless of role-research cache hits. Caching alone does not resolve the blocking risk.
  - **(c) Raise the Vercel timeout ceiling.** Cheapest if available — config-only — but unverified whether the current plan supports it, and even 800s (Fluid Compute ceiling) isn't a full fix for a student with multiple uncovered roles stacked against a 100–200s+ DeepSeek call; it buys headroom, not a guarantee.

  (a) is the only real fix; (c) is the fastest stopgap if the plan allows it; (b) is already half-built and worth closing the TTL gap on regardless, but doesn't move the needle on the timeout itself.

## 🟠 Product integrity — unsourced claims presented as data

- [ ] **Tavily is the wrong grounding tool for FIT/SHIFT's quantitative claims** — still open. Tavily is a search/summarization API — correct fit for GAP's actual use (qualitative role research), wrong for claims requiring structured counts (postings, percentages). Same underlying gap as the job-posting-vendor item below; the FIT fix worked by removing the false promise of data, not by adding real posting data. That's still a future project.

## 🟡 Data coverage — no API needed, pure data work

- [ ] **No generation script for the O*NET file** — `data/onet/build_onet.py` exists now (375 lines) but coverage is still curated/manual, not automated against the full O*NET release.

## 🟡 Job posting data — doesn't exist at all

- [ ] **Vendor never actually decided.** `market_data.py` docstring says Adzuna/JSearch. `react-dashboard-plan.md` says Lightcast. No credential, no config, no code for any of them. `dfw_postings: None` is a hardcoded literal.
- [ ] **Quota math requires cache-first architecture** — Adzuna ~1,000 calls/mo (~33/day), JSearch free tier ~200/mo. Must fetch-on-schedule + cache, never call live per student request.
- [ ] **No TTL primitive exists anywhere in the codebase.** The one cache that exists (`role_research_cache.json`) has no timestamp field — would need to be built from scratch for posting data, which goes stale in days not years.
- [ ] **Cache architecture won't scale as-is even once built.** Flat single-file read-modify-write, no locking under `WEB_CONCURRENCY > 1`. Fine at 15 roles; wrong shape for one-to-many posting data.
- [ ] **JSearch's role narrowed from original plan.** Originally scoped as gap-filler for
  Adzuna-thin roles + LinkedIn-source confirmation. Gap-fill use case is now closed (see
  above — JSearch is equally thin for the one role that needed it). LinkedIn-source
  confirmation remains untested — the one live call spent on this investigation returned
  zero results, so there's no response body to inspect for `job_publisher`/source fields
  yet. Worth one more cheap live call (a high-volume role like "software engineering",
  not a thin one) if/when LinkedIn-sourcing actually matters for a feature — not urgent.
  Adzuna is confirmed as the sole primary vendor for job-posting data going forward;
  JSearch's remaining justified use is narrow, not a general secondary source.

## 🟢 Academic Record — term structure (Phase 1 audited and built, not yet merged)

Full audit complete (2026-08-11) and Phase 1 implementation built and staged (2026-08-11), not yet committed. Key findings/decisions, for reference:

- **Schema:** terms live in `academic_terms` (per-student rows: label, year, season, sequence), joined to `course_records` via `term_id`. `course_records.status` has a live DB CHECK, currently `{'completed', 'in_progress'}` only — no 'planned' value exists.
- **Decision made:** planned courses get a **separate `planned_courses` table**, not a third `course_records.status` value — this avoids the `course_records_student_term_course_key` unique-index collision, where a real transcript row could silently lose to a stale planned placeholder under the old approach.
- **TAMU term dates:** hardcoded per-year table, sourced from TAMU's official academic calendar PDF (verified by reading the PDF text directly, not a search summary — one intermediate summary source had the wrong date for Spring 2027).
- **SMU term dates:** fetched live from Coursedog's unauthenticated terms endpoint, snapshotted (not called live at runtime) into `data/reference/smu_term_dates.json`. 16 real terms imported for 2026-2027, including first-class January/May/August intersessions. Coursedog's unflagged far-future placeholder rows (e.g., Fall 2027 shown as raw month boundaries) were correctly excluded from the import window.
- **Status:** applied and live as of 2026-08-12. `supabase migration list --linked` shows `20260811120000` (academic_term_dates), `20260811120100` (planned_courses) and `20260811120200` (course_catalog_search) all present remotely, local and remote in sync with no drift. SMU's `--push` has also run (`2a9909f`): 16 coursedog rows are live in `academic_term_dates`, carrying `source_last_checked` 2026-08-12, and the committed snapshot matches them byte-for-byte apart from the re-read stamps.
- **Explicitly deferred to Phase 2:** reconciliation logic for what happens when a real transcript arrives for a course a student had marked "planned" — this needs its own careful pass, not bolted onto Phase 1.

## ✅ Confirmed working / not actually broken (don't re-investigate)

- GAP's Tavily-backed live role research (`role_research_agent.py`) — genuinely live, timeout-bounded, injection-bounded, fails safe to static, 15 roles cached.
- Demo-analysis cache (`data/demo_cache/`) infrastructure — the old "failed entries served as successes" bug is confirmed fixed.
- The O*NET *data itself* isn't fake — real O*NET 30.3, correctly rescaled. It's a coverage mismatch, not a correctness bug.
- **CI gate is live and working.** No direct-to-main pushes by anyone since 2026-08-09; all subsequent PRs (#23 through #39) landed as proper merge commits with passing checks.
- **FIT/GAP/SHIFT grounding, `validate_data` conflict, and demo-cache fabrication** — all resolved and merged to main as of 2026-08-12 (PRs #37, #38, #39). See 🟠 section above for specifics. Don't re-audit from scratch; the known residuals are documented there.

## 🟢 Agentic architecture — proposed, not started

- `role_research_agent.py` is the one real agent in the codebase (bounded tool loop, Tavily, timeout/injection bounds, cache-first). Copy this pattern, don't reinvent it.
- FIT/GAP/SHIFT/PCA are single-shot LLM calls (`CareerFeatureRunner`) — no tool use, no loop. Chat is session-only today.

- [ ] Improve prerequisite/restriction data coverage and course-ranking quality if C2R.2 remains unresolved-heavy; do not weaken conservative `UNRESOLVED` semantics.
- [ ] Course degree applicability and term offering/section/seat availability remain unresolved; no authoritative degree-planning or schedule model exists.
- [ ] Advisor orchestration remains proposed; do not grant course-write or registration authority.
- [ ] Run and review the controlled B2 live baseline (12 synthetic evaluations; explicit paid/network opt-in required).
- [ ] Phase B2: choose and review durable trace storage/retention before enabling production persistence. Cost estimation remains deferred until reliable repository-controlled model pricing exists.

Proposed agents, roughly in order of leverage:

- [ ] **Orchestrator Agent** — runs FIT/GAP/SHIFT/PCA together, synthesizes one coherent narrative instead of four disjoint outputs.
- [ ] **Market Intelligence Agent** — owns the job-posting fetch/cache/refresh cycle. Scheduled, not request-triggered.
- [ ] **Course Planning Agent** — cross-references `course_catalog` + transcript + GPA + GAP's skill gaps → recommends actual next-semester courses. Now has a natural home once Phase 1's `planned_courses` table lands.
- [ ] **Advisor Agent (persistent chat)** — existing chat + cross-session memory + tool access to the other agents' outputs.

## 🟢 Student memory system — proposed, not started

- **Session memory** (exists) vs. **longitudinal memory** (doesn't exist — target role changes, closed skill gaps, corrections that shouldn't re-flag).
- [ ] Design a `student_events` / `student_memory` table: student_id, fact, source, confidence, first_seen, last_confirmed.
- [ ] Feature runners write to it when they detect something durable.
- [ ] Advisor Agent reads from it via tool-calling, not by re-deriving from scratch.

## 🔵 Bigger picture — process & product gaps

- [ ] **Canvas integration is still mocked.** The academic side is fake for every real student while career data (resume/transcript) is now genuinely real. This asymmetry gets worse, not better, once real students sign up.
- [ ] **No end-to-end smoke test.** 820+ unit tests, zero tests walking the real signup→provision→upload→confirm→run-a-feature flow against live/staging. More urgent than before: post-confirm flow, document processing states, and the career profile redesign all shipped to production, and the test account used for manual dry-runs was deleted.
- [ ] **Design consistency pass, once the review screen pattern settles.** Worth checking whether FIT/GAP/SHIFT displays and the GPA view still look like the old generic-form aesthetic. Note: the career-profile section on the authenticated dashboard was reordered 2026-08-12 (analysis panels now above the profile, matching the demo page) — worth including in this pass.
- [ ] **Surface data provenance to students, not just internally.** Real `catalog_year` / `source_last_checked` fields exist but never reach the UI.
- [ ] **`ats-fetcher` work is a single point of failure.** Per dev's `STATUS.md`, the fetcher implementation and `skill_terms_review.csv` exist only on one local branch on one machine — untracked corpus, no remote copy, no history anywhere. Accepted risk per the file, but worth confirming whether `skill_terms_review.csv` is reusable before it's the only copy left.
- [ ] **4 grounding-related commits never remapped/merged, deliberately deferred.** From `feat/gap-shift-grounding`, still living only on that branch (pre-rename paths): SHIFT concurrency (`a5b5ae0`, `ThreadPoolExecutor` around `get_role_trends`), 30-day trend-cache expiry (`f1e1635`), `.env` loading in `build_demo_cache.py` (`31cdc5a`), and a generic parse-retry loop in `base.run()` (`48aa9fb`). None were in scope for the FIT/GAP fabrication fix. The retry loop touches `base.py` and will need the same signature care the FIT/GAP work needed if picked up later — though `validate_data` is now settled, which makes it easier than it would have been.

---

## Suggested order

1. **Commit and deploy Phase 1** (academic term structure) — migrations written, staged, not yet applied to production. Apply migrations → run SMU `--push` → wire frontend → verify live.
2. Decide the job-posting vendor for real (Adzuna vs JSearch vs drop Lightcast from the plan doc)
3. Build the posting-data cache layer (new, TTL-aware)
4. Wire FIT/SHIFT into real market data once the vendor is chosen — this is the actual fix for the Tavily-mismatch problem, not just prompt-level restraint
5. Add an end-to-end smoke test before the next production deploy
6. Extend O*NET role coverage toward full 14/14
