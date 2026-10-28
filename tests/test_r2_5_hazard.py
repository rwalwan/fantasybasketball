"""Review 2, finding 5: the first hazard refit (review 1) censored every absence that ran to the team's last game,
so end-of-season shutdowns counted as season-ending injuries, and fixed-length health-and-safety protocol stays
counted as injuries. Long absences looked too sticky (13-20 missed: 0.084, 21+: 0.078), undervaluing mid-season
injured players. Refit (research/hazard_refit.py): last stint observed to the team's 15th-to-last game, protocol and
reconditioning stays dropped. 13-20 = 0.114 (n=273) and 21+ = 0.138 (n=65) don't differ, so 13+ is pooled at 0.118:
still below the original biased 0.139, above the overcorrected 0.084."""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import availability as A

print("hazard after 13 / 25 missed:", A.hazard(13), A.hazard(25), "| at risk:", A.M.get("at_risk"))
assert 0.10 <= A.hazard(13) <= 0.13, A.hazard(13)
assert A.hazard(25) == A.hazard(13), "13+ pooled: the data can't tell 13-20 from 21+"
assert A.M.get("at_risk", {}).get("21+", 0) > 0, "at-risk counts are recorded with the fit"
src = open(os.path.join(os.path.dirname(__file__), "..", "research", "hazard_refit.py")).read()
non_inj = re.search(r'NON_INJ = r"([^"]+)"', src).group(1)
for comment in ("NWT - Health and Safety Protocols", "DND-Return to Competition Reconditioning"):
    assert re.search(non_inj, comment), comment
assert not re.search(non_inj, "DNP - Concussion Protocol"), "a concussion is an injury"
assert "TAIL = 15" in src
# the engine's fallback copy (used when the job's availability.json is missing) must match the fitted model
import json
js = open(os.path.join(os.path.dirname(__file__), "..", "site", "engine.js")).read()
copy = json.loads(re.search(r"const DEFAULT_AVAIL = (\{.*\});", js).group(1))
assert all(copy[k] == A.M[k] for k in copy), {k: (copy[k], A.M[k]) for k in copy if copy[k] != A.M[k]}
print("ok: review 2 finding 5")
