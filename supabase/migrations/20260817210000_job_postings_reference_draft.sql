-- DRAFT -- staged, NOT applied. Written for review alongside
-- scripts/job_postings/{adzuna_client,jsearch_client}.py, ahead of any real
-- fetch-scheduler or FIT/SHIFT integration. Do not run `supabase migration up`
-- against this file until Deepak has reviewed it.
--
-- ============================================================================
-- AMENDED 2026-08-19 on feat/postings-grounding -- ATS SOURCES FOLDED IN
-- ============================================================================
--
-- Amended in place rather than layered under a follow-up ALTER migration:
-- this file has never been applied anywhere (confirmed -- no sibling
-- migration references job_postings), so there is no migration history to
-- preserve and an ALTER on top of an unapplied CREATE would only obscure the
-- final shape. Deepak's original design, comments, and RLS rationale are
-- untouched below; everything added here is marked AMENDED.
--
-- What changed, and why:
--
-- 1. `source` now admits the five ATS platforms alongside the two vendors.
--    The ATS fetcher (data/ats_fetcher/ on the ats-fetcher branch) and the
--    vendor clients are becoming one corpus, so they need one table. Keeping
--    them apart would mean cross-source dedup could not be expressed at all.
--
-- 2. `url` added -- MISSING FROM THE ORIGINAL DRAFT AND LOAD-BEARING. Three
--    separate things need it: the brief requires posting URL as a stored
--    field, spot-checking a suspicious row requires "go look at this one",
--    and above all the cross-source dedup in data/ats_fetcher/DEDUP.md §3.1
--    recovers an ATS job id by parsing it out of the apply URL. Without this
--    column the exact-match dedup path cannot exist and everything falls back
--    to fuzzy matching.
--
-- 3. `is_dfw` added. DEDUP.md §3.2 clusters on this rather than on raw
--    location text, because syndicators rewrite location strings freely
--    ("Dallas, TX" / "Dallas-Fort Worth" / "Dallas Metroplex") and raw-text
--    matching splits clusters that should merge.
--
-- 4. `posting_identity` added -- the cluster layer. The original unique key
--    (source, source_job_id) is correct and unchanged: it answers "did this
--    source re-send this listing." It cannot answer "have I already counted
--    this job under a different source," which is a new question now that
--    job search APIs syndicate the same ATS listings this repo also fetches
--    directly. See posting_clusters below.
--
-- 5. `raw_payload` is now NULLABLE, was `not null`. Retention is a 90-day
--    rolling window rather than forever or the 7 days an earlier brief
--    proposed. Sized from measured data, not guessed: descriptions in the
--    real 153-posting pull average 5.0 KB (p90 7.8 KB), and O*NET turns out
--    to occupy none of the 500 MB tier at all (it is a 5.6 MB flat file in
--    data/reference/, never in Postgres -- the same finding as the precedent
--    check above). So storage is not the binding constraint the 7-day window
--    was defending against. Quota is: re-running skill extraction against a
--    changed vocabulary must not require re-fetching, and that vocabulary is
--    near-certain to change (only 121 of 8,725 candidate terms have ever
--    fired against a real posting). 90 days covers a realistic iteration
--    loop; `not null` forever was unbounded growth with no eviction path.
--
-- 6. `location_kind` added, adopted from the ats-puller-draft skeleton's
--    sql/draft_tables.sql. It records WHY is_dfw came out the way it did.
--    Whether a fully-remote role open to DFW residents counts as DFW is a
--    product question, not a string-matching one, and a bare boolean stores
--    the verdict while throwing away the reasoning. Re-deriving that reasoning
--    months later means re-running a classifier that has since changed, so the
--    decision would not actually be revisitable. With this column it is one
--    statement:
--
--      update job_postings set is_dfw = true
--       where location_kind in ('remote_us', 'remote_anywhere');
--
--    Cost is one text column. Drop it only once the remote call is settled.
--
-- Adds job_postings (fetched listings, deduped per vendor) and
-- job_posting_fetch_log (one row per fetch attempt, for quota accounting and
-- staleness detection) -- the schema outstanding-fixes.md's "Job posting
-- data" section calls for before any live vendor integration can exist:
-- cache-first architecture is a hard requirement given Adzuna's ~1,000/mo and
-- JSearch's ~200/mo free-tier quotas, not an optimization.
--
-- ============================================================================
-- PRECEDENT CHECK -- FLAG FOR DEEPAK: THIS IS NOT A DROP-IN-THE-SAME-PATTERN
-- MIGRATION, IT IS THE FIRST OF ITS KIND
-- ============================================================================
--
-- The two datasets this task's brief pointed to as precedent --
-- role_research_cache and the O*NET reference catalog -- are BOTH flat JSON
-- files (data/.cache/role_research_cache.json,
-- data/reference/onet_soc_requirements.json), confirmed by grepping every
-- migration under supabase/migrations/ for either name: zero matches. Neither
-- has ever lived in Postgres. There is no "shared reference data skips RLS"
-- precedent to inherit from them, because neither of them went through RLS
-- at all -- they went through the filesystem instead.
--
-- The precedent that DOES exist, for every genuinely-public reference table
-- actually built in Postgres so far (institutions, grade_point_map,
-- academic_term_dates, course_catalog), is the opposite of "no RLS": each
-- enables RLS and adds exactly one permissive SELECT policy for
-- {anon, authenticated}, paired with a revoke of anon's write grants
-- (20260801175516_revoke_anon_writes_on_reference_tables.sql;
-- academic_term_dates repeats the same pair inline). job_postings below
-- follows THAT established convention rather than the "no RLS" assumption
-- this migration was originally briefed with, since it is public
-- job-listing data with the same shape (service-role-written, read by
-- anyone) as those tables.
--
-- job_posting_fetch_log is different: it's an internal operational log (call
-- counts, quota usage, error detail from a vendor), not something a
-- frontend page needs to read. RLS is enabled with NO policies at all, so it
-- defaults to deny for anon/authenticated and stays readable/writable only
-- by the service role (which bypasses RLS entirely, same as every fetch
-- script in this repo that writes with SUPABASE_SECRET_KEY).
--
-- Net: if this table set is built, job_postings would be this repo's first
-- reference dataset to move from flat-file to Postgres. Worth Deepak's
-- explicit sign-off on that move alone, independent of the RLS question
-- above -- it's a bigger decision than "which policy shape."
--
-- ============================================================================
-- DEDUP / CACHE-KEY DESIGN
-- ============================================================================
--
-- unique (source, source_job_id) is the vendor-native identity: Adzuna and
-- JSearch both hand back a per-listing id that is stable across repeat
-- fetches of the same posting, so re-fetching the same search a week later
-- and upserting on this key is how the same listing avoids duplicating
-- rather than accumulating one row per fetch. It is NOT unique on
-- (source, target_role, source_job_id) -- a posting fetched under two
-- different target_role queries (plausible: a hybrid SWE/hardware intern
-- posting could surface under both "Software Engineering Intern" and
-- "Computer Engineering Intern" searches) is the same real-world listing and
-- should stay one row, not fork per query. target_role is kept as a plain
-- column for filtering, not folded into the identity.
--
-- fetched_at (not source_job_id alone) is what a TTL/staleness check reads:
-- outstanding-fixes.md flags "no TTL primitive exists anywhere in the
-- codebase" as a specific gap for posting data, which goes stale in days,
-- not years like O*NET. A consumer asking "is this posting data fresh
-- enough to show" compares now() - fetched_at against a TTL constant, not
-- posted_date (the vendor's own listing date, which is metadata about the
-- posting, not about when GradusIQ last saw it).
--
-- job_posting_fetch_log is the OTHER half of the TTL/quota answer: "when did
-- we last fetch target_role X from source Y, and how many quota units did
-- that cost" -- a fetch scheduler reads the latest row per (source,
-- target_role) to decide whether a re-fetch is due, without having to
-- infer that from job_postings.fetched_at aggregates (which would silently
-- go blank for a target_role/source pair that returned zero results, a
-- state fetch_log's results_count=0 + status='success' represents
-- explicitly, that job_postings alone cannot represent as a row).

