<!-- Archived from planning-docs/outstanding-fixes.md (as of 413b243), lines 41-92. Content below is unchanged. -->

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

~~All quality metrics are clean. The residual 3/4 is whole-response terseness — run 4 dropped O*NET scores too, not just postings — so it is generic instruction-following variance, not postings avoidance. Do not chase it with an output-contract change; that would optimize against noise at n=4.~~ **Wrong — retested 2026-09-28, live, same code/prompt/model as this table** (`git log` confirms no commits touched `fit.py` or the FIT prompt since this section was written). 20 fresh runs (n=15 plus an earlier same-session n=5, one student, one covered role) put the citation rate at **20% (4/20), not 75%.** The n=4 figure was sampling noise, not a stable baseline. Length-crowding isn't the mechanism either: cited rationale averaged 461.5 chars against 273.6 for non-cited runs — citing runs *longer*, not shorter, when it happens at all, so verbosity isn't squeezing the citation out. "Do not chase it" doesn't survive the bigger sample. Two independent next steps, not mutually exclusive: (a) give `role_matches[]` a dedicated structured field for hiring-signal data instead of folding it into free-text `rationale` — this also fixes the frontend gap where `RoleMatchCard` has nowhere to render posting data even on the runs that do cite it; or (b) a harder prompt-level imperative than the current "you MAY name hiring employers" phrasing.

**Resolved 2026-09-29, branch `feat/fit-hiring-signal-field`.** Took path (a): `role_matches[].hiring_signal` (`coverage`/`employers`/`posting_count`) is now a schema-enforced field (`FitHiringSignal` in `contracts.py`), not optional prose. It is not model-trusted output, though — `fit.py`'s `_hiring_signal_by_role` derives the correct value server-side from `role_postings` *before* the model call, and `_apply_hiring_signal_ground_truth` unconditionally overwrites whatever the model returns for this field with that precomputed value, after `FitOutput.model_validate` succeeds and before the result returns to the caller. The model's own attempt is only ever compared for a `fit_hiring_signal_mismatch` log line, never trusted. This makes the frontend-facing number model-independent, and the live re-measurement confirms it: n=20, student `85a3c88a-52fb-43df-97db-d8257d1098db`, "Computer Engineering Intern" (same student/role as the 20% baseline above, for comparability) — **100% of runs (20/20) delivered accurate `hiring_signal` to the frontend**, identical across every run (`coverage: "available"`, `employers: ["Micron Technology, Inc.", "Micron"]`, `posting_count: 5`), versus the 20% free-text citation baseline this replaces. `fit_hiring_signal_mismatch` fired 0/20 (the model's own attempt never diverged from server truth at this n) and the new rationale-instruction change (below) held at 0/20 rationale re-mentions of a cited employer. `RoleMatchCard` now renders the field (`hiring_signal`).

- **Employer-normalization gap surfaced in the UI for the first time.** `hiring_signal.employers` for this role shows `"Micron Technology, Inc."` and `"Micron"` as two separate entries — real output of the existing `normalize_employer` function (`identity.py`), which strips legal suffixes (`Inc.`) but not the word "Technology", so the two strings normalize to different keys and don't collapse. This is the same underlying gap as the open "Employer normalization doesn't strip 'Company' or 'Services'" item below — not a new bug, just the first place a student would actually see it rendered. Left unfixed here; fixing `normalize_employer` is that existing item's job, not this task's.
- **One whole-run `"failed"` status observed, not reproduced.** Of 21 total live FIT attempts across this measurement (1 exploratory + this n=20), exactly one (the first) came back `status: "failed"` — JSON parse/validation repair exhausted within `AIRuntime`'s existing one-retry budget. Not reproduced in any of the following 20 runs. The existing fail-path already handles this safely (no malformed data reaches the frontend; the caller gets an explicit `"failed"` result). Flagging as an observed rare rate for future reference, not a new open item requiring action.
- **Mismatch/mention logging is `logger.info` only, not a durable/queryable store.** `fit_hiring_signal_mismatch` and `fit_rationale_employer_mention` are structured log lines (Python `logging`, same convention as `role_research_agent.py`), not a DB write or counter — nothing currently aggregates them over time. Deferred: this measurement's numbers (0% both, n=20) don't justify building that infrastructure yet. Revisit if a live incident or a larger-n remeasurement suggests either log line fires often enough to need trend tracking rather than ad hoc `grep`.

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

