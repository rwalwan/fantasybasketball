"""Review 2, finding 7d: other managers' league ids sat in leagues.sqlite and other_leagues.json on the public state
branch. Now the database stores hashed ids (existing rows migrated) and the real discovery list lives in data/cache
(private Actions cache)."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import leagues, sleeper

leagues.STATE, leagues.CACHE = tempfile.mkdtemp(), tempfile.mkdtemp()
# a database saved before hashing
import sqlite3
con = sqlite3.connect(os.path.join(leagues.STATE, "leagues.sqlite"))
con.executescript("""CREATE TABLE snap(league TEXT, week INT, day TEXT, final INT, roster INT, matchup INT, starters TEXT,
  players_points TEXT, starters_points TEXT, points REAL, PRIMARY KEY(league, week, day, roster));
  CREATE TABLE league(league TEXT PRIMARY KEY, teams INT, scoring TEXT, positions TEXT, verified INT, checked TEXT);""")
con.execute("INSERT INTO league VALUES('1234567890',10,'{}','[]',1,'x')")
con.execute("INSERT INTO snap VALUES('1234567890',1,'final',1,1,1,'[]','{}','[]',0)"); con.commit(); con.close()
json.dump({"at": "2026-10-28", "leagues": {"999": {"teams": 10, "scoring": {}, "positions": []}}},
          open(os.path.join(leagues.STATE, "other_leagues.json"), "w"))
con = leagues.connect()
ids = {r[0] for r in con.execute("SELECT league FROM league UNION SELECT league FROM snap")}
assert ids == {leagues.hid("1234567890")}, ids
# new snapshots: fetched with the real id, stored hashed
sleeper.matchups = lambda lid, w: [{"roster_id": 1, "matchup_id": 1, "starters": [], "players_points": {}, "starters_points": [], "points": 0}] if lid == "999" else []
found = leagues.discover("seed", "2026", "2026-10-29")
assert "999" in found and not os.path.exists(os.path.join(leagues.STATE, "other_leagues.json"))
assert os.path.exists(os.path.join(leagues.CACHE, "other_leagues.json")), "real ids only in the private cache"
leagues.PAUSE = 0
leagues.snapshot(con, found, 2, "2026-10-29")
stored = {r[0] for r in con.execute("SELECT DISTINCT league FROM snap WHERE week=2")}
assert stored == {leagues.hid("999")}, stored
con.commit()
raw = open(os.path.join(leagues.STATE, "leagues.sqlite"), "rb").read()
assert b"1234567890" not in raw and b"999" not in raw, "no real league id anywhere in the saved file" 
print("ok: review 2 finding 7d")
