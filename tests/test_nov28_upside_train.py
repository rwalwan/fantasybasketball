"""Nov 28: the nightly trainer keeps the upside model (app/upside.py) current (app/train_models.py Upside).

Rule: each absence bucket's outcome range is learned from graded games as multipliers on the normal range, shrunk
K games toward no change; a promotion moves a multiplier at most 0.15, every multiplier stays in 0.5-2.0, and the
pinball loss decides. Synthetic games where big-absence nights really run 1.6x must teach a higher, longer range for
that bucket and nothing for the normal one.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import upside, train_models as TM

rng = np.random.default_rng(3)
rows = []
for i in range(6000):
    day = f"2026-11-{1 + i % 27:02d}"
    f = 1.5 if i % 10 == 0 else 1.0
    pred = 30.0
    r = rng.gamma(4, 0.25) * (1.6 if f > 1.35 else 1.0)
    rows.append({"day": day, "pid": str(i), "y": pred * r, "pred": pred, "f": f})

P = upside.fit(rows)
g4, g1 = np.array(P["g"]["4"]), np.array(P["g"]["1"])
assert np.allclose(g1, 1), "the normal bucket never moves"
assert upside.mean_mult(P, 4) > 1.35, upside.mean_mult(P, 4)
assert P["n"]["4"] == 600
# shrinkage: 600 games vs K=100 keeps ~86% of the raw 1.6
assert upside.mean_mult(P, 4) < 1.6
# the learned model beats "no change" on these games
P0 = dict(P, g={b: [1.0] * len(upside.TAUS) for b in P["g"]})
assert upside.loss(P, rows).mean() < upside.loss(P0, rows).mean()

m = TM.Upside()
assert m.bounds(P) is None
bad = dict(P, g=dict(P["g"], **{"4": [2.5] * len(upside.TAUS)}))
assert m.bounds(bad), "a multiplier above 2 is refused"
st = m.step(P0, P)
assert all(abs(a - 1) <= 0.15 + 1e-9 for a in st["g"]["4"]), "a promotion moves each multiplier 0.15 at most"
assert abs(st["mean"]["4"] - upside.mean_mult(st, 4)) < 1e-3
assert "a lot more minutes" in m.describe(P0, P)
# the factory file is what the job sends the page when nothing is promoted
F = upside.factory()
assert F and upside.for_page(F)["edges"] == upside.EDGES
print("ok: Nov 28 upside (trainer)")
