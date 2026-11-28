"""Nov 28: teammate absences -> minutes (app/absence.py).

What Ryan saw: Fri Nov 27 Neemias Queta sat on his bench and scored 70.5. Mitchell Robinson, Boston's other center,
had been out four straight games (COVID). Queta: 22 min / 30.4 FP a game with Robinson, 29 min / 41.6 FP without.
The app never counted Robinson's absence: he plays 17.5 min, and every teammate-absence path only counted rotation
players at 20+ min (memory._derive, run.build_context, usage.build), and the usage model is gated off anyway.

The rule now: any teammate who plays 10+ min counts; a player's minutes move by his own on/off record with that
teammate (the current streak weighted most), shrunk toward a share of the teammate's minutes; the boost lasts exactly
as long as the teammate is out, turns into a cut when he's back, and a traded teammate's minutes are gone for good.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import absence

con = sqlite3.connect(":memory:")
con.execute("CREATE TABLE games(pid TEXT, gid TEXT, date TEXT, season TEXT, team TEXT, min REAL, fp REAL, reb REAL, ast REAL)")
dates = [f"2026-11-{d:02d}" for d in range(1, 27, 2)] + ["2026-11-21", "2026-11-22", "2026-11-24", "2026-11-25"]
dates = sorted(set(dates))[:17]
out_from = dates[-4]                                   # Robinson's absence: the last 4 games
for i, d in enumerate(dates):
    rob_out = d >= out_from
    rows = [("Q", 29.0 if rob_out else 22.0), ("W", 31.0), ("X", 30.0), ("Y", 28.0), ("Z", 26.0)]
    if not rob_out:
        rows.append(("R", 17.5))
    for p, m in rows:
        con.execute("INSERT INTO games VALUES(?,?,?,?,?,?,?,?,?)", (p, f"g{i}", d, "2026", "BOS", m, m * 1.3, 8, 2))

meta = {p: {"team": "BOS"} for p in "QRWXYZ"}
prof = {"Q": {"mpg": 23.6, "grp": "C"}, "R": {"mpg": 17.5, "grp": "C"}, "W": {"mpg": 31, "grp": "G"},
        "X": {"mpg": 30, "grp": "F"}, "Y": {"mpg": 28, "grp": "G"}, "Z": {"mpg": 26, "grp": "F"}}
today = "2026-11-27"
team_dates = {"BOS": {today: {"opp": "ATL"}, "2026-11-29": {"opp": "SAS"}}}
names = {"R": "Mitchell Robinson"}.get
healthy = lambda n: 0.95


def run(avail, meta_=meta):
    return absence.build(con, "2026", meta_, prof, team_dates, {today, "2026-11-29"}, avail, ["Q", "W"], names, healthy, today)


# 1) Robinson out tonight (play chance 0): Queta's minutes go up, and the reason names Robinson
out = run({"R": {"q": {today: 0.0, "2026-11-29": 0.3}}})
f, why, m, usual = out[("Q", today)]
assert f > 1.05, f"Robinson out must raise Queta's minutes (factor {f})"
assert any("Mitchell Robinson out" in w for w in why), why
assert m > usual, (m, usual)
# a guard on another position gains far less than the center behind him
assert out[("W", today)][0] < f, (out[("W", today)][0], f)
# a chance he's back Sunday: a smaller boost then
assert 1.0 <= out[("Q", "2026-11-29")][0] < f

# 2) a 17.5-minute teammate counts at all (the Nov 27 bug: only 20+ minute teammates did)
assert absence.MIN_MPG <= 17.5

# 3) Robinson back tonight: Queta's usual minutes already include the games he missed, so they come down
back = run({"R": {"q": {today: 1.0, "2026-11-29": 1.0}}})
assert back[("Q", today)][0] < 1.0, back[("Q", today)]

# 4) Robinson traded away: his minutes are gone for good, whatever his play chance says
gone = run({"R": {"q": {today: 1.0}}}, dict(meta, R={"team": "NYK"}))
assert abs(gone[("Q", today)][0] - f) < 1e-9, (gone[("Q", today)][0], f)

# 5) the learning data: the factor with the teammates who actually sat matches the live one when he's surely out
wf = absence.walk_factors(con, "2026")
assert wf[("Q", dates[-1])] > 1.0, wf[("Q", dates[-1])]
assert all(abs(v - 1) < 1e-9 for (p, d), v in wf.items() if p == "W" and d < out_from), "nobody sat: no factor"
print("ok: Nov 28 teammate absences")
