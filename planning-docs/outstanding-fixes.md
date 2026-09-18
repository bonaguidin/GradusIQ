# GradusIQ — Improvements Backlog

_Running list: bugs, gaps, and feature ideas. Update as items close._

_Last updated 2026-09-15. Adzuna ingestion enabled, three write-path bugs fixed, the posting corpus repaired, a post-ingest integrity check added, and FIT grounded on role-labeled postings. Several long-standing entries in an earlier version were found to be false — see "Corrected claims" at the bottom before trusting older notes._

---

## 🔴 Open correctness risks

- [ ] **422 Workday postings are off their employers' boards but still in the corpus.** They correlate perfectly with pre-2026-09-12 `fetched_at`; Workday fetches whole boards, so a row that stops coming back has been taken down. They are now correctly clustered, which makes them look more trustworthy than they are. There is no "closed" or "last_seen" concept in the schema, and `retention.py` only nulls `raw_payload` after 90 days — it never marks or deletes a row. A demand signal counting dead listings is the same class of problem as FIT's ungrounded claims, with a database behind it. Breakdown: Parkland Health 120, AT&T 60, Toyota 57, Michaels 44, Fidelity 30, McKesson 28, Southwest 23, Atmos 21, Copart 19, Vistra 15, Solera 4, Kimberly-Clark 1.
- [ ] **Adzuna salary is a model estimate, not a posted wage.** Live rows carry `salary_is_predicted: "1"` alongside `salary_min`/`salary_max`. The field map keeps the numbers and ignores the flag. Either capture the flag or never surface salary — otherwise an estimate renders as an employer-stated figure.

## 🟠 Product integrity — unsourced claims presented as data

- [x] ~~**FIT market grounding**~~ — shipped. `role_postings` is wired into `build_student_context` and the prompt permits grounded employer and count claims. See the FIT grounding section below for measured behavior and limits.
- [ ] **SHIFT has zero market grounding.** `shift_signals` from local O*NET, `role_trends` from web research. No postings. SHIFT is the weaker candidate: one snapshot cannot establish a trend, and many Workday rows have null `posted_date`.
- [ ] **FIT missing disclosure for borrowed O*NET data.** Unchanged.

## 🟢 FIT posting grounding — shipped, with measured limits

Branch `feat/fit-posting-provider`, seven commits. FIT now cites real employers and posting counts from live Adzuna data.

- `a6c28e1` — role-labeled posting provider. Built on whether a posting carries a `target_role` from the query that fetched it, not on vendor name. Adzuna and JSearch qualify; Workday does not (whole-board scrape, null `target_role`). Every requested role always appears in the result; a role with no postings returns `coverage: "no_market_data"` with a reason, so FIT can tell absent data from an unqueried role.
- `83f2a92` — employer counting. Reuses `normalize_employer` from `identity.py` so "Texas Instruments" and "Texas Instruments Incorporated" count once. Adds `unknown_employer_postings` so a null company reads as "employer unknown" rather than "0 employers".
- `d7f89ef` — wiring. `role_postings` as its own context key. On provider failure returns `{"status": "unavailable"}` with no `by_role` key, so "could not look" is structurally distinct from "looked and found nothing".
- `d5d2f67` — prompt permits grounded posting claims.
- `69abccd` — prompt restructure (see "What the variance investigation found" below).
- `5602419`, `8a8aef2` — context trim: 10,623 → 8,021 tokens.

### Measured behavior (4 runs, student 3cb86d81, final state)

| Metric | Baseline | Post-restructure | Post-trim |
|---|---|---|---|
| Cites employers/counts for a covered role | 3/4 | 2/4 | 3/4 |
| States "no posting data found" when absent | 3/4 | 2/4 | 3/4 |
| Citations correctly scoped to the sample | 2/3 | 1/2 | 6/6 |
| Hard-ban violations | 1/3 | 0/4 | 0/4 |
| Correct noun (listings, never openings) | — | 4/4 | 6/6 |

All quality metrics are clean. The residual 3/4 is whole-response terseness — run 4 dropped O*NET scores too, not just postings — so it is generic instruction-following variance, not postings avoidance. Do not chase it with an output-contract change; that would optimize against noise at n=4.

