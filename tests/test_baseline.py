"""Per-minute baseline (research/baseline_fit.py) and participation. Nov 2: Julian Reese showed 37.4 FP/G - last
season 13 games at ~31 min (41.6 FP/G on a tanking team), this season 1 game, 4 FP in a bench role - because last
season counted as 8 games whatever its size or minutes. The engine's copy of the constants must match the data file."""
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import model

B = model.BASE
assert B["R_minutes"] == 200 and B["M_games"] == 4 and B["c_size"] == 10
assert B["fit"]["mae_per_minute"] < B["fit"]["mae_current"]
js = open(os.path.join(os.path.dirname(__file__), "..", "site", "engine.js")).read()
m = re.search(r"export const BASELINE = \{ R: (\d+), M: (\d+), c: (\d+), part: \[([^\]]+)\] \}", js)
assert m and (int(m[1]), int(m[2]), int(m[3])) == (B["R_minutes"], B["M_games"], B["c_size"])
assert [float(x) for x in m[4].split(",")] == B["participation_last5"]

b = model.PlayerBook({"pts": 1.0}, {"R": {"team": "NOP"}, "S": {"team": "AAA"}})
b.prior = {"R": 41.6, "S": 41.6}
b.prior_min = {"R": (31.0, 13), "S": (31.0, 70)}
b.games["R"] = [("2026-10-30", 4.0, 6.0, "g")]
b.games["S"] = [("2026-10-30", 40.0, 31.0, "g")]
r, s = b.baseline("R"), b.baseline("S")
print("Reese-like (13 games last season, 6 min now):", round(r, 1), "| steady starter:", round(s, 1))
assert r < 32, "a bench role now and a short last season: below the old 37.4 (one game is little evidence)"
assert 38 < s < 43, "a steady starter stays near his level"
print("ok: baseline")