-- AMENDED: the source vocabulary. Two vendors plus five ATS platforms, but
-- the platforms are at three different maturity levels and the constraint
-- deliberately admits all of them anyway, so that adding a fetcher never
-- requires a migration:
--
--   greenhouse, lever          Run for real -- PMG 70 postings, Match Group
--                              83, on 2026-08-05.
--   ashby, smartrecruiters     Adapters written in fetch_postings.py, never
--                              executed against a live board.
--   recruitee                  NO adapter in fetch_postings.py at all. Only
--                              the ats-puller-draft skeleton has a recruitee
--                              module, and that module is a stub. Nothing can
--                              currently write a row with this source.
--
-- Recorded because it is easy to get wrong: the ats-fetcher commit message
-- claims five platforms are normalized, and the ADAPTERS map has four.
create table job_postings (
  id uuid primary key default gen_random_uuid(),
  source text not null check (source in (
    'adzuna', 'jsearch',
    'greenhouse', 'lever', 'ashby', 'smartrecruiters', 'recruitee',
    'workday'
  )),
  source_job_id text not null,
  title text not null,
  company text,
  location text,
  url text,                        -- AMENDED -- see note 2 in the header
  is_dfw boolean,                  -- AMENDED -- see note 3
  location_kind text check (location_kind is null or location_kind in (
    'dfw_metro', 'multi_includes_dfw', 'hybrid_dfw',
    'texas_non_dfw', 'remote_us', 'remote_anywhere', 'non_dfw', 'unknown'
  )),                              -- AMENDED -- see note 6
  posting_identity uuid,           -- AMENDED -- see note 4; FK added below
  target_role text not null,
  skills_extracted jsonb not null default '[]'::jsonb,
  salary_min numeric,
  salary_max numeric,
  posted_date date,
  fetched_at timestamptz not null default now(),
  raw_payload jsonb,               -- AMENDED -- was `not null`; see note 5
  created_at timestamptz not null default now(),
  unique (source, source_job_id),
  constraint job_postings_salary_range check (
    salary_min is null or salary_max is null or salary_max >= salary_min
  )
);

