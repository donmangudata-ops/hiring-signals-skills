"""A fake apify_client for offline tests. It never touches the network.

It answers the three Actors the skills use with small, realistic rows, and logs
every call (Actor, input, spending cap) as JSON lines to $FAKE_APIFY_LOG.
Entry words steer the fake: 'unsupported' gives unsupported_job_board, 'empty'
gives no_open_jobs, 'down' gives a homepage timeout, and 'fresh' is a first
monitor check (baseline).
"""
import json
import os

JOBS = "conserving_celerytop/live-career-page-jobs-api"
STACK = "conserving_celerytop/website-tech-stack-detector"
SEARCH = "conserving_celerytop/tech-jobs-search"

_DATASETS = {}


def _jobs_for(entry, with_desc):
    name = entry.split(".")[0].split("/")[-1].title()
    base = [
        ("Account Executive, Mid-Market", "sales", "mid", "2026-09-20", "US", ["Salesforce", "Gong"]),
        ("VP Sales", "sales", "vp", "2026-09-18", "US", ["Salesforce"]),
        ("SDR", "sales", "entry", "2026-09-02", "DE", ["HubSpot"]),
        ("Senior Backend Engineer", "engineering", "senior", "2026-08-01", "US", ["Python", "Snowflake"]),
        ("Founding Data Engineer", "data", "senior", "2026-09-22", "GB", ["Snowflake", "dbt"]),
        ("Product Designer", "design", "mid", "2026-04-10", "US", ["Figma"]),
    ]
    rows = []
    for i, (title, func, sen, posted, cc, tools) in enumerate(base):
        r = {"rowType": "job", "company": entry, "companyName": name, "title": title, "jobFunction": func,
             "seniority": sen, "postedAt": posted + "T00:00:00Z", "countryCode": cc, "location": cc,
             "url": f"https://jobs.example.com/{name.lower()}/{i}", "change": None}
        if with_desc:
            r["description"] = "Long description text " * 50
            r["tools"] = tools
        rows.append(r)
    return name, rows


def _run_jobs(inp):
    out, charged = [], {"company-lookup": 0, "new-jobs-check": 0}
    funcs = set(inp.get("jobFunctions") or [])
    mode = inp.get("outputMode", "jobs")
    desc = bool(inp.get("includeDescription"))
    for entry in inp["companies"]:
        if "unsupported" in entry:
            out.append({"rowType": "status", "company": entry, "companyName": None,
                        "companyStatus": "unsupported_job_board", "error": "iCIMS is not supported", "charged": False})
            continue
        name, jobs = _jobs_for(entry, desc)
        if "empty" in entry:
            jobs = []
        if funcs:
            jobs = [j for j in jobs if j["jobFunction"] in funcs]
        first = "fresh" in entry
        if inp.get("onlyNewJobs"):
            if first:
                for j in jobs:
                    j["change"] = "new"
                charged["company-lookup"] += 1
            else:
                jobs = jobs[:2]
                for j in jobs:
                    j["change"] = "new"
                jobs.append({"rowType": "job", "company": entry, "companyName": name, "title": "Old Role",
                             "location": "US", "url": "https://jobs.example.com/old", "change": "closed"})
                charged["new-jobs-check"] += 1
        else:
            charged["company-lookup"] += 1
        open_jobs = [j for j in jobs if j.get("change") != "closed"]
        fc, fc30 = {}, {}
        for j in open_jobs:
            f = j.get("jobFunction") or "other"
            fc[f] = fc.get(f, 0) + 1
            if (j.get("postedAt") or "") >= "2026-08-27":
                fc30[f] = fc30.get(f, 0) + 1
        summary = {
            "rowType": "company", "company": entry, "companyName": name, "ats": "greenhouse",
            "boardUrl": f"https://boards.greenhouse.io/{name.lower()}",
            "companyStatus": "ok" if open_jobs else "no_open_jobs",
            "openJobs": len(open_jobs), "jobsPostedLast7Days": sum(1 for j in open_jobs if (j.get("postedAt") or "") >= "2026-09-19"),
            "jobsPostedLast30Days": sum(fc30.values()), "jobsOpenOver90Days": sum(1 for j in open_jobs if (j.get("postedAt") or "") < "2026-06-28"),
            "functionCounts": fc, "functionCountsLast30Days": fc30,
            "countries": [{"countryCode": "US", "count": 3}, {"countryCode": "DE", "count": 1}] if open_jobs else None,
            "remoteShare": 0.25 if open_jobs else None, "salesShare": 0.5, "engineeringShare": 0.17,
            "topDepartments": [{"name": "Sales", "count": 3}],
            "leadershipRoles": [{"title": "VP Sales", "seniority": "vp", "postedAt": "2026-09-18", "url": "https://jobs.example.com/vp", "status": "open"}] if open_jobs else [],
            "firstHireRoles": [{"title": "Founding Data Engineer", "postedAt": "2026-09-22", "url": "https://jobs.example.com/fde", "cue": "title"}] if open_jobs and not funcs else [],
            "topTools": [{"name": "Salesforce", "category": "crm_sales", "count": 2}, {"name": "Snowflake", "category": "data", "count": 2}] if desc and open_jobs else None,
            "previousCheckAt": None if (first or not inp.get("onlyNewJobs")) else "2026-09-19T08:00:00Z",
            "newFunctions": None if first else (["sales"] if inp.get("onlyNewJobs") else None),
            "newCountries": None if first else (["JP"] if inp.get("onlyNewJobs") else None),
            "warning": None,
        }
        if mode in ("jobs", "both"):
            out += jobs
        if mode in ("companies", "both"):
            out.append(summary)
    return out, charged


