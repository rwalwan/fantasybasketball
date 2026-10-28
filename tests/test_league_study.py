"""Other-league study on a synthetic league: Lock-In verification, decision points, rule replay, bar scaling."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import leagues, league_study

leagues.STATE = tempfile.mkdtemp()
con = leagues.connect()
sc = {"pts": 10.0, "reb": 20.0, "ast": 20.0}
st = lambda pts: {"pts": pts, "reb": 0, "ast": 0}
# week 1: players A..Y each with 3 games (dates 1..3); A's games 20, 50, 30 (FP = pts here)
stats = {1: []}
pids = [chr(65 + i) for i in range(25)]
for i, p in enumerate(pids):
    for d, pts in zip(("2026-10-20", "2026-10-22", "2026-10-24"), (20 + i, 50, 30)):
        stats[1].append({"player_id": p, "date": d, "stats": st(pts)})
prior = [{"player_id": p, "stats": {"gp": 50, "pts": 40 * 50}} for p in pids]
for lid, final_pts in (("LOCK", lambda i: 50), ("DAILY", lambda i: 20 + i + 50 + 30)):
    con.execute("INSERT INTO league VALUES(?,?,?,?,?,?)", (lid, 10, json.dumps(sc), "[]", None, None))
    con.execute("INSERT INTO snap VALUES(?,?,?,?,?,?,?,?,?,?)", (lid, 1, "final", 1, 1, 1, json.dumps(pids), "{}",
                json.dumps([final_pts(i) * 10 for i in range(25)]), 0))   # Sleeper stores x10
leagues.verify(con, 1, stats[1])
ver = dict(con.execute("SELECT league, verified FROM league").fetchall())
assert ver == {"LOCK": 1, "DAILY": 0}, ver
out = league_study.study(con, [1], stats, prior, boot=50)
print({k: out[k] for k in ("leagues", "decision_points", "starter_weeks", "engine_minus_manager")})
assert out["leagues"] == 1 and out["starter_weeks"] == 25 and out["decision_points"] == 50   # pass game 1, lock game 2
# engine rule with mu 40: game 2 (50) beats the 1-game bar; game 1 is below the 2-game bar except the 44
assert out["engine_minus_manager"]["share_same"] >= 0.9   # the 44 in game 1 beats the bar (~43): engine locks it
assert {r["scale"] for r in out["bar_scale"]} >= {0.9, 1.0, 1.1}
print("ok: league study")
