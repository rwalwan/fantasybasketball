"""Nov 16: the Celtics ruled Queta out for rest at 5:16 pm ET ('Queta (rest) won't play in Monday's game', RotoWire),
but Sleeper still listed him GTD, so he was modeled at 76% to play and started at UTIL. A fresh single-game 'out'
report must make that game 0% (and only that game: a rest day, back at the healthy rate after)."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import availability as av

class Book:
    def __init__(self, done): self._d = done
    def done(self, pid): return self._d.get(pid, [])

dates = {"BOS": {d: {} for d in ("2026-11-14", "2026-11-16", "2026-11-18", "2026-11-20")},
         "LAL": {d: {} for d in ("2026-11-15", "2026-11-16", "2026-11-18")}}
final = lambda d, t: d < "2026-11-16"
meta = {"2302": {"team": "BOS", "injury_status": "GTD", "injury_body_part": "Rest"},
        "9": {"team": "LAL", "injury_status": None}, "8": {"team": "LAL", "injury_status": None},
        "7": {"team": "BOS", "injury_status": None}}
queta = {"pid": "2302", "team": "BOS", "source": "RotoWire news", "at": "2026-11-16T22:16+00:00", "kind": "other",
         "status": "out", "games_out_estimate": 1, "title": "Neemias Queta: Sitting out Monday",
         "text": "Queta (rest) won't play in Monday's game against the Magic.", "summary": "held out for rest"}
news = [queta,
        # healthy on Sleeper, ruled out Monday (injury), then the hazard decides the next game
        {"pid": "9", "team": "LAL", "at": "2026-11-16T18:16+00:00", "kind": "injury", "status": "out",
         "games_out_estimate": 1, "title": "Won't play Monday", "text": "", "summary": "out Monday"},
        # out Monday, then upgraded: the newer report wins
        {"pid": "8", "team": "LAL", "at": "2026-11-16T15:00+00:00", "kind": "injury", "status": "out",
         "games_out_estimate": 1, "title": "Ruled out Monday", "text": ""},
        {"pid": "8", "team": "LAL", "at": "2026-11-16T20:00+00:00", "kind": "injury", "status": "questionable",
         "games_out_estimate": None, "title": "Upgraded to questionable", "text": ""},
        # Saturday's report about Saturday's game (already final): doesn't touch Monday
        {"pid": "7", "team": "BOS", "at": "2026-11-14T22:00+00:00", "kind": "injury", "status": "out",
         "games_out_estimate": 1, "title": "Out Saturday", "text": ""}]
av.STATE = tempfile.mkdtemp()
json.dump(news, open(os.path.join(av.STATE, "news.json"), "w"))
book = Book({"2302": [("2026-11-14", 20)], "9": [("2026-11-15", 30)], "8": [("2026-11-15", 30)], "7": []})
out = av.build(book, meta, dates, "2026-11-16", final, ["2302", "9", "8", "7"])

q = out["2302"]["q"]
assert q["2026-11-16"] == 0.0, q
assert q["2026-11-18"] > 0.9, q                   # a rest day: back at the healthy rate
assert "ruled out" in out["2302"]["basis"], out["2302"]["basis"]
print("ok: Queta ruled out for rest though Sleeper says GTD")
q = out["9"]["q"]
assert q["2026-11-16"] == 0.0 and 0.3 < q["2026-11-18"] < 0.7, q
print("ok: healthy-on-Sleeper player ruled out Monday is modeled out, then the return rate")
assert "8" not in out, out.get("8")
print("ok: a newer questionable report cancels the out")
assert "7" not in out or "2026-11-16" not in out["7"]["q"] or out["7"]["q"]["2026-11-16"] > 0, out.get("7")
print("ok: an old report about a finished game doesn't zero the next one")
# no weekday, posted after a game he played: ambiguous, ignored
s, r = av.news_out([{"pid": "x", "at": "2026-11-17T04:00+00:00", "status": "out", "games_out_estimate": 1,
                     "title": "Ruled out", "text": ""}], "x", "BOS", sorted(dates["BOS"]), ["2026-11-16"])
assert s == set(), s
print("ok: ambiguous report ignored")
