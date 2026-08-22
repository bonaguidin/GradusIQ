# Slug worksheet — DFW employer list

The ATS fetcher needs `{ats, slug}` per employer. The employer list has
slugs for none of its 44. This is that gap as a checklist.

**The slug is the identifier in the employer's own careers URL.** Open the
employer's careers page, look at where it redirects, and read it off:

| ATS | Careers URL shape | Slug is |
|---|---|---|
| greenhouse | `boards.greenhouse.io/<slug>` | the path segment |
| lever | `jobs.lever.co/<slug>` | the path segment |
| ashby | `jobs.ashbyhq.com/<slug>` | the path segment |
| smartrecruiters | `careers.smartrecruiters.com/<slug>` | the path segment — **PascalCase, case-sensitive** |
| recruitee | `<slug>.recruitee.com` | the **subdomain** |

Many of these employers will be on none of the five — enterprise HCM
platforms like Workday are common at this size, and the `notes` column
already flags several. Write `none` rather than leaving a row ambiguous,
so nobody researches it twice.

**A wrong slug is worse than a blank one.** A blank means an employer is not
fetched, which reads as an obvious zero. A slug pointing at the wrong company
files real postings under the wrong employer, which reads as data. Confirm the
board you land on actually belongs to the employer before writing it down.

Filling this in is the input to `dfw_employers_ats.csv`'s `ats` and `slug`
columns. `resolve_slugs.py --live` can attempt the same job automatically.

## Priority 1 — 11 employers