### What the variance investigation found

FIT ignored `role_postings` entirely in 1 of 4 early runs and once said "8 DFW employers" despite an explicit ban. GAP and SHIFT went 8/8 clean on structurally identical prose-only rules, so the cause was FIT-specific:

- The frontmatter manifest listing what the script hands the model omitted `role_postings`, and the MARKET CONTEXT header said "Two blocks" when there were three. The model read an inaccurate inventory of its own inputs. Three separate stale self-inventory bugs were found in this one prompt — the third had `in_demand_software` attributed to `role_context` when it lives on `market_requirements`. Worth checking the other prompts for the same class of error.
- Rules sat in a 646-word mid-body block; GAP and SHIFT state theirs in one sentence at line 6. Compressed to 237 words with an early rule added.
- The prohibition text contained the banned phrase as a worked example.
- Context was 10,623 tokens against GAP's 4,969, with 41.7% being `role_postings` — mostly `description_snippet` text the prompt forbids using. Trimmed along with duplicated `hot_software` and unused `related`.

### Limits this ships with — state them before demoing

- Adzuna only. Workday carries no role label. A classifier would reach 13 of 1,319 rows: those boards are retail, clinical and support roles, not what students target. The lever is employer selection, not labeling.
- Coverage is thin and uneven. 28 postings for Software Engineering Intern, 25 for Research Assistant, 1 for People Operations Intern, zero for several others.
- Counts are `distinct_clusters`, not openings. Adzuna's fuzzy matching cannot separate syndication duplicates from separate requisitions.
- The same job may be counted twice across sources. Vendor rows carry no employer ATS ID.
- `freshness` is always unknown. Adzuna is query-scoped, so absence from a page is not evidence of closure.
- No visual check yet. The "Who's hiring" bullet has never been inspected in the rendered dashboard.

### Settled — do not re-investigate

- LLM-generated query terms: tested, rejected. 12 calls across 4 roles returned 5 usable postings, all from one employer. Two other roles are structurally absent from Adzuna — an unpaid volunteer position and a campus job. The bottleneck is corpus supply, not phrasing.
- `related` dropped from FIT — unused in 0/4 runs, no instruction referenced it. SHIFT keeps it. Surfacing adjacent roles in FIT is worth doing properly, with its own output bullet and a way for students to act on it, not smuggled in as background context.

### Follow-ups from this work

- [ ] `description_completeness: "truncated"` is now orphaned in the provider — it describes a field that no longer ships.
- [ ] `market_requirements.in_demand_software` is real but referenced by no block-specific instruction in any prompt.
- [ ] FIT's `overall_fit_summary` sits outside `role_matches`; a soft unscoped phrase ("local employers") appeared there once. The postings rules may not reach summary generation.

## 🟢 Job postings — pipeline works, corpus repaired

Ingestion is functional end to end and running nightly. The original blocker was never code: `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` were empty in GitHub Actions, so the config gate skipped the step while the job still reported success. Secrets set 2026-09-08.

