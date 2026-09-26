"""Shared helpers for the scripts in this repo.

Every skill ships its own byte-identical copy as scripts/apify_common.py, so a
skill still works when it is installed on its own. tools/validate.py fails when
a copy drifts from tools/apify_common.py; `python tools/validate.py --fix-common`
copies it again.

Network: the scripts talk to api.apify.com only. Prices are read from the public
Actor page of the Apify API (no token sent). Runs use the user's own APIFY_TOKEN
through the official apify-client package. Nothing else is sent anywhere.
"""
import json
import math
import os
import sys
import urllib.error
import urllib.request
from decimal import Decimal

PRICE_TABLE_URL = "https://github.com/donmangudata-ops/hiring-signals-skills#prices"
STORE_USER = "conserving_celerytop"
TIER_NAMES = ("FREE", "BRONZE", "SILVER", "GOLD")

# Company statuses that mean the board was read. Anything else means "unknown".
READ_STATUSES = {"ok", "no_matching_jobs", "no_open_jobs"}


def api_base():
    return os.environ.get("APIFY_API_BASE_URL", "https://api.apify.com").rstrip("/")


def field(obj, camel, snake=None):
    """Read a field from an apify-client result (dict in v1 and v2, model in v3)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(camel)
    return getattr(obj, snake or camel, None)


def split_list(text):
    return [s.strip() for s in (text or "").split(",") if s.strip()]


def read_entries(path=None, inline="", limit=500):
    """Company entries from a file (one per line, # comments) and/or a comma list, deduplicated."""
    raw = split_list(inline)
    if path:
        with open(path, encoding="utf-8") as f:
            raw += [line.strip() for line in f if line.strip() and not line.lstrip().startswith("#")]
    seen, out = set(), []
    for r in raw:
        key = r.lower().rstrip("/")
        if key not in seen:
            seen.add(key)
            out.append(r)
    if len(out) > limit:
        sys.exit(f"{len(out)} entries; this script takes up to {limit} per run. Split the list.")
    return out


def live_prices(actor_id):
    """Free-plan price per event for a public Store Actor, read from the public Apify API.

    Returns {event_name: price_usd} or None when the prices cannot be read.
    The free-plan price is the highest tier, so an estimate made with it is an upper bound.
    """
    url = f"{api_base()}/v2/acts/{actor_id.replace('/', '~')}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=15) as r:
            data = json.load(r).get("data") or {}
    except (urllib.error.URLError, OSError, ValueError):
        return None
    infos = data.get("pricingInfos") or []
    info = infos[-1] if infos else (data.get("currentPricingInfo") or {})
    events = ((info.get("pricingPerEvent") or {}).get("actorChargeEvents")) or {}
    out = {}
    for name, ev in events.items():
        tiers = ev.get("eventTieredPricingUsd") or {}
        price = (tiers.get("FREE") or {}).get("tieredEventPriceUsd")
        if price is None:
            price = ev.get("eventPriceUsd")
        if price is not None:
            out[name] = float(price)
    return out or None


def estimate(lines):
    """Print a cost estimate and return the total in USD, or None if a price is missing.

    lines: list of (actor_id, event, count, note). Prices are read live; nothing is hardcoded.
    count None means the event may fire but its number is unknown before the run.
    """
    cache, total, missing = {}, 0.0, False
    print("Estimated charge on the free Apify plan (paid plans pay less):")
    for actor_id, event, count, note in lines:
        if actor_id not in cache:
            cache[actor_id] = live_prices(actor_id)
        prices = cache[actor_id]
        price = prices.get(event) if prices else None
        label = f"  {'?' if count is None else count} x {event} ({actor_id.split('/')[-1]})"
        if note:
            label += f", {note}"
        if price is None:
            missing = True
            print(f"{label}: price not available")
        elif count is None:
            print(f"{label}: ${price:.3f} each, not in the total")
        else:
            cost = count * price
            total += cost
            print(f"{label}: ${cost:.3f}")
    starts = len(cache)
    if missing:
        print(f"Could not read live prices. Check the price table before running: {PRICE_TABLE_URL}")
        return None
    print(f"  plus {starts} Actor start event(s), a fraction of a cent each")
    print(f"  Total, about: ${total:.2f}")
    return total


def resolve_cap(user_cap, total):
    """Hard spending cap for a run: the user's --max-charge, or the estimate plus 25 percent."""
    if user_cap is not None:
        return user_cap
    if total is None:
        sys.exit("Live prices are unknown, so pass --max-charge (a hard cap in USD) to run.")
    return max(0.05, math.ceil(total * 1.25 * 100) / 100)


def client():
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("Set APIFY_TOKEN in the environment (Apify Console, Settings, API & Integrations). "
                 "Never write it into a file or a URL.")
    try:
        from apify_client import ApifyClient
    except ImportError:
        sys.exit("Install the Apify client first: pip install apify-client")
    return ApifyClient(token)


def run_actor(apify, actor_id, run_input, cap):
    """Run an Actor with a hard spending cap and return (status, rows, charged_events)."""
    print(f"Running {actor_id} with a spending cap of ${cap:.2f}...")
    run = apify.actor(actor_id).call(run_input=run_input, max_total_charge_usd=Decimal(str(cap)))
    if run is None:
        sys.exit(f"{actor_id}: the run did not start or did not finish.")
    status = field(run, "status")
    status = getattr(status, "value", status)
    rows = list(apify.dataset(field(run, "defaultDatasetId", "default_dataset_id")).iterate_items())
    charged = field(run, "chargedEventCounts", "charged_event_counts") or {}
    charged = dict(charged) if not isinstance(charged, dict) else charged
    print(f"  {status}, {len(rows)} rows, charged events: {charged or 'none reported'}")
    if status and status != "SUCCEEDED":
        print("  The run did not finish cleanly. Rows may be partial; companies past the cap show skipped_spending_limit.")
    return status, rows, charged


def names(items, key="name"):
    out = []
    for t in items or []:
        n = t.get(key) if isinstance(t, dict) else str(t)
        if n and n not in out:
            out.append(n)
    return out


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
