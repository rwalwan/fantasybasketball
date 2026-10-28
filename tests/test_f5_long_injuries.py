"""Finding 5 (review 2026-10-28): long-term injuries without a timeline were barely penalized.
The return hazard came from absences that ENDED inside a stint (a player's panel stopped at his last appearance),
so season-ending absences never entered, and coach's-decision/rest absences were mixed in. Giveaway: the return
rate after 21+ misses (0.212) was higher than after 13-20 (0.139). Refit (research/hazard_refit.py): stints run
to the team's last game (censored absences included) and non-injury absences are dropped.
A player Out since opening night with no timeline (missed = 13) used to reach ~49% to play 6 games out."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import availability as A, model

assert A.hazard(13) <= 0.09, A.hazard(13)
assert A.hazard(25) <= A.hazard(13), "return rate must not rise with a longer absence"
assert A.M.get("n_censored", 0) > 100, "censored (never-ended) absences must be in the fit"

meta = {"x": {"team": "AAA", "injury_status": "Out"}}
dates = {"AAA": {f"2026-11-{d:02d}": {} for d in range(1, 31, 2)} | {"2026-10-24": {}, "2026-10-26": {}, "2026-10-28": {}}}
b = model.PlayerBook({}, meta)
A.STATE = "/nonexistent"                      # no timelines
av = A.build(b, meta, dates, "2026-10-31", lambda d, t: d < "2026-10-31", ["x"])["x"]
q6 = list(av["q"].values())[5]
print("opening-night Out, no timeline: missed", av["missed"], "| 6 games out q =", q6, "| uncertain", av.get("uncertain"))
assert av["missed"] >= 13 and q6 < 0.35, q6
assert av.get("uncertain") is True, "long absence with no reported timeline must be flagged"
print("ok: finding 5")
