#!/usr/bin/env python3
"""New and closed jobs at a watchlist of companies since the last check.

Runs the paid Apify Actor conserving_celerytop/live-career-page-jobs-api by Don
Mangu on the user's own Apify account, with Only new jobs and a monitor name,
and writes a Markdown digest plus the raw rows. The Actor keeps the memory of
what it returned before in the user's own Apify account.

Run with --estimate first: it prints the cost from live prices and makes no run.
Needs: pip install apify-client, and APIFY_TOKEN in the environment.
"""
import argparse
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apify_common as ac  # noqa: E402

ACTOR = "conserving_celerytop/live-career-page-jobs-api"
BILLED_EVENTS = [
    (ACTOR, "company-lookup"),
    (ACTOR, "new-jobs-check"),
]
LEADERSHIP = {"director", "vp", "c_level"}


def digest(rows, monitor):
    by_company = defaultdict(lambda: {"new": [], "closed": [], "summary": None})
    for r in rows:
        name = r.get("companyName") or r.get("company") or "?"
        c = by_company[name]
        kind = r.get("rowType")
        if kind in ("company", "status"):
            c["summary"] = r
        elif kind == "job" and r.get("change") in ("new", "closed"):
            c[r["change"]].append(r)

    first_check = any((c["summary"] or {}).get("previousCheckAt") is None and c["summary"] and
                      (c["summary"].get("companyStatus") in ac.READ_STATUSES) for c in by_company.values())
    lines = [f"# Hiring changes: {monitor}", ""]
    if first_check:
        lines += ["Some companies had their first check in this run. Their jobs are the baseline, not news.", ""]
    quiet, unknown = [], []
    for name in sorted(by_company):
        c = by_company[name]
        s = c["summary"] or {}
        st = s.get("companyStatus")
        if st not in ac.READ_STATUSES:
            unknown.append(f"{name} ({st or 'no result'})")
            continue
        if not c["new"] and not c["closed"]:
            quiet.append(name)
            continue
        head = f"## {name}: {len(c['new'])} new, {len(c['closed'])} closed"
        if s.get("openJobs") is not None:
            head += f", {s['openJobs']} open"
        if s.get("previousCheckAt") is None:
            head += " (first check, baseline)"
        lines.append(head)
        funcs = defaultdict(int)
        for j in c["new"]:
            funcs[j.get("jobFunction") or "other"] += 1
        if funcs:
            lines.append("New by function: " + ", ".join(f"{k} {v}" for k, v in sorted(funcs.items(), key=lambda x: -x[1])))
        if s.get("newFunctions"):
            lines.append("Hiring in a function with no open jobs at the last check: " + ", ".join(s["newFunctions"]))
        if s.get("newCountries"):
            lines.append("Hiring in a new country: " + ", ".join(s["newCountries"]))
        lead = [j for j in c["new"] if j.get("seniority") in LEADERSHIP]
        for j in lead:
            lines.append(f"- Leadership: {j.get('title')} ({j.get('location') or 'no location'}) {j.get('url') or ''}".rstrip())
        rest = [j for j in c["new"] if j not in lead]
        for j in rest[:15]:
            lines.append(f"- New: {j.get('title')} ({j.get('location') or 'no location'}) {j.get('url') or ''}".rstrip())
        if len(rest) > 15:
            lines.append(f"- and {len(rest) - 15} more new jobs in the JSON file")
        for j in c["closed"][:10]:
            lines.append(f"- Closed: {j.get('title')} ({j.get('location') or 'no location'})")
        lines.append("")
    if quiet:
        lines += ["No changes: " + ", ".join(quiet), ""]
    if unknown:
        lines += ["Not read (unknown, not 'no changes'): " + ", ".join(unknown), ""]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--companies-file", required=True, help="One job board link, domain or name per line")
    p.add_argument("--monitor-name", required=True, help="Letters, numbers, - and _, up to 40 characters. Keep it the same every run")
    p.add_argument("--titles", default="", help="Comma list of title words to watch, optional")
    p.add_argument("--functions", default="", help="Comma list of job functions to watch, optional")
    p.add_argument("--first-run", action="store_true", help="Price the estimate as a first check (baseline)")
    p.add_argument("--max-charge", type=float, default=None, help="Hard spending cap for the run in USD (default: estimate plus 25 percent)")
    p.add_argument("--out", default="hiring_changes", help="Output file prefix")
    p.add_argument("--estimate", action="store_true", help="Print the cost from live prices and stop")
    a = p.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", a.monitor_name):
        sys.exit("--monitor-name: letters, numbers, - and _ only, up to 40 characters.")
    companies = ac.read_entries(a.companies_file, limit=500)
    if not companies:
        sys.exit("Give between 1 and 500 companies.")
    if a.first_run:
        lines = [(ACTOR, "company-lookup", len(companies), "first check, all open jobs become the baseline")]
    else:
        lines = [(ACTOR, "new-jobs-check", len(companies), "later check, per started 1,000 open jobs on a board"),
                 (ACTOR, "company-lookup", None, "for any company this monitor has not seen before")]
    total = ac.estimate(lines)
    if a.estimate:
        return

    apify = ac.client()
    if not a.first_run and a.max_charge is None and total is not None:
        # A later run can still meet new companies; leave room for their first check.
        first = ac.estimate([(ACTOR, "company-lookup", len(companies), "worst case: every company is new")])
        total = max(total, first or 0)
    cap = ac.resolve_cap(a.max_charge, total)
    run_input = {"companies": companies, "onlyNewJobs": True, "monitorName": a.monitor_name, "outputMode": "both"}
    if a.titles:
        run_input["titleIncludes"] = ac.split_list(a.titles)
    if a.functions:
        run_input["jobFunctions"] = [f.lower() for f in ac.split_list(a.functions)]
    _, rows, charged = ac.run_actor(apify, ACTOR, run_input, cap)

    ac.write_json(a.out + ".json", rows)
    text = digest(rows, a.monitor_name) + f"\nCharged events: {charged or 'none reported'}\n"
    with open(a.out + ".md", "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
