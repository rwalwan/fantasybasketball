"""What other Lock-In leagues show about lock decisions (finished weeks of verified Lock-In leagues).

Only LINEUP-CHECKED player-weeks count (review 2, finding 3): every one of the team's game days that week has a
morning snapshot of that league (daily job, before tip-offs), so we know which games the player was in that
manager's lineup for. Week 1 had no snapshots and is reported as context only.
For each such starter-week:
  * his games = the team's scheduled games he was in the lineup for; a scheduled game with no stat row is a DNP (0)
  * the manager's result = his final slot score, 0 included (a final-game DNP is a real cost of waiting)
  * the engine's rule replayed on the same games with the production bar: RotoWire per-game projection x the
    current stacking scale, the volatility tier for that projection, the healthy play curve and the b2b factor
    (not modeled: rotation through the bench, injury designations)
  * decision points: at each lineup game before the kept one, score / his own continuation (the same quantity the
    opponent model reads: site/engine.js humanLockRate) and whether the manager locked
Confidence intervals resample NBA player-weeks (every league shares the same game results).
"""
import datetime as dt
import json
import os
import random

import numpy as np

from .availability import healthy_at
from .leagues import fantasy_points
from .model import B2B_FACTOR

BINS = [0, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5, 99]
QS = json.load(open(os.path.join(os.path.dirname(__file__), "data", "game_ratio_quantiles.json")))


def tier_q(mu):
    for t in QS.get("tiers", []):
        if t.get("max") is None or mu <= t["max"]:
            return np.array(t["quantiles"])
    return np.array(QS["quantiles"])


def cont(games):
    """Production continuation value W over games [(mu, q)], same recursion as site/engine.js contStats."""
    W = 0.0
    for k in range(len(games) - 1, -1, -1):
        mu, q = games[k]
        W = q * mu if k == len(games) - 1 else q * float(np.mean(np.maximum(mu * tier_q(mu), W))) + (1 - q) * W
    return W


def bar(mus):
    """Single-player continuation with flat projections and the healthy curve (kept for tests/tools)."""
    return cont([(m, healthy_at(k + 1)) for k, m in enumerate(mus)])


def replay(scores, games, scale=1.0):
    """Points the engine's rule ends with on these actual scores (0 = DNP); games[i] = (mu, q) for game i."""
    n = len(scores)
    for i, s in enumerate(scores):
        if i == n - 1:
            return s
        if s > 0 and s >= scale * cont(games[i + 1:]):
            return s
    return 0.0


