# O*NET Load — What This Is and What Was Decided

**What it does:** downloads an O\*NET tabular release, trims it to what GradusIQ queries, writes Supabase-ready CSVs, and reports what's missing.

**Run it:**
```
python build_onet.py --version 30_3
python build_onet.py --version 31_0          # after the late-August release
python build_onet.py --version 31_0 --keep-level
```

Output lands in `out/`. Import those CSVs into Supabase.

**Do not hand-edit the output.** If something's wrong, fix the script and re-run. This happens again every year and nobody will remember what was done by hand.

---

## Attribution — required, not optional

O\*NET is CC BY 4.0. Any surface that shows this data must credit the **versioned** database, not just "O\*NET":

> This product uses the O\*NET 30.3 Database by the U.S. Department of Labor, Employment and Training Administration (USDOL/ETA). Used under the CC BY 4.0 license. O\*NET® is a trademark of USDOL/ETA.

Bump the version string when the data is refreshed.

---

## Decisions baked into the script

**Importance only, Level dropped by default.**
Every rating file carries two scales: IM (does this matter for this job) and LV (how much of it you need). GAP only uses Importance today. Dropping LV halves the rating tables. `--keep-level` turns it back on if a "you need SQL at a basic level, not expert" feature ever arrives.

**Suppressed and Not Relevant rows dropped.**
O\*NET flags ratings it considers unreliable. Worth knowing: these flags land almost entirely on **LV rows** — only 20 IM rows in all of 30.3 are suppressed. So this filter barely matters at Importance-only, and matters a lot if `--keep-level` is used. Left in either way.

**Both SOC granularities stored.**
O\*NET uses 8-digit extended codes (`13-2051.00`, with `.01`/`.02` sub-specializations). BLS wage data and most crosswalks use 6-digit (`13-2051`). Every table carries `onet_soc_code` **and** `soc6`. Joining on either works, and the choice isn't foreclosed.

**Four rating files unified into one table.**
30.3 split skills into Essential Skills, Transferable Skills, Knowledge, and Abilities. They're written to a single `occupation_skills` table with a `domain` column. GAP asks one question — "what matters for this role" — across all four, so one table means one query instead of four joins. The `domain` column keeps them separable.

**Job Titles + Sample of Reported Titles merged and deduped.**
57k+ real-world titles mapped to SOC codes. This is the free-text resolution layer — it's what decides whether the live O\*NET Keyword Search API is needed at all.

---

## Two gotchas that will bite on the next refresh

**1. File names changed in 30.3 and will change again.**
30.3 reorganized around a Worker / Job / Market structure and renamed files. The old single `Skills.txt` no longer exists — it's now three files. Any tutorial or script written before 30.3 is against a dead structure.

All the rename exposure is isolated in the `RATING_FILES` dict at the top of the script. If **31.0** renames things, that dict is the only edit. The script fails loudly with the missing filename rather than silently producing a short table.

**2. The release cadence.**
Quarterly, with the primary update in Q3. **31.0 lands late August 2026.** Run the refresh in September/October, after the primary update — not on some arbitrary anniversary.

---

## The coverage gap — read this before building against the data

`out/coverage_gaps.csv` lists occupations with **no ratings data at all**. In 30.3 that's **122 of 1,016 occupations.**

These aren't obscure. They include, dead center in GradusIQ's target range:

| Code | Title |
|---|---|
| 13-2051.00 | Financial and Investment Analysts |
| 13-1082.00 | Project Management Specialists |
| 13-2054.00 | Financial Risk Specialists |
| 13-1199.00 | Business Operations Specialists, All Other |
| 15-2051.00 | Data Scientists |
| 15-1255.00 | Web and Digital Interface Designers |
| 11-2032.00 | Public Relations Managers |

Mostly newer or recently reorganized SOC codes that haven't been surveyed yet.

**This confirms the July repo audit finding** that Financial Analysts came back with no skills/knowledge/abilities data. It was never a bug — the data does not exist.

**Consequence:** GAP cannot fall back to O\*NET importance scores for these occupations, because there is nothing to fall back to. For a career product aimed at business and finance students, that's a real hole. It needs a product answer — nearest-neighbor occupation, postings-only mode, or an explicit "we don't have good data for this role yet" — not a code fix.

