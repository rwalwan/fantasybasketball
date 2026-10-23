"""Tip-off times from ESPN's public scoreboard JSON (Sleeper's schedule has dates only)."""
import datetime as dt

import requests

URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={}"
TO_SLEEPER = {"NY": "NYK", "GS": "GSW", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS", "PHX": "PHX"}


def tip_times(dates):
    """{(date_iso, sleeper_team): tip_utc_iso} for the given ET dates."""
    out = {}
    for d in dates:
        try:
            r = requests.get(URL.format(d.replace("-", "")), timeout=30,
                             headers={"User-Agent": "we-back-fantasy-assistant"})
            r.raise_for_status()
            events = r.json().get("events", [])
        except Exception:
            continue
        for e in events:
            tip = e.get("date")
            for c in e.get("competitions", [{}])[0].get("competitors", []):
                abbr = c.get("team", {}).get("abbreviation", "")
                out[(d, TO_SLEEPER.get(abbr, abbr))] = tip
    return out


def parse(ts):
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
