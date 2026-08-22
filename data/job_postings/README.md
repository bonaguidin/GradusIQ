# Job postings config

Hand-edited reference data for the postings ingest. Not code — these files are
meant to be read and corrected by people, and the ingest reads them at runtime
rather than hardcoding anything.

## Where these came from

Harvested 2026-08-19 from `ats-puller-draft`, a local-only skeleton repo that
was never under version control. That repo's Python is entirely
`raise NotImplementedError` stubs, but these three config files are real
hand-built work and were the only things in it at risk of being lost.

The skeleton implements `GradusIQ_ATS_Puller_Spec.md`; section references in
the comments inside each file point at that spec.

## Before anything reads these

Nothing in the repo parses them yet. Whoever wires that up has to do two
things together, not one:

1. Add `pyyaml` to `pyproject.toml`.
2. Run `uv lock` to regenerate `uv.lock`.

PyYAML is currently in the local venv only as a transitive dependency, so a
module that imports it will pass locally and fail on a fresh install. And the
CI workflow runs `uv sync --frozen`, which refuses a lockfile that does not
match `pyproject.toml` — so declaring the dependency without relocking breaks
the nightly run instead of fixing anything.

## The files

| File | What it is | Trust level |
|---|---|---|
| `dfw_employers_ats.csv` | 44 DFW employers, platforms and slugs | Researched 2026-08-19 |
| `role_families.yaml` | Title → one of the 14 target roles | Remapped 2026-08-19, unreviewed |
| `skill_aliases.yaml` | Canonical skill → surface forms | 46 skills, review still owed |
| `slug_worksheet.md` | Generated checklist behind the CSV | Complete |
| `employers.example.yaml` | Shape template from the skeleton repo | Superseded by the CSV |

## role_families.yaml — remapped 2026-08-19

Now the fourteen target roles from `data/role_requirements.json`, exactly. The
previous ten families were general professional occupations from the DFW
market research, correct for the mid-career Career OS concept this project
started as and wrong for a product serving students.

**Expect ~99% of employer-board postings to map to NULL, and expect that to be
correct.** Measured: of 153 real postings from PMG and Match Group, 2 have
student-shaped titles — 1.3%, and one of those is "Apprenticeship - Junior
Marketing Assistant". Atmos Energy's board returns "Sr Applications
Developer", "Service Technician", "Mgr Safety".

That is what an employer's own ATS board is: every open role, overwhelmingly
experienced hires. It splits the two source types by purpose:

- **Employer-direct (ATS, Workday)** is for breadth — who is hiring in DFW, in
  what volume, wanting which skills. Student-role hit rate 1–2%.
- **Adzuna and JSearch** are for student roles specifically, because they are
  searched by role. Their `target_role` comes from the query and never touches
  this file.

Anyone reading a low mapped-count as "the rules are broken" will loosen
phrases until general postings match student families. That is the silent
failure the file's own comments warn about, and it is worse than mapping
nothing.

Status: first pass, unreviewed. The boundaries worth a second look are
Computer Engineering vs. Embedded Systems, and Lab Assistant vs. Research
Assistant — both overlap in real posting language.

## skill_aliases.yaml — 46 skills, and it won the vocabulary question

Two approaches were drifting in parallel. This file is curated, alias-based,
word-boundary matched. `skill_terms_review.csv` on the `ats-fetcher` branch
generated 8,725 candidates from the O*NET software catalogue and ranked them
by how often each fired against real posting text.

**The frequency data settled it against the generated file.** Only 121 of its
8,725 terms fired at all, and the hardest-firing are Training (91), IMPACT
(89), Testing (84), Experian (70), Client (65), Shape (42), MAGIC (39),
Vision (33) — O*NET product names and ordinary words colliding with prose.
Experian is a PMG *client*, not a skill. Fire count measures collision, not
relevance, which is the failure the "never naive substring search" rule exists
to prevent.

So `skill_terms_review.csv` is retired as a vocabulary source and kept as the
record of what was rejected and why. **Do not delete it** — it is the evidence
behind this decision.

Seven genuine skills were harvested from those 121: Google Analytics, Adobe
Analytics, Google Ads, Social Media Marketing, Epic, Figma, Node.js. Epic
earns its place because seven of the 44 DFW employers are health systems and
it is the dominant EHR; it is deliberately not aliased as bare "Epic", since
"epic collaboration" is common prose.

46 skills against a target of roughly 60–120. Still under, and that gap is
real work rather than rounding.

## dfw_employers_ats.csv — researched and merged 2026-08-19

44 hand-researched DFW employers plus one example row the loader skips.
Columns: priority, employer, sector, dfw_location, domain,
target_role_families, ats, slug, checked_date, notes.

**43 platforms and 44 slugs are filled in. 13 employers are actually
fetchable.** The gap between those numbers is the finding:

| | |
|---|---:|
| on a platform with an adapter | 13 |
| no adapter for their platform | 23 |
| supported platform, slug will not build an endpoint | 7 |
| platform never confirmed | 1 |

Of 44 employers, exactly **one** — Match Group, on Lever — was reachable
before the Workday adapter. Nineteen are on Workday, of which twelve carry a
usable `/site` path. The other seven record a host only; the endpoint cannot
be built without the site segment, and `parse_workday_slug` returns `None`
rather than guessing `careers`, which would 404 or hit another tenant's board.

`load_employers.py` reports all four categories separately, because they need
different people: an adapter is code, a site path is research, an unconfirmed
platform is neither until someone looks.

Two other things to know:

- `notes` mixes verified findings with the original hypotheses. Entries
  carrying `verified 2026-08-19:` were confirmed against a live endpoint or
  DNS; the rest are still guesses like "Enterprise HCM likely".
- `target_role_families` still uses the **mid-career taxonomy** —
  "Financial analyst; client service associate" rather than any of the
  fourteen student roles. Unlike `role_families.yaml`, this column was left as
  written: it records what the research assumed, and rewriting it inside a
  loader would bury a decision.

Comerica's `fifththird` Workday tenant is correct, not a wrong-company error —
Fifth Third completed its acquisition of Comerica in February 2026.

PMG is not in this list, despite being one of the two employers actually
fetched in the 2026-08-05 run. Match Group is.

## employers.example.yaml

A shape template for the ats-puller-draft skeleton's own config format
(`{ats, slug, employer_name}` in YAML). Superseded by the CSV above for
content, kept because the skeleton's loader still refers to it.
