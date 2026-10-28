"""Review 2, finding 4: normalizing usage factors to mean 1 over EVERY player moved healthy-team players down
whenever other teams had injuries. 30 teams; 12 of them have a 31-mpg starter out. A player on a fully healthy team
facing a healthy opponent must stay at ~1.0, and an injured team's teammates must still get their lift."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import memory, usage

memory.STATE = tempfile.mkdtemp(); memory.DB = os.path.join(memory.STATE, "m.sqlite")
con = memory.connect()
meta, prof, dates, D = {}, {}, {}, "2026-11-02"
for t in range(30):
    dates[f"T{t}"] = {D: {"opp": f"T{t ^ 1}"}}
    for i in range(5):
        meta[f"T{t}p{i}"] = {"team": f"T{t}"}
        prof[f"T{t}p{i}"] = {"mpg": 31 if i < 3 else 24, "bpg": 0.6, "grp": "GFC"[i % 3]}
injured = {f"T{t}p0": {"q": {D: 0.0}} for t in range(0, 24, 2)}      # teams 0,2,..,22 lose a starter
out = usage.build(con, "2026", meta, prof, dates, {D}, injured, list(meta), lambda p: p)
healthy = [out[(f"T{t}p{i}", D)][0] for t in (24, 25, 26, 27, 28, 29) for i in range(1, 5)]
lifted = out[("T0p3", D)][0]
print("healthy-team players", round(min(healthy), 3), "-", round(max(healthy), 3), "| injured team's guard-group bench", lifted)
assert all(abs(f - 1) <= 0.01 for f in healthy), healthy
assert lifted > 1.05

# horizon grading: a factor logged 10 days ahead is graded in the 8-28 day bucket once the game is final
class B:
    def baseline(self, p): return 20.0
    def team(self, p): return "T0"
    def done(self, p): return [("2026-11-12", 24.0, 30, "g")]
sd = tempfile.mkdtemp()
usage.log_and_grade({("X", "2026-11-12"): (1.15, [])}, B(), lambda d, t: False, "2026-11-02", sd)
g = usage.log_and_grade({}, B(), lambda d, t: True, "2026-11-13", sd)
print("horizon grades", g)
assert g["8-28 days"]["n"] == 1 and g["8-28 days"]["actual_lift"] == 0.2 and g["8-28 days"]["mae_with"] == 1.0
# a bucket whose graded games (100+) show the factor hurts is switched off; others keep it
grades = {"8-28 days": {"n": 150, "mae_with": 9.9, "mae_without": 9.5}, "next 1 day": {"n": 150, "mae_with": 9.0, "mae_without": 9.4}}
um = {("X", "2026-11-03"): (1.2, ["a"]), ("X", "2026-11-20"): (1.2, ["b"])}
g2, off = usage.gate(um, grades, "2026-11-02")
assert off == {"8-28 days"} and g2[("X", "2026-11-20")][0] == 1.0 and g2[("X", "2026-11-03")][0] == 1.2
assert usage.gate(um, {"8-28 days": {"n": 40, "mae_with": 99, "mae_without": 1}}, "2026-11-02")[1] == set(), "needs 100 games"
print("ok: review 2 finding 4")
