"""Fit the teammate-absence minutes model (app/absence.py) on 2021-24 box scores, and check it on this season.

Usage: python research/absence_fit.py research/data/games.parquet [memory.sqlite] [out.json]

Walk-forward, no hindsight: for every game a player played after his first 5 for that team, his on/off record with
each teammate (10+ min/game over 3+ earlier games) is taken from earlier games only, and "sits tonight" is whether
the teammate actually played (production uses the play chance instead). Fitted on two seasons, tested on the third
(each in turn). Minutes first (share_same, share_other, k on minutes error), then the exponent e on fantasy points.

With a memory.sqlite (this season, from the state branch), it also replays the production blend on graded games:
model and matchup sources x factor, weights refit leave-one-day-out, against the blend as it is, with a paired
day-bootstrap 95% interval.
"""
import itertools
import json
import os
import sqlite3
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import absence  # noqa: E402

BASE = dict(absence.PARAMS)


def rows_from_team_days(team_days_by_team, grp, fp_of):
    """Walk-forward rows: [(day, min, fp, m_hist, fp_hist, [(x, n_on, n_off, d_obs, mpg, same)])]."""
    rows = []
    for t, td in team_days_by_team.items():
        dates = sorted(td)
        seen = defaultdict(list)                   # pid -> minutes in earlier games for this team
        for d in dates:
            mpg = {a: sum(v) / len(v) for a, v in seen.items() if len(v) >= 3}
            for p, m in td[d].items():
                if len(seen[p]) < absence.MIN_GAMES:
                    continue
                mates = {a: (mpg[a], grp.get(a) == grp.get(p)) for a in mpg if a != p}
                r = absence.terms(p, td, d, mates)
                if not r:
                    continue
                m_hist, n, tl = r
                hist = [fp_of[(p, x)] for x in dates if x < d and p in td[x]]
                feats = [((0.0 if a in td[d] else 1.0) - fa, n_on, n_off, d_obs, mp, same, n_st, d_st)
                         for a, fa, n_on, n_off, d_obs, mp, same, n_st, d_st in tl]
                rows.append((d, m, fp_of[(p, d)], m_hist, sum(hist) / len(hist), feats))
            for p, m in td[d].items():
                seen[p].append(m)
    return rows


def flatten(rows):
    idx, x, non, noff, dobs, mpg, same, nst, dst = [], [], [], [], [], [], [], [], []
    for i, r in enumerate(rows):
        for f in r[5]:
            idx.append(i); x.append(f[0]); non.append(f[1]); noff.append(f[2]); dobs.append(f[3]); mpg.append(f[4]); same.append(f[5]); nst.append(f[6]); dst.append(f[7])
    A = lambda v, t=float: np.array(v, t)
    return dict(n=len(rows), idx=A(idx, int), x=A(x), non=A(non), noff=A(noff), dobs=A(dobs), mpg=A(mpg), same=A(same, bool), nst=A(nst), dst=A(dst),
                minutes=A([r[1] for r in rows]), fp=A([r[2] for r in rows]), mh=A([r[3] for r in rows]),
                fph=A([r[4] for r in rows]), day=np.array([r[0] for r in rows]))


def predict(F, prm):
    prior = np.where(F["same"], prm["share_same"], prm["share_other"]) * F["mpg"]
    wst = prm.get("streak", 1.0) - 1
    off_w = F["noff"] + wst * F["nst"]
    d_w = np.where(off_w > 0, (F["noff"] * F["dobs"] + wst * F["nst"] * F["dst"]) / np.maximum(off_w, 1e-9), 0.0)
    neff = np.where((F["non"] > 0) & (off_w > 0), F["non"] * off_w / np.maximum(F["non"] + off_w, 1e-9), 0.0)
    d = (neff * d_w + prm["k"] * prior) / (neff + prm["k"])
    d = np.clip(d, -0.5 * F["mpg"], F["mpg"])
    tot = np.bincount(F["idx"], weights=F["x"] * d, minlength=F["n"])
    m = np.clip(F["mh"] + tot, 0.5 * F["mh"], absence.MAX_MIN)
    f = np.clip((m / F["mh"]) ** prm["e"], prm["lo"], prm["hi"])
    small = F["mh"] < 8                           # app/absence.shift: no factor for a player under 8 minutes
    return np.where(small, F["mh"], m), np.where(small, 1.0, f)


def grid_minutes(F):
    best = None
    for ss, so, k, st in itertools.product([0.06, 0.1, 0.15], [0.04, 0.06, 0.08], [30, 70, 120, 200, 350],
                                           [8, 16, 32, 64, 128]):
        prm = dict(BASE, share_same=ss, share_other=so, k=k, streak=st)
        m, _ = predict(F, prm)
        err = np.abs(F["minutes"] - m).mean()
        if best is None or err < best[0]:
            best = (err, prm)
    return best[1]