Shipped this session (PRs #93/#94, #95/#96, all on `main`):

- `acb21b9` — serialize dates at the Supabase upsert boundary. Adzuna's `posted_date` is a Python `date`; postgrest can't serialize it. Every write run died on the first role. `DryRunStore` appends to a list and accepts any type, so no dry run could have caught it.
- `67a1447` — write postings before resolving identity. Identity resolution ran first, so an upsert failure orphaned clusters. Also fixed a silent bug: `set_canonical()` looks up its source row in `job_postings`, which didn't exist yet for first-time postings.
- `2c76894` — identify Workday rows by requisition ID. `recover_ats_id()` had no Workday rule, so all Workday rows fell through to fuzzy matching on employer/title/locality. Now keyed `ats:workday:<employer>:<source_job_id>`.
- `0e1e26b` — post-ingest cluster integrity check; fails the workflow on violation, runs with `if: always()`.

Corpus repair (2026-09-14, transaction-scoped, direct Postgres): split the 30 remaining bad clusters, deleted 637 empty clusters and 636 stale keys, repaired 47 dangling and 57 null canonicals, set 83 new. Result: 1,405 postings, 1,385 clusters, 1,385 keys, all integrity assertions passing. The 243-requisition undercount is zero. Backup at `/tmp/careeros-postings-recluster-backup-20260914T003414Z`.

### Open items

- [ ] Cluster-departure leak — known, unfixed, believed dormant. Nothing cleans up the cluster a posting departs: no clearing of the old canonical, no emptiness check, no key removal, no deletion. Produced 608 empty clusters and 639 dangling canonicals before the repair. `merge_clusters()` has cleanup logic but is unreachable — Workday emits no fuzzy key, so resolution never sees both clusters. Fixing it properly requires transaction-scoped writes (a Postgres function via RPC, needing a migration), because PostgREST cannot span reassign-then-cleanup atomically; every partial ordering has a failure window, and deleting keys first would make the old cluster unreachable — worse than the leak. Deferred: the trigger surface is now small (exact-keyed Workday rows re-resolve to the same cluster; the 422 stale rows will never be refetched), and `0e1e26b` detects recurrence.
- [ ] Decide on pagination. Page size 20, no pagination; a tested role reported `count: 37`. Roughly half of available postings per role are captured. Two pages × 14 roles ≈ 840/month against a ~1,000 ceiling — tight. Leaning: stay at one page and disclose the sample.
- [ ] Six of 14 roles return zero Adzuna results. Internal role labels are passed verbatim as `what=`. "Student Success Peer Mentor" is not a phrase employers post. Needs a query-alias table. Affected: Embedded Systems Intern, Flight Systems Intern, Mechanical Analysis Intern, Pre-Health Clinical Volunteer, People Operations Intern, Student Success Peer Mentor.
- [ ] Promote `description` out of `raw_payload`. The field map resolves it but never copies it to a row field. `skills_extracted` is never populated.
- [ ] Employer normalization doesn't strip "Company" or "Services". `sierra nevada` and `sierra nevada company` produce separate clusters; same for `progress rail` / `progress rail services`. A false split, inflating employer counts.
- [ ] Locality classification isn't stable across identical listings. The same posting appeared under both `:dfw` and `:other` buckets.
- [ ] Consider `SUPABASE_DB_URL` as an Actions secret. Would let the integrity check use direct Postgres and push evaluation into SQL instead of paginating three tables over REST every night. Weigh against putting a database credential in CI.
- [ ] Integrity check scales with corpus size. It fetches all rows and evaluates client-side. Trivial at 1,405; revisit at 10x.
- [ ] Network restrictions are wide open. The Supabase database accepts all IP addresses. FERPA-adjacent student data — worth restricting.

### Constraints on what postings can honestly support

- Adzuna descriptions are 500-char truncated snippets, not full text (verified across 20 listings, ending mid-sentence). Postings ground FIT's demand signal only. GAP's skill gaps stay on O*NET + Tavily. Full text needs a per-posting detail fetch, ~20x quota.
- Clusters are not opening counts, and now for a subtler reason. Workday is exactly identified, so its counts are real. Adzuna still uses fuzzy matching — 6 of 9 inspected Adzuna-only clusters were correct syndication duplicates, 3 were wrong. The Quest Diagnostics cases are unfixable by any key: same employer, title, and locality, distinguishable only by shift schedule inside a truncated description.
- The same job may now be counted twice across sources. Copart's 5 Adzuna rows form their own cluster and attach to no Workday requisition, because Adzuna exposes no employer ATS ID. Trading a 12-to-1 undercount for a possible 2x overcount on syndicated postings. State this in the FIT prompt.
- The Workday corpus is 12 employers, Parkland at 451 rows. Any denominator must be disclosed as "within tracked employers", never as DFW.
- `posted_date` is null on many Workday rows. Rules out recency framing.

## 🟡 Data coverage

- [ ] Finance Intern and Operations Intern resolve to SOC codes with empty skills/knowledge/abilities arrays (`13-2051.00`, `13-1199.00`). They resolve successfully and then silently produce nothing.
- [ ] No generation script for the O*NET file. Still hand-maintained.

## ✅ Confirmed working — don't re-investigate

- GAP's Tavily-backed role research (`role_research_agent.py`) — live, timeout-bounded, injection-bounded, fails safe to static.
- Demo-analysis cache — the "failed entries served as successes" bug is fixed.
- PCA audited clean as of ~2026-08-17.
- Adzuna field map is correct. All nine mapped fields resolved on all 20 live listings; nested company/location handled; date and salary coercion match. Verdict was "correct but incomplete", not mismatched.
- `target_role` is populated on vendor rows from the queried role (`normalize.py:165`). Vendor locality classification annotates without filtering (`normalize.py:181`).
- Ingestion never runs on the request path. Nightly cron plus `workflow_dispatch` only.
- Nightly runs succeed as of 2026-09-12. Adzuna lands ~110 listings per run with `target_role`, `posted_date`, `is_dfw`, `location_kind`, and `posting_identity` all populated.

## 🟢 Agentic architecture — proposed, not started

- `role_research_agent.py` is the one real agent (bounded tool loop, Tavily, timeout/injection bounds, cache-first). Copy this pattern.
- FIT/GAP/SHIFT/PCA are single-shot LLM calls. Not agents.

- [ ] Orchestrator Agent — runs all four together, one coherent narrative. Highest leverage: needs no new data.
- [ ] Market Intelligence Agent — narrower than originally scoped now that the scheduled workflow handles fetch and cache mechanically.
- [ ] Course Planning Agent — catalog + transcript + GPA + GAP's gaps.
- [ ] Advisor Agent — chat + cross-session memory + tool access.

## 🟢 Student memory system — proposed, not started

Session memory exists. Longitudinal memory does not — target role changes, gaps closed vs. still open, corrections that shouldn't be re-flagged.

- [ ] Design `student_events` / `student_memory`: student_id, fact, source, confidence, first_seen, last_confirmed. Data-modeling before AI.
- [ ] Feature runners write on detecting something durable.
- [ ] Advisor Agent reads via tool-calling, not re-derivation.

## 🔵 Bigger picture

- [ ] Canvas integration is still mocked. The academic side is fake for every real student while career data is genuinely real.
- [ ] No end-to-end smoke test. 2,467 unit tests, zero walking signup → provision → upload → confirm → run a feature against a live environment.
- [ ] `feat/gap-shift-grounding` is unlanded on both `main` and `dev`, sits on the old CampusIQ_career path, and its O*NET expansion is superseded. Rebase or reimplement, do not merge. Isolate its novel content first.
- [ ] Design consistency pass once the review screen pattern settles.
- [ ] Surface data provenance to students. `catalog_year` / `source_last_checked` exist but never reach the UI.

## Corrected claims — this file was wrong about these

- **"O*NET covers the wrong roles, only 2/14 resolve."** False. 1,016 SOC codes; all 14 resolve. Only the two empty-array roles are real.
- **"`dfw_postings: None` is a hardcoded literal."** False. The key doesn't exist in executable code.
- **"No TTL primitive exists anywhere."** False. `job_postings.fetched_at` exists, `retention.py` applies 90 days, and `degree_plan_career_optimization.py` has a 15-minute in-memory TTL.
- **"Vendor never decided / no credential, no config, no code."** False. Adzuna is the default vendor with a validated field map and nightly runs.
- **"Job posting data doesn't exist at all."** False.
- **"121 of 130 multi-posting clusters are bad."** Was true; repaired 2026-09-14. Now zero.
- **"FIT has zero market grounding."** Was true through 2026-09-14; FIT now cites real employers and counts from live Adzuna postings.

---

## Suggested order

1. Visual check: how "Who's hiring" renders in the dashboard — never inspected
2. Decide the stale-posting question (the 422) — now lower urgency, since those rows are retail and clinical listings FIT will rarely retrieve
3. Query-alias table for the six zero-result roles
4. Decide the salary-disclosure question before any salary reaches the UI
5. Revisit the cluster-departure leak if the integrity check ever fires
6. Scope "FIT surfaces adjacent roles" as a real feature, with an output bullet and a path for students to act on it
