#!/usr/bin/env python3
"""
GradusIQ — O*NET loader
Downloads an O*NET tabular release, trims it to what GradusIQ actually queries,
and writes Supabase-ready CSVs plus a coverage report.

Run:  python build_onet.py --version 30_3
      python build_onet.py --version 31_0 --keep-level

Re-run this after each annual O*NET refresh. Do not hand-edit the output.
"""

import argparse, csv, io, json, os, sys, zipfile, urllib.request
from collections import defaultdict
from datetime import date

# ---------------------------------------------------------------- config

DL = "https://www.onetcenter.org/dl_files/database/db_{v}_text.zip"

# Rating files -> domain label written into occupation_skills.domain.
# NOTE: O*NET 30.3 renamed these. Pre-30.3 releases used a single "Skills.txt".
# If a release renames them again, this dict is the only thing to change.
RATING_FILES = {
    "Essential Skills.txt":    "essential_skill",
    "Transferable Skills.txt": "transferable_skill",
    "Knowledge.txt":           "knowledge",
    "Abilities.txt":           "ability",
}

# Non-rating source files, named here for the same reason RATING_FILES is a
# dict: a release rename should be one edit at the top, not a hunt through main().
TASKS_FILE   = "Task Statements.txt"
RELATED_FILE = "Related Occupations.txt"

OUT = "out"

# The reference file is application input, not loader output, so it lands in
# data/reference/ rather than out/. market_data.py already reads this exact
# path -- see _DEFAULT_DATA_PATH there. Emitting it replaces the hand-built
# 10-occupation file that covered 2 of the 12 demo SOC codes.
REF_DIR  = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "reference"))
REF_NAME = "onet_soc_requirements.json"

# Importance at or above this is a must-have. Carried in the reference file so
# the consumer never hardcodes it.
MUST_HAVE_THRESHOLD = 70

# Floor for knowledge/abilities in the reference file. Essential Skills are kept
# in full (all 10) to preserve the prior file's inclusion rule; knowledge and
# abilities run ~33 and ~52 rows per occupation unfiltered, which buries the
# signal in noise the model then has to rank itself.
REF_MIN_IMPORTANCE = 50

# Only the Primary-Short tier (exactly 5 per occupation) is carried. Primary-Long
# and Supplemental add 15 more with progressively looser relatedness -- more
# candidates than SHIFT's adjacent_paths can use, and weaker ones.
RELATED_TIER = "Primary-Short"

# A handful of SOC codes have ZERO rows in O*NET's own Related Occupations.txt,
# in either direction (confirmed against the raw 30.3 release, not a RELATED_TIER
# filtering artifact) -- so market_data.py's neighbor-borrow fallback
# (_nearest_rated_neighbour) has nothing to walk for them, even though they are
# otherwise unrated and would benefit most from it (e.g. 13-1199.00, GradusIQ's
# "Operations Intern" mapping -- see data/onet/README.md's coverage-gap table).
#
# This is a hand-curated exception, same spirit as data/role_requirements.json
# ("SOC codes reference the ... taxonomy for realism only"), not O*NET graph
# data. Each entry is marked "manual_override": True in the emitted JSON so
# market_data.py's disclosure note and FIT/SHIFT's prompts can tell a curated
# pick apart from one O*NET itself rated as related -- picked by matching the
# target's own official O*NET task/skill description, not guessed. Only
# applied when the real Related Occupations table has nothing for that code;
# never overrides genuine O*NET relatedness data.
MANUAL_RELATED_OVERRIDES = {
    # Business Operations Specialists, All Other -- O*NET's residual/catch-all
    # code for generalist business-ops roles, has no ratings and no related-
    # occupations rows at all (confirmed against Related Occupations.txt,
    # 2026-09-30, O*NET 30.3). Its own 13-1199.0X sibling specializations
    # (Business Continuity Planners, Sustainability Specialists, Online
    # Merchants, Security Management Specialists) are all niche and none
    # reciprocally relates to it or each other, so a same-family pick isn't
    # actually a stronger match than a content-matched one outside the family.
    # Logisticians (13-1081.00) is rated, and its official O*NET description
    # ("coordinate the ongoing logistical functions of a firm... acquisition,
    # distribution, internal allocation, delivery") and core tasks (customer/
    # vendor coordination, proposals, estimates) line up with role_requirements
    # .json's hand-curated Operations Intern skill list (process analysis,
    # data-driven problem solving, supply chain fundamentals, project
    # coordination) far better than the generic alternative, General and
    # Operations Managers (11-1021.00) -- which is a people-management
    # occupation ("manage through subordinate supervisors"), not an
    # entry-level analyst/coordinator task profile.
    "13-1199.00": ["13-1081.00"],
}

