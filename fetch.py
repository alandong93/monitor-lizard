"""Fetch GetYourGuide availability for the Vatican Highlights tour and save the raw response."""
import json
import os
from datetime import date as date_cls, timedelta
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
URL = "https://travelers-api.getyourguide.com/user-interface/activity-details-page/blocks"
# MONITOR_DATE / MONITOR_ADULTS env vars override these (used for test runs on GitHub)
DATE = os.environ.get("MONITOR_DATE") or "2026-10-05"
ADULTS = int(os.environ.get("MONITOR_ADULTS") or 2)
ACTIVITY_ID = 9537

HEADERS = {
    "Referer": "https://www.getyourguide.com/",
    "Origin": "https://www.getyourguide.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                  "(KHTML, like Gecko) Version/27.0.1 Safari/605.1.15",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Accept-Language": "en-US",
    "accept-currency": "USD",
    "visitor-platform": "desktop",
    "x-gyg-app-type": "Web",
    "x-gyg-is-new-visitor": "true",
    "x-gyg-original-accept-language": "en-US",
    "partner-id": "",
    "x-gyg-partner-hash": "",
    "x-gyg-geoip-country": "US",
    "geo-ip-country": "US",
    "x-gyg-geoip-city": "-",
    "x-gyg-time-zone": "America/Los_Angeles",
    "visitor-id": "PQ8QC242PJEZC5H5SQOFL4WOTDNKSKTK",
}


def build_payload(date=DATE, adults=ADULTS):
    return {
        "events": [{"event": {
            "type": "bookingAssistantInputsChanged",
            "emitterId": "bookingAssistantConfiguratorContentIdentifier",
            "payload": {
                "participants": [{"categoryId": 1, "count": adults},
                                 {"categoryId": 3, "count": 0},
                                 {"categoryId": 4, "count": 0}],
                "language": "",
                "selectedDate": date,
                "hasButtonBeenClickedWithValidForm": True,
            },
        }}],
        "payload": {
            "activityId": ACTIVITY_ID,
            "templateName": "ActivityDetails",
            "contentIdentifier": "bookingAssistantConfiguratorContentIdentifier",
            "rankingUuid": "3b537b75-5f79-4005-86a6-94810eaa1a55",
            "participantsLanguage": "en-US",
            "participants": [{"categoryId": 1, "count": adults}],
            "datesSelected": {"fromDate": date, "toDate": str(date_cls.fromisoformat(date) + timedelta(days=30))},
            "hasButtonBeenClickedWithValidForm": False,
            "reviewsExperiments": [],
            "fromPriceAtPageLoad": {"price": 81.75, "formattedPrice": "$82"},
        },
    }


def fetch(date=DATE, adults=ADULTS):
    req = urllib.request.Request(
        f"{URL}?ranking_uuid=3b537b75-5f79-4005-86a6-94810eaa1a55"
        f"&q=vatican+highlights+fast+track&_pc=1%2C2&date_from={date}",
        data=json.dumps(build_payload(date, adults)).encode(),
        headers=HEADERS,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        (HERE / "last_error.txt").write_text(f"HTTP {e.code} {e.reason}\n{e.headers}\n{body}")
        raise SystemExit(f"HTTP {e.code} {e.reason}\n{body[:1000]}")


if __name__ == "__main__":
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else DATE
    adults = int(sys.argv[2]) if len(sys.argv) > 2 else ADULTS
    data = fetch(date, adults)
    out = HERE / ("last_response.json" if (date, adults) == (DATE, ADULTS)
                  else f"response_{date}_{adults}.json")
    out.write_text(json.dumps(data, indent=2))
    print(f"OK - saved {out} ({out.stat().st_size} bytes)")
