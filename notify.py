"""Notifications: Mac popup (when running on a Mac) + phone push via ntfy.sh."""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

NTFY_TOPIC_FILE = Path(__file__).parent / "ntfy_topic.txt"


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
