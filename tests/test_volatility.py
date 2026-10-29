"""app/volatility.py: a player's own spread, shrunk toward his tier (fit: research/volatility_fit.py)."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import volatility as V

assert V.M["a_prev"] == 0.3 and V.M["k_games"] == 40
sd = V.tier_sd(35)
z = np.tile(np.linspace(-1, 1, 10), 6); z = z / z.std()                     # exact unit spread in every 10 games
wild = list(35 * (1 + 1.6 * sd * z))                                           # 1.6x his tier's spread
calm = list(35 * (1 + 0.6 * sd * z))
out = V.build({"w": wild[:10], "c": calm[:10], "new": wild[:3]}, {"w": wild[10:], "c": calm[10:]})
print(out)
assert out["w"] > 1.1 and out["c"] < 0.9, "last season + 10 games: partly trusted"
assert out["w"] < 1.4, "shrunk: 10 games and a 30% carry-over can't make him fully 1.6x"
assert "new" not in out, "3 games, no last season: his tier's spread"
print("ok: volatility")
