"""Review 2, finding 3: the other-leagues study was biased toward the engine and toward waiting.
  (a) the engine replay used every game the player played, the manager only games he was in the lineup for
  (b) a final-game DNP (no stat row) never entered the sequence, and slot scores of 0 were skipped
  (c) weeks without lineup records were compared anyway
One player, three scheduled games: 60 (on the manager's BENCH that morning), 45, DNP. The manager locked the 45.
Before: the engine 'locked' the bench 60 -> engine +15. Now: lineup games only (45, DNP): the engine's bar after
game 2 is the DNP-risk value of game 3 (~37), so it locks 45 too -> same result. A second player whose manager
waited into the final-game DNP (slot 0) must count, as a 0."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import leagues, league_study

leagues.STATE = tempfile.mkdtemp()
con = leagues.connect()
sc = {"pts": 10.0}
days = ["2026-11-02", "2026-11-04", "2026-11-06"]
stats = {2: [{"player_id": "P", "team": "AAA", "date": days[0], "stats": {"pts": 60}},
             {"player_id": "P", "team": "AAA", "date": days[1], "stats": {"pts": 45}},
             {"player_id": "Q", "team": "AAA", "date": days[0], "stats": {"pts": 30}},
             {"player_id": "Q", "team": "AAA", "date": days[1], "stats": {"pts": 33}}]}   # both DNP game 3
prior = [{"player_id": p, "stats": {"gp": 50, "pts": 40 * 50}} for p in "PQ"]
con.execute("INSERT INTO league VALUES(?,?,?,?,?,?)", ("L", 10, json.dumps(sc), "[]", 1, "x"))
con.execute("INSERT INTO snap VALUES(?,?,?,?,?,?,?,?,?,?)", ("L", 2, "final", 1, 1, 1, json.dumps(["P", "Q"]), "{}", json.dumps([450, 0]), 0))
for d in days:   # P sat on the bench the morning of game 1; Q was in the lineup every day
    con.execute("INSERT INTO snap VALUES(?,?,?,?,?,?,?,?,?,?)", ("L", 2, d, 0, 1, 1, json.dumps(["Q"] if d == days[0] else ["P", "Q"]), "{}", "[]", 0))
out = league_study.study(con, [2], stats, prior, team_dates={2: {"AAA": days}}, boot=50)
print({k: out[k] for k in ("starter_weeks", "decision_points", "engine_minus_manager")})
assert out["starter_weeks"] == 2, "the 0-point slot (Q) must count"
# P: the engine locks the 45 like the manager (the bench 60 isn't available to it). Q: 33 is below the game-3 bar
# (~37), so the engine also waits into the DNP and ends with 0, like the manager. Before the fix, P was +15 for the
# engine and Q was skipped.
assert out["engine_minus_manager"]["share_same"] == 1.0, out["engine_minus_manager"]
assert abs(out["engine_minus_manager"]["mean_pct_of_proj"]) < 0.01
print("ok: review 2 finding 3")
