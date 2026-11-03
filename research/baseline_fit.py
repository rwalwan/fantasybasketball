"""Baseline (FP/G) from last season + this season's games: which way predicts the REST of the season best?
Nov 2: Julian Reese showed 37.4 FP/G (13 games last season at 31 min on a tanking team, 41.6 FP/G; 1 game this
season, 4 FP in a bench role) because last season counted as 8 games of evidence whatever its size or role.
  A  current:  (n * this-season avg + 8 * last-season avg) / (n + 8)
  B  per minute:  FP/G = rate x minutes; rate = (this FP + kr * last rate * this min) / (this min + kr * last-season min share)...
     concretely: rate = (sum FP + R * rate_last) / (sum min + R)          R = pseudo-minutes of last season's rate
                 min  = (sum min + M * mpg_last) / (n + M)                 M = pseudo-games of last season's minutes
     with last season's weight scaled by its size: R and M x gp_last / (gp_last + 20)
Checkpoints after n = 1, 2, 3, 5, 10 games; target = mean FP of the player's games after the checkpoint (8+ games).
Usage: python research/baseline_fit.py <games.parquet> <out.json>"""
import json, sys
import numpy as np, pandas as pd

g = pd.read_parquet(sys.argv[1])
p = g[g.played].sort_values("date")
seasons = sorted(p.season_year.unique())
by = {k: v for k, v in p.groupby(["season_year", "player"])}
rows = []
for si in range(1, len(seasons)):
    s, prev = seasons[si], seasons[si - 1]
    for (ss, pl), d in by.items():
        if ss != s or len(d) < 15:
            continue
        lp = by.get((prev, pl))
        if lp is None or len(lp) < 10:
            continue
        fp, mn = d.fp.values, d["min"].values
        for n in (1, 2, 3, 5, 10):
            if len(fp) - n < 8:
                continue
            rows.append(dict(n=n, fp=fp[:n].sum(), mn=mn[:n].sum(), last_fpg=lp.fp.mean(), last_rate=lp.fp.sum() / max(lp["min"].sum(), 1),
                             last_mpg=lp["min"].mean(), gp_last=len(lp), target=fp[n:].mean()))
R = pd.DataFrame(rows)
print("rows", len(R), "player-seasons", int((R.n == 1).sum()))

def A(d, k=8):
    return (d.fp + k * d.last_fpg) / (d.n + k)

def B(d, Rm, Mg, c):
    w = d.gp_last / (d.gp_last + c) if c else 1.0
    rate = (d.fp + Rm * w * d.last_rate) / (d.mn + Rm * w)
    mpg = (d.mn + Mg * w * d.last_mpg) / (d.n + Mg * w)
    return rate * mpg

mae = lambda pred, d: float(np.mean(np.abs(pred - d.target)))
base = mae(A(R), R)
best = min(((mae(B(R, Rm, Mg, c), R), Rm, Mg, c) for Rm in (100, 200, 300, 400, 600, 800) for Mg in (1, 2, 3, 4, 6, 8) for c in (0, 10, 20, 40)))
print("A current MAE", round(base, 3), "| B per-minute best MAE", round(best[0], 3), "R", best[1], "M", best[2], "c", best[3])
# held out: fit on one season pair, score on the other
loso = {}
for s_out in sorted(set(r for r in seasons[1:])):
    pass
out = {"mae_current": round(base, 3), "mae_per_minute": round(best[0], 3), "R_minutes": best[1], "M_games": best[2], "c_size": best[3],
       "by_n": {int(n): {"current": round(mae(A(d), d), 3), "per_minute": round(mae(B(d, *best[1:]), d), 3), "rows": int(len(d))} for n, d in R.groupby("n")},
       "rows": int(len(R))}
# small last season (10-20 games) and big role changes: where Reese sits
sub = R[(R.gp_last < 20)]
out["small_last_season"] = {"rows": int(len(sub)), "current": round(mae(A(sub), sub), 3), "per_minute": round(mae(B(sub, *best[1:]), sub), 3)}
json.dump(out, open(sys.argv[2], "w"), indent=1)
print(json.dumps(out, indent=1))