def grid_e(F, prm):
    best = None
    for e in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]:
        p = dict(prm, e=e)
        _, f = predict(F, p)
        err = np.abs(F["fp"] - F["fph"] * f).mean()
        if best is None or err < best[0]:
            best = (err, p)
    return best[1]


def sub(F, mask):
    keep = np.where(mask)[0]
    remap = -np.ones(F["n"], int); remap[keep] = np.arange(len(keep))
    fm = mask[F["idx"]]
    G = {k: F[k][fm] for k in ("x", "non", "noff", "dobs", "mpg", "same", "nst", "dst")}
    G["idx"] = remap[F["idx"][fm]]
    G.update({k: F[k][keep] for k in ("minutes", "fp", "mh", "fph", "day")})
    G["n"] = len(keep)
    return G


def boot(diff, days, n=2000, seed=0):
    """95% interval of the mean per-game difference, resampling whole days."""
    rng = np.random.default_rng(seed)
    u = np.unique(days)
    by = {d: diff[days == d] for d in u}
    sums = np.array([by[d].sum() for d in u]); cnt = np.array([len(by[d]) for d in u])
    res = []
    for _ in range(n):
        pick = rng.integers(0, len(u), len(u))
        res.append(sums[pick].sum() / cnt[pick].sum())
    return float(np.percentile(res, 2.5)), float(np.percentile(res, 97.5))


def history(parquet):
    import pandas as pd
    g = pd.read_parquet(parquet)
    g = g[g.played]
    out = {}
    for season, s in g.groupby("season_year"):
        prof = s.groupby("pid").agg(mins=("min", "sum"), ast=("ast", "sum"), reb=("reb", "sum"))
        a36, r36 = prof.ast / prof.mins * 36, prof.reb / prof.mins * 36
        grp = dict(zip(prof.index, np.where(a36 >= 4.5, "G", np.where(r36 >= 9, "C", "F"))))
        td = defaultdict(lambda: defaultdict(dict))
        fp_of = {}
        for t, d, p, m, fp in zip(s.team, s.game_date, s.pid, s["min"], s.fp):
            td[t][d][p] = float(m)
            fp_of[(p, d)] = float(fp)
        out[season] = flatten(rows_from_team_days(td, grp, fp_of))
        print(season, "rows", out[season]["n"], file=sys.stderr)
    return out


def season_factors(con, prm):
    """Walk-forward absence factor for every played game of the store's latest season: (season, {(pid, date): f})."""
    season = con.execute("SELECT max(season) FROM games").fetchone()[0]
    rows = con.execute("SELECT pid, date, team, min, fp, reb, ast FROM games WHERE season=? AND min > 0", (season,)).fetchall()
    # position group from this season's per-36 profile (the production rule, app/usage.py profiles)
    acc = defaultdict(lambda: [0.0, 0.0, 0.0])
    for p, d, t, m, fp, reb, ast in rows:
        a = acc[p]; a[0] += m; a[1] += reb or 0; a[2] += ast or 0
    grp = {p: ("G" if a[2] / a[0] * 36 >= 4.5 else "C" if a[1] / a[0] * 36 >= 9 else "F") for p, a in acc.items() if a[0] > 0}
    td = defaultdict(lambda: defaultdict(dict)); fp_of = {}
    for p, d, t, m, fp, *_ in rows:
        td[t][d][p] = m; fp_of[(p, d)] = fp
    F = flatten(rows_from_team_days(td, grp, fp_of))
    _, f = predict(F, prm)
    keys = []                                     # same walk order as rows_from_team_days
    for t, tdd in td.items():
        seen = defaultdict(int)
        for d in sorted(tdd):
            for p in tdd[d]:
                if seen[p] >= absence.MIN_GAMES:
                    keys.append((p, d))
            for p in tdd[d]:
                seen[p] += 1
    assert len(keys) == F["n"], (len(keys), F["n"])
    return season, dict(zip(keys, f))


