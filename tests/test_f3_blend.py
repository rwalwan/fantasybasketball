"""Finding 3 (review 2026-10-28): the learned blend was worse than RotoWire alone.

Inverse-MSE weights treat the sources as independent, but 'model' and 'ctx' errors correlate 0.977, so the two
near-duplicates took ~62% of the weight. On the 378 graded games in the fixture: RotoWire MAE 8.99, model 10.16,
ctx 10.45, inverse-MSE blend 9.46. The fix fits weights by minimizing the blend's own error (non-negative, sum 1),
keeps them only if they beat RotoWire alone out of sample (leave-one-day-out), and corrects the mean bias.
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from app import experts

fx = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "graded_games_2026-10-25_27.json")))
rows = fx["rows"]
y = np.array([r[1] for r in rows]); X = np.array([r[2:] for r in rows])
mae = lambda w, s=1.0: float(np.mean(np.abs(y - s * (X @ w) / sum(w))))

# the old way, reproduced: inverse-MSE weights from these same games
inv = 1 / np.mean((y[:, None] - X) ** 2, axis=0)
old = inv / inv.sum()
print("inverse-MSE weights", np.round(old, 3), "MAE", round(mae(old), 2), "| RotoWire alone", round(mae(np.array([1, 0, 0])), 2))
assert round(mae(np.array([1, 0, 0])), 2) == 8.99
assert mae(old) > mae(np.array([1, 0, 0])) + 0.3          # the defect: blend worse than its best input

w = experts.stack_weights(rows)
nw = np.array([w["rotowire"], w["model"], w["ctx"]])
print("stacked", w, "MAE", round(mae(nw, w["scale"]), 2))
assert mae(nw, w["scale"]) <= mae(np.array([1, 0, 0])) + 1e-9, "never worse than RotoWire alone"
assert w["rotowire"] >= 0.6 and w["ctx"] <= 0.2
# too little data: fall back to RotoWire alone (the best single source so far), no scale change
assert experts.stack_weights(rows[:50]) == {"rotowire": 1.0, "model": 0.0, "ctx": 0.0, "usage": 0.0, "scale": 1.0, "n": 50, "basis": "too few graded games"}
print("ok: finding 3")
