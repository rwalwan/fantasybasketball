"""What other Lock-In leagues show about lock decisions (finished weeks of verified Lock-In leagues).

For every starter whose final slot score equals one of his games (the locked or kept game), with 2+ games:
  * decision points: at each of his games up to the one kept, the score, and the engine's bar for the games still
    left (stopping value with his pre-season projection, the historical healthy play rate, the game-spread curve)
    -> how often real managers lock as a function of score / bar (an opponent model, review finding 11)
  * the engine's rule replayed on the same games vs what the manager ended with
  * the bar scaled by 0.85-1.15 and replayed on every player-week -> is the bar set too high or too low?
Caveat: a 'pass' may just mean the player wasn't in that manager's lineup for that game (box scores can't show
the lineup), so lock rates at a given score are lower bounds.
"""
import json
import random

import numpy as np

from .availability import healthy_at
from .leagues import fantasy_points
from .lockin import expected_max

BINS = [0, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5, 99]


def bar(mus):
    """Engine's continuation value for the remaining games (means `mus`), same recursion as site/engine.js."""
    W = 0.0
    n = len(mus)
    for k in range(n - 1, -1, -1):
        q = healthy_at(k + 1)
        W = q * mus[k] if k == n - 1 else q * expected_max(mus[k], W) + (1 - q) * W
    return W


def replay(scores, mu, scale=1.0):
    """Points the engine's rule ends with on these actual game scores (0 = DNP game)."""
    n = len(scores)
    for i, s in enumerate(scores):
        if i == n - 1:
            return s
        if s > 0 and s >= scale * bar([mu] * (n - 1 - i)):
            return s
    return 0.0


def study(con, weeks, stats_by_week, prior_rows, boot=400, seed=7):
    prior = {}
    for r in prior_rows or []:
        st, gp = r.get("stats") or {}, (r.get("stats") or {}).get("gp") or 0
        if gp >= 10:
            prior[r["player_id"]] = {k: (v or 0) / gp for k, v in st.items() if isinstance(v, (int, float))}
    games = {}
    for w in weeks:
        for r in stats_by_week.get(w, []):
            if r.get("date") and r.get("stats"):
                games.setdefault((w, r["player_id"]), []).append((r["date"], r["stats"]))
    for v in games.values():
        v.sort(key=lambda x: x[0])

    points, outcomes, seqs = [], [], {}
    leagues = con.execute("SELECT league, scoring FROM league WHERE verified=1").fetchall()
    for lid, scoring in leagues:
        sc = json.loads(scoring)
        for w in weeks:
            for st_json, sp_json in con.execute("SELECT starters, starters_points FROM snap WHERE league=? AND week=? AND final=1", (lid, w)):
                for p, s in zip(json.loads(st_json), json.loads(sp_json)):
                    g = games.get((w, p))
                    if not g or len(g) < 2 or not s or p not in prior:
                        continue
                    fp = [fantasy_points(x, sc) for _, x in g]
                    idx = next((i for i, x in enumerate(fp) if abs(x - s) < 0.06), None)
                    if idx is None:
                        continue
                    mu = fantasy_points(prior[p], sc)
                    if mu <= 0:
                        continue
                    for i in range(min(idx, len(fp) - 2) + 1):
                        b = bar([mu] * (len(fp) - 1 - i))
                        points.append((fp[i] / b if b else 0, len(fp) - 1 - i, int(i == idx), lid))
                    outcomes.append((replay(fp, mu) - s, s, lid))
                    seqs[(w, p, json.dumps(sc, sort_keys=True))] = (fp, mu, lid)

    out = {"leagues": len(leagues), "weeks": list(weeks), "decision_points": len(points), "starter_weeks": len(outcomes)}
    if not points:
        return out
    # 1) lock rate by score / bar
    rows = []
    for lo, hi in zip(BINS, BINS[1:]):
        sel = [a for r, k, a, _ in points if lo <= r < hi]
        if sel:
            rows.append({"score_vs_bar": f"{lo:.2f}-{hi:.2f}" if hi < 99 else f"{lo:.2f}+", "n": len(sel), "lock_rate": round(sum(sel) / len(sel), 3)})
    out["lock_rate_by_score_vs_bar"] = rows
    # 2) engine rule vs managers, same player and games; CI by resampling leagues
    rng = random.Random(seed)
    by_lg = {}
    for d, s, lid in outcomes:
        by_lg.setdefault(lid, []).append(d)
    lids = list(by_lg)

    def boot_mean(f):
        vals = []
        for _ in range(boot):
            pick = [rng.choice(lids) for _ in lids]
            xs = [x for l in pick for x in f(l)]
            vals.append(sum(xs) / len(xs) if xs else 0)
        return [round(float(np.percentile(vals, 2.5)), 2), round(float(np.percentile(vals, 97.5)), 2)]
    diffs = [d for d, _, _ in outcomes]
    out["engine_minus_manager"] = {"mean_fp": round(sum(diffs) / len(diffs), 2), "ci95": boot_mean(lambda l: by_lg[l]),
                                   "share_engine_better": round(sum(d > 0 for d in diffs) / len(diffs), 3),
                                   "share_same": round(sum(abs(d) < 0.06 for d in diffs) / len(diffs), 3)}
    # 3) bar scale: replay every unique player-week with the bar x scale
    scales = [0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15]
    seq_by_lg = {}
    for (fp, mu, lid) in seqs.values():
        seq_by_lg.setdefault(lid, []).append((fp, mu))
    res = []
    for sc_ in scales:
        vals = [replay(fp, mu, sc_) for fp, mu in (x for v in seq_by_lg.values() for x in v)]
        res.append({"scale": sc_, "mean_fp": round(sum(vals) / len(vals), 3)})
    base = next(r["mean_fp"] for r in res if r["scale"] == 1.0)
    for r in res:
        r["vs_current"] = round(r["mean_fp"] - base, 3)
    best = max(res, key=lambda r: r["mean_fp"])
    best["ci95_vs_current"] = boot_mean(lambda l: [replay(fp, mu, best["scale"]) - replay(fp, mu, 1.0) for fp, mu in seq_by_lg.get(l, [])])
    out["bar_scale"] = res
    out["best_scale"] = best
    return out