comment on table job_postings is
  'Fetched job listings from Adzuna/JSearch, deduped per vendor listing id. '
  'Shared reference data, not student-owned -- see the precedent-check note '
  'above this table''s CREATE statement for the RLS rationale.';

comment on column job_postings.source_job_id is
  'The vendor''s own listing id (Adzuna: "id"; JSearch: "job_id"). Paired '
  'with source as the true identity -- see the dedup design note above.';

comment on column job_postings.target_role is
  'Which of the 14 data/role_requirements.json role keys this fetch was '
  'searching for, NOT parsed from the listing itself. Filtering only -- not '
  'part of the unique key, since one real listing can legitimately surface '
  'under more than one target_role search.';

comment on column job_postings.skills_extracted is
  'Reserved for a future extraction step (e.g. parsed off raw_payload''s '
  'description text). Defaults to an empty array; nothing populates it yet.';

comment on column job_postings.fetched_at is
  'When GradusIQ last fetched this listing -- the TTL/staleness field. '
  'Distinct from posted_date, which is the vendor''s own listing date.';

comment on column job_postings.raw_payload is
  'The full vendor response for this listing, kept verbatim so a future '
  'extraction pass (skills_extracted, or a field nobody thought to promote '
  'to a column yet) can be re-run without re-fetching from the vendor. '
  'AMENDED: nullable, on a 90-day rolling window -- the retention job nulls '
  'this on rows older than that and keeps the row. Null here means "aged '
  'out", never "this listing had no payload".';

-- AMENDED column comments below.

comment on column job_postings.url is
  'Link to the live posting. Load-bearing for dedup, not just for humans: '
  'ATS URLs embed the job id in the path '
  '(job-boards.greenhouse.io/pmg/jobs/8496729002), so a vendor listing that '
  'links back to an ATS board can recover that board''s own external id and '
  'match a row already fetched directly. See data/ats_fetcher/DEDUP.md §3.1.';

