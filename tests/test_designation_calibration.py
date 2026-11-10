"""Play rates by Sleeper designation self-calibrate from this season's graded predictions (Nov 10 review: GTD
players played 78.5% of 158 graded games, DTD 91% of 35, while the engine used the published 48% for the NBA's
official 'Questionable'). Blend: published rate worth 50 games + this season's graded games."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import availability as A

log = {"open": {}, "graded": [{"status": "GTD", "played": i < 124} for i in range(158)] + [{"status": "DTD", "played": i < 32} for i in range(35)]
       + [{"status": None, "played": True}] * 10}
A._load = lambda name, default: log if name == "availability_log.json" else default
out = A.calibrate_designations()
print(out)
assert out["Questionable"][1] == 193 and abs(out["Questionable"][0] - (0.483 * 50 + 156) / 243) < 0.002
assert A.M["designation"]["Questionable"] == out["Questionable"][0]
assert out["Probable"] == (0.866, 0), "no graded games: the published rate"
# idempotent across calls in one process (blends from the published rate, not from the last result)
assert A.calibrate_designations()["Questionable"] == out["Questionable"]
print("ok: designation calibration")
