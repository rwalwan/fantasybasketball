"""Lineup snapshots -> which games are lock-eligible.

Lock-In only lets you lock a game a player played while he was in a STARTING slot. Sleeper's API only
returns the current lineup, so every run records who is starting; when a game tips, the last snapshot
before tip-off is frozen as that game's lineup.

State lives in data/state/lineups_<season>_w<week>.json (kept on the `state` branch by the workflow):
  {"<date>|<pid>": {"slot": "G" | null, "seen": "<utc iso>", "frozen": bool}}
Manual answers for games played before tracking started go in data/state/eligibility_overrides.json:
  {"<date>|<pid>": true | false}
"""
import datetime as dt
import json
import os

STATE = os.path.join(os.path.dirname(__file__), "..", "data", "state")


def _load(name):
    path = os.path.join(STATE, name)
    return json.load(open(path)) if os.path.exists(path) else {}


def _save(name, obj):
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, name), "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)


class LineupTracker:
    def __init__(self, season, week, now_utc=None, prefix="lineups"):
        self.name = f"{prefix}_{season}_w{week}.json"
        self.snaps = _load(self.name)
        self.overrides = _load("eligibility_overrides.json")
        self.now = now_utc or dt.datetime.now(dt.timezone.utc)

    def record(self, slots, starters, roster_players, team_of, game_dates_of, tips):
        """Snapshot today's/future games for every rostered player. Frozen once the game has tipped."""
        slot_of = {pid: s for s, pid in zip(slots, starters) if pid and pid != "0"}
        stamp = self.now.isoformat(timespec="minutes")
        for pid in roster_players:
            team = team_of(pid)
            for d in game_dates_of(team):
                key = f"{d}|{pid}"
                tip = tips.get((d, team))
                cur = self.snaps.get(key)
                if cur and cur.get("frozen"):
                    continue
                if tip and dt.datetime.fromisoformat(tip.replace("Z", "+00:00")) <= self.now:
                    if cur:                       # tipped: freeze the last pre-tip snapshot
                        cur["frozen"] = True
                    continue
                if tip is None and d < self.now.date().isoformat():
                    continue
                self.snaps[key] = {"slot": slot_of.get(pid), "seen": stamp, "frozen": False}
        _save(self.name, self.snaps)

    def eligible(self, pid, date):
        """True / False if known, None if the game was played before tracking started."""
        key = f"{date}|{pid}"
        if key in self.overrides:
            return bool(self.overrides[key])
        s = self.snaps.get(key)
        if s and s.get("frozen"):
            return s.get("slot") is not None
        return None