def _b2b(d, dates):
    return (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat() in dates


def study(con, weeks, stats_by_week, prior_rows, team_dates=None, proj_by_week=None, proj_scale=1.0, boot=400, seed=7):
    """team_dates: {week: {team: [dates]}} from the schedule; proj_by_week: {week: Sleeper projection rows}."""
    team_dates, proj_by_week = team_dates or {}, proj_by_week or {}
    prior = {}
    for r in prior_rows or []:
        st, gp = r.get("stats") or {}, (r.get("stats") or {}).get("gp") or 0
        if gp >= 10:
            prior[r["player_id"]] = {k: (v or 0) / gp for k, v in st.items() if isinstance(v, (int, float))}
    played, team_of = {}, {}
    for w in weeks:
        for r in stats_by_week.get(w, []):
            if r.get("date") and r.get("stats"):
                played[(w, r["player_id"], r["date"])] = r["stats"]
                if r.get("team"):
                    team_of[(w, r["player_id"])] = r["team"]
    proj = {(w, r["player_id"], r["date"]): r["stats"] for w in weeks for r in proj_by_week.get(w, []) if r.get("date") and r.get("stats")}

    points, outcomes, seqs, unchecked = [], [], {}, 0
    leagues = con.execute("SELECT league, scoring FROM league WHERE verified=1").fetchall()
    for lid, scoring in leagues:
        sc = json.loads(scoring)
        for w in weeks:
            morning = {(d, r): set(json.loads(s_)) for d, r, s_ in con.execute(
                "SELECT day, roster, starters FROM snap WHERE league=? AND week=? AND final=0", (lid, w))}
            days_seen = {d for d, _ in morning}
            for roster, st_json, sp_json in con.execute("SELECT roster, starters, starters_points FROM snap WHERE league=? AND week=? AND final=1", (lid, w)):
                for p, s in zip(json.loads(st_json), json.loads(sp_json)):
                    s = (s or 0) / 10                     # Sleeper stores NBA points x10
                    team = team_of.get((w, p))
                    dates = sorted((team_dates.get(w) or {}).get(team) or [])
                    if not team or len(dates) < 2:
                        continue
                    if not all(d in days_seen for d in dates):
                        unchecked += 1                    # no lineup record for some game day: can't compare fairly
                        continue
                    lineup = [d for d in dates if p in morning.get((d, roster), set())]
                    if not lineup:
                        continue
                    fp = [fantasy_points(played[(w, p, d)], sc) if (w, p, d) in played else 0.0 for d in lineup]
                    base = fantasy_points(prior[p], sc) if p in prior else 0
                    mus = [proj_scale * fantasy_points(proj[(w, p, d)], sc) if (w, p, d) in proj else base for d in lineup]
                    if min(mus) <= 0:
                        continue
                    allset = set(dates)
                    games = [(m, healthy_at(k + 1) * (B2B_FACTOR if _b2b(d, allset) else 1)) for k, (m, d) in enumerate(zip(mus, lineup))]
                    mu = sum(mus) / len(mus)
                    key = (w, p)
                    outcomes.append(((replay(fp, games) - s) / mu, key))     # % of his projection: leagues score differently
                    seqs[(w, p, json.dumps(sc, sort_keys=True), tuple(lineup))] = (fp, games, mu, key)
                    if s <= 0 or len(fp) < 2:
                        continue
                    idx = next((i for i, x in enumerate(fp) if abs(x - s) < 0.06), None)
                    if idx is None:
                        continue
                    for i in range(min(idx, len(fp) - 2) + 1):
                        if fp[i] <= 0:
                            continue                      # a DNP isn't a lock decision
                        b = cont(games[i + 1:])
                        points.append((fp[i] / b if b else 0, len(fp) - 1 - i, int(i == idx)))

    out = {"leagues": len(leagues), "weeks": list(weeks), "decision_points": len(points), "starter_weeks": len(outcomes),
           "unchecked_starter_weeks": unchecked, "player_weeks": len({k for _, k in outcomes}),
           "method": "lineup-checked weeks only; DNPs count as 0; production bar (RotoWire x scale, tiers, b2b); CI by NBA player-week"}
    out["eligible_points"] = len(points)
    if not points and not outcomes:
        out["opponent_model_ready"] = False
        return out

    def table(pts):
        rows = []
        for lo, hi in zip(BINS, BINS[1:]):
            sel = [a for r, k, a in pts if lo <= r < hi]
            if sel:
                rows.append({"score_vs_bar": f"{lo:.2f}-{hi:.2f}" if hi < 99 else f"{lo:.2f}+", "lo": lo, "hi": hi, "n": len(sel),
                             "lock_rate": round(sum(sel) / len(sel), 3)})
        return rows
    # lock rate by score / own continuation, lineup games only: the opponent model uses it once every bin has 50+
    out["lock_rate_eligible"] = table(points)
    out["opponent_model_ready"] = len(out["lock_rate_eligible"]) == len(BINS) - 1 and all(r["n"] >= 50 for r in out["lock_rate_eligible"])
    if not outcomes:
        return out
    rng = random.Random(seed)
    by_pw = {}
    for d, k in outcomes:
        by_pw.setdefault(k, []).append(d)
    keys = list(by_pw)

    def boot_mean(f):
        vals = []
        for _ in range(boot):
            xs = [x for k in (rng.choice(keys) for _ in keys) for x in f(k)]
            vals.append(sum(xs) / len(xs) if xs else 0)
        return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]
    diffs = [d for d, _ in outcomes]
    ci = boot_mean(lambda k: by_pw[k])
    out["engine_minus_manager"] = {"mean_pct_of_proj": round(100 * sum(diffs) / len(diffs), 2), "ci95": [round(100 * x, 2) for x in ci],
                                   "share_engine_better": round(sum(d > 0 for d in diffs) / len(diffs), 3),
                                   "share_same": round(sum(abs(d) < 0.06 for d in diffs) / len(diffs), 3)}
    # bar scale: replay every unique lineup sequence with the bar x scale
    scales = [0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15]
    seq_by_pw = {}
    for fp, games, mu, k in seqs.values():
        seq_by_pw.setdefault(k, []).append((fp, games, mu))
    allseq = [x for v in seq_by_pw.values() for x in v]
    res = []
    for sc_ in scales:
        vals = [replay(fp, g, sc_) / mu for fp, g, mu in allseq]
        res.append({"scale": sc_, "mean_pct_of_proj": round(100 * sum(vals) / len(vals), 2)})
    base = next(r["mean_pct_of_proj"] for r in res if r["scale"] == 1.0)
    for r in res:
        r["vs_current"] = round(r["mean_pct_of_proj"] - base, 2)
    best = max(res, key=lambda r: r["mean_pct_of_proj"])
    keys = list(seq_by_pw)
    best["ci95_vs_current"] = [round(100 * x, 2) for x in boot_mean(lambda k: [(replay(fp, g, best["scale"]) - replay(fp, g, 1.0)) / mu for fp, g, mu in seq_by_pw.get(k, [])])]
    out["bar_scale"] = res
    out["best_scale"] = best
    return out