def _run_stack(inp):
    out = []
    for w in inp["websites"][: inp.get("maxSites", 10000)]:
        if "down" in w:
            out.append({"inputUrl": w, "status": "timeout", "technologies": [], "charged": False})
            continue
        techs = [{"name": "WordPress", "categories": ["CMS"]}, {"name": "HubSpot", "categories": ["Marketing automation"]},
                 {"name": "Google Analytics", "categories": ["Analytics"]}]
        if "shop" in w:
            techs.append({"name": "Shopify", "categories": ["Ecommerce"]})
        out.append({"inputUrl": w, "status": "ok", "technologies": techs, "cms": [techs[0]],
                    "analytics": [techs[2]], "ecommerce": [t for t in techs if t["name"] == "Shopify"],
                    "tagManagers": [{"name": "Google Tag Manager"}], "charged": True})
    return out, {"site-analyzed": sum(1 for r in out if r["charged"])}


def _run_search(inp):
    rows = []
    for i in range(min(inp.get("maxResults", 200), 5)):
        rows.append({"rowType": "job", "companyName": f"AI Co {i}", "title": f"{inp['titleIncludes'][0].title()} {i}",
                     "location": "Remote", "workplaceType": "remote", "postedAt": f"2026-09-2{i}T00:00:00Z",
                     "salaryAnnualMin": 150000 + i, "salaryAnnualMax": 190000, "salaryCurrency": "USD",
                     "url": f"https://jobs.example.com/search/{i}"})
    rows.append(dict(rows[0]))  # a duplicate the script must drop
    return rows, {"matching-job": len(rows) - 1}


class _Actor:
    def __init__(self, actor_id):
        self.actor_id = actor_id

    def call(self, run_input=None, max_total_charge_usd=None, **_):
        log = os.environ.get("FAKE_APIFY_LOG")
        if log:
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"actor": self.actor_id, "input": run_input, "cap": str(max_total_charge_usd)}) + "\n")
        handler = {JOBS: _run_jobs, STACK: _run_stack, SEARCH: _run_search}.get(self.actor_id)
        if handler is None:
            raise ValueError(f"unknown Actor {self.actor_id}")
        rows, charged = handler(run_input)
        ds = f"ds-{len(_DATASETS) + 1}"
        _DATASETS[ds] = rows
        return {"status": "SUCCEEDED", "defaultDatasetId": ds, "chargedEventCounts": charged}


class _Dataset:
    def __init__(self, ds):
        self.ds = ds

    def iterate_items(self):
        return iter(_DATASETS[self.ds])


class ApifyClient:
    def __init__(self, token=None, **_):
        if not token:
            raise ValueError("token required")

    def actor(self, actor_id):
        return _Actor(actor_id)

    def dataset(self, dataset_id):
        return _Dataset(dataset_id)