def this_season(db, prm):
    """Replay the production blend on this season's graded games (memory.sqlite)."""
    from app import experts
    con = sqlite3.connect(db)
    season, fac = season_factors(con, prm)
    g = con.execute("SELECT date, pid, fp, proj_rw, proj_model, proj_ctx FROM games WHERE season=? AND proj_rw IS NOT NULL "
                    "AND proj_model IS NOT NULL AND proj_ctx IS NOT NULL ORDER BY date", (season,)).fetchall()
    old = [[d, fp, rw, m, c] for d, p, fp, rw, m, c in g]
    new = [[d, fp, rw, m * fac.get((p, d), 1.0), c * fac.get((p, d), 1.0)] for d, p, fp, rw, m, c in g]
    res = {}
    for name, rs in (("current", old), ("with absences", new)):
        dates = np.array([r[0] for r in rs]); y = np.array([r[1] for r in rs]); X = np.array([r[2:] for r in rs])
        pred = np.zeros(len(rs))
        for d in np.unique(dates):          # leave-one-day-out: the weights never see the day they predict
            tr = dates != d
            w = experts._fit_simplex(y[tr], X[tr])
            pred[dates == d] = X[dates == d] @ w
        res[name] = (np.abs(y - pred), dates, experts._fit_simplex(y, X))
    diff = res["with absences"][0] - res["current"][0]
    lo, hi = boot(diff, res["current"][1])
    moved = np.array([abs(fac.get((p, d), 1.0) - 1) >= 0.05 for d, p, *_ in g])
    out = {"season": season, "games": len(g), "mae_current": round(float(res["current"][0].mean()), 3),
           "mae_with": round(float(res["with absences"][0].mean()), 3), "diff": round(float(diff.mean()), 3),
           "ci95": [round(lo, 3), round(hi, 3)],
           "moved_5pct": int(moved.sum()),
           "mae_moved_current": round(float(res["current"][0][moved].mean()), 3) if moved.any() else None,
           "mae_moved_with": round(float(res["with absences"][0][moved].mean()), 3) if moved.any() else None,
           "weights_current": [round(float(v), 2) for v in res["current"][2]],
           "weights_with": [round(float(v), 2) for v in res["with absences"][2]]}
    q = [(d, round(float(fac.get(("2302", d), 1.0)), 3)) for d, p, *_ in g if p == "2302"]
    out["queta"] = q[-6:]
    return out


if __name__ == "__main__":
    H = history(sys.argv[1])
    seasons = sorted(H)
    report = {"loso": []}
    for test in seasons:
        tr = [s for s in seasons if s != test]
        Ftr = {k: None for k in H[tr[0]]}
        # concatenate training seasons
        parts = [H[s] for s in tr]
        off = np.cumsum([0] + [p["n"] for p in parts[:-1]])
        Ftr = {"n": sum(p["n"] for p in parts), "idx": np.concatenate([p["idx"] + o for p, o in zip(parts, off)])}
        for k in ("x", "non", "noff", "dobs", "mpg", "same", "nst", "dst", "minutes", "fp", "mh", "fph", "day"):
            Ftr[k] = np.concatenate([p[k] for p in parts])
        prm = grid_e(Ftr, grid_minutes(Ftr))
        Fte = H[test]
        m, f = predict(Fte, prm)
        min_gain = np.abs(Fte["minutes"] - Fte["mh"]) - np.abs(Fte["minutes"] - m)
        fp_gain = np.abs(Fte["fp"] - Fte["fph"]) - np.abs(Fte["fp"] - Fte["fph"] * f)
        moved = np.abs(f - 1) >= 0.05
        report["loso"].append({"test": test, "params": {k: prm[k] for k in ("share_same", "share_other", "k", "streak", "e")},
                               "rows": int(Fte["n"]), "min_mae_gain": round(float(min_gain.mean()), 3),
                               "fp_mae_gain": round(float(fp_gain.mean()), 3), "fp_ci95": [round(v, 3) for v in boot(-fp_gain, Fte["day"])],
                               "moved_5pct": int(moved.sum()), "fp_mae_gain_moved": round(float(fp_gain[moved].mean()), 3)})
        print(json.dumps(report["loso"][-1]), file=sys.stderr)
    # final: all seasons
    parts = [H[s] for s in seasons]
    off = np.cumsum([0] + [p["n"] for p in parts[:-1]])
    Fall = {"n": sum(p["n"] for p in parts), "idx": np.concatenate([p["idx"] + o for p, o in zip(parts, off)])}
    for k in ("x", "non", "noff", "dobs", "mpg", "same", "nst", "dst", "minutes", "fp", "mh", "fph", "day"):
        Fall[k] = np.concatenate([p[k] for p in parts])
    prm = grid_e(Fall, grid_minutes(Fall))
    report["params"] = {k: prm[k] for k in ("share_same", "share_other", "k", "streak", "e", "lo", "hi")}
    if len(sys.argv) > 2 and os.path.exists(sys.argv[2]):
        report["this_season"] = this_season(sys.argv[2], prm)
        print(json.dumps(report["this_season"]), file=sys.stderr)
    if len(sys.argv) > 3:
        json.dump(dict(prm, note="Teammate absences -> minutes (app/absence.py). Fitted by research/absence_fit.py on "
                       "2021-24 box scores; see 'fit' for the held-out checks.", fit=report), open(sys.argv[3], "w"), indent=1)
    print(json.dumps(report, indent=1))
