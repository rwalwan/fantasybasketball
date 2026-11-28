"""Fit and check the upside model (app/upside.py) on this season's graded games (Nov 28).

Usage: python research/boom_fit.py <memory.sqlite> [out.json]   (out: app/data/upside_model.json, the factory numbers)

Prints the outcome range by absence-factor bucket (actual / projection), then checks the bucket model on days held
out of the fit both ways (fit on the earlier half, test on the later, and the reverse), with a day-bootstrap 95%
interval for the change in pinball loss, for several shrinkage strengths K.

Tried and dropped (Nov 28): a smooth model, each quantile moving by exp(beta(tau) x log f) with beta quadratic in
tau. Most games sit at f 0.97-1.1, where the outcome range doesn't move, and the fit followed them: it raised the
floor, not the ceiling, and lost to the buckets on the later half. Also dropped: his minutes over his last 3 games
as a second input (the fit gave it zero weight).
"""
import json
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import upside  # noqa: E402
from research.absence_fit import boot  # noqa: E402


def table(rows):
    f = np.array([r["f"] for r in rows]); r = np.array([r["y"] / r["pred"] for r in rows])
    out = []
    for lo, hi in [(0, 0.9), (0.9, 0.97), (0.97, 1.03), (1.03, 1.1), (1.1, 1.2), (1.2, 1.35), (1.35, 9)]:
        s = (f >= lo) & (f < hi)
        if s.sum():
            q = np.percentile(r[s], [10, 50, 90])
            out.append({"f": f"{lo}-{hi}", "n": int(s.sum()), "mean": round(float(r[s].mean()), 3),
                        "p10_p50_p90": [round(float(v), 2) for v in q], "share_1_5x": round(float((r[s] >= 1.5).mean()), 3)})
    return out


def check(rows, k):
    days = sorted({r["day"] for r in rows}); mid = days[len(days) // 2]
    out = []
    for name, tr, te in (("fit before, test from " + mid, lambda r: r["day"] < mid, lambda r: r["day"] >= mid),
                         ("fit from, test before " + mid, lambda r: r["day"] >= mid, lambda r: r["day"] < mid)):
        a, b = [r for r in rows if tr(r)], [r for r in rows if te(r)]
        P = upside.fit(a, k)
        P0 = dict(P, g={i: [1.0] * len(upside.TAUS) for i in P["g"]})
        d = upside.loss(P, b) - upside.loss(P0, b)
        lo, hi = boot(d, np.array([r["day"] for r in b]))
        big = np.array([upside.bucket(r["f"]) >= 3 for r in b])
        out.append({"split": name, "k": k, "test_games": len(b), "pinball_change": round(float(d.mean()), 4),
                    "ci95": [round(lo, 4), round(hi, 4)], "big_games": int(big.sum()),
                    "pinball_change_big": round(float(d[big].mean()), 3) if big.any() else None})
    return out


if __name__ == "__main__":
    con = sqlite3.connect(sys.argv[1])
    season = con.execute("SELECT max(season) FROM games").fetchone()[0]
    rows = upside.rows_from_store(con, season)
    report = {"season": season, "games": len(rows), "by_factor": table(rows), "checks": []}
    for k in (50, 100, 200):
        report["checks"] += check(rows, k)
    P = upside.fit(rows)
    report["final"] = {"n": P["n"], "mean": P["mean"]}
    print(json.dumps(report, indent=1))
    if len(sys.argv) > 2:
        json.dump(dict(P, note="Upside model (app/upside.py), fitted by research/boom_fit.py on this season's graded "
                                "games; see 'fit' for the held-out checks.", fit=report), open(sys.argv[2], "w"), indent=1)
