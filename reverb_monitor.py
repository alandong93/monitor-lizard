"""Watch a Reverb search and notify (Mac + phone via ntfy) on new listings, price drops, relists and sales.

Run: python3 reverb_monitor.py          (normal check)
     python3 reverb_monitor.py --test   (send a test notification)
"""
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from notify import notify

HERE = Path(__file__).parent
STATE = HERE / "reverb_state.json"
LOG = HERE / "reverb_log.csv"
# MONITOR_QUERY env var overrides this (used for test runs on GitHub)
QUERY = os.environ.get("MONITOR_QUERY") or "abasi cordoba stage 7"
CONDITIONS = ("used", "b-stock", "mint", "excellent", "very-good")
SEARCH_URL = "https://reverb.com/marketplace?" + urllib.parse.urlencode(
    [("query", QUERY)] + [("condition[]", c) for c in CONDITIONS])
# When only a USD-converted price is available, ignore drops smaller than this between checks
# (exchange rates move far less than this in one check interval; real price cuts are sudden)
FX_NOISE = 0.03
# A listing must be missing from this many consecutive checks before it's reported gone
GONE_AFTER = 2


def api_get(page=1, currency=None):
    params = urllib.parse.urlencode([("query", QUERY), ("per_page", 50), ("page", page)]
                                    + [("condition[]", c) for c in CONDITIONS])
    headers = {"Accept-Version": "3.0", "Accept": "application/hal+json",
               "User-Agent": "reverb-search-monitor (personal use)"}
    if currency:
        headers["X-Display-Currency"] = currency
    req = urllib.request.Request(f"https://api.reverb.com/api/listings?{params}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Reverb HTTP {e.code} {e.reason}: {e.read().decode(errors='replace')[:300]}")


def search(currency=None):
    """Return all live listings for the search (follows pagination)."""
    listings, page = [], 1
    while True:
        data = api_get(page, currency)
        listings += data.get("listings", [])
        if page >= data.get("total_pages", 1):
            return listings
        page += 1


def fetch():
    """Return {id: listing info} with each price in the listing's own currency where possible.

    The API converts prices to USD at the current exchange rate, which would make EUR/GBP listings look
    like they change price every day. So re-fetch once per foreign currency to get the seller's price.
    """
    listings = search()
    native = {}
    for cur in {l.get("listing_currency") for l in listings} - {"USD", None}:
        for l in search(cur):
            if l["price"]["currency"] == cur:
                native[l["id"]] = l["price"]
    out = {}
    for l in listings:
        exact = l["listing_currency"] == l["price"]["currency"] or l["id"] in native
        price = l["price"] if l["listing_currency"] == l["price"]["currency"] else native.get(l["id"], l["price"])
        out[str(l["id"])] = {
            "title": l["title"],
            "condition": l["condition"]["display_name"],
            "cents": price["amount_cents"],
            "currency": price["currency"],
            "display": price["display"],
            "exact_price": exact,
            "published_at": l.get("published_at"),
            "shop": l.get("shop_name"),
            "url": l["_links"]["web"]["href"],
        }
    return out


def describe(item):
    return f"{item['display']} ({item['condition']}) - {item['title']}"


def compare(old, new):
    """Return (events, merged snapshot) for the change from old to new {id: info} snapshots.

    events is a list of (event, id, item, detail). A listing missing from one response is kept with a
    "missing" count and only reported gone after GONE_AFTER misses, so a flaky response can't trigger
    gone + new alerts for the same listing.
    """
    events, merged = [], {}
    for id_, item in new.items():
        prev = old.get(id_)
        merged[id_] = item
        if prev is None:
            events.append(("new", id_, item, ""))
            continue
        if item["currency"] == prev["currency"] and item["cents"] < prev["cents"]:
            drop = 1 - item["cents"] / prev["cents"]
            if item["exact_price"] and prev["exact_price"] or drop >= FX_NOISE:
                events.append(("price_drop", id_, item, f"{prev['display']} -> {item['display']} (-{drop:.0%})"))
        if prev.get("published_at") and item["published_at"] and item["published_at"] > prev["published_at"]:
            events.append(("relisted", id_, item, f"published {prev['published_at']} -> {item['published_at']}"))
    for id_, prev in old.items():
        if id_ in new:
            continue
        missing = prev.get("missing", 0) + 1
        if missing >= GONE_AFTER:
            events.append(("gone", id_, prev, "sold or ended"))
        else:
            merged[id_] = {**prev, "missing": missing}
    return events, merged


def log(rows):
    new_log = not LOG.exists()
    with LOG.open("a", newline="") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["timestamp", "event", "id", "price", "condition", "title", "detail"])
        w.writerows(rows)


def main():
    now = datetime.now().isoformat(timespec="seconds")
    state = json.loads(STATE.read_text()) if STATE.exists() else None
    try:
        current = fetch()
    except (Exception, SystemExit) as e:
        error = f"ERROR: {str(e).splitlines()[0][:200]}"
        log([[now, "error", "", "", "", "", error]])
        print(f"{now}  {error}")
        if state is not None and state.get("error") != error:
            notify("Reverb monitor error", error, priority=3, tags=["warning"])
        if state is not None:
            state["error"] = error
            STATE.write_text(json.dumps(state, indent=1))
        return

    if state is None:
        # First run: record what's already listed without alerting on each one
        events, merged = [], current
        notify("Reverb monitor started", f"Watching '{QUERY}': {len(current)} listings now", priority=2,
               tags=["guitar"], click=SEARCH_URL)
    else:
        events, merged = compare(state["listings"], current)

    for event, id_, item, detail in events:
        if event == "new":
            notify("🎸 New Reverb listing", describe(item), priority=5, tags=["guitar"], click=item["url"])
        elif event == "price_drop":
            notify("💸 Reverb price drop", f"{detail}: {item['title']}", priority=5, tags=["money_with_wings"],
                   click=item["url"])
        elif event == "relisted":
            notify("🔁 Reverb listing relisted/bumped", describe(item), priority=3, tags=["repeat"],
                   click=item["url"])
        elif event == "gone":
            notify("Reverb listing gone", f"{describe(item)} - sold or ended", priority=2, tags=["wave"],
                   click=item["url"])
        print(f"{now}  {event:<10} {id_}  {describe(item)}  {detail}")

    log([[now, "check", "", "", "", "", f"{len(current)} listings"]]
        + [[now, ev, id_, it["display"], it["condition"], it["title"], d] for ev, id_, it, d in events])
    if state and state.get("error"):
        notify("Reverb monitor recovered", f"{len(current)} listings", priority=2, tags=["white_check_mark"])
    STATE.write_text(json.dumps({"listings": merged, "updated": now}, indent=1))
    print(f"{now}  {len(current)} listings, {len(events)} changes")


if __name__ == "__main__":
    if "--test" in sys.argv:
        notify("🎸 Reverb monitor test", "If you see this, notifications work. Tap to open the search.",
               priority=5, tags=["guitar"], click=SEARCH_URL)
    else:
        main()
