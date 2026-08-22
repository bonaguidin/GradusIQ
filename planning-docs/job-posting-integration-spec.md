# Job Posting Integration — Pre-Build Specification

Status: DRAFT — for Deepak review before any build prompt is written
Owner: Deepak
Depends on: none blocking; complements the GAP timeout blocker (separate, unrelated fix)

---

## 1. Problem this solves

FIT and SHIFT currently make no quantitative market claims (post-fix, PR #37-39) because
there's no real data to back them. Tavily (GAP's tool) is a search/summarization API — right
tool for GAP's qualitative role research, wrong tool for aggregate counts/percentages, which
require a real denominator over a defined corpus. This spec adds that corpus.

## 2. Vendors

- **Adzuna** — primary. ~1,000 free calls/mo. Has aggregate/histogram endpoints (real
  denominators without per-posting aggregation work). Register at developer.adzuna.com
  (App ID + App Key, both required).
- **JSearch** (RapidAPI/OpenWebNinja) — secondary, role now narrower than originally
  planned. ~200 free calls/mo. Originally scoped for two uses: (1) gap-filling
  Pre-Health Clinical Volunteer where Adzuna tested thin, (2) LinkedIn-sourced postings.
  **(1) is now closed** — tested live 2026-08-17 (working subscription, `clinical
  volunteer` / Dallas, TX), returned 0 results, same as Adzuna. Two-vendor agreement on
  near-zero volume means this is accepted as a real market-coverage gap, not something
  either vendor's index will resolve — see §6a. **(2) remains untested** — JSearch's
  LinkedIn-sourcing claim (via Google Jobs) hasn't been empirically confirmed against a
  real response yet, since the one live call spent didn't return any results to inspect.
  JSearch's justified role going forward is narrower: LinkedIn-source confirmation only,
  if/when that's worth a call — not a general gap-filler.

**Not in scope:** LinkedIn scraping (considered, rejected — ToS/legal risk, no stable
schema, community-maintained dependency with no SLA). Lightcast (enterprise-only, no
self-serve). Coresignal (sales-led, $1k+/mo). See "Rejected alternatives" note in
outstanding-fixes.md.

## 3. Schema (new tables — not a bolt-on to role_research_cache.json)

```sql
job_postings
  id                uuid primary key
  source            text not null check (source in ('adzuna', 'jsearch'))
  source_job_id     text not null
  title             text not null
  company           text
  location          text
  target_role       text          -- FK-ish to your 14 SOC-mapped roles, nullable if unmatched
  skills_extracted  jsonb         -- populated by extraction pass, see §6
  salary_min        numeric
  salary_max        numeric
  posted_date       date
  fetched_at        timestamptz not null default now()
  raw_payload       jsonb not null  -- full vendor response, for reprocessing without refetch
  unique (source, source_job_id)

job_posting_fetch_log
  id             uuid primary key
  source         text not null
  target_role    text not null
  fetched_at     timestamptz not null default now()
  results_count  int not null
  quota_used     int not null      -- calls consumed by this fetch (usually 1, but paginated = N)
  status         text not null check (status in ('success', 'error', 'partial'))
  error_detail   text
```

Design notes:
- `fetched_at` + `posted_date` together are the TTL primitive currently missing from
  `role_research_cache.json`. Do not retrofit that file — this is deliberately separate,
  per the existing backlog note that the flat-file cache won't scale to one-to-many posting
  data.
- `raw_payload` stored so skill extraction (§6) can be re-run or improved later without
  burning quota on a refetch.