# ---------------------------------------------------------------- helpers

def soc6(code):
    """13-2051.00 -> 13-2051. O*NET uses 8-digit extended codes with .01/.02
    sub-specializations; BLS wage data and most crosswalks use 6-digit."""
    return code.split(".")[0].strip()

def read(folder, name):
    """O*NET ships tab-delimited, CRLF, BOM. utf-8-sig handles the BOM."""
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        sys.exit(f"MISSING FILE: {name}\n  The release may have renamed it. "
                 f"Check the migration reference on onetcenter.org and update RATING_FILES.")
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def write(name, header, rows):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    kb = os.path.getsize(path) / 1024
    print(f"  {name:<28} {len(rows):>7,} rows   {kb:>8,.0f} KB")
    return len(rows)

def write_json(directory, name, payload):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    kb = os.path.getsize(path) / 1024
    print(f"  {name:<28} {len(payload['roles']):>7,} occs   {kb:>8,.0f} KB   -> {directory}")
    return path


def rescale(value):
    """O*NET native Importance is 1-5. The reference file uses 0-100 so
    MUST_HAVE_THRESHOLD reads as a percentage and matches what the prior
    hand-built file recorded in its _meta."""
    return round((float(value) - 1) / 4 * 100)


def build_reference(occ_rows, rating_rows, sw_rows, jz_rows, tasks, related, version):
    """Assemble the per-occupation reference consumed by market_data.py.

    Every occupation in the release gets an entry, including the 122 with no
    ratings data. An entry with empty lists and a _data_status of
    "partial_onet_profile"/"no_data" is strictly more useful to the caller than
    a missing key: it distinguishes "this occupation has no O*NET ratings" from
    "this SOC code is not in the release", and those need different handling
    downstream (agent fallback vs. a bad SOC mapping to fix).
    """
    # Ratings -> {soc: {domain: [{name, importance}, ...]}}. IM only: --keep-level
    # puts LV rows in rating_rows too, and they are a different scale entirely.
    by_domain = defaultdict(lambda: defaultdict(list))
    for code, _soc6, domain, _eid, element_name, scale_id, data_value, _n in rating_rows:
        if scale_id != "IM":
            continue
        importance = rescale(data_value)
        if domain in ("knowledge", "ability") and importance < REF_MIN_IMPORTANCE:
            continue
        by_domain[code][domain].append({"name": element_name, "importance": importance})
    for domains in by_domain.values():
        for items in domains.values():
            items.sort(key=lambda i: (-i["importance"], i["name"]))

    hot = defaultdict(list)
    in_demand = defaultdict(list)
    for code, _soc6, product, _category, is_hot, is_in_demand in sw_rows:
        if is_hot:
            hot[code].append(product)
        # O*NET flags these separately: Hot Technology is "frequently included in
        # employer job postings", In Demand is "certification or skill frequently
        # required". Both were extracted to CSV from the start; only hot was
        # reaching the app.
        if is_in_demand:
            in_demand[code].append(product)

    zones = {code: int(zone) for code, _soc6, zone in jz_rows if zone.isdigit()}

    core_tasks = defaultdict(list)
    for row in tasks:
        if row["Task Type"].strip() == "Core":
            core_tasks[row["O*NET-SOC Code"].strip()].append(row["Task"].strip())

    titles = {code: title for code, _soc6, title, _desc in occ_rows}
    related_by_soc = defaultdict(list)
    for row in related:
        if row["Relatedness Tier"].strip() != RELATED_TIER:
            continue
        target = row["Related O*NET-SOC Code"].strip()
        related_by_soc[row["O*NET-SOC Code"].strip()].append(
            (int(row["Index"]), {"soc": target, "title": titles.get(target, target)}))

    def related_for(code):
        real = [entry for _idx, entry in sorted(related_by_soc.get(code, []))]
        if real:
            return real
        overrides = MANUAL_RELATED_OVERRIDES.get(code)
        if not overrides:
            return []
        return [
            {"soc": target, "title": titles.get(target, target), "manual_override": True}
            for target in overrides
        ]

    roles = {}
    for code, soc6_code, title, _desc in occ_rows:
        domains = by_domain.get(code, {})
        skills = domains.get("essential_skill", [])
        software = sorted(set(hot.get(code, [])))
        demanded = sorted(set(in_demand.get(code, [])))
        tasks_for_code = core_tasks.get(code, [])
        if skills:
            status = "onet_full"
        elif software or demanded or tasks_for_code:
            status = "partial_onet_profile"
        else:
            status = "no_data"
        roles[code] = {
            "title": title,
            "soc6": soc6_code,
            "job_zone": zones.get(code),
            "skills": skills,
            "knowledge": domains.get("knowledge", []),
            "abilities": domains.get("ability", []),
            "hot_software": software,
            "in_demand_software": demanded,
            "core_tasks": tasks_for_code,
            "related": related_for(code),
            "_data_status": status,
        }

    return {
        "_meta": {
            "source": f"O*NET {version.replace('_', '.')} Database (canonical text release), "
                      "Importance (IM) scale",
            "source_url": "https://www.onetcenter.org/database.html",
            "taxonomy": "O*NET-SOC 2019",
            "generated": date.today().isoformat(),
            "generated_by": "data/onet/build_onet.py -- do not hand-edit, re-run instead",
            "importance_scale": "0-100, rescaled from O*NET native 1-5 via (value-1)/4*100",
            "inclusion_rule": (
                f"skills: full Essential Skills set; knowledge & abilities: "
                f"importance >= {REF_MIN_IMPORTANCE}; each sorted descending. "
                f"Transferable Skills are deliberately NOT merged into skills -- "
                f"see occupation_skills.csv if they are needed."),
            "data_status_values": {
                "onet_full": "has Essential Skills ratings",
                "partial_onet_profile": "no ratings; software and/or tasks present",
                "no_data": "no ratings, software, or tasks in this release",
            },
            "license": "O*NET data © under CC-BY 4.0 (US DOL/ETA)",
            "manual_related_overrides": {
                "note": (
                    "SOC codes where O*NET's own Related Occupations.txt has zero rows "
                    "(either direction) and a hand-picked neighbor was substituted so "
                    "the app's borrow-nearest-rated-neighbor fallback has something to "
                    "use. Not O*NET graph data -- see MANUAL_RELATED_OVERRIDES in "
                    "build_onet.py for the per-SOC rationale. Each affected entry's "
                    "related[] item carries \"manual_override\": true."
                ),
                "socs": sorted(MANUAL_RELATED_OVERRIDES),
            },
        },
        "must_have_threshold": MUST_HAVE_THRESHOLD,
        "roles": roles,
    }


