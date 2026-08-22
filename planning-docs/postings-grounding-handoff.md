# Postings grounding — handoff

Branch: `feat/postings-grounding` (off `dev`) · 12 commits · 544 tests passing
PR: https://github.com/bonaguidin/GradusIQ/pull/49
Owner going forward: **Deepak**
Written 2026-08-19

---

## The finding that should shape your review

**The five ATS adapters reach one employer.**

The 44-employer DFW list was researched against every platform. Exactly one —
Match Group, on Lever — is on a platform the puller supported. The DFW
enterprise employer set is Workday, iCIMS, Oracle Cloud HCM, Taleo, Avature,
SuccessFactors, Eightfold and UKG.

| Platform | Employers | Adapter exists |
|---|---:|---|
| Workday | 19 | **yes, new** |
| Proprietary / self-hosted | 5 | no, and won't |
| iCIMS | 4 | no |
| Oracle Cloud HCM | 4 | no |
| Taleo | 3 | no |
| SuccessFactors | 2 | no |
| Avature | 2 | no |
| Eightfold / UKG / Talent Community | 3 | no |
| lever | 1 | yes |
| unconfirmed | 1 | — |

So the Workday adapter is the difference between reaching 1 employer and 13.
Thirteen employers have confirmed live posting counts totalling **6,092** —
against an existing corpus of 153.

The second-order point: because most DFW employers are unreachable directly,
**Adzuna and JSearch carry more weight than the original plan assumed.** They
index across all these platforms. That's worth factoring into the quota
budget.

---

## What you need to do

1. **Review and apply the migration.** `supabase/migrations/20260817210000_...`
   is still staged and unapplied. Its own precedent-check note asks for your
   sign-off on this being the repo's first flat-file-to-Postgres dataset.
2. **Add four repo secrets**: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`,
   `SUPABASE_URL`, `SUPABASE_SECRET_KEY`. Until they exist the nightly
   workflow skips with a notice rather than failing.
3. **Spend one call on `--dump-shape`.** The Adzuna and JSearch field maps in
   `normalize.py` are written from documented response shapes, not captured
   ones. This is the only unverified code on the branch:
   ```
   python scripts/job_postings/ingest.py --source adzuna --role "Finance Intern" --live --dump-shape
   ```
   It prints what the vendor actually sent against what the map expects.
4. **`uv sync`.** `pypdf` and `python-docx` are declared but missing locally,
   which is why 26 test modules can't collect. Predates this work.
5. **Resolve the JSearch credential mismatch** your own client docstring
   flags — `JSEARCH_BASE_URL` points at OpenWebNinja-direct while the key is
   named `JSEARCH_RAPIDAPI_KEY`. Not reachable from Kasheia's machine.

---

## What's on the branch

### Schema — `supabase/migrations/20260817210000_...`

Your draft, amended in place rather than layered under an ALTER, since it had
never been applied. Your tables, comments and RLS rationale are untouched;
additions are marked `AMENDED`. What changed:

- **`url`** — the draft had no equivalent, and cross-source dedup depends on
  it entirely.
- **Cluster layer** — `posting_clusters`, `posting_identity_keys`,
  `posting_cluster_merges`. `(source, source_job_id)` is unchanged and still
  answers "did this source re-send this listing"; it cannot answer "have I
  counted this job under another source," which is new now that vendors
  syndicate the same ATS listings we fetch directly.
- **`raw_payload` nullable, 90-day window** — sized from measurement.
  Descriptions average 5.0 KB, and O*NET occupies none of the 500 MB tier
  because it's a flat file. Quota, not storage, is the binding constraint.
- **`location_kind`** — records *why* `is_dfw` came out as it did, so the
  contested remote call is one `UPDATE` rather than a re-pull.
- **`ats_platform` widened** — separates "what platform is this employer on"
  (data) from "can we fetch it" (a property of which adapters exist, in code).

### Code — `scripts/job_postings/`

| File | What | Verified? |
|---|---|---|
| `identity.py` | Cross-source identity per `DEDUP.md` | **yes** — 153/153 real postings |
| `workday.py` | Workday adapter, new sixth source | **yes** — live probe + full paged fetch |
| `normalize.py` | Adzuna/JSearch → row shape | **no** — see step 3 above |
| `ingest.py` | Fetch → normalize → dedup → upsert | logic tested, no live run |
| `retention.py` | 90-day payload expiry | cutoff tested |
| `load_employers.py` | DFW list → `employers` | tested against the real CSV |
| `resolve_slugs.py` | Slug worksheet + live prober | tested |

Everything is dry-run by default, matching your vendor clients.

### Scheduler — `.github/workflows/postings-ingest.yml`

The repo's first workflow. 07:15 UTC nightly, Adzuna only — JSearch's ~200/mo
can't take a nightly sweep. Gated on a config check so it skips cleanly until
your secrets exist. Swap to `pg_cron` if you prefer; everything real is in the
Python entrypoint.

---

## Known gaps, deliberately left

- **Seven Workday employers have a host but no `/site` path** — BofA, USAA,
  Capital One, PwC, Accenture, Globe Life, Comerica. The endpoint can't be
  built without it. `parse_workday_slug` returns `None` rather than guessing
  `careers`, which would 404 or, worse, hit a different site on the same
  tenant and file postings under the wrong board. One lookup each.
- **23 employers are on platforms with no adapter.** iCIMS (4) and Oracle
  Cloud (4) are the next-biggest buckets if this is worth extending.
- **`role_families.yaml` is remapped** to the 14 student roles and matches
  `role_requirements.json` exactly. First pass, unreviewed — the boundaries
  worth a second look are Computer Engineering vs. Embedded Systems, and Lab
  Assistant vs. Research Assistant.

  **Expect ~99% NULL from employer boards, and expect that to be right.** Of
  153 real postings, 2 are student-shaped — 1.3%. Atmos returns "Sr
  Applications Developer", "Service Technician", "Mgr Safety". That is what an
  employer's own board is, and it splits the sources by purpose:
  employer-direct for breadth, vendors for student roles. Anyone reading a low
  mapped-count as broken rules will loosen phrases until general postings match
  student families, which is worse than mapping nothing.
- **The CSV's `target_role_families` still uses the mid-career taxonomy**,
  deliberately. It records what the research assumed, and rewriting it inside a
  loader would bury a decision.
- **The vocabulary question is settled.** `skill_aliases.yaml` (now 46 skills)
  is the vocabulary; `skill_terms_review.csv` is retired as a source and kept
  as the rejection record — do not delete it. Its own frequency data decided
  it: of 8,725 terms only 121 fired, and the hardest-firing are Training,
  IMPACT, Testing, Experian, Client, Shape, MAGIC. Experian is a PMG client,
  not a skill. Fire count measures collision, not relevance. Seven genuine
  skills were harvested; 46 is still under §4's 60–120 target.
- **Not built**: the retrieval layer FIT/GAP/SHIFT would call, and the
  GAP/SHIFT prompt updates. FIT was deliberately closed — it stays out of
  naming employers, and its prompt already forbids it.

---

## Things worth knowing before you trust a number

- `fetch_postings.py` has **four** adapters, not five. There is no Recruitee
  fetcher anywhere except as a stub. The `ats-fetcher` commit message says
  otherwise.
- Only **greenhouse and lever** have ever been run for real. Ashby and
  SmartRecruiters are written and unexercised.
- Comerica's `fifththird` Workday tenant is **correct** — Fifth Third
  completed its acquisition of Comerica in February 2026.
- `data/onet/STATUS.md` used to say this work was parked. It was rewritten
  2026-08-19 and is now accurate. PR #20 is closed but was not a rejection.
