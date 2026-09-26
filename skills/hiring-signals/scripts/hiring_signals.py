#!/usr/bin/env python3
"""Rank an account list by hiring for the team you sell to, with each homepage's tech stack.

Reads each company's open jobs live from its own job board (one summary row per
company) and the technologies on its homepage, then writes one ranked row per
company to CSV, JSON and a short Markdown table.

Runs two paid Apify Actors by Don Mangu on the user's own Apify account.
Run with --estimate first: it prints the cost from live prices and makes no run.

Needs: pip install apify-client, and APIFY_TOKEN in the environment.
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apify_common as ac  # noqa: E402

JOBS_ACTOR = "conserving_celerytop/live-career-page-jobs-api"
STACK_ACTOR = "conserving_celerytop/website-tech-stack-detector"
BILLED_EVENTS = [
    (JOBS_ACTOR, "company-lookup"),
    (STACK_ACTOR, "site-analyzed"),
]
MAX_COMPANIES = 500
STACK_GROUPS = ["cms", "ecommerce", "analytics", "frameworks", "cdn", "hosting",
                "paymentProcessors", "tagManagers"]


def rank_key(row):
    # Unknown boards go last; then accounts showing a watched tool; then recent matching jobs; then all matching jobs.
    known = row["companyStatus"] in ac.READ_STATUSES
    return (known, bool(row["watchedToolsSeen"]), row["jobsPostedLast30Days"] or 0, row["openJobs"] or 0)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--domains-file", required=True, help="Text file, one company domain or job board link per line")
    p.add_argument("--titles", default="", help="Comma list of title words, e.g. 'account executive,SDR'")
    p.add_argument("--functions", default="", help="Comma list of job functions, e.g. sales,marketing")
    p.add_argument("--location", default="", help="City, region or country, e.g. Germany or DE")
    p.add_argument("--posted-since", default="", help="e.g. '30 days' or 2026-09-01")
    p.add_argument("--stack-categories", default="", help="Comma list, e.g. 'CRM,Marketing automation'. Empty = all")
    p.add_argument("--watch-tools", default="", help="Comma list of tools that move an account up, e.g. 'HubSpot,Shopify'")
    p.add_argument("--skip-stack", action="store_true", help="Only run the hiring step")
    p.add_argument("--max-charge", type=float, default=None, help="Hard spending cap per Actor run in USD (default: estimate plus 25 percent)")
    p.add_argument("--out", default="hiring_signals", help="Output file prefix")
    p.add_argument("--estimate", action="store_true", help="Print the cost from live prices and stop")
    a = p.parse_args()

    domains = ac.read_entries(a.domains_file, limit=MAX_COMPANIES)
    if not domains:
        sys.exit("No domains in the file.")
    watch = {t.lower() for t in ac.split_list(a.watch_tools)}

    lines = [(JOBS_ACTOR, "company-lookup", len(domains), "one summary row each, filters do not change the price")]
    if not a.skip_stack:
        lines.append((STACK_ACTOR, "site-analyzed", len(domains), "only sites that load are charged"))
    total = ac.estimate(lines)
    if a.estimate:
        return

    apify = ac.client()
    cap = ac.resolve_cap(a.max_charge, total)
    jobs_input = {"companies": domains, "outputMode": "companies"}
    if a.titles:
        jobs_input["titleIncludes"] = ac.split_list(a.titles)
    if a.functions:
        jobs_input["jobFunctions"] = [f.lower() for f in ac.split_list(a.functions)]
    if a.location:
        jobs_input["location"] = a.location
    if a.posted_since:
        jobs_input["postedSince"] = a.posted_since
    _, job_rows, charged_jobs = ac.run_actor(apify, JOBS_ACTOR, jobs_input, cap)

    stack_by_input, charged_stack = {}, {}
    if not a.skip_stack:
        stack_input = {"websites": domains, "maxSites": len(domains)}
        if a.stack_categories:
            stack_input["categories"] = ac.split_list(a.stack_categories)
        _, stack_rows, charged_stack = ac.run_actor(apify, STACK_ACTOR, stack_input, cap)
        stack_by_input = {str(r.get("inputUrl", "")).lower(): r for r in stack_rows}

    by_entry = {str(r.get("company", "")).lower(): r for r in job_rows if r.get("rowType") in ("company", "status")}
    merged = []
    for entry in domains:
        r = by_entry.get(entry.lower(), {"companyStatus": "no_result"})
        s = stack_by_input.get(entry.lower(), {})
        techs = ac.names(s.get("technologies"))
        row = {
            "company": entry,
            "companyName": r.get("companyName"),
            "companyStatus": r.get("companyStatus"),
            "ats": r.get("ats"),
            "boardUrl": r.get("boardUrl"),
            "openJobs": r.get("openJobs"),
            "jobsPostedLast30Days": r.get("jobsPostedLast30Days"),
            "jobsPostedLast7Days": r.get("jobsPostedLast7Days"),
            "salesShare": r.get("salesShare"),
            "engineeringShare": r.get("engineeringShare"),
            "topDepartments": ", ".join(ac.names(r.get("topDepartments"))),
            "leadershipRoles": " | ".join(x.get("title", "") for x in r.get("leadershipRoles") or []),
            "stackStatus": s.get("status") if s else ("skipped" if a.skip_stack else "no_result"),
            "watchedToolsSeen": ", ".join(t for t in techs if t.lower() in watch),
            "allTechnologies": ", ".join(techs),
            "warning": r.get("warning") or "",
        }
        for g in STACK_GROUPS:
            row[g] = ", ".join(ac.names(s.get(g)))
        merged.append(row)
    merged.sort(key=rank_key, reverse=True)

    ac.write_json(a.out + ".json", merged)
    with open(a.out + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(merged[0].keys()))
        w.writeheader()
        w.writerows(merged)
    md = [f"# Hiring signals ({len(merged)} accounts)", "",
          f"Filters: {json.dumps({k: v for k, v in jobs_input.items() if k not in ('companies', 'outputMode')}) or 'none'}", "",
          "| # | Company | Matching open jobs | Posted last 30 days | Leaders hiring | Watched tools | Status |",
          "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(merged, 1):
        md.append(f"| {i} | {r['companyName'] or r['company']} | {r['openJobs'] if r['openJobs'] is not None else '?'} | "
                  f"{r['jobsPostedLast30Days'] if r['jobsPostedLast30Days'] is not None else '?'} | "
                  f"{r['leadershipRoles'] or ''} | {r['watchedToolsSeen']} | {r['companyStatus']} |")
    md += ["", f"Charged events: jobs {charged_jobs or 'none reported'}; homepages {charged_stack or 'none reported'}."]
    with open(a.out + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(f"Wrote {len(merged)} rows to {a.out}.csv, {a.out}.json and {a.out}.md")


if __name__ == "__main__":
    main()
