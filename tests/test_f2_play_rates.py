"""Finding 2, Python side: availability.py uses the same healthy curve and b2b ratio as the engine."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import availability as A, model

assert abs(model.B2B_FACTOR - 0.93) < 0.005, model.B2B_FACTOR
assert abs(A.M["b2b_factor"] - 0.93) < 0.005
assert round(A.healthy_at(1), 3) == 0.944 and 0.84 <= A.healthy_at(30) <= 0.86
# undesignated players get a logged next-game prediction (b2b-adjusted) so the curve can be graded
meta = {"h": {"team": "AAA"}, "inj": {"team": "AAA", "injury_status": "Out"}}
dates = {"AAA": {"2026-11-01": {}, "2026-11-02": {}, "2026-11-04": {}}}
hn = A.healthy_next(meta, dates, "2026-11-02", lambda d, t: d < "2026-11-02", ["h", "inj"], set())
assert hn == {"h": ("2026-11-02", round(0.944 * 0.93, 3))}, hn
A.STATE = tempfile.mkdtemp()
b = model.PlayerBook({}, meta)
A.log_and_grade({}, b, lambda d, t: False, "2026-11-02", hn)
assert "2026-11-02|h" in json.load(open(os.path.join(A.STATE, "availability_log.json")))["open"]
print("ok: finding 2 (python)")
