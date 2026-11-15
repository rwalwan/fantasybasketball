"""Nov 15: once a player is moved out of the slot he played a game in, that game can't be locked again, even if he's
moved back. The lineup tracker marks the game's record "left" the first time his slot differs after the game."""
import datetime as dt, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import lineups

lineups.STATE = tempfile.mkdtemp()
slots = ["C", "UTIL", "UTIL"]
tips = {("2026-11-13", "BBB"): "2026-11-14T00:00Z"}
def run(now, starters):
    t = lineups.LineupTracker(2026, 4, now_utc=now)
    t.record(slots, starters, ["O", "Q"], lambda p: "BBB", lambda team: ["2026-11-13"], tips)
    return t.snaps["2026-11-13|O"]
before = dt.datetime(2026, 11, 13, 23, 30, tzinfo=dt.timezone.utc)
r = run(before, ["Q", "O", "0"])
assert r == {"slot": "UTIL", "i": 1, "seen": r["seen"], "frozen": False}, r
r = run(before + dt.timedelta(hours=2), ["Q", "O", "0"])       # tipped: frozen in UTIL index 1, still there
assert r["frozen"] and not r.get("left"), r
r = run(before + dt.timedelta(hours=30), ["O", "Q", "0"])      # moved to C
assert r["left"] is True, r
r = run(before + dt.timedelta(hours=31), ["Q", "O", "0"])      # moved back: still left
assert r["left"] is True, r
# the other UTIL (index 2) counts as a move
t = lineups.LineupTracker(2026, 5, now_utc=before)
t.snaps = {"2026-11-13|O": {"slot": "UTIL", "i": 1, "seen": "x", "frozen": True}}
t.record(slots, ["Q", "0", "O"], ["O", "Q"], lambda p: "BBB", lambda team: ["2026-11-13"], tips)
assert t.snaps["2026-11-13|O"].get("left") is True
print("ok: nov 15 lineup left")
