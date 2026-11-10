"""Review 3, finding 2: play rates were graded on the LAST status seen before the game, not the status when the
prediction was made. log_and_grade rewrote a game's open record on every run, so a healthy or GTD player who was ruled
out that afternoon was graded as 'Out', and the healthy / GTD groups kept only the players still carrying that label
at the final run: healthy 1,004 of 1,005 played (99.9%), GTD 124 of 158 (78.5%). Those became the next-game play
probabilities used a day or more ahead, where this season's rate for rotation players is 95.8% (1,385 of 1,445, non-b2b)
and the GTD rate is somewhere between 49% and 78% (97 fresh 'Out' records could each have started as GTD).
Now: the record made when the game becomes his next game is the one graded (status at first sight); later news is kept
beside it (last_status). Rates used days ahead come from first sight, game-day rates from the last status."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import availability as A

A.STATE = tempfile.mkdtemp()
A._load = lambda name, default: json.load(open(os.path.join(A.STATE, name))) if os.path.exists(os.path.join(A.STATE, name)) else default


class Book:
    def team(self, p): return "AAA"
    def done(self, p): return [("2026-11-04", 30.0, 30, "g")] if p == "G" else []      # only G played on the 4th


not_final, final = (lambda d, t: False), (lambda d, t: True)
# run 1 (the evening before): H has no designation, G is GTD, both for the game on the 4th
gtd = {"G": {"status": "GTD", "missed": 0, "timeline": None, "q": {"2026-11-04": 0.483}}}
A.log_and_grade(gtd, Book(), not_final, "2026-11-03", {"H": ("2026-11-04", 0.955, False)})
# run 2 (game day): H is ruled out, G is cleared (no longer in the injured set)
out = {"H": {"status": "Out", "missed": 0, "timeline": None, "q": {"2026-11-04": 0.0}}}
A.log_and_grade(out, Book(), not_final, "2026-11-04", {"G": ("2026-11-04", 0.955, False)})
# run 3: the game is final. H sat, G played.
A.log_and_grade({}, Book(), final, "2026-11-05", {})
g = {r["pid"]: r for r in json.load(open(os.path.join(A.STATE, "availability_log.json")))["graded"]}
print({p: (r["status"], r.get("last_status"), r["q"], r["played"]) for p, r in g.items()})
assert g["H"]["status"] is None and g["H"]["played"] is False, "H was healthy when the prediction was made: a healthy player who sat"
assert g["H"]["last_status"] == "Out" and g["H"]["q"] == 0.955
assert g["G"]["status"] == "GTD" and g["G"]["played"] is True and g["G"]["last_status"] is None

# the next-game rate for an undesignated player uses first-sight records only: 300 of them at 95%, plus 1,000 old-style
# records (last status, 99.9%) that must not count
first = [{"status": None, "b2b": False, "played": i < 285, "q": 0.955, "first": True} for i in range(300)]
legacy = [{"status": None, "b2b": False, "played": i > 0, "q": 0.955} for i in range(1000)]
json.dump({"open": {}, "graded": legacy}, open(os.path.join(A.STATE, "availability_log.json"), "w"))
rate, basis = A.next_game_healthy("2026-11-20")
assert rate == 0.944, f"old records are 'still undesignated at the last run': not a next-game rate ({rate}, {basis})"
json.dump({"open": {}, "graded": legacy + first}, open(os.path.join(A.STATE, "availability_log.json"), "w"))
rate, basis = A.next_game_healthy("2026-11-20")
print(rate, "-", basis)
assert rate == 0.95, rate
# ...and the game-day rate (no designation at the last run) is kept for games that tip today
gd = A.gameday_healthy()
assert gd is not None and gd[0] > 0.98, gd
print("ok: review 3 finding 2 (first-sight play rates)")
