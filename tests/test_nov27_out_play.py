"""Nov 27: Sleeper's "Out" label sticks between games. Graded Nov 2-25 (availability_log.json, status when the game
first became the player's next game): Out after 0 missed games played 31 of 73 (42%), Out after 1 missed 19 of 55
(35%), but availability.build gave every such game 0%. GTD/DTD split the same way by games missed (DTD 65% after 0
missed vs 19% after 1+). The nightly trainer's PlayFirst model learns one rate per (status, games missed), for a day or
more ahead and for game day; availability.build uses it for the next game when promoted, and the old rule otherwise.
"""
import datetime as dt, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from app import availability as av, train as T
from app.train_models import PlayFirst

# --- the model, on a synthetic log shaped like the real one ----------------------------------------------------------
rng = np.random.default_rng(5)
d0 = dt.date(2026, 11, 13)
graded = []
for i in range(14):
    day = (d0 + dt.timedelta(days=i)).isoformat()
    for j in range(12):                         # Out after 0 missed: plays ~40%
        graded.append({"date": day, "pid": f"o{i}_{j}", "first": True, "status": "Out", "q": 0.0, "missed": 0,
                       "timeline": False, "last_status": "Out", "last_q": 0.0, "played": bool(rng.random() < 0.4)})
    for j in range(10):                         # GTD after 0 missed: plays ~75%
        graded.append({"date": day, "pid": f"g{i}_{j}", "first": True, "status": "GTD", "q": 0.577, "missed": 0,
                       "timeline": False, "last_status": None, "last_q": 0.95, "played": bool(rng.random() < 0.75)})
    # a news 'ruled out' zero (status GTD, q 0): decided by the news rule, so not a GTD row
    graded.append({"date": day, "pid": f"n{i}", "first": True, "status": "GTD", "q": 0.0, "missed": 0,
                   "timeline": False, "last_status": "GTD", "last_q": 0.0, "played": False})
    # a reported timeline: its own logic, not a status row
    graded.append({"date": day, "pid": f"t{i}", "first": True, "status": "Out", "q": 0.0, "missed": 5,
                   "timeline": True, "last_status": "Out", "last_q": 0.0, "played": False})
state, learn = tempfile.mkdtemp(), tempfile.mkdtemp()
json.dump({"open": {}, "graded": graded}, open(os.path.join(state, "availability_log.json"), "w"))
av.STATE, T.STATE, T.LEARN = state, state, learn
ctx = {"today": "2026-11-28", "state": state, "learn": learn, "cache": {}}
m = PlayFirst()
rows = m.rows(ctx)
assert sum(1 for r in rows if r["h"] == "ahead") == 14 * 22, "news zeros and timelines are left out"
fac = m.factory(ctx)
assert fac["ahead"]["Out"]["0"] == 0.0 and fac["gameday"]["Out"]["4+"] == 0.0, fac
doc = {"models": {}, "log": []}
assert T.run_model(m, ctx, doc, "2026-11-28") == "promoted", doc["log"]
p = doc["models"]["play_first"]["params"]
assert p["ahead"]["Out"]["0"] == 0.25, p["ahead"]["Out"]          # capped first step (truth ~0.4)
assert p["ahead"]["Questionable"]["0"] > fac["ahead"]["Questionable"]["0"], (p["ahead"], fac["ahead"])
assert m.bounds(p) is None
print("ok: PlayFirst learns Out after 0 missed from 0% toward 40%, a capped step at a time")
assert len(open(os.path.join(learn, "avail_graded.jsonl")).read().splitlines()) == len(graded)
print("ok: graded predictions archived on the learning branch")

# --- the job uses it ---------------------------------------------------------------------------------------------------
class Book:
    def __init__(self, done): self._d = done
    def done(self, pid): return self._d.get(pid, [])

dates = {"BOS": {d: {} for d in ("2026-11-26", "2026-11-28", "2026-11-30", "2026-12-02")}}
final = lambda d, t: d < "2026-11-27"
meta = {"A": {"team": "BOS", "injury_status": "Out"}, "B": {"team": "BOS", "injury_status": "IR"},
        "C": {"team": "BOS", "injury_status": "DTD"}}
book = Book({"A": [("2026-11-26", 30)], "B": [], "C": [("2026-11-26", 30)]})
json.dump([], open(os.path.join(state, "news.json"), "w"))
av.M.pop("first_game", None)
before = av.build(book, meta, dates, "2026-11-27", final, ["A", "B", "C"])
assert before["A"]["q"]["2026-11-28"] == 0.0
av.M["first_game"] = p
after = av.build(book, meta, dates, "2026-11-27", final, ["A", "B", "C"])
assert after["A"]["q"]["2026-11-28"] == 0.25, after["A"]["q"]
assert "learned" in after["A"]["basis"], after["A"]["basis"]
assert after["A"]["q"]["2026-11-30"] > before["A"]["q"]["2026-11-30"], (before["A"]["q"], after["A"]["q"])
assert after["B"]["q"]["2026-11-28"] == 0.0                         # IR keeps the old rule
assert after["C"]["q"]["2026-11-28"] == p["ahead"]["Questionable"]["0"]
# game day uses the game-day rates
today = av.build(book, meta, {"BOS": {**dates["BOS"], "2026-11-27": {}}}, "2026-11-27", final, ["A"])
assert today["A"]["q"]["2026-11-27"] == p["gameday"]["Out"]["0"], today["A"]["q"]
av.M.pop("first_game", None)
print("ok: availability uses the learned next-game rates (Out, DTD), IR keeps 0%, game day its own rate")
