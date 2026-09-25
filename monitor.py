"""Check tour availability, log it, and notify (Mac + phone via ntfy) when the status changes."""
import csv
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from fetch import ADULTS, DATE, HERE, fetch

LOG = HERE / "log.csv"
STATE = HERE / "state.json"
NTFY_TOPIC_FILE = HERE / "ntfy_topic.txt"
TOUR_URL = f"https://www.getyourguide.com/rome-l33/skip-the-line-vatican-highlights-morning-tour-t9537?date_from={DATE}"


def find_option_cards(obj):
    if isinstance(obj, dict):
        if obj.get("type") == "carouselOptionCard":
            yield obj
        for v in obj.values():
            yield from find_option_cards(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from find_option_cards(v)


def parse(data):
    """Return (available, spots_left, message, slots) for the tour option.

    slots is a list of (start time label, total price label), e.g. ("8:00 AM", "$163.50").
    """
    cards = list(find_option_cards(data))
    if not cards:
        raise ValueError("no option card in response - API format may have changed")
    card = cards[0]
    available = card.get("onImpressionEvent", {}).get("properties", {}).get("available")
    if available is None:
        raise ValueError("no 'available' flag in response - API format may have changed")
    message = (card.get("warningLabel") or {}).get("label", {}).get("text", "").strip()
    m = re.search(r"(\d+) spots? left", message)
    spots = int(m.group(1)) if m else None
    slots = [
        (a.get("label", {}).get("text", "").replace("\u202f", " "),
         a.get("totalPrice", {}).get("priceLabel", {}).get("text", ""))
        for a in (card.get("startTimePicker") or {}).get("availabilities", [])
    ]
    return available, spots, message, slots


def ntfy_topic():
    topic = os.environ.get("NTFY_TOPIC")
    if not topic and NTFY_TOPIC_FILE.exists():
        topic = NTFY_TOPIC_FILE.read_text().strip()
    return topic


def push(title, text, priority=3, tags=(), click=None):
    """Send a phone notification via ntfy. Failures are printed, never raised."""
    topic = ntfy_topic()
    if not topic:
        return
    msg = {"topic": topic, "title": title, "message": text, "priority": priority, "tags": list(tags)}
    if click:
        msg["click"] = click
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(msg).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15).close()
    except Exception as e:
        print(f"ntfy push failed: {e}", file=sys.stderr)


def notify(title, text, priority=3, tags=(), click=None):
    """Notify on the Mac (if running on one) and on the phone via ntfy."""
    if sys.platform == "darwin":
        # Pass text as arguments rather than embedding it in the script, so quotes/emoji can't break it
        script = ('on run argv\n'
                  'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"\n'
                  'end run')
        subprocess.run(["osascript", "-e", script, title, text], check=False)
    push(title, text, priority, tags, click)


def main():
    now = datetime.now().isoformat(timespec="seconds")
    try:
        available, spots, message, slots = parse(fetch())
        times = ", ".join(t for t, _ in slots)
        status = f"AVAILABLE: {times or 'times not listed'}" if available \
            else f"unavailable: {message or 'no reason given'}"
    except (Exception, SystemExit) as e:
        available, spots, message, slots, times = None, None, "", [], ""
        status = f"ERROR: {str(e).splitlines()[0][:200]}"

    new_log = not LOG.exists()
    with LOG.open("a", newline="") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["timestamp", "date", "adults", "available", "spots_left", "message", "slots", "status"])
        w.writerow([now, DATE, ADULTS, available, spots, message,
                    "; ".join(f"{t} {p}" for t, p in slots), status])

    prev = json.loads(STATE.read_text())["status"] if STATE.exists() else None
    if status != prev:
        STATE.write_text(json.dumps({"status": status, "since": now}))
        if available:
            notify("🎉 Vatican tour AVAILABLE", f"{DATE} for {ADULTS}: {times or 'check site'} - book now!",
                   priority=5, tags=["tada"], click=TOUR_URL)
            if sys.platform == "darwin":
                subprocess.run(["open", TOUR_URL], check=False)
        elif status.startswith("ERROR"):
            notify("Vatican monitor error", status, priority=3, tags=["warning"])
        elif prev is not None:
            notify("Vatican tour status changed", status, priority=4, tags=["information_source"])
    print(f"{now}  {status}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        notify("🎉 Vatican monitor test", "If you see this, notifications work. Tap to open the tour page.",
               priority=5, tags=["tada"], click=TOUR_URL)
    else:
        main()
