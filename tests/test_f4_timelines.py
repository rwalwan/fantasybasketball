"""Finding 4 (review 2026-10-28): AI-extracted injury timelines changed play chances with no validation.
Real extractions from state news.json (fixture), replayed in time order:
  * Cason Wallace "could miss rest of season" -> (none, 200): was ignored (no minimum), so he looked healthy soon.
  * Jaren Jackson Jr. "won't return Monday" -> (0, 0): read as 'back now' for ~17 hours.
  * Kawhi Leonard: a history piece (kind 'other') -> (7, 7).
  * Anthony Edwards: one story, four different extractions; the latest outlet won.
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import news

fx = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "timeline_news_2026-10-27.json")))["items"]
fx.sort(key=lambda x: x["at"])
team = {"2586": "OKC", "2133": "MIN", "1924": "UTA", "1308": "TOR"}.get
WAL, ANT, JJJ, KAW = "2586", "2133", "1924", "1308"
win = lambda tl, pid: (tl[pid]["out_min_days"], tl[pid]["out_max_days"]) if pid in tl else None

tl = news.update_timelines({}, fx, team)
print({p: win(tl, p) for p in (WAL, ANT, JJJ, KAW)})
assert win(tl, WAL) == (100, 200), "max-only: out at least half the max"
assert win(tl, JJJ) == (42, 56)
assert win(tl, KAW) == (14, None), "the 2019 history piece (kind 'other') must not count"
assert win(tl, ANT) == (60, 60), "most-cited window within 48h"

# JJJ before the 6-8 week report: the in-game '0 days' extraction must not mean 'back now'
early = news.update_timelines({}, [x for x in fx if x["at"] < "2026-10-27T03"], team)
assert JJJ not in early, early.get(JJJ)
# one late contrary outlet doesn't flip Edwards
late = dict(fx[-1], at="2026-10-28T05:00+00:00", out_min_days=60, out_max_days=None, source="Late Outlet", title="x")
assert win(news.update_timelines(tl, [late], team), ANT) == (60, 60)
# wrong team or out-of-bounds values are rejected
bad = [dict(fx[0], pid=KAW, team="LAL", at="2026-10-28T06:00+00:00", out_min_days=3, out_max_days=5, title="y"),
       dict(fx[0], pid=KAW, team="TOR", at="2026-10-28T06:01+00:00", out_min_days=30, out_max_days=10, title="z")]
assert win(news.update_timelines(tl, bad, team), KAW) == (14, None)
# a timeline stored before this fix (no minimum) is normalized on the next run
assert win(news.update_timelines({WAL: {"at": "2026-10-27T00:46+00:00", "out_min_days": None, "out_max_days": 200,
                                         "summary": "s", "source": "Yahoo NBA", "player": "Cason Wallace"}}, [], team), WAL) == (100, 200)
print("ok: finding 4")
