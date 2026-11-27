"""Nov 27: the decision scorecard misgraded week 5.
* Ryan locked Gobert's 59 (Nov 16), Carter's 40.5 and Okongwu's 56.5 (Nov 18), all in Sleeper's lock record
  (sleeper_locks_2026_w5.json), yet the scorecard said "not followed", final 39.0 / 31.0 / 30.5: grade() read the public
  feed's starters_points, which mid-week (and right after the week flips) show each starter's LATEST game, not the
  locked one. Rule: Sleeper's lock record decides final and followed when we have it, and a week is graded only once
  it has settled (2 days after its last game day), so the feed fallback reads Sleeper's settled score.
* Ty Jerome, Nov 11: the engine said pass on 37.0, Ryan passed, the slot ended at 41.0, and the scorecard said the
  call cost 37 (cf 0.0): the replay of his own games scores a final-game DNP as 0 and ignores who else filled the slot.
  Rule: a pass that was followed is graded on what the slot really ended with.
"""
import datetime as dt, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import learn, memory

memory.STATE = tempfile.mkdtemp(); memory.DB = os.path.join(memory.STATE, "m.sqlite")
con = memory.connect()
games = [("gob", "g1", "2026-11-16", 59.0), ("gob", "g2", "2026-11-21", 39.0),
         ("wcj", "w1", "2026-11-18", 40.5), ("wcj", "w2", "2026-11-22", 31.0),
         ("ty", "t1", "2026-11-17", 37.0), ("ty", "t2", "2026-11-19", 20.0),
         ("al", "a1", "2026-11-17", 45.0), ("al", "a2", "2026-11-20", 30.0)]
team = {"gob": "MIN", "wcj": "ORL", "ty": "MEM", "al": "CHA"}
for pid, gid, d, fp in games:
    con.execute("INSERT INTO games(pid, gid, date, season, team, fp, proj_rw) VALUES(?,?,?,?,?,?,?)", (pid, gid, d, "2026", team[pid], fp, 40.0))
dec = [(5, "2026-11-16", "UTIL", 0, "gob", 59.0, "lock"), (5, "2026-11-18", "C", 1, "wcj", 40.5, "lock"),
       (5, "2026-11-17", "SG", 2, "ty", 37.0, "pass"), (5, "2026-11-17", "SF", 3, "al", 45.0, "lock")]
for w, d, slot, idx, pid, sc, call in dec:
    con.execute("INSERT INTO decisions(week,date,slot,idx,pid,kind,score,bar,ev_call,mx_call,deadline,made_at,extra) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (w, d, slot, idx, pid, "lock-call", sc, 45.0, call, call, d + "T23:00Z", d, json.dumps({"name": pid})))
# Ty's last scheduled game (Nov 21) is a DNP; another player was streamed into SG and the slot ended at 41.0
sched = [{"week": 5, "date": d, "home": {"team": t}, "away": {"team": "X"}, "status": "complete"}
         for t, ds in {"MIN": ["2026-11-16", "2026-11-21"], "ORL": ["2026-11-18", "2026-11-22"], "MEM": ["2026-11-17", "2026-11-19", "2026-11-21"],
                       "CHA": ["2026-11-17", "2026-11-20"]}.items() for d in ds]
feed = [{"roster_id": 3, "starters": ["gob", "wcj", "x", "al"], "starters_points": [390, 310, 410, 300]}]   # latest games, unsettled
learn.sleeper.rosters = lambda lid: [{"owner_id": learn.USER_ID, "roster_id": 3}]
learn.sleeper.matchups = lambda lid, w: feed
learn.sleeper.schedule = lambda season: sched
locks = {5: {"status": "ok", "teams": {"3": {"gob": "g1", "wcj": "w1"}}}}      # Allen's 45 was NOT locked

# Monday after the week: not settled yet, nothing graded
assert learn.grade(con, "2026", 6, {}, locks, today="2026-11-23") == 0
assert learn.grade(con, "2026", 6, {}, locks, today="2026-11-24") == 4
g = {pid: (final, cf, regret, fol) for pid, final, cf, regret, fol in con.execute("SELECT pid, final, cf, regret, followed FROM decisions")}
assert g["gob"][0] == 59.0 and g["gob"][3] == 1, g["gob"]        # the locked game, followed
assert g["wcj"][0] == 40.5 and g["wcj"][3] == 1, g["wcj"]
assert g["al"][3] == 0, g["al"]                                   # told to lock, wasn't locked
assert g["ty"][1] == 41.0 and g["ty"][2] == -4.0 and g["ty"][3] == 1, g["ty"]   # passing gained 4, not "cost 37"

# without a lock record (token expired): the settled feed decides, as before
con.execute("UPDATE decisions SET final=NULL, cf=NULL, regret=NULL, followed=NULL")
feed[0]["starters_points"] = [590, 405, 410, 300]
assert learn.grade(con, "2026", 6, {}, {}, today="2026-11-25") == 4
assert con.execute("SELECT final, followed FROM decisions WHERE pid='gob'").fetchone() == (59.0, 1)
print("ok: nov 27 grading")