comment on column job_postings.is_dfw is
  'Whether this posting is in the DFW metro, derived from location at '
  'ingest. Cluster matching uses this rather than the raw location string, '
  'which syndicators rewrite freely. Always a definite verdict where a '
  'location was given -- location_kind carries the reasoning, so a contested '
  'call can be reversed later without re-deriving anything.';

comment on column job_postings.location_kind is
  'Why is_dfw is what it is. dfw_metro / multi_includes_dfw / hybrid_dfw are '
  'the true cases; texas_non_dfw / remote_us / remote_anywhere / non_dfw are '
  'the false ones; unknown means no usable location was given. The remote '
  'cases are the point: they are false today, and flipping that is an UPDATE '
  'on this column rather than a re-pull.';

comment on column job_postings.posting_identity is
  'Which cluster of cross-source duplicates this row belongs to. Mutable by '
  'design: a vendor can deliver a listing before the employer''s own ATS '
  'feed surfaces it, and the later ATS row is the exact evidence that two '
  'clusters are one. Null until the identity pass has run on this row.';


-- AMENDED: ATS fetches log here too. Two shape changes that follow from it.
-- First, an ATS run loops employers, not target roles, so target_role becomes
-- nullable and an employer column joins it, with a check that a row carries
-- at least one of the two. Second, quota_used defaults to 1 for the metered
-- vendors but is legitimately 0 for ATS boards, which are public zero-auth
-- endpoints with no quota to spend -- the >= 0 check already allowed that,
-- and the column comment below now says so explicitly. Staleness detection,
-- the log's other job, applies to both kinds of source unchanged.
create table job_posting_fetch_log (
  id uuid primary key default gen_random_uuid(),
  source text not null check (source in (
    'adzuna', 'jsearch',
    'greenhouse', 'lever', 'ashby', 'smartrecruiters', 'recruitee',
    'workday'
  )),
  target_role text,                -- AMENDED -- was `not null`
  employer text,                   -- AMENDED -- ATS runs are per-employer
  fetched_at timestamptz not null default now(),
  results_count integer not null check (results_count >= 0),
  quota_used integer not null default 1 check (quota_used >= 0),
  status text not null check (status in ('success', 'error')),
  error_detail text,
  constraint job_posting_fetch_log_has_subject check (
    target_role is not null or employer is not null
  )
);

comment on table job_posting_fetch_log is
  'One row per fetch attempt against a vendor, for quota accounting '
  '(Adzuna ~1,000/mo, JSearch ~200/mo -- see outstanding-fixes.md''s "Job '
  'posting data" section) and staleness checks. Internal/operational --  '
  'unlike job_postings, nothing here is meant for a frontend page to read '
  'directly, hence no public SELECT policy below.';

comment on column job_posting_fetch_log.results_count is
  'How many listings this fetch returned, INCLUDING zero. A target_role/'
  'source pair that legitimately has no matches still gets a row here with '
  'results_count=0 and status=''success'' -- distinct from status=''error'', '
  'where the vendor call itself failed and results_count should be read as '
  '"unknown", not "zero".';

comment on column job_posting_fetch_log.quota_used is
  'Vendor quota units this fetch consumed. Defaults to 1 (one call = one '
  'unit for both Adzuna and JSearch''s simple per-request pricing); kept as '
  'its own column rather than assumed constant so a future paginated fetch '
  '(quota_used > 1 per logical target_role/source fetch) doesn''t need a '
  'schema change to report itself accurately.';

comment on column job_posting_fetch_log.error_detail is
  'Vendor error message or exception text when status=''error''. Null on '
  'success.';


-- ============================================================================
-- Row level security
-- ============================================================================

-- job_postings: public-read reference data, same posture as institutions,
-- grade_point_map, academic_term_dates, course_catalog -- see the
-- precedent-check note above. Writes happen only via a fetch script running
-- under SUPABASE_SECRET_KEY, which bypasses RLS as the service role.

alter table job_postings enable row level security;

create policy job_postings_read_public
  on job_postings for select
  to anon, authenticated
  using (true);

