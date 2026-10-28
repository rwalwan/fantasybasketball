"""Usage model (app/usage.py): teammates out raise a player's projection relative to what was typical in his games;
an absent opponent at his position does not (tested in research/usage_fit.py: no effect out of sample)."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import memory, usage

memory.STATE = tempfile.mkdtemp(); memory.DB = os.path.join(memory.STATE, "m.sqlite")
con = memory.connect()
meta = {"S": {"team": "AAA"}, "P": {"team": "AAA"}, "C": {"team": "AAA"}, "OG": {"team": "BBB"}, "OC": {"team": "BBB"}}
prof = {"S": {"mpg": 34, "bpg": 0.3, "grp": "G"}, "P": {"mpg": 30, "bpg": 0.2, "grp": "G"}, "C": {"mpg": 28, "bpg": 1.0, "grp": "C"},
        "OG": {"mpg": 34, "bpg": 0.3, "grp": "G"}, "OC": {"mpg": 30, "bpg": 2.5, "grp": "C"}}
dates = {"AAA": {"2026-11-02": {"opp": "BBB"}}, "BBB": {"2026-11-02": {"opp": "AAA"}}}
for t in range(28):                                   # the rest of a (healthy) league
    dates[f"T{t}"] = {"2026-11-02": {"opp": f"T{t ^ 1}"}}
    for i in range(5):
        meta[f"T{t}p{i}"] = {"team": f"T{t}"}
        prof[f"T{t}p{i}"] = {"mpg": 31 if i < 3 else 24, "bpg": 0.6, "grp": "GFC"[i % 3]}
out_all = lambda d: {"q": {"2026-11-02": 0.0}}
ALL = list(meta)          # factors are normalized to a league mean of 1, so score the whole (tiny) league
f = lambda av: usage.build(con, "2026", meta, prof, dates, {"2026-11-02"}, av, ALL, lambda p: p)[("P", "2026-11-02")]

healthy, star_out = f({}), f({"S": out_all(None)})
print("P healthy", healthy, "| teammate S (same position, 34 mpg) out", star_out)
assert abs(healthy[0] - 1) < 0.03
assert star_out[0] - healthy[0] > 0.05 and "S likely out" in star_out[1]
assert abs(f({"OG": out_all(None)})[0] - healthy[0]) <= 0.005, "the opposing guard being out doesn't move it"
assert 0.01 < f({"OC": out_all(None)})[0] - healthy[0] < 0.04, "lost rim protection: small lift"
# S already missed all 10 of P's games: part of the lift is already in P's baseline (shrunk with 8 pseudo-games)
rows = [("P", f"g{i}", f"2026-10-{10 + i}", "2026", "AAA", "BBB", 1, 30, 10, 2, 20, 5, 5, 40, 100, 100, 0) for i in range(10)]
con.executemany("INSERT INTO games(pid,gid,date,season,team,opp,home,min,fga,pf,pts,reb,ast,fp,team_pts,opp_pts,margin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
con.execute("UPDATE games SET out_mates=?", (json.dumps(["S"]),))
assert f({"S": out_all(None)})[0] < star_out[0] - 0.015
print("ok: usage")
