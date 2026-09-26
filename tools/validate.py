#!/usr/bin/env python3
"""Validate the repo: skills, README, plugin files and prices stay in sync. No dependencies.

  python tools/validate.py              offline checks (CI runs this)
  python tools/validate.py --live       also compare the price table with the live Apify Store
  python tools/validate.py --fix-common copy tools/apify_common.py into every skill, then check
"""
import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
README = ROOT / "README.md"
COMMON = ROOT / "tools" / "apify_common.py"
PROFILE_URL = "https://apify.com/conserving_celerytop"
REPO_SLUG = "donmangudata-ops/hiring-signals-skills"
ALLOWED_KEYS = {"name", "description", "license", "metadata"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
DISCLOSURE_RE = re.compile(r"built and published by Don Mangu, the author of this skill")
PRICE_START, PRICE_END = "<!-- prices:start -->", "<!-- prices:end -->"
DOLLAR_RE = re.compile(r"\$\d")
HYPE = ["supercharge", "seamless", "seamlessly", "revolutionize", "revolutionary", "game-changer",
        "game-changing", "unleash", "effortless", "effortlessly", "cutting-edge", "world-class",
        "best-in-class", "skyrocket", "turbocharge", "next-level"]
TEXT_SUFFIXES = {".md", ".py", ".json", ".yml", ".yaml", ".txt"}
TOKEN_RES = [re.compile(r"apify_api_[A-Za-z0-9]{10,}"), re.compile(r"[?&]token=[A-Za-z0-9]")]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TIERS = ["FREE", "BRONZE", "SILVER", "GOLD"]

errors = []


def err(msg):
    errors.append(msg)


def parse_frontmatter(text):
    """Parse the small YAML subset used here: top-level scalars and one level of nested string maps."""
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None, text
    data, current = {}, None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        if line.startswith("  ") and current is not None:
            k, _, v = line.strip().partition(":")
            data[current][k.strip()] = unquote(v.strip())
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if v == "":
            data[k] = {}
            current = k
        else:
            data[k] = unquote(v)
            current = None
    return data, text[m.end():]


def unquote(v):
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def first_sentence(text):
    m = re.search(r"\.(\s|$)", text)
    return text[: m.start() + 1] if m else text


def money(cell):
    m = re.fullmatch(r"\$(\d+(?:\.\d+)?)", cell.strip())
    return float(m.group(1)) if m else None


def parse_price_table(readme_text):
    """Return {(actor_id, event): {"FREE": price, ...}} from the one price table in the README."""
    if readme_text.count(PRICE_START) != 1 or readme_text.count(PRICE_END) != 1:
        raise ValueError("README needs exactly one price table between the prices:start and prices:end markers")
    block = readme_text.split(PRICE_START)[1].split(PRICE_END)[0]
    rows = [r for r in block.strip().splitlines() if r.startswith("|")]
    if len(rows) < 3:
        raise ValueError("price table has no rows")
    table = {}
    for r in rows[2:]:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        actor, event = cells[0].strip("`"), cells[1].strip("`")
        prices = [money(c) for c in cells[2:6]]
        if None in prices:
            raise ValueError(f"price row for {actor} {event} needs four plain dollar prices, got {cells[2:6]}")
        table[(actor, event)] = dict(zip(TIERS, prices))
    return table


def help_flags(script):
    out = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        err(f"{script.relative_to(ROOT)} --help failed: {out.stderr.strip()[:300]}")
        return set()
    return set(re.findall(r"--[a-z][a-z0-9-]*", out.stdout))


def billed_events(script):
    tree = ast.parse(script.read_text(encoding="utf-8"))
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if isinstance(node.value, ast.Constant):
                consts[name] = node.value.value
            elif name == "BILLED_EVENTS":
                pairs = []
                for elt in node.value.elts:
                    a, e = elt.elts
                    actor = consts.get(a.id) if isinstance(a, ast.Name) else a.value
                    pairs.append((actor, e.value))
                return pairs
    return None


def check_skill(folder, readme_text, plugin_version, price_table):
    rel = folder.relative_to(ROOT)
    skill_md = folder / "SKILL.md"
    if not skill_md.exists():
        err(f"{rel}: missing SKILL.md")
        return
    text = skill_md.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    if fm is None:
        err(f"{rel}/SKILL.md: must start with YAML frontmatter")
        return
    extra = set(fm) - ALLOWED_KEYS
    if extra:
        err(f"{rel}/SKILL.md: nonportable frontmatter keys {sorted(extra)}; use only {sorted(ALLOWED_KEYS)}")
    name = fm.get("name", "")
    if name != folder.name:
        err(f"{rel}/SKILL.md: name '{name}' must match the folder name '{folder.name}'")
    if not NAME_RE.match(name) or len(name) > 64:
        err(f"{rel}/SKILL.md: name must be lowercase letters, digits and single hyphens, 64 characters at most")
    desc = fm.get("description", "")
    if not desc or len(desc) > 1024:
        err(f"{rel}/SKILL.md: description must be 1 to 1024 characters (now {len(desc)})")
    if "Use when" not in desc:
        err(f"{rel}/SKILL.md: description must say when to use the skill ('Use when ...')")
    if fm.get("license") != "MIT":
        err(f"{rel}/SKILL.md: license must be MIT")
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    version = meta.get("version", "")
    if not SEMVER_RE.match(version):
        err(f"{rel}/SKILL.md: metadata.version must be a quoted x.y.z version")
    elif version != plugin_version:
        err(f"{rel}/SKILL.md: metadata.version {version} differs from plugin.json {plugin_version}")
    if len(text.splitlines()) > 500:
        err(f"{rel}/SKILL.md: over 500 lines")

    # Disclosure at the top, exactly one reference at the bottom.
    if not DISCLOSURE_RE.search(body):
        err(f"{rel}/SKILL.md: needs the disclosure sentence ('built and published by Don Mangu, the author of this skill')")
    if text.count(PROFILE_URL) != 1:
        err(f"{rel}/SKILL.md: the profile link must appear exactly once (found {text.count(PROFILE_URL)})")
    h2 = re.findall(r"(?m)^## (.+)$", body)
    if not h2 or h2[-1] != "Reference":
        err(f"{rel}/SKILL.md: the last section must be '## Reference'")
    else:
        ref = body.split("\n## Reference\n", 1)[1]
        ref_lines = [x for x in ref.splitlines() if x.strip()]
        if len(ref_lines) != 1 or PROFILE_URL not in ref_lines[0]:
            err(f"{rel}/SKILL.md: '## Reference' must hold one line with the profile link")
    if f"github.com/{REPO_SLUG}#prices" not in body:
        err(f"{rel}/SKILL.md: must link the price table (github.com/{REPO_SLUG}#prices)")

    # Scripts: referenced ones exist, flags used in SKILL.md exist, shared helper in sync, events priced.
    scripts = sorted(set(re.findall(r"scripts/([a-z0-9_]+\.py)", body)))
    if not scripts:
        err(f"{rel}/SKILL.md: references no script")
    for s in scripts:
        path = folder / "scripts" / s
        if not path.exists():
            err(f"{rel}/SKILL.md: references scripts/{s}, which does not exist")
            continue
        known = help_flags(path)
        used = set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", body))
        missing = sorted(used - known - {"--global", "--skill", "--agent", "--list"})
        if missing:
            err(f"{rel}/SKILL.md: flags not accepted by scripts/{s}: {missing}")
        events = billed_events(path)
        if not events:
            err(f"{rel}/scripts/{s}: needs a BILLED_EVENTS list")
        else:
            for pair in events:
                if pair not in price_table:
                    err(f"{rel}/scripts/{s}: billed event {pair} is not in the README price table")
    common = folder / "scripts" / "apify_common.py"
    if not common.exists() or common.read_bytes() != COMMON.read_bytes():
        err(f"{rel}/scripts/apify_common.py: missing or differs from tools/apify_common.py (run --fix-common)")

    # README drift: table row with the same version, a section quoting the description's first sentence.
    row = re.search(rf"(?m)^\| \[{re.escape(name)}\]\(skills/{re.escape(name)}/SKILL\.md\) \| ([^|]+) \|", readme_text)
    if not row:
        err(f"README: no skills table row for {name}")
    elif row.group(1).strip() != version:
        err(f"README: skills table shows {name} {row.group(1).strip()}, SKILL.md has {version}")
    sec = re.search(rf"(?m)^### {re.escape(name)}\n\n(.+)$", readme_text)
    if not sec:
        err(f"README: no '### {name}' section")
    elif sec.group(1).strip() != "> " + first_sentence(desc):
        err(f"README: the '### {name}' section must open with '> {first_sentence(desc)}'")


def check_text_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES or ".git" in path.parts:
            continue
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        is_self = path.resolve() == Path(__file__).resolve()
        if chr(0x2014) in text or chr(0x2013) in text:
            err(f"{rel}: contains an em or en dash")
        if not is_self:
            low = text.lower()
            for w in HYPE:
                if re.search(rf"(?<![a-z-]){re.escape(w)}(?![a-z-])", low):
                    err(f"{rel}: hype word '{w}'")
            for rx in TOKEN_RES:
                if rx.search(text):
                    err(f"{rel}: looks like a token or a token in a URL")
            if EMAIL_RE.search(text):
                err(f"{rel}: contains an email address")
        if rel.parts[0] == "tests" or is_self:
            continue
        scan = text
        if path == README:
            scan = text.split(PRICE_START)[0] + text.split(PRICE_END)[-1] if PRICE_START in text else text
        for m in DOLLAR_RE.finditer(scan):
            line = scan[: m.start()].count("\n") + 1
            err(f"{rel}:{line}: a price outside the README price table ('{scan[m.start():m.start() + 8]}')")


def check_plugin_files(skill_names):
    try:
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        err(f".claude-plugin: {e}")
        return ""
    version = plugin.get("version", "")
    if not SEMVER_RE.match(version):
        err("plugin.json: version must be x.y.z")
    for k in ("name", "description", "author", "homepage", "repository", "license"):
        if not plugin.get(k):
            err(f"plugin.json: missing {k}")
    if plugin.get("license") != "MIT":
        err("plugin.json: license must be MIT")
    if REPO_SLUG not in str(plugin.get("repository", "")):
        err(f"plugin.json: repository must be {REPO_SLUG}")
    entries = [p for p in market.get("plugins", []) if p.get("name") == plugin.get("name")]
    if not entries:
        err("marketplace.json: no plugin entry named like plugin.json")
    else:
        e = entries[0]
        if e.get("source") != "./":
            err("marketplace.json: the plugin source must be './' (single-repo marketplace)")
        if e.get("version") != version:
            err(f"marketplace.json: version {e.get('version')} differs from plugin.json {version}")
        if e.get("description") != plugin.get("description"):
            err("marketplace.json: plugin description differs from plugin.json")
    if not market.get("owner", {}).get("name"):
        err("marketplace.json: missing owner.name")
    readme = README.read_text(encoding="utf-8")
    hist = re.search(r"(?m)^- \*\*(\d+\.\d+\.\d+)\*\*", readme)
    if not hist or hist.group(1) != version:
        err(f"README: the newest version history entry must be {version}")
    rows = set(re.findall(r"(?m)^\| \[([a-z0-9-]+)\]\(skills/", readme))
    if rows != set(skill_names):
        err(f"README: skills table lists {sorted(rows)}, folders are {sorted(skill_names)}")
    if readme.count(PROFILE_URL) != 1:
        err(f"README: the profile link must appear exactly once (found {readme.count(PROFILE_URL)})")
    return version


def live_check(price_table):
    diffs = 0
    for actor in sorted({a for a, _ in price_table if "/" in a}):
        url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}"
        with urllib.request.urlopen(url, timeout=20) as r:
            info = (json.load(r)["data"].get("pricingInfos") or [{}])[-1]
        events = (info.get("pricingPerEvent") or {}).get("actorChargeEvents") or {}
        for (a, event), tiers in sorted(price_table.items()):
            if a != actor:
                continue
            ev = events.get(event)
            if ev is None:
                print(f"LIVE DIFF {actor} {event}: not on the Store")
                diffs += 1
                continue
            for t in TIERS:
                tiered = (ev.get("eventTieredPricingUsd") or {}).get(t, {}).get("tieredEventPriceUsd")
                live = tiered if tiered is not None else ev.get("eventPriceUsd")
                if live is None or abs(float(live) - tiers[t]) > 1e-9:
                    print(f"LIVE DIFF {actor} {event} {t}: table {tiers[t]}, Store {live}")
                    diffs += 1
    print(f"Live price check: {diffs} difference(s).")
    return diffs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="Also compare the price table with the live Apify Store")
    ap.add_argument("--fix-common", action="store_true", help="Copy tools/apify_common.py into every skill first")
    a = ap.parse_args()

    folders = sorted(p for p in SKILLS.iterdir() if p.is_dir())
    if a.fix_common:
        for f in folders:
            shutil.copyfile(COMMON, f / "scripts" / "apify_common.py")
    readme_text = README.read_text(encoding="utf-8")
    try:
        price_table = parse_price_table(readme_text)
    except ValueError as e:
        err(f"README: {e}")
        price_table = {}
    version = check_plugin_files([f.name for f in folders])
    for f in folders:
        check_skill(f, readme_text, version, price_table)
    check_text_files()
    if not (ROOT / "LICENSE").exists() or "MIT License" not in (ROOT / "LICENSE").read_text(encoding="utf-8"):
        err("LICENSE: must be the MIT license")

    if errors:
        print(f"{len(errors)} problem(s):")
        for e in errors:
            print(f"- {e}")
        sys.exit(1)
    print(f"OK: {len(folders)} skills, version {version}, {len(price_table)} priced events, README and plugin files in sync.")
    if a.live and live_check(price_table):
        sys.exit(1)


if __name__ == "__main__":
    main()
