"""Fresher injury reports than Sleeper's labels (Nov 28): ESPN's public injury report, read every minute in the two
hours before each tip by the Worker (worker/src/injuries.js, saved in KV and served on /state) and once per run by
the job itself (in case the Worker's copy is missing). A report only ever makes a player LESS likely to play than
Sleeper says, and only to Doubtful or Out (Nov 16: Queta ruled out at 5:16 pm ET while Sleeper still said GTD).
Same rule as site/engine.js escalateStatus (tests/test_nov28_injury_watch.mjs, test_nov28_injuries.py)."""
import datetime as dt
import re
from zoneinfo import ZoneInfo

import requests

URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
ABBR = {"NY": "NYK", "GS": "GSW", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}
TEAM_BY_NAME = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND", "LA Clippers": "LAC",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM", "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP", "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA", "Washington Wizards": "WAS"}
RANK = {None: 0, "": 0, "Available": 0, "Probable": 1, "Day-To-Day": 2, "DTD": 2, "GTD": 2, "Questionable": 2,
        "Doubtful": 3, "Out": 4}


def parse(j):
    """ESPN's injuries JSON -> [{name, team, status, comment, at}] (same reading as worker/src/injuries.js)."""
    out = []
    for blk in (j or {}).get("injuries") or []:
        bt = (blk.get("team") or {}).get("abbreviation")
        for it in blk.get("injuries") or []:
            a = it.get("athlete") or {}
            t = bt or (a.get("team") or {}).get("abbreviation") or TEAM_BY_NAME.get(blk.get("displayName")) \
                or TEAM_BY_NAME.get((a.get("team") or {}).get("displayName"))
            st = it.get("status") or (it.get("type") or {}).get("description") or \
                ((it.get("details") or {}).get("fantasyStatus") or {}).get("description")
            if a.get("displayName") and t and st:
                out.append({"name": a["displayName"], "team": ABBR.get(t, t), "status": str(st),
                            "comment": (it.get("shortComment") or "")[:200], "at": it.get("date")})
    return out


def fetch():
    r = requests.get(URL, timeout=30, headers={"User-Agent": "we-back-fantasy-assistant"})
    r.raise_for_status()
    return parse(r.json())


def escalate(sleeper_status, report_status):
    r, s = RANK.get(report_status, 0), RANK.get(sleeper_status, 4)      # IR, Suspended, NA...: already out
    return report_status if r > s and report_status in ("Out", "Doubtful") else None


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]     # date.weekday() order
SAYS_OUT = re.compile(r"\b(out|ruled out|won't play|will not play|inactive|sidelined|miss(es)?|doubtful)\b")
SAYS_MAYBE = re.compile(r"\b(probable|upgraded|available|questionable|game-time|expected to play|will play|cleared|in the lineup|return(s|ed)?)\b")
ET = ZoneInfo("America/New_York")


def current(x, now=None):
    """Nov 28 (first live run): ESPN's status field lags its own notes and outlives the game it was about (Grayson
    Allen "Out" with "upgraded to probable for Saturday's game"; Landale "Out" from "out for Friday's game", read on
    Saturday). A report counts only when its note says he sits, nothing in it says he may play, and it's about a game
    still to come: the weekday it names is today or later (ET), or, naming none, it's under 24 hours old.
    Same rule as site/engine.js reportCurrent."""
    now = now or dt.datetime.now(dt.timezone.utc)
    c = (x.get("comment") or "").lower()
    try:
        at = dt.datetime.fromisoformat((x.get("at") or "").replace("Z", "+00:00"))
        if at.tzinfo is None:
            at = at.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return False
    if not c or not SAYS_OUT.search(c) or SAYS_MAYBE.search(c):
        return False
    wd = next((i for i, w in enumerate(WEEKDAYS) if w in c), None)
    if wd is None:
        return dt.timedelta(0) - dt.timedelta(hours=1) <= now - at <= dt.timedelta(hours=24)
    d0 = at.astimezone(ET).date()
    return d0 + dt.timedelta(days=(wd - d0.weekday()) % 7) >= now.astimezone(ET).date()


def apply(meta, reports, names, now=None):
    """Raise Sleeper's injury_status in meta where a report is more severe. reports: [{name, team, status, ...}] or the
    Worker's {key: {pid, name, team, status, ...}}; names: news.Names (report name -> Sleeper id). Returns the changes."""
    items = list(reports.values()) if isinstance(reports, dict) else list(reports or [])
    out = []
    for x in items:
        pid = x.get("pid") or names.pid(x.get("name"), x.get("team"))
        m = meta.get(pid) if pid else None
        if not m or m.get("team") != x.get("team") or not current(x, now):
            continue
        new = escalate(m.get("injury_status"), x.get("status"))
        if new:
            out.append({"pid": pid, "name": x.get("name"), "team": x.get("team"), "from": m.get("injury_status"), "to": new,
                        "comment": x.get("comment"), "at": x.get("at")})
            m["injury_status"] = new
    return out
