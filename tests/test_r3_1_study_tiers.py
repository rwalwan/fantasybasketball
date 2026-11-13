"""Review 3, finding 1: the other-leagues study picked every player's volatility tier with a projection in the wrong
units. Tier thresholds (18 / 26 / 34 / 42) are 'we back' FP per game; the study's mu is each league's own scoring
divided by 10 (2-5 for everyone), so tier_q always returned the bench tier (<= 18 FP/G, sd 0.80). With two games
left that bar is 1.25x the projection instead of 1.06x for a star, so the study's bars ran high and 'x0.90' looked
better. Here: a star (66 FP/G in our scoring) in a default-scoring league scores 1.05x his correct bar in game 1 of 3
and the manager locks it. The decision point must land in the 1.00-1.15 bin (it landed in 0.85-1.00)."""
import inspect, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import leagues, league_study

OURS = {"pts": 10.0, "tpm": 10.0, "reb": 20.0, "ast": 20.0, "stl": 15.0, "blk": 15.0}           # x10, like Sleeper sends ours
THEIRS = {"pts": 0.5, "reb": 1.0, "ast": 1.0, "stl": 2.0, "blk": 2.0, "to": -1.0, "tpm": 0.5}   # Sleeper's default
line = {"pts": 30, "reb": 10, "ast": 8}                                                         # 66 FP ours, 33 theirs
days = ["2026-11-02", "2026-11-04", "2026-11-06"]
top = next(t for t in league_study.QS["tiers"] if t.get("max") is None)
low = league_study.QS["tiers"][0]
assert league_study.tier_q(66) is not None

def bar_with(tier, mu):          # two games left, healthy curve, same recursion as league_study.cont
    import numpy as np
    q1, q2 = league_study.healthy_at(1), league_study.healthy_at(2)
    return q1 * float(np.mean(np.maximum(mu * np.array(tier["quantiles"]), q2 * mu))) + (1 - q1) * q2 * mu

mu = leagues.fantasy_points(line, THEIRS)                 # the study's units (FP/10 of their scoring)
right, wrong = bar_with(top, mu), bar_with(low, mu)
assert wrong / right > 1.12, (wrong, right)
score1 = 1.05 * right                                      # 1.05x the correct bar = about 0.89x the bench-tier bar
pts1 = score1 * 10 / THEIRS["pts"]                         # a points-only stat line worth exactly that
leagues.STATE = tempfile.mkdtemp()
con = leagues.connect()
con.execute("INSERT INTO league VALUES(?,?,?,?,?,?)", ("L", 10, json.dumps(THEIRS), "[]", 1, "x"))
stats = {2: [{"player_id": "P", "team": "AAA", "date": days[0], "stats": {"pts": pts1}},
             {"player_id": "P", "team": "AAA", "date": days[1], "stats": line},
             {"player_id": "P", "team": "AAA", "date": days[2], "stats": line}]}
proj = {2: [{"player_id": "P", "date": d, "stats": line} for d in days]}
con.execute("INSERT INTO snap VALUES(?,?,?,?,?,?,?,?,?,?)", ("L", 2, "final", 1, 1, 1, json.dumps(["P"]), "{}", json.dumps([score1 * 10]), 0))
for d in days:
    con.execute("INSERT INTO snap VALUES(?,?,?,?,?,?,?,?,?,?)", ("L", 2, d, 0, 1, 1, json.dumps(["P"]), "{}", "[]", 0))
kw = {"tier_scoring": OURS} if "tier_scoring" in inspect.signature(league_study.study).parameters else {}
out = league_study.study(con, [2], stats, [], team_dates={2: {"AAA": days}}, proj_by_week=proj, boot=20, **kw)
bins = {r["score_vs_bar"]: (r["n"], r["lock_rate"]) for r in out["lock_rate_eligible"]}
print("decision points by score/bar bin:", bins, "| correct bar", round(right, 3), "bench-tier bar", round(wrong, 3))
assert bins.get("1.00-1.15") == (1, 1.0), f"a lock at 1.05x the star's bar must be graded in 1.00-1.15, got {bins}"
assert out.get("tier_units"), "the study must say which units its tiers used (site/engine.js studyBarScale checks it)"
print("ok: review 3 finding 1 (study tiers)")
