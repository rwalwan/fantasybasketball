"""Nov 15 (Sleeper's rule): once a player is moved to the bench after his game began, that game can't be locked again, even if he's
moved back. Starting slot to starting slot is fine. The tracker marks the record "benched"."""
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
r = run(before + dt.timedelta(hours=30), ["O", "Q", "0"])      # moved to C (starting slot to starting slot): still fine
assert not r.get("benched"), r
r = run(before + dt.timedelta(hours=31), ["Q", "0", "0"])      # benched
assert r["benched"] is True, r
r = run(before + dt.timedelta(hours=32), ["Q", "O", "0"])      # back in UTIL: still gone (Sleeper)
assert r["benched"] is True, r
print("ok: nov 15 lineup benched")