-- Companion to 20260801175516_revoke_anon_writes_on_reference_tables.sql:
-- strip the Supabase-default `GRANT ALL` write grants at creation time
-- rather than as a later cleanup pass, so this table is never anon-writable
-- even transiently. SELECT is deliberately NOT revoked -- the policy above
-- depends on it.

revoke insert, update, delete, truncate on job_postings from anon;

-- job_posting_fetch_log: RLS enabled, NO policies added. PostgreSQL RLS
-- default-denies any command with no permissive policy, so this table is
-- unreadable and unwritable by anon/authenticated and reachable only by the
-- service role -- deliberate, since this is an internal operational log (see
-- the table comment), not data any page needs to render.

alter table job_posting_fetch_log enable row level security;


-- ============================================================================
-- Indexes
-- ============================================================================

-- "Latest fetch per (source, target_role)" is job_posting_fetch_log's one
-- real access pattern -- a scheduler asking "is a re-fetch due" reads this
-- before deciding to spend quota. DESC on fetched_at so LIMIT 1 against this
-- index answers it directly.

create index job_posting_fetch_log_source_role_fetched_idx
  on job_posting_fetch_log (source, target_role, fetched_at desc);

-- job_postings' own access pattern is "this target_role's postings, freshest
-- first" -- whatever eventually reads this table for FIT/SHIFT grounding
-- asks for one role at a time, not the whole table.

create index job_postings_target_role_fetched_idx
  on job_postings (target_role, fetched_at desc);


-- ============================================================================
-- AMENDED 2026-08-19 -- CROSS-SOURCE IDENTITY AND THE EMPLOYER FLOOR
-- ============================================================================
--
-- Everything below is new on feat/postings-grounding. Nothing above this line
-- was removed; the two tables Deepak drafted keep their shape and rationale.


-- ---------------------------------------------------------------------------
-- posting_clusters -- the layer above (source, source_job_id)
-- ---------------------------------------------------------------------------
--
-- One row per real-world job, however many sources sent it. job_postings rows
-- point here via posting_identity. The problem this exists for: job search
-- APIs syndicate ATS listings, so the same Match Group role can arrive three
-- times on one nightly run under three different vendor ids. Each of those is
-- a separate vote in any skill count, and the ranking that falls out reflects
-- syndication reach rather than the DFW labor market.
--
-- Counting reads clusters. It must never read job_postings rows directly.