### Charles Schwab
- domain: `schwab.com`
- candidate slugs: `schwab`, `charlesschwab`, `charles-schwab`, `charles`
- check: [greenhouse](https://boards.greenhouse.io/schwab) · [lever](https://jobs.lever.co/schwab) · [ashby](https://jobs.ashbyhq.com/schwab) · [smartrecruiters](https://careers.smartrecruiters.com/schwab) · [recruitee](https://schwab.recruitee.com)
- notes: Enterprise HCM likely — check for myworkdayjobs.com
- **ats:** `____________`   **slug:** `____________`

### Fidelity Investments
- domain: `fidelity.com`
- candidate slugs: `fidelity`, `fidelityinvestments`, `fidelity-investments`
- check: [greenhouse](https://boards.greenhouse.io/fidelity) · [lever](https://jobs.lever.co/fidelity) · [ashby](https://jobs.ashbyhq.com/fidelity) · [smartrecruiters](https://careers.smartrecruiters.com/fidelity) · [recruitee](https://fidelity.recruitee.com)
- notes: Large DFW campus; heavy entry-level hiring
- **ats:** `____________`   **slug:** `____________`

### Goldman Sachs
- domain: `goldmansachs.com`
- candidate slugs: `goldmansachs`, `goldman-sachs`, `goldman`
- check: [greenhouse](https://boards.greenhouse.io/goldmansachs) · [lever](https://jobs.lever.co/goldmansachs) · [ashby](https://jobs.ashbyhq.com/goldmansachs) · [smartrecruiters](https://careers.smartrecruiters.com/goldmansachs) · [recruitee](https://goldmansachs.recruitee.com)
- notes: Named in DFW market research as expanding
- **ats:** `____________`   **slug:** `____________`

### JPMorgan Chase
- domain: `jpmorganchase.com`
- candidate slugs: `jpmorganchase`, `jpmorgan-chase`, `jpmorgan`
- check: [greenhouse](https://boards.greenhouse.io/jpmorganchase) · [lever](https://jobs.lever.co/jpmorganchase) · [ashby](https://jobs.ashbyhq.com/jpmorganchase) · [smartrecruiters](https://careers.smartrecruiters.com/jpmorganchase) · [recruitee](https://jpmorganchase.recruitee.com)
- notes: Enterprise HCM likely
- **ats:** `____________`   **slug:** `____________`

### Fisher Investments
- domain: `fisherinvestments.com`
- candidate slugs: `fisherinvestments`, `fisher-investments`, `fisher`
- check: [greenhouse](https://boards.greenhouse.io/fisherinvestments) · [lever](https://jobs.lever.co/fisherinvestments) · [ashby](https://jobs.ashbyhq.com/fisherinvestments) · [smartrecruiters](https://careers.smartrecruiters.com/fisherinvestments) · [recruitee](https://fisherinvestments.recruitee.com)
- notes: Named in market research (client service profiling)
- **ats:** `____________`   **slug:** `____________`

### Bank of America
- domain: `bankofamerica.com`
- candidate slugs: `bankofamerica`, `bank-of-america`, `bank`
- check: [greenhouse](https://boards.greenhouse.io/bankofamerica) · [lever](https://jobs.lever.co/bankofamerica) · [ashby](https://jobs.ashbyhq.com/bankofamerica) · [smartrecruiters](https://careers.smartrecruiters.com/bankofamerica) · [recruitee](https://bankofamerica.recruitee.com)
- notes: Enterprise HCM likely
- **ats:** `____________`   **slug:** `____________`

### Comerica
- domain: `comerica.com`
- candidate slugs: `comerica`
- check: [greenhouse](https://boards.greenhouse.io/comerica) · [lever](https://jobs.lever.co/comerica) · [ashby](https://jobs.ashbyhq.com/comerica) · [smartrecruiters](https://careers.smartrecruiters.com/comerica) · [recruitee](https://comerica.recruitee.com)
- notes: Mid-size — worth checking non-Workday platforms
- **ats:** `____________`   **slug:** `____________`

### USAA
- domain: `usaa.com`
- candidate slugs: `usaa`
- check: [greenhouse](https://boards.greenhouse.io/usaa) · [lever](https://jobs.lever.co/usaa) · [ashby](https://jobs.ashbyhq.com/usaa) · [smartrecruiters](https://careers.smartrecruiters.com/usaa) · [recruitee](https://usaa.recruitee.com)
- notes: Large Plano campus
- **ats:** `____________`   **slug:** `____________`

### Mr. Cooper Group
- domain: `mrcoopergroup.com`
- candidate slugs: `mrcoopergroup`, `mr-cooper-group`, `mrcooper`, `mr-cooper`
- check: [greenhouse](https://boards.greenhouse.io/mrcoopergroup) · [lever](https://jobs.lever.co/mrcoopergroup) · [ashby](https://jobs.ashbyhq.com/mrcoopergroup) · [smartrecruiters](https://careers.smartrecruiters.com/mrcoopergroup) · [recruitee](https://mrcoopergroup.recruitee.com)
- notes: Mid-market — reasonable odds of a readable board
- **ats:** `____________`   **slug:** `____________`

### Capital One
- domain: `capitalone.com`
- candidate slugs: `capitalone`, `capital-one`, `capital`
- check: [greenhouse](https://boards.greenhouse.io/capitalone) · [lever](https://jobs.lever.co/capitalone) · [ashby](https://jobs.ashbyhq.com/capitalone) · [smartrecruiters](https://careers.smartrecruiters.com/capitalone) · [recruitee](https://capitalone.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Globe Life
- domain: `globelifeinsurance.com`
- candidate slugs: `globelifeinsurance`, `globelife`, `globe-life`, `globe`
- check: [greenhouse](https://boards.greenhouse.io/globelifeinsurance) · [lever](https://jobs.lever.co/globelifeinsurance) · [ashby](https://jobs.ashbyhq.com/globelifeinsurance) · [smartrecruiters](https://careers.smartrecruiters.com/globelifeinsurance) · [recruitee](https://globelifeinsurance.recruitee.com)
- notes: Smaller HQ headcount but entry-heavy
- **ats:** `____________`   **slug:** `____________`

## Priority 2 — 8 employers

### Deloitte
- domain: `deloitte.com`
- candidate slugs: `deloitte`
- check: [greenhouse](https://boards.greenhouse.io/deloitte) · [lever](https://jobs.lever.co/deloitte) · [ashby](https://jobs.ashbyhq.com/deloitte) · [smartrecruiters](https://careers.smartrecruiters.com/deloitte) · [recruitee](https://deloitte.recruitee.com)
- notes: Deloitte University in Westlake; major DFW campus recruiter
- **ats:** `____________`   **slug:** `____________`

### PwC
- domain: `pwc.com`
- candidate slugs: `pwc`
- check: [greenhouse](https://boards.greenhouse.io/pwc) · [lever](https://jobs.lever.co/pwc) · [ashby](https://jobs.ashbyhq.com/pwc) · [smartrecruiters](https://careers.smartrecruiters.com/pwc) · [recruitee](https://pwc.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### EY
- domain: `ey.com`
- candidate slugs: `ey`
- check: [greenhouse](https://boards.greenhouse.io/ey) · [lever](https://jobs.lever.co/ey) · [ashby](https://jobs.ashbyhq.com/ey) · [smartrecruiters](https://careers.smartrecruiters.com/ey) · [recruitee](https://ey.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### KPMG
- domain: `kpmg.us`
- candidate slugs: `kpmg`
- check: [greenhouse](https://boards.greenhouse.io/kpmg) · [lever](https://jobs.lever.co/kpmg) · [ashby](https://jobs.ashbyhq.com/kpmg) · [smartrecruiters](https://careers.smartrecruiters.com/kpmg) · [recruitee](https://kpmg.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Accenture
- domain: `accenture.com`
- candidate slugs: `accenture`
- check: [greenhouse](https://boards.greenhouse.io/accenture) · [lever](https://jobs.lever.co/accenture) · [ashby](https://jobs.ashbyhq.com/accenture) · [smartrecruiters](https://careers.smartrecruiters.com/accenture) · [recruitee](https://accenture.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Jacobs
- domain: `jacobs.com`
- candidate slugs: `jacobs`
- check: [greenhouse](https://boards.greenhouse.io/jacobs) · [lever](https://jobs.lever.co/jacobs) · [ashby](https://jobs.ashbyhq.com/jacobs) · [smartrecruiters](https://careers.smartrecruiters.com/jacobs) · [recruitee](https://jacobs.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Fluor
- domain: `fluor.com`
- candidate slugs: `fluor`
- check: [greenhouse](https://boards.greenhouse.io/fluor) · [lever](https://jobs.lever.co/fluor) · [ashby](https://jobs.ashbyhq.com/fluor) · [smartrecruiters](https://careers.smartrecruiters.com/fluor) · [recruitee](https://fluor.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### CBRE Group
- domain: `cbre.com`
- candidate slugs: `cbre`, `cbregroup`, `cbre-group`
- check: [greenhouse](https://boards.greenhouse.io/cbre) · [lever](https://jobs.lever.co/cbre) · [ashby](https://jobs.ashbyhq.com/cbre) · [smartrecruiters](https://careers.smartrecruiters.com/cbre) · [recruitee](https://cbre.recruitee.com)
- notes: Named in market research
- **ats:** `____________`   **slug:** `____________`

## Priority 3 — 7 employers

### AT&T
- domain: `att.com`
- candidate slugs: `att`, `at-t`
- check: [greenhouse](https://boards.greenhouse.io/att) · [lever](https://jobs.lever.co/att) · [ashby](https://jobs.ashbyhq.com/att) · [smartrecruiters](https://careers.smartrecruiters.com/att) · [recruitee](https://att.recruitee.com)
- notes: Enterprise HCM likely
- **ats:** `____________`   **slug:** `____________`

### Texas Instruments
- domain: `ti.com`
- candidate slugs: `ti`, `texasinstruments`, `texas-instruments`, `texas`
- check: [greenhouse](https://boards.greenhouse.io/ti) · [lever](https://jobs.lever.co/ti) · [ashby](https://jobs.ashbyhq.com/ti) · [smartrecruiters](https://careers.smartrecruiters.com/ti) · [recruitee](https://ti.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Toyota Motor North America
- domain: `toyota.com`
- candidate slugs: `toyota`, `toyotamotornorthamerica`, `toyota-motor-north-america`
- check: [greenhouse](https://boards.greenhouse.io/toyota) · [lever](https://jobs.lever.co/toyota) · [ashby](https://jobs.ashbyhq.com/toyota) · [smartrecruiters](https://careers.smartrecruiters.com/toyota) · [recruitee](https://toyota.recruitee.com)
- notes: Named in market research
- **ats:** `____________`   **slug:** `____________`

### Match Group
- domain: `mtch.com`  _already recorded: `lever`_
- candidate slugs: `mtch`, `matchgroup`, `match-group`, `match`
- check: [greenhouse](https://boards.greenhouse.io/mtch) · [lever](https://jobs.lever.co/mtch) · [ashby](https://jobs.ashbyhq.com/mtch) · [smartrecruiters](https://careers.smartrecruiters.com/mtch) · [recruitee](https://mtch.recruitee.com)
- notes: VERIFIED Lever in Aug 6 test run — 82 postings returned
- **ats:** `____________`   **slug:** `____________`

### Solera
- domain: `solera.com`
- candidate slugs: `solera`
- check: [greenhouse](https://boards.greenhouse.io/solera) · [lever](https://jobs.lever.co/solera) · [ashby](https://jobs.ashbyhq.com/solera) · [smartrecruiters](https://careers.smartrecruiters.com/solera) · [recruitee](https://solera.recruitee.com)
- notes: Named in market research
- **ats:** `____________`   **slug:** `____________`

### Vistra Energy
- domain: `vistracorp.com`
- candidate slugs: `vistracorp`, `vistraenergy`, `vistra-energy`, `vistra`
- check: [greenhouse](https://boards.greenhouse.io/vistracorp) · [lever](https://jobs.lever.co/vistracorp) · [ashby](https://jobs.ashbyhq.com/vistracorp) · [smartrecruiters](https://careers.smartrecruiters.com/vistracorp) · [recruitee](https://vistracorp.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Atmos Energy
- domain: `atmosenergy.com`
- candidate slugs: `atmosenergy`, `atmos-energy`, `atmos`
- check: [greenhouse](https://boards.greenhouse.io/atmosenergy) · [lever](https://jobs.lever.co/atmosenergy) · [ashby](https://jobs.ashbyhq.com/atmosenergy) · [smartrecruiters](https://careers.smartrecruiters.com/atmosenergy) · [recruitee](https://atmosenergy.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

## Priority 4 — 7 employers

### Baylor Scott & White Health
- domain: `bswhealth.com`
- candidate slugs: `bswhealth`, `baylorscottwhitehealth`, `baylor-scott-white-health`, `baylor`
- check: [greenhouse](https://boards.greenhouse.io/bswhealth) · [lever](https://jobs.lever.co/bswhealth) · [ashby](https://jobs.ashbyhq.com/bswhealth) · [smartrecruiters](https://careers.smartrecruiters.com/bswhealth) · [recruitee](https://bswhealth.recruitee.com)
- notes: Largest not-for-profit health system in Texas
- **ats:** `____________`   **slug:** `____________`

### Texas Health Resources
- domain: `texashealth.org`
- candidate slugs: `texashealth`, `texashealthresources`, `texas-health-resources`, `texas`
- check: [greenhouse](https://boards.greenhouse.io/texashealth) · [lever](https://jobs.lever.co/texashealth) · [ashby](https://jobs.ashbyhq.com/texashealth) · [smartrecruiters](https://careers.smartrecruiters.com/texashealth) · [recruitee](https://texashealth.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Medical City Healthcare (HCA)
- domain: `medicalcityhealthcare.com`
- candidate slugs: `medicalcityhealthcare`, `medicalcityhealthcarehca`, `medical-city-healthcare-hca`, `medical`
- check: [greenhouse](https://boards.greenhouse.io/medicalcityhealthcare) · [lever](https://jobs.lever.co/medicalcityhealthcare) · [ashby](https://jobs.ashbyhq.com/medicalcityhealthcare) · [smartrecruiters](https://careers.smartrecruiters.com/medicalcityhealthcare) · [recruitee](https://medicalcityhealthcare.recruitee.com)
- notes: Named in market research (revenue cycle documentation)
- **ats:** `____________`   **slug:** `____________`

### Tenet Healthcare
- domain: `tenethealth.com`
- candidate slugs: `tenethealth`, `tenethealthcare`, `tenet-healthcare`, `tenet`
- check: [greenhouse](https://boards.greenhouse.io/tenethealth) · [lever](https://jobs.lever.co/tenethealth) · [ashby](https://jobs.ashbyhq.com/tenethealth) · [smartrecruiters](https://careers.smartrecruiters.com/tenethealth) · [recruitee](https://tenethealth.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### UT Southwestern Medical Center
- domain: `utsouthwestern.edu`
- candidate slugs: `utsouthwestern`, `utsouthwesternmedicalcenter`, `ut-southwestern-medical-center`
- check: [greenhouse](https://boards.greenhouse.io/utsouthwestern) · [lever](https://jobs.lever.co/utsouthwestern) · [ashby](https://jobs.ashbyhq.com/utsouthwestern) · [smartrecruiters](https://careers.smartrecruiters.com/utsouthwestern) · [recruitee](https://utsouthwestern.recruitee.com)
- notes: Public institution — separate hiring system likely
- **ats:** `____________`   **slug:** `____________`

### Parkland Health
- domain: `parklandhealth.org`
- candidate slugs: `parklandhealth`, `parkland-health`, `parkland`
- check: [greenhouse](https://boards.greenhouse.io/parklandhealth) · [lever](https://jobs.lever.co/parklandhealth) · [ashby](https://jobs.ashbyhq.com/parklandhealth) · [smartrecruiters](https://careers.smartrecruiters.com/parklandhealth) · [recruitee](https://parklandhealth.recruitee.com)
- notes: Public hospital district
- **ats:** `____________`   **slug:** `____________`

### McKesson
- domain: `mckesson.com`
- candidate slugs: `mckesson`
- check: [greenhouse](https://boards.greenhouse.io/mckesson) · [lever](https://jobs.lever.co/mckesson) · [ashby](https://jobs.ashbyhq.com/mckesson) · [smartrecruiters](https://careers.smartrecruiters.com/mckesson) · [recruitee](https://mckesson.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

## Priority 5 — 11 employers

### American Airlines
- domain: `aa.com`
- candidate slugs: `aa`, `americanairlines`, `american-airlines`, `american`
- check: [greenhouse](https://boards.greenhouse.io/aa) · [lever](https://jobs.lever.co/aa) · [ashby](https://jobs.ashbyhq.com/aa) · [smartrecruiters](https://careers.smartrecruiters.com/aa) · [recruitee](https://aa.recruitee.com)
- notes: Named in market research
- **ats:** `____________`   **slug:** `____________`

### Southwest Airlines
- domain: `southwest.com`
- candidate slugs: `southwest`, `southwestairlines`, `southwest-airlines`
- check: [greenhouse](https://boards.greenhouse.io/southwest) · [lever](https://jobs.lever.co/southwest) · [ashby](https://jobs.ashbyhq.com/southwest) · [smartrecruiters](https://careers.smartrecruiters.com/southwest) · [recruitee](https://southwest.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Amazon
- domain: `amazon.com`
- candidate slugs: `amazon`
- check: [greenhouse](https://boards.greenhouse.io/amazon) · [lever](https://jobs.lever.co/amazon) · [ashby](https://jobs.ashbyhq.com/amazon) · [smartrecruiters](https://careers.smartrecruiters.com/amazon) · [recruitee](https://amazon.recruitee.com)
- notes: 30+ DFW facilities; own careers system
- **ats:** `____________`   **slug:** `____________`

### Walmart
- domain: `walmart.com`
- candidate slugs: `walmart`
- check: [greenhouse](https://boards.greenhouse.io/walmart) · [lever](https://jobs.lever.co/walmart) · [ashby](https://jobs.ashbyhq.com/walmart) · [smartrecruiters](https://careers.smartrecruiters.com/walmart) · [recruitee](https://walmart.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Lennox International
- domain: `lennoxinternational.com`
- candidate slugs: `lennoxinternational`, `lennox-international`, `lennox`
- check: [greenhouse](https://boards.greenhouse.io/lennoxinternational) · [lever](https://jobs.lever.co/lennoxinternational) · [ashby](https://jobs.ashbyhq.com/lennoxinternational) · [smartrecruiters](https://careers.smartrecruiters.com/lennoxinternational) · [recruitee](https://lennoxinternational.recruitee.com)
- notes: Named in market research (RevOps + Salesforce)
- **ats:** `____________`   **slug:** `____________`

### Kimberly-Clark
- domain: `kimberly-clark.com`
- candidate slugs: `kimberly-clark`, `kimberlyclark`, `kimberly`
- check: [greenhouse](https://boards.greenhouse.io/kimberly-clark) · [lever](https://jobs.lever.co/kimberly-clark) · [ashby](https://jobs.ashbyhq.com/kimberly-clark) · [smartrecruiters](https://careers.smartrecruiters.com/kimberly-clark) · [recruitee](https://kimberly-clark.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Sally Beauty Holdings
- domain: `sallybeautyholdings.com`
- candidate slugs: `sallybeautyholdings`, `sally-beauty-holdings`, `sallybeauty`, `sally-beauty`, `sally`
- check: [greenhouse](https://boards.greenhouse.io/sallybeautyholdings) · [lever](https://jobs.lever.co/sallybeautyholdings) · [ashby](https://jobs.ashbyhq.com/sallybeautyholdings) · [smartrecruiters](https://careers.smartrecruiters.com/sallybeautyholdings) · [recruitee](https://sallybeautyholdings.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Michaels
- domain: `michaels.com`
- candidate slugs: `michaels`
- check: [greenhouse](https://boards.greenhouse.io/michaels) · [lever](https://jobs.lever.co/michaels) · [ashby](https://jobs.ashbyhq.com/michaels) · [smartrecruiters](https://careers.smartrecruiters.com/michaels) · [recruitee](https://michaels.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### GameStop
- domain: `gamestop.com`
- candidate slugs: `gamestop`
- check: [greenhouse](https://boards.greenhouse.io/gamestop) · [lever](https://jobs.lever.co/gamestop) · [ashby](https://jobs.ashbyhq.com/gamestop) · [smartrecruiters](https://careers.smartrecruiters.com/gamestop) · [recruitee](https://gamestop.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Builders FirstSource
- domain: `bldr.com`
- candidate slugs: `bldr`, `buildersfirstsource`, `builders-firstsource`, `builders`
- check: [greenhouse](https://boards.greenhouse.io/bldr) · [lever](https://jobs.lever.co/bldr) · [ashby](https://jobs.ashbyhq.com/bldr) · [smartrecruiters](https://careers.smartrecruiters.com/bldr) · [recruitee](https://bldr.recruitee.com)
- **ats:** `____________`   **slug:** `____________`

### Copart
- domain: `copart.com`
- candidate slugs: `copart`
- check: [greenhouse](https://boards.greenhouse.io/copart) · [lever](https://jobs.lever.co/copart) · [ashby](https://jobs.ashbyhq.com/copart) · [smartrecruiters](https://careers.smartrecruiters.com/copart) · [recruitee](https://copart.recruitee.com)
- **ats:** `____________`   **slug:** `____________`