- **RLS — CORRECTED per 2026-08-17 audit.** Original assumption ("no RLS needed, matches
  `role_research_cache`/O*NET flat-file precedent") was wrong on two counts: those are
  flat JSON files, never in Postgres, so there's no RLS precedent to inherit from them
  either way. The actual Postgres precedent — `institutions`, `grade_point_map`,
  `academic_term_dates`, `course_catalog` — is RLS enabled + public-read policy + anon-
  write revoke, for every genuinely-public reference table built so far in this repo.
  `job_postings` should follow that real pattern: RLS enabled, public-read policy,
  anon-write revoked. `job_posting_fetch_log` is RLS-enabled with no policies
  (service-role-only), since it's an operational log, not page data.
- **New-precedent flag:** `job_postings` would be the first reference dataset in this repo
  to move from flat-file caching to Postgres entirely (role_research_cache, O*NET, term
  dates are all flat files or hybrid). Worth being deliberate about this rather than
  letting it set an unreviewed precedent — see note in §8.

## 4. Fetch scheduler — never live, never per-request

Non-negotiable given quota math. A student page load must never trigger a live Adzuna/
JSearch call.

- Runs on a schedule (cron or scheduled job — **needs an infra decision**, see §8).
- Loops the 14 target roles × DFW metro.
- Adzuna first (larger quota headroom); JSearch used to fill roles flagged thin (see §5).
- Upserts on `(source, source_job_id)` — re-fetches don't duplicate.
- Every call, success or failure, writes a `job_posting_fetch_log` row.

This is the concrete first slice of the "Market Intelligence Agent" already listed in the
backlog's proposed-agents section — this schema is its foundation, not a separate project.

## 5. Quota budget

Rough allocation across 14 roles:
- Adzuna: ~1,000/mo ÷ 14 ≈ 70 calls/role/month → daily fetch per role is affordable
- JSearch: ~200/mo ÷ 14 ≈ 14 calls/role/month → every-other-day, OR reserved specifically
  for roles where Adzuna's DFW result count is empirically thin

**Blocking pre-work:** Adzuna's actual DFW/Texas posting density for the 14 target roles is
still unverified (flagged in the earlier conversation, not yet checked). Must be checked
empirically — pull a sample query for 3-4 roles in the Dallas metro — before committing the
70-calls/role/month budget on the assumption it'll return meaningful volume. If DFW density
is thin across the board, the Adzuna/JSearch split above needs to shift toward JSearch
despite its smaller quota.

## 6a. Search keyword mapping — RESOLVED, tested against live Adzuna DFW results 2026-08-17

O*NET alternate-titles data does not exist in this codebase (confirmed via Claude Code
audit — `onet_soc_requirements.json` has no alternate/reported-title field, and
`build_onet.py` never ingests O*NET's `Alternate Titles.txt` source). Hand-written
keywords, tested live, is the resolved approach — not a fallback.

| Role (canonical string, matches `data/role_requirements.json` keys) | SOC | Search keyword | DFW result count | Note |
|---|---|---|---|---|
| Software Engineering Intern | 15-1252.00 | `software engineering` | 3,114 | strong |
| Computer Engineering Intern | 17-2061.00 | `computer engineering` | 2,571 | strong |
| Embedded Systems Intern | 17-2061.00 | `embedded systems` | 357 | good |
| Business Analyst Intern | 13-1111.00 | `business analyst` | 764 | good |
| Finance Intern | 13-2051.00 | `finance analyst` | 115 | moderate |
| Operations Intern | 13-1199.00 | `business operations` | 5,614 | strong but noisy — see §6b |
| Aerospace Engineering Intern | 17-2011.00 | `aerospace engineering` | 440 | good |
| Flight Systems Intern | 17-2011.00 | `flight systems` | 115 | moderate |
| Mechanical Analysis Intern | 17-2141.00 | `mechanical engineering` | 1,627 | strong |
| Lab Assistant | 19-4021.00 | `lab assistant` | 226 | moderate |
| Pre-Health Clinical Volunteer | 31-9092.00 | `clinical volunteer` | 23 | thin — accepted known gap, see below |
| Research Assistant | 19-4061.00 | `research assistant` | 522 | good |
| People Operations Intern | 13-1071.00 | `human resources` | 3,480 | strong but noisy — see §6b |
| Student Success Peer Mentor | 21-1012.00 | `peer mentor` | 166 | moderate |

**Pre-Health Clinical Volunteer — accepted known coverage gap, cross-vendor confirmed.**
Tested exact phrase (0, DFW and nationwide) and broad keyword (23, DFW) on Adzuna —
consistently thin across every phrasing tried. Cross-checked against JSearch/OpenWebNinja
(2026-08-17, working subscription, same query/location): **0 results.** Two independent
vendors now agree this role has near-zero indexed volume, not a keyword-phrasing problem
on either platform. Read: clinical volunteer positions are largely posted through
hospital/nonprofit portals directly, not aggregated onto either platform's index. No
further keyword tuning planned for this role on either vendor; the fetch pipeline should
handle low/zero-result roles gracefully (already a requirement per the "never cache
failures" principle — a thin result set is not a failure, don't let it look like one
downstream).

## 6b. Entry-level/intern filtering — RESOLVED, tested live 2026-08-17

**Vendor-side filter param: confirmed not usable.** Tested `job_type=placement student`
(third-party-documented value, UK terminology for internship/co-op) against Adzuna's US
search endpoint (`/v1/api/jobs/us/search/1`) — returned `400 Bad Request`, not a silent
no-op. Confirms this parameter/value is not recognized on the US index. No further vendor-
param testing planned; Adzuna's official docs page does not list a seniority/experience-
level parameter for the search endpoint, and this negative result closes off the one
promising third-party lead.

**Resolved approach: client-side title filtering, applied post-fetch, before writing to
`job_postings`.** No extra API calls — filtering happens on data already retrieved.

```python
INCLUDE_SIGNALS = [
    "intern", "internship", "co-op", "coop", "entry level", "entry-level",
    "new grad", "new graduate", "student", "trainee", "associate",
]

EXCLUDE_SIGNALS = [
    "senior", "sr.", "sr ", "principal", "staff", "lead", "director",
    "vp", "vice president", "head of", "manager", "chief", "10+ years",
    "5+ years", "7+ years",
]

def is_entry_level(title: str) -> bool:
    """
    Conservative filter: title must contain at least one entry-level signal
    AND must not contain a seniority-exclusion signal. Applied post-fetch,
    before writing to job_postings — costs no extra API calls.
    """
    t = title.lower()
    has_signal = any(s in t for s in INCLUDE_SIGNALS)
    has_exclusion = any(s in t for s in EXCLUDE_SIGNALS)
    return has_signal and not has_exclusion
```

Filters on `title` only (not `description`) for now — cheaper and more reliable than
scanning full snippet text; revisit if filtered volume per role proves too thin (see
follow-up below).

**Known limitation, accepted:** this will under-match, not over-match — some genuine
entry-level postings don't say "intern"/"entry level" in the title, only in the body.
Accepted tradeoff: missing real postings is a safer failure mode for grounding data than
including senior-role postings in the corpus. This does mean effective post-filter volume
per role will be meaningfully smaller than the raw counts tested in §6a.

**Follow-up required once the scheduler is actually built (not before):** re-check filtered
result volume per role against the raw §6a counts. If filtered volume for any role drops
too low to compute a meaningful aggregate (e.g. single digits), that role may need the same
"accepted known gap" treatment given to Pre-Health Clinical Volunteer, rather than forcing
a fix. Do not pre-solve this now — it's only checkable once real filtered data exists.

## 6. Skill extraction

Postings return free text, not tagged skills.

- **Phase 1 (cheap, do this first):** keyword-match posting text against the existing
  O*NET skill taxonomy per role — you already have this vocabulary from the O*NET
  expansion work (PR #37). No new AI calls, no new cost.
- **Phase 2 (only if Phase 1 proves too lossy):** LLM-extract skills per posting. This is
  a per-posting AI call — do not build this until Phase 1's output has been reviewed
  against real postings and found insufficient. Do not build both phases speculatively.

## 7. Wiring into FIT/SHIFT — CORRECTED per 2026-08-17 audit

**Original assumption was wrong.** `build_student_context` already exists as a live,
exercised seam — not something to build from scratch:
- `base.py:201` — default implementation
- `base.py:180` — `build_messages()` calls `self.build_student_context(student_profile)`
  and serializes the result straight into the prompt
- `fit.py:191` — FIT's override, already composes `market_requirements`
  (`get_market_requirements`) and `role_context` (`get_shift_signals`) from target roles
- `shift.py:54` — SHIFT's override, same shape: `shift_signals` (local O*NET) +
  `role_trends_for(target_roles)` (live Tavily via `role_research_agent.get_role_trends`)

**Corrected plan:** add a `get_job_postings(target_roles)`-style provider function
(new module, e.g. `market_data.py` alongside the existing O*NET providers) and call it
from inside FIT's and SHIFT's existing `build_student_context` overrides, merging its
output into the dict already being assembled there — same call shape as
`get_market_requirements`/`get_shift_signals`, not a new integration mechanism.

- Provider reads from `job_postings` (DB), never live, never per-request.
- Compute real aggregates in Python before the prompt is built: posting count, % mentioning
  a given skill, top skills by frequency. These are genuine denominators, not LLM-estimated.
- Output merges into the same structured context block FIT/SHIFT already send to the model —
  contract-validated the same way `market_requirements`/`shift_signals` already are, via
  the existing `validate_data(data, student_profile) -> list[str]` guard (confirmed current
  signature, `base.py:215`, single call site `base.py:161`). Do not introduce a second
  validation mechanism.
- **`target_role` matching (confirmed real constraint, was unverified in original spec):**
  the 14 real target roles are free-text string keys in `data/role_requirements.json`
  (e.g. `"Software Engineering Intern"`, `"Embedded Systems Intern"` — 14 roles + a
  `_notes` key, 15 top-level keys total). Not slugs, not SOC codes. `job_postings.target_role`
  must match these literal strings exactly, or the join fails silently. §12 below tracks
  the open decision on how postings get mapped to these strings.

## 7a. Client implementation pattern — confirmed from audit, do not deviate

- **No retry/backoff exists anywhere in this codebase** (`OpenRouterClient._send` makes
  exactly one request; transient-failure classification is metadata for the caller, not
  an actual retry). The Adzuna/JSearch client should follow the same shape — classify
  failures (network/timeout/429/5xx = transient) and let the scheduler's next scheduled
  run be the retry, not an in-request retry loop.
- **Credential loading:** match OpenRouter's pattern (raise a typed config error if
  missing), not Tavily's degrade-to-None pattern — job postings aren't optional-with-
  fallback the way Tavily search is; a missing credential should fail the scheduled job
  loudly, not silently skip a role.
- **Timeout:** explicit param, no reliance on a library default. No DeepSeek-scale
  budget needed here (these are simple REST calls, not reasoning-model calls) — a
  conservative fixed timeout (e.g. 15-20s, matching Tavily's `_TAVILY_TIMEOUT_SECONDS`
  precedent) is appropriate.
- **Injection bounding:** any posting text (title, description snippets) that reaches a
  prompt must go through the same field-length/list-size capping already established in
  `role_research_agent.py` (`_MAX_FIELD_CHARS = 120`, `_MAX_LIST_ITEMS = 20`) — reuse
  those constants or mirror their values, don't reinvent bounds.
- **Test convention:** hand-written `Fake*` client classes + `monkeypatch.setattr`
  (confirmed pattern in `test_role_research_agent.py`, `test_career_features.py`) — no
  cassette library (`responses`, VCR) is used anywhere in this suite; don't introduce one.

## 8. Open decisions before a build prompt can be written

1. **Scheduler infra — RESOLVED.** GitHub Actions scheduled workflow hitting a new
   protected FastAPI endpoint, reusing the `keep-render-awake.yml` pattern already
   proven in this repo (confirmed via audit: it's the only `schedule:`-triggered workflow
   that exists, currently just a health-check ping — same trigger mechanism, new target).
   Chosen over a native Render Cron Job service because: (a) free, vs. Render cron's ~$1/
   month floor — trivial either way, but no reason to pay for a second service type when
   an equivalent free mechanism already works in this repo; (b) avoids duplicating
   Adzuna/Supabase credentials into a second secrets store (GitHub Secrets) — the fetch
   logic stays in FastAPI where it already has DB access, GitHub Actions only needs one
   new shared secret to authenticate the trigger call, same shape as the existing
   `X-GradusIQ-Proxy-Secret` pattern. Tradeoff accepted: Render-native cron would have
   given built-in per-job execution logs/monitoring; this approach relies on GitHub
   Actions' run history plus whatever logging the endpoint itself emits — acceptable
   given the cost/complexity difference is minor.
2. **Adzuna DFW density — RESOLVED, see §6a.** Tested live 2026-08-17 across all 14
   roles. 13/14 returned real volume once broad (non-literal) keywords were used; Pre-
   Health Clinical Volunteer confirmed as a genuine, cross-vendor-agreed thin-coverage
   role, not a query problem.
3. **JSearch account — provisioned and working**, OpenWebNinja-direct (not RapidAPI
   marketplace, despite the misleadingly-named `JSEARCH_RAPIDAPI_KEY` env var — worth a
   rename to `JSEARCH_API_KEY` for clarity, low priority, non-blocking). Given JSearch's
   narrowed role (§2), heavy usage isn't expected — account ownership question is
   effectively moot for now.
4. **`target_role` string-matching strategy — RESOLVED, see §6a.** Search keywords are
   hand-written and live-tested against DFW Adzuna results for all 14 roles (2026-08-17).
   The keyword table in §6a is the seed list for the fetch scheduler. Pre-Health Clinical
   Volunteer accepted as a known thin-coverage role, not a query problem to keep chasing.
5. **Entry-level/intern filtering — RESOLVED, see §6b.** Vendor-side filter param tested
   and confirmed unusable on Adzuna's US index (400 error). Client-side title filtering
   function is written and ready to drop into the fetch scheduler. One follow-up remains,
   but it's non-blocking and only checkable after the scheduler runs: verify filtered
   volume per role isn't too thin once real data exists (see §6b).
6. **RLS / flat-file-to-Postgres precedent — needs Deepak's explicit sign-off, not yet
   decided.** Per §3's corrected design notes: `job_postings` would be the first reference
   dataset in this repo to move from flat-file caching to Postgres entirely, and should
   follow the `institutions`/`academic_term_dates`-style RLS-enabled + public-read pattern
   if it does. This is a real architectural choice (does all future reference data go to
   Postgres from here on, or was flat-file caching deliberate for some data and not
   others?), not a formality — flagged for a decision before the schema migration is
   finalized, not assumed.

## 9. Explicitly out of scope for this pass

- Skill extraction Phase 2 (LLM-based) — gated on Phase 1 review, see §6
- Personalized "new posting for you" student-facing feed/notification — this spec only
  builds the data layer; matching new postings to individual students is a join against
  student profile data, a separate feature on top of this table
- Any LinkedIn data source — rejected, see §2

## 10. Audit checklist — status as of 2026-08-17, mostly complete

- [x] Confirmed no pre-existing Adzuna/JSearch credentials in the repo before this work
      started (clean — only stale prose mentions in README/docs referencing the
      integration as "planned")
- [x] Confirmed no scheduled-job pattern exists — `keep-render-awake.yml` is the only
      `schedule:`-triggered workflow, a health-check ping, now the template for §8.1's
      resolved scheduler approach
- [x] Adzuna DFW density check run for all 14 roles, see §6a
- [x] `role_research_cache.json` structure confirmed — flat dict, no TTL field, no
      module-level memoization at this file (the `_role_soc_cache` memoization referenced
      in the backlog is a different module, `market_data.py`'s `_load_onet()`)
- [x] `validate_data` signature confirmed current and matches backlog:
      `(data, student_profile) -> list[str]`, single call site `base.py:161`
- [x] `build_student_context` confirmed to already exist for FIT/SHIFT — corrected §7
      accordingly, this was the one real halt during the process
- [x] External-API client pattern documented (OpenRouter + Tavily) — no retry/backoff
      exists anywhere, credential loading raises on missing, explicit timeouts, file-based
      revalidate-on-read caching, injection bounds via field/list caps — see §7a
- [x] Test-mocking convention confirmed — hand-written `Fake*` + `monkeypatch`, no
      cassette library — see §7a
- [x] Scratch client scripts built and unit-tested (`scripts/job_postings/adzuna_client.py`,
      `jsearch_client.py`) — dry-run by default, 16 passing tests, minimal live-call
      footprint maintained throughout this investigation
- [x] Draft schema migration staged (not applied):
      `supabase/migrations/20260817210000_job_postings_reference_draft.sql` — RLS
      corrected per real Postgres precedent, see §3
- [ ] **Open, needs Deepak's decision, not Claude Code's:** the flat-file-to-Postgres
      precedent question, §8 item 6
- [ ] **Housekeeping, non-blocking:** `test.py` in repo root has a hardcoded Adzuna
      credential and is untracked — delete or gitignore before any `git add -A`
- [ ] **Housekeeping, non-blocking:** rename `JSEARCH_RAPIDAPI_KEY` → `JSEARCH_API_KEY`
      in `.env`/`.env.example` for clarity (it's actually an OpenWebNinja-direct key)
