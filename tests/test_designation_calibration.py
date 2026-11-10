"""Play rates by Sleeper designation self-calibrate from this season's graded predictions, blended with the published
table (worth 50 games). Nov 10: GTD players played 78.5% of 158 graded games, DTD 91% of 35, vs the published 48%.
Review 3, finding 2: those 193 records carry the LAST status before the game (a GTD player ruled out that afternoon
was graded as Out), so they measure 'still GTD on game day'. They now feed the game-day rate only; the rate used a day
or more ahead comes from records graded on the status at first sight."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import availability as A

old = [{"status": "GTD", "played": i < 124} for i in range(158)] + [{"status": "DTD", "played": i < 32} for i in range(35)] \
    + [{"status": None, "played": True}] * 10
log = {"open": {}, "graded": old}
A._load = lambda name, default: log if name == "availability_log.json" else default
out = A.calibrate_designations()
print(out, A.M["designation_gameday"])
gd = (0.483 * 50 + 156) / 243
assert abs(A.M["designation_gameday"]["Questionable"] - gd) < 0.002, "the old records are the game-day rate (0.741)"
prior = (0.483 + gd) / 2
assert out["Questionable"][1] == 0 and abs(out["Questionable"][0] - prior) < 0.002, "a day ahead: halfway between published and game-day until first-sight games are graded"
assert out["Probable"] == (0.866, 0), "no graded games: the published rate"
# first-sight records: 100 GTD the evening before, 60 played (20 of the 40 who sat had become Out by tip)
log["graded"] = old + [{"status": "GTD", "last_status": "Out" if 60 <= i < 80 else "GTD", "played": i < 60, "first": True} for i in range(100)]
out = A.calibrate_designations()
gd2 = (0.483 * 50 + 156 + 60) / (50 + 193 + 80)      # game day: the 80 still GTD at the last run (60 played) join the 193 old records
assert abs(A.M["designation_gameday"]["Questionable"] - gd2) < 0.002
assert out["Questionable"][1] == 100 and abs(out["Questionable"][0] - ((0.483 + gd2) / 2 * 50 + 60) / 150) < 0.002, out
assert A.M["designation"]["Questionable"] == out["Questionable"][0]
# idempotent across calls in one process (blends from the published rate, not from the last result)
assert A.calibrate_designations()["Questionable"] == out["Questionable"]
print("ok: designation calibration")
