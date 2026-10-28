"""Review 2, F2 refinement: the next-game play rate of an undesignated player was the whole-season historical 0.944.
Early in the season it is higher (2021-24, Oct 1 - Nov 10: 0.955, n=2,120; after mid-March 0.930). Use the rate for
the stage of the season until this season's log has 300 graded healthy (non-b2b) games, then this season's own."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import availability as A

A.STATE = tempfile.mkdtemp()
A._load = lambda name, default: json.load(open(os.path.join(A.STATE, name))) if os.path.exists(os.path.join(A.STATE, name)) else default
assert A.next_game_healthy("2026-10-29")[0] == 0.955
assert A.next_game_healthy("2027-01-15")[0] == 0.944
assert A.next_game_healthy("2027-03-20")[0] == 0.930
# 300 graded healthy non-b2b games this season, 290 played -> 0.967
graded = [{"status": None, "b2b": False, "played": i < 290, "q": 0.955} for i in range(300)] + [{"status": None, "b2b": True, "played": False, "q": 0.89}] * 50
json.dump({"open": {}, "graded": graded}, open(os.path.join(A.STATE, "availability_log.json"), "w"))
rate, basis = A.next_game_healthy("2026-11-20")
print(rate, "-", basis)
assert rate == 0.967 and "own" in basis, "b2b games don't count toward the non-b2b rate"
A.set_next_game(0.955, "x")
assert A.healthy_at(1) == 0.955 and A.healthy_at(2) == 0.923, "only the next game changes"
print("ok: review 2 F2")