def fetch(version, workdir):
    """Download + unzip unless already present."""
    folder = os.path.join(workdir, f"db_{version}_text")
    if os.path.isdir(folder):
        print(f"Using cached {folder}")
        return folder
    url = DL.format(v=version)
    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as r:
        data = r.read()
    zipfile.ZipFile(io.BytesIO(data)).extractall(workdir)
    if not os.path.isdir(folder):
        # some releases nest differently; find the one dir that exists
        cands = [d for d in os.listdir(workdir) if os.path.isdir(os.path.join(workdir, d))]
        sys.exit(f"Unexpected archive layout. Found: {cands}")
    return folder

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="30_3", help="O*NET release, e.g. 30_3 or 31_0")
    ap.add_argument("--keep-level", action="store_true",
                    help="keep LV (Level) ratings as well as IM (Importance)")
    ap.add_argument("--keep-suppressed", action="store_true",
                    help="keep rows O*NET flags Recommend Suppress / Not Relevant (don't)")
    ap.add_argument("--skip-reference", action="store_true",
                    help="don't rewrite data/reference/onet_soc_requirements.json")
    ap.add_argument("--workdir", default="onet_src")
    args = ap.parse_args()

    os.makedirs(args.workdir, exist_ok=True)
    src = fetch(args.version, args.workdir)
    scales = {"IM"} | ({"LV"} if args.keep_level else set())

    print(f"\nBuilding from {src}")
    print(f"  scales kept: {sorted(scales)}")
    print(f"  suppressed rows: {'KEPT' if args.keep_suppressed else 'dropped'}\n")

    # ---- occupations -------------------------------------------------
    occ = read(src, "Occupation Data.txt")
    occ_rows = [[r["O*NET-SOC Code"].strip(), soc6(r["O*NET-SOC Code"]),
                 r["Title"].strip(), r["Description"].strip()] for r in occ]
    all_socs = {r[0] for r in occ_rows}
    titles = {r[0]: r[2] for r in occ_rows}

    # ---- ratings: four files unified into one table -------------------
    # Unified rather than four tables because GAP asks one question
    # ("what matters for this role") across all four domains. A `domain`
    # column keeps them separable without four joins at query time.
    rating_rows, rated, dropped = [], set(), defaultdict(int)
    for fname, domain in RATING_FILES.items():
        for r in read(src, fname):
            if r["Scale ID"].strip() not in scales:
                continue
            if not args.keep_suppressed:
                if r.get("Recommend Suppress", "").strip() == "Y":
                    dropped["suppressed"] += 1; continue
                if r.get("Not Relevant", "").strip() == "Y":
                    dropped["not_relevant"] += 1; continue
            code = r["O*NET-SOC Code"].strip()
            rated.add(code)
            rating_rows.append([code, soc6(code), domain,
                                r["Element ID"].strip(), r["Element Name"].strip(),
                                r["Scale ID"].strip(), r["Data Value"].strip(),
                                r.get("N", "").strip()])

    # ---- software / tools: the ATS matcher's vocabulary ---------------
    sw = read(src, "Software Skills.txt")
    sw_rows = [[r["O*NET-SOC Code"].strip(), soc6(r["O*NET-SOC Code"]),
                r["Workplace Example"].strip(), r["Element Name"].strip(),
                r["Hot Technology"].strip() == "Y", r["In Demand"].strip() == "Y"]
               for r in sw]

    # Deduped product list — this is what the posting matcher scans against.
    vocab = {}
    for r in sw:
        p = r["Workplace Example"].strip()
        hot = r["Hot Technology"].strip() == "Y"
        dem = r["In Demand"].strip() == "Y"
        cur = vocab.get(p, (False, False, ""))
        vocab[p] = (cur[0] or hot, cur[1] or dem, r["Element Name"].strip())
    vocab_rows = [[p, cat, hot, dem] for p, (hot, dem, cat) in sorted(vocab.items())]

    # ---- titles for free-text resolution ------------------------------
    jt = read(src, "Job Titles.txt")
    title_rows = [[r["O*NET-SOC Code"].strip(), soc6(r["O*NET-SOC Code"]),
                   r["Job Title"].strip()] for r in jt]

    rt = read(src, "Sample of Reported Titles.txt")
    title_rows += [[r["O*NET-SOC Code"].strip(), soc6(r["O*NET-SOC Code"]),
                    r["Reported Job Title"].strip()] for r in rt]
    seen, deduped = set(), []
    for row in title_rows:
        k = (row[0], row[2].lower())
        if k not in seen:
            seen.add(k); deduped.append(row)
    title_rows = deduped

    # ---- job zones (entry-level filtering) ----------------------------
    jz = read(src, "Job Zones.txt")
    jz_rows = [[r["O*NET-SOC Code"].strip(), soc6(r["O*NET-SOC Code"]),
                r["Job Zone"].strip()] for r in jz]

    # ---- tasks + related occupations (reference file only) -------------
    # Core tasks ground "what this job actually does"; Primary-Short related
    # occupations ground adjacent-role suggestions. Neither is written to CSV --
    # they exist to keep the reference file from having to invent either.
    tasks = read(src, TASKS_FILE)
    related = read(src, RELATED_FILE)

    # ---- write --------------------------------------------------------
    print("Writing:")
    write("occupations.csv",
          ["onet_soc_code", "soc6", "title", "description"], occ_rows)
    write("occupation_skills.csv",
          ["onet_soc_code", "soc6", "domain", "element_id", "element_name",
           "scale_id", "data_value", "sample_n"], rating_rows)
    write("occupation_software.csv",
          ["onet_soc_code", "soc6", "product", "category",
           "hot_technology", "in_demand"], sw_rows)
    write("skill_vocabulary.csv",
          ["product", "category", "hot_technology", "in_demand"], vocab_rows)
    write("occupation_titles.csv",
          ["onet_soc_code", "soc6", "title"], title_rows)
    write("job_zones.csv",
          ["onet_soc_code", "soc6", "job_zone"], jz_rows)

    # ---- coverage report ----------------------------------------------
    # The point of this file: know which occupations have NO ratings data
    # before a student's target role returns an empty result in production.
    unrated = sorted(all_socs - rated)
    write("coverage_gaps.csv",
          ["onet_soc_code", "title"], [[c, titles[c]] for c in unrated])

    total_kb = sum(os.path.getsize(os.path.join(OUT, f))
                   for f in os.listdir(OUT)) / 1024
    print(f"\n  {'TOTAL':<28} {'':>7}        {total_kb:>8,.0f} KB")

    # ---- reference file for the app -----------------------------------
    reference = None
    if not args.skip_reference:
        print("\nWriting reference (replaces the hand-built file):")
        reference = build_reference(occ_rows, rating_rows, sw_rows, jz_rows,
                                    tasks, related, args.version)
        write_json(REF_DIR, REF_NAME, reference)

    print(f"\nFiltering dropped:")
    for k, v in sorted(dropped.items()):
        print(f"  {k:<20} {v:>7,} rows")

    print(f"\nCoverage:")
    print(f"  occupations in release      {len(all_socs):>6,}")
    print(f"  with ratings data           {len(rated):>6,}")
    print(f"  WITHOUT any ratings         {len(unrated):>6,}   -> out/coverage_gaps.csv")
    print(f"  software products (unique)  {len(vocab_rows):>6,}")
    print(f"  hot technologies            {sum(1 for r in vocab_rows if r[2]):>6,}")

    if reference is not None:
        status = defaultdict(int)
        for entry in reference["roles"].values():
            status[entry["_data_status"]] += 1
        print(f"\nReference file ({REF_NAME}):")
        for key in ("onet_full", "partial_onet_profile", "no_data"):
            print(f"  {key:<27} {status[key]:>6,}")
        print(f"  with hot software           "
              f"{sum(1 for e in reference['roles'].values() if e['hot_software']):>6,}")
        print(f"  with in-demand software     "
              f"{sum(1 for e in reference['roles'].values() if e['in_demand_software']):>6,}")
        print(f"  with related occupations    "
              f"{sum(1 for e in reference['roles'].values() if e['related']):>6,}")

    print(f"\nDone. Import out/*.csv into Supabase.")

if __name__ == "__main__":
    main()
