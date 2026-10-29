"""Per-player game-to-game spread: how much of a player's own boom/bust tendency is real (2021-24 box scores).

The engine draws every game as projection x R, with R from the spread of the player's FP/G tier (app/data/
game_ratio_quantiles.json). Lock-In keeps the best game, so a player who booms more than his tier is worth more.
Per player: r = sd(FP / his mean) / sd of his tier's R. Production uses R_p = 1 + r_hat (R_tier - 1).
  prior   = 1 + a (r_last_season - 1)            (1 if no last season)
  r_hat   = prior + (r_this_season - prior) n / (n + k)       n = games so far this season
a and k are fitted to the spread of the REST of the season (checkpoints n = 0, 5, 10, 20, 30, 40), then the per-player
spread is checked against the tier spread on those future games: pinball loss over the quantiles (all, and the top
30%, which is what lock decisions use), with each future game scaled by the player's rest-of-season mean so that only
the spread is being tested.
Usage: python research/volatility_fit.py <games.parquet> <game_ratio_quantiles.json> <out.json>
"""
import json
import sys

import numpy as np
import pandas as pd

g = pd.read_parquet(sys.argv[1])
QS = json.load(open(sys.argv[2]))
TIERS = [(t.get("max"), np.array(t["quantiles"])) for t in QS["tiers"]]
LEVELS = np.arange(len(QS["quantiles"])) / len(QS["quantiles"]) + 0.5 / len(QS["quantiles"])


def tier(mu):
    return next(q for mx, q in TIERS if mx is None or mu <= mx)


def tier_sd(mu):
    return float(tier(mu).std())


p = g[g.played & (g["min"] >= 10)].sort_values("date")
seasons = sorted(p.season_year.unique())
by = {k: v.fp.values for k, v in p.groupby(["season_year", "player"])}


def ratio(x):
    m = x.mean()
    return (x / m).std() / tier_sd(m) if m > 0 else 1.0


rows = []                              # (r_prev or nan, n_prev, r_cur, n, r_future, future ratios, tier at checkpoint)
for si, s in enumerate(seasons):
    for (ss, pl), x in by.items():
        if ss != s or len(x) < 35 or x.mean() < 15:
            continue
        prev = by.get((seasons[si - 1], pl)) if si > 0 else None
        r_prev = ratio(prev) if prev is not None and len(prev) >= 20 and prev.mean() >= 10 else np.nan
        for n in (0, 5, 10, 20, 30, 40):
            fut = x[n:]
            if len(fut) < 15:
                continue
            cur = x[:n]
            mu_ck = cur.mean() if n >= 5 else (prev.mean() if prev is not None and len(prev) else fut.mean())
            rows.append(dict(r_prev=r_prev, r_cur=ratio(cur) if n >= 5 else np.nan, n=n, r_fut=ratio(fut),
                             fut=fut / fut.mean(), mu=mu_ck, season=s))
R = pd.DataFrame(rows)


def predict(d, a, k):
    prior = np.where(np.isnan(d.r_prev), 1.0, 1 + a * (d.r_prev - 1))
    w = np.where(d.n >= 5, d.n / (d.n + k), 0.0)
    cur = np.where(np.isnan(d.r_cur), prior, d.r_cur)
    return prior + (cur - prior) * w


fit = R[R.season != seasons[0]]        # seasons with a previous season available
best = None
for a in np.arange(0, 1.01, 0.05):
    for k in (2, 5, 8, 10, 15, 20, 25, 30, 40, 60, 80, 120):
        e = float(np.mean((predict(fit, a, k) - fit.r_fut) ** 2))
        if best is None or e < best[0]:
            best = (e, round(float(a), 2), k)
_, A, K = best
base_mse = float(np.mean((1 - fit.r_fut) ** 2))


def pinball(qs, x, top=False):
    """Mean pinball loss of quantile set qs (sorted) for outcomes x."""
    lv = LEVELS[None, :]
    d = x[:, None] - qs[None, :]
    loss = np.maximum(lv * d, (lv - 1) * d)
    if top:
        loss = loss[:, LEVELS >= 0.7]
    return float(loss.mean())


ev = {"tier": [0.0, 0.0], "player": [0.0, 0.0]}
nev = 0
for (i, row), rh in zip(fit.iterrows(), predict(fit, A, K)):
    Qt = tier(row.mu)
    Qp = np.maximum(0, 1 + rh * (Qt - 1))
    Qp = Qp / Qp.mean()
    for name, Q in (("tier", Qt), ("player", Qp)):
        ev[name][0] += pinball(Q, row.fut) * len(row.fut)
        ev[name][1] += pinball(Q, row.fut, top=True) * len(row.fut)
    nev += len(row.fut)
score = {k: {"pinball_all": round(v[0] / nev, 5), "pinball_top30": round(v[1] / nev, 5)} for k, v in ev.items()}
by_n = {int(n): {"n": int(len(d)), "mse_player": round(float(np.mean((predict(d, A, K) - d.r_fut) ** 2)), 4),
                 "mse_tier": round(float(np.mean((1 - d.r_fut) ** 2)), 4)} for n, d in fit.groupby("n")}
# held out: fit a, k on one season, score the other (two seasons have a previous season)
loso = {}
for s_out in sorted(fit.season.unique()):
    tr, te = fit[fit.season != s_out], fit[fit.season == s_out]
    b2 = min(((float(np.mean((predict(tr, a, k) - tr.r_fut) ** 2)), a, k) for a in np.arange(0, 1.01, 0.05)
              for k in (2, 5, 8, 10, 15, 20, 25, 30, 40, 60, 80, 120)))
    acc = {"tier": [0.0, 0.0], "player": [0.0, 0.0]}; m = 0
    for (i, row), rh in zip(te.iterrows(), predict(te, b2[1], b2[2])):
        Qt = tier(row.mu); Qp = np.maximum(0, 1 + rh * (Qt - 1)); Qp = Qp / Qp.mean()
        for name, Q in (("tier", Qt), ("player", Qp)):
            acc[name][0] += pinball(Q, row.fut) * len(row.fut); acc[name][1] += pinball(Q, row.fut, top=True) * len(row.fut)
        m += len(row.fut)
    loso[s_out] = {"a": round(float(b2[1]), 2), "k": b2[2],
                   "pinball_all_tier": round(acc["tier"][0] / m, 5), "pinball_all_player": round(acc["player"][0] / m, 5),
                   "pinball_top30_tier": round(acc["tier"][1] / m, 5), "pinball_top30_player": round(acc["player"][1] / m, 5)}
out = {"note": __doc__.strip().split("\n")[0], "a_prev": A, "k_games": K, "mse": round(best[0], 4), "mse_tier_only": round(base_mse, 4),
       "rows": int(len(fit)), "player_seasons": int(fit[fit.n == 0].shape[0]), "by_checkpoint": by_n, "future_games": nev,
       "pinball": score, "held_out_season": loso, "r_future_sd": round(float(fit.r_fut.std()), 3)}
json.dump(out, open(sys.argv[3], "w"), indent=1)
print(json.dumps(out, indent=1))
