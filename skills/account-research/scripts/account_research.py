#!/usr/bin/env python3
"""One-page research brief per target account, from live hiring data and the company website.

For each account it reads every open job on the company's own job board and the
technologies on its homepage, then writes a brief: hiring momentum, the teams
growing, new leaders and first hires, roles open for months, tools named in job
posts, homepage tech, and the newest roles on the teams you sell to.

Runs two paid Apify Actors by Don Mangu on the user's own Apify account.
Run with --estimate first: it prints the cost from live prices and makes no run.

Needs: pip install apify-client, and APIFY_TOKEN in the environment.
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apify_common as ac  # noqa: E402

JOBS_ACTOR = "conserving_celerytop/live-career-page-jobs-api"
STACK_ACTOR = "conserving_celerytop/website-tech-stack-detector"
BILLED_EVENTS = [
    (JOBS_ACTOR, "company-lookup"),
    (JOBS_ACTOR, "job-details"),
    (STACK_ACTOR, "site-analyzed"),
]
MAX_ACCOUNTS = 25
STACK_GROUPS = [("cms", "CMS"), ("ecommerce", "Ecommerce"), ("analytics", "Analytics"),
                ("tagManagers", "Tag managers"), ("paymentProcessors", "Payments"),
                ("hosting", "Hosting"), ("frameworks", "Frameworks")]


def momentum(summary):
    """Plain-language hiring pace from the share of open jobs posted in the last 30 days."""
    open_jobs = summary.get("openJobs") or 0
    last30 = summary.get("jobsPostedLast30Days")
    if not open_jobs:
        return "no open jobs"
    if last30 is None:
        return "unknown (the board gives no posting dates)"
    share = last30 / open_jobs
    if share >= 0.4:
        label = "fast"
    elif share >= 0.15:
        label = "steady"
    else:
        label = "slow, mostly older roles"
    return f"{label}: {last30} of {open_jobs} open jobs posted in the last 30 days ({share:.0%})"


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def top_counts(counts, n=5):
    return sorted((counts or {}).items(), key=lambda kv: -kv[1])[:n]


def brief(entry, summary, jobs, stack, sell_functions, watch_tools):
    name = summary.get("companyName") or entry
    status = summary.get("companyStatus")
    lines = [f"## {name}", ""]
    lines.append(f"Input: `{entry}`" + (f", job board: {summary['boardUrl']}" if summary.get("boardUrl") else ""))
    signals = []

    if status not in ac.READ_STATUSES:
        reason = (summary.get("error") or "").strip().rstrip(".")
        lines.append(f"Hiring: not read ({status or 'no result'}). " + (f"{reason}. " if reason else "")
                     + "This is unknown, not 'not hiring'.")
    else:
        lines.append(f"Hiring pace: {momentum(summary)}.")
        if summary.get("jobsPostedLast7Days"):
            lines.append(f"Posted in the last 7 days: {summary['jobsPostedLast7Days']}.")
        funcs = top_counts(summary.get("functionCounts"))
        recent = summary.get("functionCountsLast30Days") or {}
        if funcs:
            lines.append("Teams with the most open jobs: " + ", ".join(
                f"{f} {c}" + (f" ({recent[f]} new in 30 days)" if recent.get(f) else "") for f, c in funcs) + ".")
        countries = [c.get("countryCode") for c in summary.get("countries") or [] if c.get("countryCode")]
        if countries:
            lines.append("Hiring in: " + ", ".join(countries[:6])
                         + (f"; remote share {summary['remoteShare']:.0%}" if summary.get("remoteShare") is not None else "") + ".")
        old = summary.get("jobsOpenOver90Days")
        if old:
            lines.append(f"Open more than 90 days: {plural(old, 'job')} (hard to fill, or evergreen postings).")
            if summary.get("openJobs") and old / summary["openJobs"] >= 0.3:
                signals.append(f"{old} of {summary['openJobs']} jobs open for 90+ days")
        for r in summary.get("leadershipRoles") or []:
            if r.get("status") == "closed":
                continue
            signals.append(f"Leadership hire: {r.get('title')} (posted {str(r.get('postedAt') or '?')[:10]}) {r.get('url') or ''}".rstrip())
        for r in summary.get("firstHireRoles") or []:
            signals.append(f"First or founding hire: {r.get('title')} (posted {str(r.get('postedAt') or '?')[:10]}) {r.get('url') or ''}".rstrip())

        if sell_functions:
            lines.append("")
            lines.append("Teams you sell to:")
            for f in sell_functions:
                fj = [j for j in jobs if j.get("jobFunction") == f]
                fj.sort(key=lambda j: j.get("postedAt") or "", reverse=True)
                lines.append(f"- {f}: {len(fj)} open, {recent.get(f, 0)} posted in the last 30 days")
                for j in fj[:5]:
                    lines.append(f"  - {j.get('title')} ({j.get('location') or 'no location'}, "
                                 f"posted {str(j.get('postedAt') or '?')[:10]}) {j.get('url') or ''}".rstrip())

        tools = summary.get("topTools")
        if tools:
            lines.append("")
            lines.append("Tools named in their job posts (jobs naming each): " + ", ".join(
                f"{t.get('name')} ({t.get('count')})" for t in tools[:12]) + ".")
        if watch_tools:
            named = Counter()
            for j in jobs:
                for t in j.get("tools") or []:
                    if t.lower() in watch_tools:
                        named[t] += 1
            if named:
                signals.append("Your watched tools in job posts: " + ", ".join(f"{t} in {plural(c, 'job')}" for t, c in named.most_common()))

    lines.append("")
    if stack is None:
        lines.append("Homepage tech: not checked.")
    elif stack.get("status") != "ok":
        lines.append(f"Homepage tech: not read ({stack.get('status')}). Unknown, not 'none'.")
    else:
        parts = []
        for key, label in STACK_GROUPS:
            n = ac.names(stack.get(key))
            if n:
                parts.append(f"{label}: {', '.join(n[:4])}")
        lines.append("Homepage tech: " + ("; ".join(parts) if parts else "nothing in the main groups") + ".")
        if watch_tools:
            seen = [t for t in ac.names(stack.get("technologies")) if t.lower() in watch_tools]
            if seen:
                signals.append("Your watched tools on the homepage: " + ", ".join(seen))

    lines.append("")
    lines.append("Signals to check:" if signals else "Signals to check: none found by the rules in SKILL.md.")
    lines += [f"- {s}" for s in signals]
    lines.append("")
    return "\n".join(lines), name, signals


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--accounts", default="", help="Comma list of domains or job board links, e.g. 'linear.app,notion.so'")
    p.add_argument("--accounts-file", default="", help="Text file, one domain or job board link per line")
    p.add_argument("--sell-to", default="", help="Job functions you sell to, e.g. 'sales,marketing' or 'engineering,data'")
    p.add_argument("--watch-tools", default="", help="Tools you integrate with or replace, e.g. 'Salesforce,HubSpot,Snowflake'")
    p.add_argument("--no-descriptions", action="store_true", help="Skip job descriptions: no tools from job posts, no job-details charge")
    p.add_argument("--skip-stack", action="store_true", help="Skip the homepage tech check")
    p.add_argument("--max-charge", type=float, default=None, help="Hard spending cap per Actor run in USD (default: estimate plus 25 percent)")
    p.add_argument("--out", default="account_briefs", help="Output file prefix")
    p.add_argument("--estimate", action="store_true", help="Print the cost from live prices and stop")
    a = p.parse_args()

    accounts = ac.read_entries(a.accounts_file or None, a.accounts, limit=MAX_ACCOUNTS)
    if not accounts:
        sys.exit("Give at least one account with --accounts or --accounts-file.")
    sell = [f.lower() for f in ac.split_list(a.sell_to)]
    watch = {t.lower() for t in ac.split_list(a.watch_tools)}

    lines = [(JOBS_ACTOR, "company-lookup", len(accounts), "all open jobs, up to 1,000 each")]
    if not a.no_descriptions:
        lines.append((JOBS_ACTOR, "job-details", None, "only on Workday and a few other boards, per started 200 jobs, unknown until the run"))
    if not a.skip_stack:
        lines.append((STACK_ACTOR, "site-analyzed", len(accounts), "only sites that load are charged"))
    total = ac.estimate(lines)
    if a.estimate:
        return

    apify = ac.client()
    cap = ac.resolve_cap(a.max_charge, total)
    jobs_input = {"companies": accounts, "outputMode": "both", "maxJobsPerCompany": 1000,
                  "includeDescription": not a.no_descriptions}
    _, rows, charged_jobs = ac.run_actor(apify, JOBS_ACTOR, jobs_input, cap)

    stack_by_input = {}
    charged_stack = {}
    if not a.skip_stack:
        _, stack_rows, charged_stack = ac.run_actor(apify, STACK_ACTOR, {"websites": accounts, "maxSites": len(accounts)}, cap)
        stack_by_input = {str(r.get("inputUrl", "")).lower(): r for r in stack_rows}

    summaries, jobs_by = {}, {}
    for r in rows:
        key = str(r.get("company", "")).lower()
        if r.get("rowType") in ("company", "status"):
            summaries[key] = r
        elif r.get("rowType") == "job":
            r.pop("description", None)
            jobs_by.setdefault(key, []).append(r)

    out_md = [f"# Account briefs ({len(accounts)} accounts)", ""]
    out_json = []
    for entry in accounts:
        key = entry.lower()
        summary = summaries.get(key, {"companyStatus": None})
        stack = None if a.skip_stack else stack_by_input.get(key, {"status": "no_result"})
        text, name, signals = brief(entry, summary, jobs_by.get(key, []), stack, sell, watch)
        out_md.append(text)
        out_json.append({"input": entry, "companyName": name, "summary": summary, "stack": stack,
                         "signals": signals, "jobs": jobs_by.get(key, [])})
    out_md.append(f"Charged events: jobs {charged_jobs or 'none reported'}; homepages {charged_stack or 'none reported'}.")

    with open(a.out + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(out_md) + "\n")
    ac.write_json(a.out + ".json", out_json)
    print(f"Wrote {a.out}.md and {a.out}.json")


if __name__ == "__main__":
    main()
