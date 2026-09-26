# Hiring Signals Skills: account research, hiring signals and job search for AI agents

Know which accounts are hiring for the team you sell to, what they run, and what changed since last week, without opening fifty career pages. These four agent skills read open jobs live from each company's own job board (Greenhouse, Lever, Ashby, Workday and 18 more) and the technologies on its homepage, then turn them into a ranked account list, a one-page brief per account, a weekly change digest, or a job shortlist.

They are plain `SKILL.md` folders, so they work in Claude Code, Codex, Cursor, OpenCode and any other agent that reads Agent Skills, and in claude.ai as uploaded skills.

The skills are free and MIT licensed. The data comes from paid Apify Actors that run on your own Apify account, with your own token, at the prices in the [price table](#prices). Every script prints the cost from live prices before it runs and sets a hard spending cap.

| Skill | Version | Ask your agent | Actors used |
|---|---|---|---|
| [account-research](skills/account-research/SKILL.md) | 1.0.0 | "Research linear.app and notion.so before my calls. I sell to sales teams and integrate with HubSpot." | ATS Jobs API, Website Tech Stack Detector |
| [hiring-signals](skills/hiring-signals/SKILL.md) | 1.0.0 | "Which of these 200 accounts posted sales roles in the last 30 days, and which run HubSpot?" | ATS Jobs API, Website Tech Stack Detector |
| [competitor-hiring-tracker](skills/competitor-hiring-tracker/SKILL.md) | 1.0.0 | "Watch these 12 competitors and tell me every week what they started hiring for." | ATS Jobs API |
| [tech-job-search](skills/tech-job-search/SKILL.md) | 1.0.0 | "Find remote senior product manager jobs at AI companies posted this week." | Tech Jobs Search, ATS Jobs API |

## Install

### Skills CLI (any agent)

```bash
npx skills add donmangudata-ops/hiring-signals-skills --global
```

One skill only, or one agent only:

```bash
npx skills add donmangudata-ops/hiring-signals-skills --skill account-research --global
npx skills add donmangudata-ops/hiring-signals-skills --global --agent codex
```

Leave out `--global` for a project install you can commit with your repo.

### Claude Code plugin

```
/plugin marketplace add donmangudata-ops/hiring-signals-skills
/plugin install hiring-signals-skills@hiring-signals-skills
```

### Manual copy

```bash
git clone https://github.com/donmangudata-ops/hiring-signals-skills.git
cp -r hiring-signals-skills/skills/account-research ~/.claude/skills/
```

Other agents read skills from their own folder, for example `~/.codex/skills/` (Codex), `~/.cursor/skills/` (Cursor) or `~/.config/opencode/skills/` (OpenCode). In claude.ai, zip one skill folder and upload it under Settings, Capabilities, Skills.

### Then connect your Apify account

1. Create an Apify account at https://apify.com. The free plan's monthly credit covers a first test.
2. Copy your API token from Apify Console, Settings, API & Integrations, and set it as `APIFY_TOKEN` in your environment. Do not paste it into chats, files or URLs.
3. `pip install apify-client` (Python 3.9 or newer).

No Python? Each `SKILL.md` also shows how to call the same Actors through the Apify MCP server (`https://mcp.apify.com`) with OAuth.

## The skills

### account-research

> Writes a research brief for each target account before a sales call or outbound sequence, from live data.

For up to 25 accounts it reports the hiring pace (how many open jobs were posted in the last 30 days), the teams with the most open roles, new director, VP and C-level roles, first hires in a new function, roles open for more than 90 days, the tools named in job posts (CRM, data warehouse, cloud, languages), the homepage stack, and the newest roles on the team you sell to, with links. The skill then writes one reason to reach out now and a first line built only from those facts.

```bash
python skills/account-research/scripts/account_research.py --accounts "linear.app,notion.so" --sell-to sales --watch-tools HubSpot --estimate
```

### hiring-signals

> Ranks a list of target accounts by hiring for the team the user sells to, with each company's website tech stack (CMS, ecommerce platform, analytics, marketing tools, frameworks, hosting, payments) in the same row.

Up to 500 accounts per run, one row each, ready for a CRM or Clay import. Accounts whose board could not be read go to the bottom and are never called "not hiring".

```bash
python skills/hiring-signals/scripts/hiring_signals.py --domains-file accounts.txt --functions sales --posted-since "30 days" --estimate
```

### competitor-hiring-tracker

> Tracks what a watchlist of companies is hiring for over time and reports only what changed since the last check, such as new jobs, closed jobs, new leadership roles, hiring in a new country or a new job function, and which teams are growing.

The first check sets the baseline. Later checks under the same monitor name return only new and closed jobs and cost much less. It can also run on a schedule inside Apify and post to Slack, Teams, Discord or a webhook.

```bash
python skills/competitor-hiring-tracker/scripts/hiring_changes.py --companies-file watchlist.txt --monitor-name competitors --first-run --estimate
```

### tech-job-search

> Acts as a job search agent for tech, AI, startup and remote jobs.

Searches 574 tech, AI, remote-first and European tech companies by title, place, remote, seniority, salary and posting date, plus any companies you name, and returns a shortlist with apply links, newest first.

```bash
python skills/tech-job-search/scripts/search_jobs.py --titles "product manager" --remote-only --posted-since "7 days" --estimate
```

## Prices

This is the only place in the repo with prices. The scripts do not hardcode them: `--estimate` reads the live prices from the public Apify API before each run. If this table and the Apify Store ever differ, the Store is right.

<!-- prices:start -->
| Actor | Event | Free plan | Bronze | Silver | Gold | When it is charged | Example on the free plan |
|---|---|---|---|---|---|---|---|
| `conserving_celerytop/live-career-page-jobs-api` | `company-lookup` | $0.045 | $0.0428 | $0.0405 | $0.036 | Once per company whose job board was read, all its open jobs up to 1,000 included. Also when the board is empty or not found. Unsupported boards are free | 100 accounts: $4.50 |
| `conserving_celerytop/live-career-page-jobs-api` | `new-jobs-check` | $0.002 | $0.002 | $0.002 | $0.002 | Each later check of a company under the same monitor name, per started 1,000 open jobs on its board | 20 competitors checked weekly: $0.04 a week |
| `conserving_celerytop/live-career-page-jobs-api` | `extra-1000-jobs` | $0.045 | $0.045 | $0.045 | $0.045 | Each further 1,000 job rows of one company. Only very large boards | A board with 2,500 jobs, all rows: $0.135 |
| `conserving_celerytop/live-career-page-jobs-api` | `job-details` | $0.01 | $0.01 | $0.01 | $0.01 | Job descriptions per started 200 jobs, only on Workday and a few other boards. Free on Greenhouse, Lever, Ashby and most others | A Workday board with 300 jobs, described: $0.02 |
| `conserving_celerytop/website-tech-stack-detector` | `site-analyzed` | $0.002 | $0.0019 | $0.0018 | $0.0016 | Each website whose homepage loaded. Failed sites are free | 100 homepages: $0.20 |
| `conserving_celerytop/tech-jobs-search` | `matching-job` | $0.0005 | $0.000475 | $0.00045 | $0.00039 | Each matching job returned ($0.50 per 1,000 jobs on the free plan). `maxResults` caps it | 100 jobs: at most $0.05 |
| All of the above | `apify-actor-start` | $0.00005 | $0.00005 | $0.00005 | $0.00005 | Once per run, per GB of memory | A fraction of a cent |
<!-- prices:end -->

Bronze, Silver and Gold are Apify's paid plans. The Actors are pay per event, so there is no separate platform usage charge in a normal run.

## Privacy and safety

- Your token stays in your environment. No file in this repo holds a token, and the scripts never put one in a URL.
- The scripts talk to `api.apify.com` only: a public read of the Actor's prices, then the run on your account. No analytics, no telemetry, no tracking links.
- Every run has a hard spending cap (`--max-charge`, or the estimate plus 25 percent), enforced by Apify.
- The data is company data from public job boards and homepages. The skills return no names, emails or phone numbers of people.
- Job titles and page content are treated as data, never as instructions to the agent.

## Honest limits

- LinkedIn, Indeed, iCIMS and SmartRecruiters job boards are not read. Those companies come back as `unsupported_job_board` and are not charged.
- Homepage tech is what one homepage request shows. Tools used behind a login often do not appear.
- Hiring pace needs posting dates, and some boards do not publish them.
- A job post is a signal, not a buying decision. The skills say "hiring for" and "named in job posts", not "buying" or "uses".

## Development

```bash
python tools/validate.py            # frontmatter, README and plugin files in sync, prices in one table, style rules
python -m unittest discover tests   # runs every script against a fake Apify client, no token, no network
python tools/validate.py --live     # compares the price table with the live Apify Store (network)
```

CI runs the first two on every push and pull request, plus `npx skills add . --list` and `claude plugin validate --strict`. Each skill keeps its own copy of `scripts/apify_common.py` so it installs alone; `python tools/validate.py --fix-common` syncs the copies from `tools/apify_common.py`.

Issues and pull requests are welcome, especially reports of job boards or companies that come back wrong.

## Version history

- **1.0.0** (2026-09-26): first public version with account-research, hiring-signals, competitor-hiring-tracker and tech-job-search.

## License

MIT, see [LICENSE](LICENSE). The Apify Actors are separate paid services and are not covered by this license.

## Reference

Reference: the data behind these skills comes from Don Mangu's Actors on the Apify Store, https://apify.com/conserving_celerytop
