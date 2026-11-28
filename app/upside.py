"""Upside model: how a game's whole outcome range moves when teammates' absences open (or close) minutes (Nov 28).

Why: the projection blend already gets the middle about right when teammates sit (RotoWire prices injuries), but not
the top end. On this season's graded games (Oct 20 - Nov 27), games the absence model (app/absence.py) put at
1.35x+ minutes went 1.5x their projection 41% of the time (vs 13% for the rest) and averaged 1.42x it; 1.2-1.35x
games averaged 1.11x; 1.03-1.1x games ran no hotter than normal. 2021-24 shows the same shape every season.

So each game falls in a bucket by its absence factor f, and each bucket has its own outcome range, learned as a
multiplier on every quantile of (actual / projection) relative to the normal bucket (0.9-1.1), shrunk K games toward
no change. The bucket's mean multiplier moves the projection; the rest moves the shape (mostly the top end).
Scored by pinball (quantile) loss at tau = 0.05..0.95. Checked Nov 28: fit on Oct 20 - Nov 10, tested on Nov 11-27,
loss down 0.008 per game (95% interval 0.005-0.012); the reverse split: no change (-0.001, interval -0.004 to +0.003).
The nightly trainer refits it (app/train_models.py Upside); research/boom_fit.py is the study.
"""
import json
import os

import numpy as np

from . import absence, experts

TAUS = [round(0.05 * i, 2) for i in range(1, 20)]
EDGES = [0.9, 1.1, 1.2, 1.35]          # buckets: <0.9, 0.9-1.1 (normal), 1.1-1.2, 1.2-1.35, 1.35+
NORMAL = 1
K = 100                                # games of "no change" behind each bucket's multipliers
FACTORY = os.path.join(os.path.dirname(__file__), "data", "upside_model.json")
NAMES = {0: "fewer minutes (teammate back)", 1: "normal", 2: "a bit more room", 3: "more minutes", 4: "a lot more minutes"}


def bucket(f, edges=EDGES):
    return int(np.searchsorted(edges, f, side="right"))


def factory():
    try:
        return {k: v for k, v in json.load(open(FACTORY)).items() if k != "fit"}
    except (OSError, ValueError):
        return None


def rows_from_store(con, season):
    """Graded games: {day, y (actual FP), pred (the projection blend, weights refit leave-one-day-out), f}."""
    g = con.execute("SELECT date, pid, fp, proj_rw, proj_model, proj_ctx FROM games WHERE season=? AND min > 0 "
                    "AND proj_rw IS NOT NULL AND proj_model IS NOT NULL AND proj_ctx IS NOT NULL ORDER BY date",
                    (season,)).fetchall()
    if len(g) < 50:
        return []
    fac = absence.walk_factors(con, season)
    dates = np.array([r[0] for r in g]); y = np.array([r[2] for r in g], float); X = np.array([r[3:] for r in g], float)
    pred = np.zeros(len(g))
    for d in np.unique(dates):
        tr = dates != d
        pred[dates == d] = X[dates == d] @ experts._fit_simplex(y[tr], X[tr])
    return [{"day": r[0], "pid": r[1], "y": float(y[i]), "pred": float(pred[i]), "f": float(fac.get((r[1], r[0]), 1.0))}
            for i, r in enumerate(g) if pred[i] > 3]


def _smooth(v):
    v = np.asarray(v, float)
    return np.convolve(np.r_[v[0], v, v[-1]], np.ones(3) / 3, "valid")


def fit(rows, k=K):
    """{edges, taus, base: pooled quantiles, g: {bucket: multipliers}, n: {bucket: games}, mean: {bucket: m}}."""
    r = np.array([x["y"] / x["pred"] for x in rows]); b = np.array([bucket(x["f"]) for x in rows])
    base = np.quantile(r, TAUS)
    normal = np.quantile(r[b == NORMAL], TAUS) if (b == NORMAL).sum() >= 50 else base
    g, n = {}, {}
    for i in range(len(EDGES) + 1):
        s = b == i
        n[str(i)] = int(s.sum())
        if i == NORMAL or s.sum() < 20:
            g[str(i)] = [1.0] * len(TAUS)
            continue
        raw = _smooth(np.quantile(r[s], TAUS) / np.maximum(normal, 1e-3))
        g[str(i)] = [round(float(v), 3) for v in 1 + (raw - 1) * s.sum() / (s.sum() + k)]
    out = {"edges": EDGES, "taus": TAUS, "base": [round(float(v), 4) for v in base], "g": g, "n": n}
    out["mean"] = {i: round(mean_mult(out, i), 3) for i in g}
    return out


def mean_mult(P, i):
    """The bucket's average multiplier on the outcome (the projection moves by this much)."""
    g, base = np.array(P["g"][str(i)]), np.array(P["base"])
    return float((g * base).sum() / base.sum())


def predict_q(P, rows):
    """(n, T) predicted quantiles of each row's FP."""
    g = np.array([P["g"][str(bucket(x["f"], P["edges"]))] for x in rows])
    return np.array([x["pred"] for x in rows])[:, None] * np.array(P["base"])[None, :] * g


def loss(P, rows):
    """Per-row mean pinball loss over TAUS (FP units)."""
    y = np.array([x["y"] for x in rows])
    d = y[:, None] - predict_q(P, rows)
    t = np.array(TAUS)[None, :]
    return np.maximum(t * d, (t - 1) * d).mean(axis=1)


def for_page(P):
    """What the engine needs: bucket edges, the quantile levels, and each bucket's multipliers and mean."""
    if not P:
        return None
    return {"edges": P["edges"], "taus": P["taus"], "g": P["g"], "mean": {str(i): mean_mult(P, i) for i in P["g"]}}
