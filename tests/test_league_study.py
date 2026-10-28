"""Other-league study on a synthetic league: Lock-In verification, decision points, rule replay, bar scaling."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import leagues, league_study

leagues.STATE = tempfile.mkdtemp()
con = leagues.connect()
sc = {"pts": 10.0, "reb": 20.0, "ast": 20.0}
st = lambda pts: {"pts": pts, "reb": 0, "ast": 0}
days = ("2026-10-20", "2026-10-22", "2026-10-24")
# week 1: players A..Y each with 3 games; game 1 = 20+i, game 2 = 50, game 3 = 30 (FP = pts here)
stats = {1: []}
pids = [chr(65 + i) for i in range(25)]
for i, p in enumerate(pids):
    for d, pts in zip(days, (20 + i, 50, 30)):
        stats[1].append({"player_id": p, "team": "AAA", "date": d, "stats": st(pts)})
prior = [{"player_id": p, "stats": {"gp": 50, "pts": 40 * 50}} for p in pids]
for lid, final_pts in (("LOCK", lambda i: 50), ("DAILY", lambda i: 20 + i + 50 + 30)):
    con.execute("INSERT INTO league VALUES(?,?,?,?,?,?)", (lid, 10, json.dumps(sc), "[]", None, None))
    con.execute("INSERT INTO snap VALUES(?,?,?,?,?,?,?,?,?,?)", (lid, 1, "final", 1, 1, 1, json.dumps(pids), "{}",
                json.dumps([final_pts(i) * 10 for i in range(25)]), 0))   # Sleeper stores x10
leagues.verify(con, 1, stats[1])
ver = dict(con.execute("SELECT league, verified FROM league").fetchall())
assert ver == {"LOCK": 1, "DAILY": 0}, ver
td = {1: {"AAA": list(days)}}
# no morning snapshots yet: nothing is lineup-checked, so nothing is compared
out = league_study.study(con, [1], stats, prior, team_dates=td, boot=50)
assert out["starter_weeks"] == 0 and out["unchecked_starter_weeks"] == 25 and out["opponent_model_ready"] is False
# morning snapshots on every game day, everyone in the lineup
for d in days:
    con.execute("INSERT INTO snap VALUES(?,?,?,?,?,?,?,?,?,?)", ("LOCK", 1, d, 0, 1, 1, json.dumps(pids), "{}", "[]", 0))
out = league_study.study(con, [1], stats, prior, team_dates=td, boot=50)
print({k: out[k] for k in ("leagues", "decision_points", "starter_weeks", "engine_minus_manager")})
assert out["leagues"] == 1 and out["starter_weeks"] == 25 and out["decision_points"] == 50   # pass game 1, lock game 2
assert out["engine_minus_manager"]["share_same"] >= 0.9
assert {r["scale"] for r in out["bar_scale"]} >= {0.9, 1.0, 1.1}
assert out["eligible_points"] == 50
print("ok: league study")
