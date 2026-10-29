"""Per-player game-to-game spread (fitted in research/volatility_fit.py, 2021-24, checked on held-out seasons).

Every game is drawn as projection x R. R used to come only from the spread of the player's FP/G tier, so two players
with the same average had the same chance of a big night. Lock-In keeps the best game, so a boom-or-bust player is
worth more than a steady one: some players really do boom more than their tier (split-half and season-to-season
correlation), but only partly, so the player's own spread is shrunk:
  r       = sd(FP / his mean) / sd of his tier's R          (games of 10+ minutes)
  prior   = 1 + 0.3 (r_last_season - 1)                     (1 if no last season)
  r_hat   = prior + (r_this_season - prior) n / (n + 40)    n = games this season
The engine uses R_p = 1 + r_hat (R_tier - 1), mean kept at 1. On held-out seasons this beat the tier spread on every
measure (future spread error -18%; quantile loss -0.6% overall and -0.8% on the top 30% of games, the ones lock
calls depend on).
"""
import json
import os

import numpy as np

D = os.path.join(os.path.dirname(__file__), "data")
M = json.load(open(os.path.join(D, "volatility_model.json")))
_QS = json.load(open(os.path.join(D, "game_ratio_quantiles.json")))
TIERS = [(t.get("max"), float(np.std(t["quantiles"]))) for t in _QS["tiers"]]


def tier_sd(mu):
    return next(sd for mx, sd in TIERS if mx is None or mu <= mx)


def ratio(fps):
    x = np.asarray(fps, dtype=float)
    m = x.mean() if len(x) else 0
    return float((x / m).std() / tier_sd(m)) if m > 0 else None


def build(this_season, last_season):
    """{pid: r_hat} from {pid: [FP of games with 10+ min]} for this season and last season."""
    a, k = M["a_prev"], M["k_games"]
    lo, hi = M["clip"]
    out = {}
    for pid in set(this_season) | set(last_season):
        prev, cur = last_season.get(pid) or [], this_season.get(pid) or []
        rp = ratio(prev) if len(prev) >= 20 and np.mean(prev) >= 10 else None
        prior = 1 + a * (rp - 1) if rp is not None else 1.0
        rc = ratio(cur) if len(cur) >= 5 else None
        r = prior + (rc - prior) * len(cur) / (len(cur) + k) if rc is not None else prior
        r = min(hi, max(lo, r))
        if abs(r - 1) >= 0.02:
            out[pid] = round(r, 3)
    return out
