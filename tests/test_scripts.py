"""Offline tests: every script runs against a fake Apify client and a local price server.

No token, no network. The local server builds each Actor's pricing from the README
price table, so the tests also prove the scripts price runs from that one table.
Run: python -m unittest discover tests
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import validate  # noqa: E402

PRICES = validate.parse_price_table((ROOT / "README.md").read_text(encoding="utf-8"))
FAKE = ROOT / "tests" / "fake_apify"


def acts_payload(actor_id):
    events = {}
    for (actor, event), tiers in PRICES.items():
        if actor == actor_id or actor == "All of the above":
            events[event] = {"eventTieredPricingUsd": {t: {"tieredEventPriceUsd": p} for t, p in tiers.items()}}
    return {"data": {"pricingInfos": [{"pricingModel": "PAY_PER_EVENT", "pricingPerEvent": {"actorChargeEvents": events}}]}}


class PriceHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        actor = self.path.rsplit("/", 1)[-1].replace("~", "/")
        if not any(a == actor for a, _ in PRICES):
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(acts_payload(actor)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), PriceHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.log = self.tmp / "calls.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_script(self, skill, script, *args, token="fake-token", base=None, expect_ok=True):
        env = dict(os.environ, PYTHONPATH=str(FAKE), FAKE_APIFY_LOG=str(self.log),
                   APIFY_API_BASE_URL=base or self.base)
        env.pop("APIFY_TOKEN", None)
        if token:
            env["APIFY_TOKEN"] = token
        cmd = [sys.executable, str(ROOT / "skills" / skill / "scripts" / script), *args]
        out = subprocess.run(cmd, cwd=self.tmp, env=env, capture_output=True, text=True, timeout=120)
        if expect_ok:
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(x) for x in self.log.read_text().splitlines()]

    def price(self, actor, event):
        return PRICES[(f"conserving_celerytop/{actor}", event)]["FREE"]

    def write(self, name, lines):
        (self.tmp / name).write_text("\n".join(lines) + "\n")
        return name

    # account-research

    def test_account_research_estimate_makes_no_run(self):
        out = self.run_script("account-research", "account_research.py", "--accounts", "acme.com,globex.com,initech.com", "--estimate")
        want = 3 * self.price("live-career-page-jobs-api", "company-lookup") + 3 * self.price("website-tech-stack-detector", "site-analyzed")
        self.assertIn(f"Total, about: ${want:.2f}", out.stdout)
        self.assertEqual(self.calls(), [])

    def test_account_research_brief(self):
        self.run_script("account-research", "account_research.py", "--accounts", "acme.com,unsupported-co.com,empty.io,down.io",
                        "--sell-to", "sales", "--watch-tools", "HubSpot,Salesforce")
        calls = self.calls()
        self.assertEqual([c["actor"] for c in calls], ["conserving_celerytop/live-career-page-jobs-api",
                                                       "conserving_celerytop/website-tech-stack-detector"])
        jobs_input = calls[0]["input"]
        self.assertEqual(jobs_input["outputMode"], "both")
        self.assertTrue(jobs_input["includeDescription"])
        self.assertEqual(jobs_input["maxJobsPerCompany"], 1000)
        self.assertNotIn("fake-token", json.dumps(calls))
        self.assertGreater(float(calls[0]["cap"]), 0)
        md = (self.tmp / "account_briefs.md").read_text()
        self.assertIn("## Acme", md)
        self.assertIn("Hiring pace: fast", md)
        self.assertIn("Leadership hire: VP Sales", md)
        self.assertIn("First or founding hire: Founding Data Engineer", md)
        self.assertIn("- sales: 3 open", md)
        self.assertIn("Tools named in their job posts", md)
        self.assertIn("Your watched tools in job posts", md)
        self.assertIn("Your watched tools on the homepage: HubSpot", md)
        self.assertIn("not read (unsupported_job_board)", md)
        self.assertIn("unknown, not 'not hiring'", md)
        self.assertIn("Homepage tech: not read (timeout)", md)
        data = json.loads((self.tmp / "account_briefs.json").read_text())
        self.assertEqual(len(data), 4)
        self.assertTrue(all("description" not in j for a in data for j in a["jobs"]))

    def test_account_research_limits(self):
        many = ",".join(f"c{i}.com" for i in range(26))
        out = self.run_script("account-research", "account_research.py", "--accounts", many, "--estimate", expect_ok=False)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("up to 25", out.stdout + out.stderr)

    # hiring-signals

    def test_hiring_signals_rank_and_outputs(self):
        f = self.write("accounts.txt", ["# comment", "acme.com", "unsupported-co.com", "shop.io", "acme.com", "empty.io"])
        out = self.run_script("hiring-signals", "hiring_signals.py", "--domains-file", f, "--estimate")
        self.assertIn("4 x company-lookup", out.stdout)
        self.assertEqual(self.calls(), [])
        self.run_script("hiring-signals", "hiring_signals.py", "--domains-file", f, "--functions", "sales",
                        "--posted-since", "30 days", "--watch-tools", "Shopify")
        inp = self.calls()[0]["input"]
        self.assertEqual(inp["outputMode"], "companies")
        self.assertEqual(inp["jobFunctions"], ["sales"])
        rows = json.loads((self.tmp / "hiring_signals.json").read_text())
        self.assertEqual([r["company"] for r in rows][0], "shop.io")
        self.assertEqual(rows[-1]["company"], "unsupported-co.com")
        self.assertTrue((self.tmp / "hiring_signals.csv").exists())
        self.assertIn("| 1 | Shop |", (self.tmp / "hiring_signals.md").read_text())

    # competitor-hiring-tracker

    def test_tracker_first_and_later_check(self):
        f = self.write("watch.txt", ["fresh-acme.com", "globex.com", "unsupported-co.com"])
        first = self.run_script("competitor-hiring-tracker", "hiring_changes.py", "--companies-file", f,
                                "--monitor-name", "competitors", "--first-run", "--estimate")
        self.assertIn("3 x company-lookup", first.stdout)
        later = self.run_script("competitor-hiring-tracker", "hiring_changes.py", "--companies-file", f,
                                "--monitor-name", "competitors", "--estimate")
        self.assertIn("3 x new-jobs-check", later.stdout)
        self.assertEqual(self.calls(), [])
        out = self.run_script("competitor-hiring-tracker", "hiring_changes.py", "--companies-file", f,
                              "--monitor-name", "competitors")
        inp = self.calls()[0]["input"]
        self.assertTrue(inp["onlyNewJobs"])
        self.assertEqual(inp["monitorName"], "competitors")
        want_cap = 3 * self.price("live-career-page-jobs-api", "company-lookup") * 1.25
        self.assertGreaterEqual(float(self.calls()[0]["cap"]), round(want_cap, 2) - 0.01)
        md = (self.tmp / "hiring_changes.md").read_text()
        self.assertIn("first check, baseline", md)
        self.assertIn("Globex: 2 new, 1 closed", md)
        self.assertIn("Hiring in a new country: JP", md)
        self.assertIn("Leadership: VP Sales", md)
        self.assertIn("Closed: Old Role", md)
        self.assertIn("Not read (unknown, not 'no changes'): unsupported-co.com", md)
        self.assertIn("Charged events", out.stdout)

    def test_tracker_rejects_bad_monitor_name(self):
        f = self.write("watch.txt", ["acme.com"])
        out = self.run_script("competitor-hiring-tracker", "hiring_changes.py", "--companies-file", f,
                              "--monitor-name", "bad name!", expect_ok=False)
        self.assertNotEqual(out.returncode, 0)

    # tech-job-search

    def test_search_jobs(self):
        f = self.write("dream.txt", ["acme.com"])
        est = self.run_script("tech-job-search", "search_jobs.py", "--titles", "product manager", "--max-results", "50", "--estimate")
        want = 50 * self.price("tech-jobs-search", "matching-job")
        self.assertIn(f"Total, about: ${want:.2f}", est.stdout)
        self.run_script("tech-job-search", "search_jobs.py", "--titles", "product manager", "--remote-only",
                        "--min-salary", "150000", "--lists", "ai-companies,remote-first", "--companies-file", f)
        calls = self.calls()
        self.assertEqual(calls[0]["input"]["companyLists"], ["ai-companies", "remote-first"])
        self.assertTrue(calls[0]["input"]["remoteOnly"])
        self.assertEqual(calls[1]["actor"], "conserving_celerytop/live-career-page-jobs-api")
        md = (self.tmp / "job_search.md").read_text().splitlines()
        self.assertTrue(md[0].startswith("# "))
        urls = [x.split()[-1] for x in md if x.startswith("- ")]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertIn("2026-09-24", md[2])

    def test_search_rejects_unknown_list(self):
        out = self.run_script("tech-job-search", "search_jobs.py", "--titles", "pm", "--lists", "nope", expect_ok=False)
        self.assertIn("Unknown list", out.stdout + out.stderr)

    # shared behaviour

    def test_missing_token_stops_before_any_run(self):
        out = self.run_script("account-research", "account_research.py", "--accounts", "acme.com", token=None, expect_ok=False)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("APIFY_TOKEN", out.stdout + out.stderr)
        self.assertEqual(self.calls(), [])

    def test_unknown_prices_need_explicit_cap(self):
        dead = "http://127.0.0.1:9"
        out = self.run_script("hiring-signals", "hiring_signals.py", "--domains-file", self.write("a.txt", ["acme.com"]),
                              base=dead, expect_ok=False)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("--max-charge", out.stdout + out.stderr)
        self.assertEqual(self.calls(), [])
        self.run_script("hiring-signals", "hiring_signals.py", "--domains-file", "a.txt", "--max-charge", "1", base=dead)
        self.assertEqual(self.calls()[0]["cap"], "1.0")


class CsvSafeTests(unittest.TestCase):
    def test_formula_cells_are_neutralized(self):
        import apify_common as ac
        for bad in ("=HYPERLINK(\"http://x\")", "+1+1", "-2", "@SUM(A1)", "\tx", "\rx"):
            self.assertEqual(ac.csv_safe(bad), "'" + bad)
        for ok in ("Senior Engineer", "", 42, None, "a=b"):
            self.assertEqual(ac.csv_safe(ok), ok)
        self.assertEqual(ac.csv_safe_rows([{"title": "=cmd", "n": 3}]), [{"title": "'=cmd", "n": 3}])


class ValidatorTests(unittest.TestCase):
    def fresh(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        repo = tmp / "repo"
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return repo

    def validate(self, repo):
        return subprocess.run([sys.executable, str(repo / "tools" / "validate.py")], capture_output=True, text=True, timeout=120)

    def edit(self, repo, rel, old, new):
        p = repo / rel
        text = p.read_text(encoding="utf-8")
        self.assertIn(old, text)
        p.write_text(text.replace(old, new, 1), encoding="utf-8")

    def test_clean_repo_passes(self):
        out = self.validate(self.fresh())
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_catches_drift(self):
        cases = [
            ("README.md", "| [hiring-signals](skills/hiring-signals/SKILL.md) | 1.0.0 |", "| [hiring-signals](skills/hiring-signals/SKILL.md) | 0.9.0 |", "skills table shows"),
            ("skills/hiring-signals/SKILL.md", "## Honest limits", "## Honest limits\n\nIt costs $0.05 per company.\n", "outside the README price table"),
            ("skills/tech-job-search/SKILL.md", "name: tech-job-search", "name: tech-jobs", "must match the folder"),
            ("skills/account-research/scripts/apify_common.py", "STORE_USER", "STORE_OWNER", "differs from tools/apify_common.py"),
            ("skills/account-research/SKILL.md", "## Workflow", "## Workflow " + chr(0x2014), "em or en dash"),
            ("skills/account-research/SKILL.md", "--no-descriptions", "--no-desc", "flags not accepted"),
            (".claude-plugin/marketplace.json", '"version": "1.0.0"', '"version": "1.0.1"', "differs from plugin.json"),
            ("skills/hiring-signals/SKILL.md", "Ranks a list of target accounts", "Sorts a list of target accounts", "must open with"),
            ("skills/competitor-hiring-tracker/SKILL.md", "## Honest limits", "Try https://apify.com/conserving_celerytop\n\n## Honest limits", "exactly once"),
            ("README.md", "Know which accounts", "Super" + "charge and know which accounts", "hype word"),
            ("skills/hiring-signals/scripts/hiring_signals.py", '(STACK_ACTOR, "site-analyzed"),', '(STACK_ACTOR, "site-visit"),', "not in the README price table"),
            ("README.md", "| `conserving_celerytop/tech-jobs-search` | `matching-job` | $0.0005 |", "| `conserving_celerytop/tech-jobs-search` | `matching-job` | about 0.0005 |", "four plain dollar prices"),
        ]
        for rel, old, new, expect in cases:
            with self.subTest(rel=rel, expect=expect):
                repo = self.fresh()
                self.edit(repo, rel, old, new)
                out = self.validate(repo)
                self.assertNotEqual(out.returncode, 0, f"validator missed: {expect}")
                self.assertIn(expect, out.stdout)


if __name__ == "__main__":
    unittest.main()
