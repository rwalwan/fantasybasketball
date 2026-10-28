"""Finding 7 (review 2026-10-28): the context factor double-counted pace and was biased upward.
Opponent-vs-position ratios are raw FP over baseline, which already include the opponent's pace; the pace factor
then applied both teams' scoring environment again (own pace is already in the baseline). The teammates bump can
only raise and every team's first game got the +1% rest bump: mean factor 1.056."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import memory

memory.STATE = tempfile.mkdtemp(); memory.DB = os.path.join(memory.STATE, "m.sqlite")
con = memory.connect()
rows = []
for i, d in enumerate(["2026-10-21", "2026-10-23", "2026-10-25"]):          # FST plays very fast games
    for pid, t, o in (("a", "FST", "SLO"), ("b", "SLO", "FST")):
        rows.append((pid, f"g{i}{pid}", d, "2026", t, o, 1, 30, 15, 2, 20, 8, 4, 40, 140, 135, 5))
    for pid, t, o in (("c", "SL2", "SL3"), ("e", "SL3", "SL2")):              # everyone else plays slow games
        rows.append((pid, f"h{i}{pid}", d, "2026", t, o, 1, 30, 15, 2, 20, 8, 4, 40, 100, 98, 2))
con.executemany("INSERT INTO games(pid,gid,date,season,team,opp,home,min,fga,pf,pts,reb,ast,fp,team_pts,opp_pts,margin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
meta = {p: {"fantasy_positions": ["SF"]} for p in "abce"}
ctx = memory.Context(con, "2026", meta, lambda p: 40.0, {}, "2026-10-26")
f, parts = ctx.factors("a", "FST", "SLO", 2, [])
print(f, parts)
assert not any(p["k"] == "pace" for p in parts), "pace is already inside the opponent ratios and the baseline"
# league-wide factors are rescaled to mean 1 (no systematic upward bias)
norm = memory.normalize_factors({"x|d": 1.10, "y|d": 1.05, "z|d": 1.02})
assert abs(sum(norm.values()) / 3 - 1) < 1e-9 and norm["x|d"] > norm["y|d"] > norm["z|d"]
print("ok: finding 7")