create table posting_clusters (
  id uuid primary key default gen_random_uuid(),
  canonical_posting_id uuid,
  match_rule text not null check (match_rule in ('ats_url_id', 'fuzzy', 'seed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table posting_clusters is
  'One row per real-world job posting, grouping job_postings rows that came '
  'from different sources. See data/ats_fetcher/DEDUP.md for the identity '
  'rules. Counting iterates clusters, never job_postings rows.';

comment on column posting_clusters.canonical_posting_id is
  'Which job_postings row represents this cluster. The ATS row always wins '
  'where one exists -- it is the employer''s own feed, so the title is '
  'unrewritten and the posting date is real. Where the cluster is vendor-only, '
  'a fixed configured vendor order decides, so output does not depend on which '
  'source happened to answer first on a given night.';

comment on column posting_clusters.match_rule is
  'How this cluster was formed. ats_url_id is the exact path: an ATS job id '
  'recovered from a vendor listing''s apply URL, matched against a row already '
  'fetched from that board -- no threshold, no false positives. fuzzy is the '
  'employer/title/is_dfw fallback for vendor-native postings, which will '
  'sometimes over-merge and is accepted as failing in the conservative '
  'direction. seed means the cluster started from a single row with no match.';

alter table job_postings
  add constraint job_postings_posting_identity_fkey
  foreign key (posting_identity) references posting_clusters (id)
  on delete set null;

create index job_postings_posting_identity_idx
  on job_postings (posting_identity);


-- canonical_posting_id gets its foreign key here rather than inline, because
-- the reference runs the other way from job_postings.posting_identity and one
-- of the two tables has to exist first. Insert order follows from it: write
-- the posting, then create or find its cluster, then point the cluster back.

alter table posting_clusters
  add constraint posting_clusters_canonical_posting_fkey
  foreign key (canonical_posting_id) references job_postings (id)
  on delete set null;

-- ---------------------------------------------------------------------------
-- posting_identity_keys -- how a cluster is found again
-- ---------------------------------------------------------------------------
--
-- Every identity key a cluster is known by, exact and fuzzy alike, pointing at
-- the cluster it resolved to. One row per key.
--
-- This exists because the alternative does not work. Recovering a cluster by
-- searching job_postings.url for a substring of the key fails two ways: an ATS
-- job id can appear inside a longer id or a query parameter and match the wrong
-- row, and a fuzzy key (employer/title/dfw) corresponds to no URL at all, so
-- the entire fallback path would silently create a new cluster every time and
-- dedup nothing. A keyed table makes both lookups exact and, unlike an
-- in-process cache, makes them survive to tomorrow night's run.
--
-- The key format is owned by scripts/job_postings/identity.py:
--   ats:<board>:<external_id>          exact, recovered from an apply URL
--   fuzzy:<employer>:<title>:<bucket>  inferred

create table posting_identity_keys (
  key text primary key,
  cluster_id uuid not null references posting_clusters (id) on delete cascade,
  created_at timestamptz not null default now()
);

comment on table posting_identity_keys is
  'Identity key -> cluster. Primary key on `key` is what makes a lookup exact '
  'rather than a substring search, and what stops two clusters from claiming '
  'the same key. See data/ats_fetcher/DEDUP.md.';

create index posting_identity_keys_cluster_idx
  on posting_identity_keys (cluster_id);


-- ---------------------------------------------------------------------------
-- posting_cluster_merges -- why two clusters became one
-- ---------------------------------------------------------------------------
--
-- Cluster assignment happens at ingest, but it cannot be write-once. A vendor
-- can deliver a posting on Monday that lands in a fuzzy cluster, and the
-- employer's own ATS feed can first surface the same job on Tuesday -- the
-- Tuesday row is exact evidence that Monday's cluster belongs elsewhere.
--
-- When a count later looks wrong the question will be "what got merged into
-- what, and on what evidence." That has to be answerable from a table rather
-- than by re-running the pipeline against data that has since changed.

create table posting_cluster_merges (
  id uuid primary key default gen_random_uuid(),
  absorbed_cluster_id uuid not null,
  surviving_cluster_id uuid not null references posting_clusters (id) on delete cascade,
  match_rule text not null check (match_rule in ('ats_url_id', 'fuzzy')),
  triggered_by_posting_id uuid references job_postings (id) on delete set null,
  merged_at timestamptz not null default now(),
  constraint posting_cluster_merges_distinct check (
    absorbed_cluster_id <> surviving_cluster_id
  )
);

comment on table posting_cluster_merges is
  'Audit trail for cluster merges. absorbed_cluster_id is deliberately NOT a '
  'foreign key -- the row it pointed at is gone by the time the merge is '
  'recorded, and keeping the dead id readable is the entire point of the log.';


-- ---------------------------------------------------------------------------
-- employers -- the DFW list
-- ---------------------------------------------------------------------------
--
-- NOTE ON SCOPE: the original justification for this table was that FIT must
-- never fabricate an employer name, so it needed a floor to fall back to.
-- That justification no longer applies -- FIT is staying out of the business
-- of naming employers at all (decided 2026-08-19), and its prompt already
-- forbids it. What still earns this table its place is confirmed_roles: a
-- hand-assembled list of DFW employers hardens into evidence as real postings
-- come back from each one. Worth re-confirming before anything depends on it.
--
-- Not loadable yet: dfw_employers_ats.csv (44 rows) has not been supplied.

create table employers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text,
  sector text,
  dfw_location text,
  domain text,
  -- Two different questions, and conflating them is what the first version of
  -- this constraint did. This column answers "what platform is this employer
  -- on", which for the real DFW list is mostly enterprise HCM: of 44
  -- employers, 19 are Workday and exactly ONE is on any of the five platforms
  -- the fetcher supports. Restricting this to the fetchable five would have
  -- rejected 43 of 44 rows on insert and thrown away hard-won research.
  --
  -- "Can we fetch it" is a property of which adapters exist, lives in code
  -- (scripts/job_postings/), and changes when someone writes one. It is
  -- deliberately not encoded here.
  ats_platform text check (ats_platform is null or ats_platform in (
    -- fetchable today
    'greenhouse', 'lever', 'ashby', 'smartrecruiters', 'recruitee', 'workday',
    -- known, no adapter
    'icims', 'oracle_cloud', 'taleo', 'successfactors', 'avature',
    'eightfold', 'ukg', 'talent_community', 'proprietary'
  )),
  priority integer,
  checked_date date,
  notes text,
  target_role_families jsonb not null default '[]'::jsonb,
  confirmed_roles jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (name)
);

comment on column employers.priority is
  'Research tier from the source CSV, 1-5. Work-ordering for slug lookup, not '
  'a ranking of the employer.';

comment on column employers.checked_date is
  'When someone last confirmed this employer''s ATS board actually exists and '
  'is on the platform claimed. Null for every row in the initial load -- see '
  'the note on slug below.';

comment on column employers.notes is
  'Free text from the source CSV. Mostly hypotheses about which ATS an '
  'employer is likely on ("Enterprise HCM likely -- check for '
  'myworkdayjobs.com"), which is research to be done rather than fact.';

comment on column employers.slug is
  'The identifier in the employer''s own careers URL, and the thing the ATS '
  'fetcher cannot work without. NULL for all 44 rows of the initial load: '
  'that column was never filled in. So this table currently describes who to '
  'target, not who can be fetched.';

comment on column employers.ats_platform is
  'Nullable on purpose: the source CSV has this column only partly filled, '
  'and an unknown ATS is a real state rather than a data error. An employer '
  'with a null platform simply is not reachable by the ATS fetcher yet.';

comment on column employers.target_role_families is
  'Which role families this employer was picked as a target for -- an '
  'assumption carried in from the hand-built list.';

comment on column employers.confirmed_roles is
  'Role families for which a real posting has actually come back from this '
  'employer. Starts empty and only ever grows from evidence. The difference '
  'between this and target_role_families is the difference between what the '
  'list guessed and what the corpus proved.';


-- ---------------------------------------------------------------------------
-- Row level security for the amended tables
-- ---------------------------------------------------------------------------
--
-- employers follows job_postings: public-read reference data, service-role
-- writes, matching the institutions / grade_point_map / course_catalog
-- convention the precedent check at the top of this file established.

alter table employers enable row level security;

create policy employers_read_public
  on employers for select
  to anon, authenticated
  using (true);

revoke insert, update, delete, truncate on employers from anon;

-- posting_clusters, posting_cluster_merges and posting_identity_keys follow
-- job_posting_fetch_log instead: RLS enabled, no policies, so they
-- default-deny to anon and authenticated and stay service-role only. All
-- three are ingest-internal bookkeeping. Anything a page needs to render
-- reaches job_postings through posting_identity, which is public-readable
-- already. posting_identity_keys in particular should never be public: its
-- fuzzy keys embed normalized employer and title strings, which is inference
-- about the corpus rather than data any reader asked for.

alter table posting_clusters enable row level security;
alter table posting_cluster_merges enable row level security;
alter table posting_identity_keys enable row level security;


-- ---------------------------------------------------------------------------
-- Indexes for the amended access patterns
-- ---------------------------------------------------------------------------

-- The exact-match dedup path looks up "have I already stored this URL",
-- once per incoming vendor listing per night. Partial, because rows with no
-- URL are never probed this way.

create index job_postings_url_idx
  on job_postings (url)
  where url is not null;

-- The retention job asks for rows whose payload is older than the window and
-- has not already been nulled. Partial for the same reason: once a payload is
-- nulled the row never qualifies again, so it should not stay in the index.

create index job_postings_raw_payload_age_idx
  on job_postings (fetched_at)
  where raw_payload is not null;
