# Status

**Updated 2026-08-19. This supersedes the earlier "parked" status — the postings work is
active again.**

## Plan

The ATS postings fetcher will be wired **alongside two job search APIs**, feeding the
**nightly cache** described in `data/ats_fetcher/README.md`. That gives the skill
vocabulary / matcher work the real postings corpus it was waiting on.

Deepak owns integration. The `ats-fetcher` branch is pushed and pending merge to `dev`.

**Disregard PR #20 (closed, not merged).** It was closed when frequency claims were out
of pilot scope. That is no longer the plan and the closure should not be read as the
work being declined.

## What exists

On branch `ats-fetcher`, in `data/ats_fetcher/`:

- `fetch_postings.py` — **stage 1 only.** Fetches 5 ATS platforms, normalizes them to one
  shape, writes CSV. Its own docstring: "Does NOT touch Supabase, does not extract."
- `build_skill_terms.py` — cross-references the O*NET vocabulary against fetched postings
  (default mode), or filters the reviewed file into `skill_terms.csv` (`--filter`).
- `skill_terms_review.csv` — the permanent record of every term considered. Still the
  reusable artifact it always was.
- `README.md` — the full build spec. `DEDUP.md` — cross-source identity, added for the
  job search API sources.
- One pull on disk, not committed (gitignored): 153 postings, 2 employers, 2026-08-05.

## What the nightly cache still needs

None of this arrives with the merge:

- **A scheduler.** There is no scheduling infrastructure in this repo — no
  `.github/workflows/`, no `crons` key in `vercel.json`, no Supabase edge function, no
  `pg_cron` in any migration. This has to be chosen and built.
- **The Supabase write**, including upsert on `(source_ats, external_id)`.
- **The derived fields** from README §3 — `role_family`, `is_dfw`, `seniority`,
  `matched_skills`, `salary_min`/`salary_max`. None are implemented.
- **The 7-day rolling retention** on raw description text, plus the `DELETE` that
  enforces it.
- **Cross-source identity** per `DEDUP.md` — needed before the job runs nightly, not
  after. Re-deriving identity across a populated table is much worse than getting it
  right up front.

Note that the existing cache in this codebase (`role_research_agent.py`) is lazy
read-through expiry, a different shape from a scheduled push job. One principle carries
over: an entry with no timestamp counts as expired, not valid-forever.

## The vocabulary is not yet evidence-backed

`skill_terms.csv` holds 8,708 terms, but only **121 of 8,725** candidates ever fired
against the 153-posting corpus. The other ~98.6% came from O*NET and were auto-kept with
no posting evidence; just 44 terms were flagged for hand review, of which 17 were cut.

The README's own target is "roughly 60–120 skills, reviewable by hand" — so the shipped
file is far above spec, and the 121 that actually fired land right in that range. Once
the nightly cache accumulates real volume, re-running `build_skill_terms.py` against it
is what turns this from unvalidated vocabulary into something grounded. That re-filter is
the payoff, and it is the reason the review file was worth preserving.
