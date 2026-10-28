"""Review 2, finding 2: the timeline vote counted items, not outlets.
Anthony Edwards (state, 2026-10-28): 6 Yahoo items said 'about two months' (60, 60); RotoWire, Hoops Rumors and
RealGM said 'up to two months' (30, 60). The Yahoo copies won. Fix: one vote per outlet (its latest item), 'about N'
read as 0.75N-1.25N, and a newer 'available' report wins outright.
Lauri Markkanen: a 'day-to-day' (0, 3) report overrode his official GTD designation (48% -> 94%)."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import news, availability as A, model

fx = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "timeline_outlets_2026-10-28.json")))["items"]
team = {"2133": "MIN", "1752": "UTA"}.get
tl = news.update_timelines({}, fx, team)
ant = tl["2133"]
print("Edwards", (ant["out_min_days"], ant["out_max_days"]), "votes", ant["cited"], "of", ant["outlets"], "outlets")
assert (ant["out_min_days"], ant["out_max_days"]) == (30, 60), "RotoWire, Hoops Rumors, RealGM: 3 outlets vs Yahoo's 1"
assert ant["outlets"] == 5 and ant["cited"] == 3
assert news.approx([60, 60]) == [45, 75] and news.approx([3, 3]) == [3, 3] and news.approx([200, 200]) == [200, 200]

# a newer 'cleared to play' report from one outlet wins outright, not after 48 h of being outvoted
ok = dict(fx[0], at="2026-10-28T06:00+00:00", source="RotoWire news", title="cleared", kind="return", status="available",
          out_min_days=0, out_max_days=0)
assert news.update_timelines(json.loads(json.dumps(tl)), [ok], team)["2133"]["out_max_days"] == 0

# Markkanen: GTD by the official report, plus a day-to-day timeline -> the designation (48%) decides
dates = {"UTA": {"2026-10-26": {}, "2026-10-29": {}, "2026-10-31": {}}}
meta = {"1752": {"team": "UTA", "injury_status": "GTD"}}
b = model.PlayerBook({}, meta)
A._load = lambda name, default: {"1752": tl["1752"]} if name == "timelines.json" else default
q = A.build(b, meta, dates, "2026-10-28", lambda d, t: d < "2026-10-28", ["1752"])["1752"]["q"]
print("Markkanen next game", q["2026-10-29"])
assert abs(q["2026-10-29"] - A.M["designation"]["Questionable"]) < 0.01, q
print("ok: review 2 finding 2")