**Nearest-neighbor landed** (`docs/plans/gap-shift-data-grounding.md`, Step B's `market_data._nearest_rated_neighbour`), walking each occupation's real O\*NET Related Occupations entries for the first one with ratings — this alone closes the gap for most of GradusIQ's 14 target roles (e.g. Finance Intern / 13-2051.00 borrows from 13-2052.00 Personal Financial Advisors).

**One further wrinkle: a few SOCs have zero Related Occupations rows at all, in either direction** — not a `RELATED_TIER` filtering artifact, confirmed against the raw release. 13-1199.00 (Business Operations Specialists, All Other — GradusIQ's "Operations Intern" mapping) is one; its own same-family `.0X` specializations (Business Continuity Planners, Sustainability Specialists, Online Merchants, Security Management Specialists) don't reciprocally relate to it or each other either, so "same family" isn't automatically "closer." For these, `MANUAL_RELATED_OVERRIDES` in `build_onet.py` hand-picks a content-matched, rated occupation (13-1199.00 → 13-1081.00 Logisticians, chosen for task/skill fit — see the comment there for the full rationale) and tags the override `"manual_override": true` in the emitted JSON, so it's never mistaken for O\*NET's own relatedness data. Only fills a real gap — never overrides an occupation O\*NET did rate as related.

Software/tools data **is** present for these occupations. Only the rated skills/knowledge/abilities are missing.

---

## What's in `out/`

| File | Rows | What it's for |
|---|---|---|
| `occupations.csv` | 1,016 | Base reference — code, title, description |
| `occupation_skills.csv` | 107,260 | The importance scores. GAP's must-have vs. nice-to-have. |
| `occupation_software.csv` | 31,821 | Named tools per occupation, with hot/in-demand flags |
| `skill_vocabulary.csv` | 8,753 | **Deduped product list — this is what the postings matcher scans against.** 176 flagged Hot Technology. |
| `occupation_titles.csv` | 57,543 | Free-text title → SOC resolution |
| `job_zones.csv` | 923 | Entry-level filtering |
| `coverage_gaps.csv` | 122 | Occupations with no ratings data |

**Total: ~13 MB as CSV.** Call it 20–25 MB in Postgres with indexes — roughly 4–5% of the Supabase free tier.

`out/` is gitignored. Re-run the script to regenerate it.

---

## What gets written outside `out/`

The script also writes **`data/reference/onet_soc_requirements.json`** (~5.3 MB, all 1,016 occupations). That one is not loader output — it's application input, read directly by
`GradusIQ_career/features/market_data.py`, and it **is** tracked in git.

It replaced a hand-built 10-occupation file that covered 2 of the 12 demo SOC codes. Per occupation it carries: title, soc6, job zone, Essential Skills (all 10), knowledge and abilities at importance ≥ 50, hot-technology software, Core task statements, and the five Primary-Short related occupations.

Two extra source files feed it and are read *only* for this purpose — `Task Statements.txt` and `Related Occupations.txt`. Like the rating files, their names are constants at the top of the script so a release rename is one edit.

`_data_status` on each entry is the field to check before trusting the lists:

| Value | Count | Meaning |
|---|---|---|
| `onet_full` | 894 | Has Essential Skills ratings |
| `partial_onet_profile` | 29 | No ratings; software and/or tasks present |
| `no_data` | 93 | Nothing in this release |

`--skip-reference` suppresses the rewrite. Same rule as everything else here: **don't hand-edit it, fix the script and re-run.** Two hand-curated fields from the old file, `role_family` and `typical_education`, are gone — neither was ever read by the app.

---

## Not included, needs a separate download

**CIP-to-SOC crosswalk** (academic program → occupation) does not ship in the database package. It's a separate file on the O\*NET Resource Center crosswalks page. Worth pulling — it's the piece that handles "students' majors will vary."

---

## Suggested indexes after import

```sql
create index on occupation_skills (onet_soc_code);
create index on occupation_skills (soc6);
create index on occupation_titles (lower(title));
create index on occupation_software (onet_soc_code);
```

The `lower(title)` one is what makes free-text title lookup fast.
