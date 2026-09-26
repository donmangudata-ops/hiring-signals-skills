#!/usr/bin/env python3
"""Search open jobs at tech, AI, remote-first and European tech companies.

Runs paid Apify Actors by Don Mangu on the user's own Apify account:
  - conserving_celerytop/tech-jobs-search, charged per matching job returned
  - conserving_celerytop/live-career-page-jobs-api, only with --companies-file,
    charged per company, all its matching jobs included
Writes a CSV and a Markdown shortlist, newest first.

Run with --estimate first: it prints the cost ceiling from live prices and makes no run.
Needs: pip install apify-client, and APIFY_TOKEN in the environment.
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apify_common as ac  # noqa: E402

SEARCH_ACTOR = "conserving_celerytop/tech-jobs-search"
COMPANY_ACTOR = "conserving_celerytop/live-career-page-jobs-api"
BILLED_EVENTS = [
    (SEARCH_ACTOR, "matching-job"),
    (COMPANY_ACTOR, "company-lookup"),
]
LISTS = ["ai-companies", "tech-companies", "remote-first", "europe-tech"]
COLUMNS = ["companyName", "title", "location", "workplaceType", "seniority", "salaryAnnualMin",
           "salaryAnnualMax", "salaryCurrency", "visaSponsorship", "postedAt", "url"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--titles", required=True, help="Comma list of title words, e.g. 'product manager,product lead'")
    p.add_argument("--exclude", default="", help="Comma list of title words to leave out, e.g. 'intern,principal'")
    p.add_argument("--lists", default=",".join(LISTS), help="Comma list of: " + ", ".join(LISTS))
    p.add_argument("--location", default="", help="City, region or country, e.g. London or DE")
    p.add_argument("--remote-only", action="store_true", help="Fully remote jobs only")
    p.add_argument("--seniorities", default="", help="Comma list: intern, entry, mid, senior, staff_principal, lead_manager, director, vp, c_level")
    p.add_argument("--min-salary", type=int, default=0, help="Minimum yearly salary; the top of a published range counts")
    p.add_argument("--currency", default="USD")
    p.add_argument("--posted-since", default="14 days", help="e.g. '7 days' or 2026-09-01 (default 14 days)")
    p.add_argument("--max-results", type=int, default=100, help="Most jobs returned and charged (default 100)")
    p.add_argument("--companies-file", default="", help="Optional: also check these named companies, one per line")
    p.add_argument("--max-charge", type=float, default=None, help="Hard spending cap per Actor run in USD (default: ceiling plus 25 percent)")
    p.add_argument("--out", default="job_search", help="Output file prefix")
    p.add_argument("--estimate", action="store_true", help="Print the cost ceiling from live prices and stop")
    a = p.parse_args()

    lists = ac.split_list(a.lists)
    bad = [x for x in lists if x not in LISTS]
    if bad:
        sys.exit(f"Unknown list(s): {bad}. Use: {LISTS}")
    companies = ac.read_entries(a.companies_file, limit=500) if a.companies_file else []

    lines = [(SEARCH_ACTOR, "matching-job", a.max_results, "ceiling, set by --max-results")]
    if companies:
        lines.append((COMPANY_ACTOR, "company-lookup", len(companies), "named companies"))
    total = ac.estimate(lines)
    if a.estimate:
        return

    apify = ac.client()
    cap = ac.resolve_cap(a.max_charge, total)
    filters = {"titleIncludes": ac.split_list(a.titles), "postedSince": a.posted_since}
    if a.exclude:
        filters["titleExcludes"] = ac.split_list(a.exclude)
    if a.location:
        filters["location"] = a.location
    if a.remote_only:
        filters["remoteOnly"] = True
    if a.seniorities:
        filters["seniorities"] = ac.split_list(a.seniorities)
    if a.min_salary:
        filters["minAnnualSalary"] = a.min_salary
        filters["minAnnualSalaryCurrency"] = a.currency

    _, rows, _ = ac.run_actor(apify, SEARCH_ACTOR, dict(filters, companyLists=lists, maxResults=a.max_results), cap)
    if companies:
        _, more, _ = ac.run_actor(apify, COMPANY_ACTOR, dict(filters, companies=companies), cap)
        rows += more

    jobs, seen = [], set()
    for r in rows:
        if r.get("rowType", "job") != "job" or not r.get("url") or r["url"] in seen:
            continue
        seen.add(r["url"])
        jobs.append(r)
    jobs.sort(key=lambda r: r.get("postedAt") or "", reverse=True)

    with open(a.out + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(jobs)
    lines = [f"# {len(jobs)} jobs, newest first", ""]
    for j in jobs:
        pay = ""
        if j.get("salaryAnnualMin") or j.get("salaryAnnualMax"):
            lo, hi = (f"{v:,}" if isinstance(v, (int, float)) else "?" for v in (j.get("salaryAnnualMin"), j.get("salaryAnnualMax")))
            pay = f", {lo} to {hi} {j.get('salaryCurrency') or ''}".rstrip()
        where = j.get("location") or "no location"
        if j.get("workplaceType"):
            where += ", " + j["workplaceType"]
        lines.append(f"- {j.get('companyName')}: {j.get('title')} ({where}{pay}), "
                     f"posted {str(j.get('postedAt') or '?')[:10]} {j.get('url')}")
    with open(a.out + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {len(jobs)} jobs to {a.out}.csv and {a.out}.md")


if __name__ == "__main__":
    main()
