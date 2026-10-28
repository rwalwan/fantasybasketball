"""Expert repository, part 1: projection sources graded against real results.

Every run logs each source's projection for games that haven't tipped (the latest pre-tip value wins).
When a game's stats are in, each source's error is added to its record and the game leaves the log.
Weights for the blended projection are inverse mean-squared-error, shrunk toward equal weights until a
source has enough graded games — so a source earns influence only by being right.

State (on the `state` branch):
  data/state/projlog_<season>.json   {"<date>|<pid>": {"rotowire": 31.2, "model": 28.4}}
  data/state/expert_scores.json      {"<source>": {"n": 812, "sae": 7920.1, "sse": 101234.5, "bias": -310.2,
                                                    "weekly": {"1": {"n": 90, "sae": 870.2}}}}
"""
import datetime as dt
import json
import os

STATE = os.path.join(os.path.dirname(__file__), "..", "data", "state")
SCORES = "expert_scores_v2.json"   # v1 graded in-progress games (biased ~-12 FP); started over clean
SHRINK_N = 300          # graded games before a source's own accuracy fully drives its weight


def _load(name, dflt):
    try:
        return json.load(open(os.path.join(STATE, name)))
    except Exception:
        return dflt


def _save(name, obj):
    os.makedirs(STATE, exist_ok=True)
    json.dump(obj, open(os.path.join(STATE, name), "w"), separators=(",", ":"))


def source_projections(book, pid, date):
    out = {}
    rw = book.proj.get((pid, date))
    if rw:
        out["rotowire"] = round(rw, 1)
    out["model"] = round(book.baseline(pid), 1)
    out["blend"] = round(book.game_mu(pid, date), 1)             # what the engine actually used
    f = getattr(book, "ctx", {}).get((pid, date))
    if f:
        out["ctx"] = round(book.baseline(pid) * f, 1)        # model x matchup context (memory.py)
    return out


def update(book, season, week, tips, now=None, w=None):
    """Log projections for untipped games this week; grade finished ones. Returns the scores table."""
    now = now or dt.datetime.now(dt.timezone.utc)
    log = _load(f"projlog_{season}.json", {})
    scores = _load(SCORES, {})
    book.w = w or weights(scores)                # log the blend with today's weights
    ratios = _load(RATIOS, {})
    done = _load(f"projlog_done_{season}.json", {})

    # 1) log: every projected game for a player who has a scheduled game and hasn't tipped
    for (pid, date) in list(book.proj):
        team = book.team(pid)
        tip = tips.get((date, team))
        if not tip or dt.datetime.fromisoformat(tip.replace("Z", "+00:00")) <= now:
            continue
        log[f"{date}|{pid}"] = source_projections(book, pid, date)

    # 2) grade: only FINAL games (grading a live stat line scored halftime numbers as misses). A final game with
    #    no stat line is a DNP: projections are "if he plays", so drop it once the stats have had a day to land.
    played = {(pid, g[0]): g[1] for pid in book.games for g in book.done(pid)}
    for key in list(log):
        date, pid = key.split("|")
        actual = played.get((pid, date))
        if actual is None:
            if date < (now.date() - dt.timedelta(days=2)).isoformat():
                del log[key]
            continue
        b = log[key].get("blend")
        if b and b > 3:
            # actual / what we projected, by volatility tier: calibrates the lock-in spread curves (export_quantiles)
            r = ratios.setdefault(tier_of(book.baseline(pid)), [])
            r.append(round(actual / b, 3))
            del r[:-RATIO_KEEP]
        for src, proj in log[key].items():
            s = scores.setdefault(src, {"n": 0, "sae": 0.0, "sse": 0.0, "bias": 0.0, "weekly": {}})
            err = actual - proj
            s["n"] += 1
            s["sae"] += abs(err)
            s["sse"] += err * err
            s["bias"] += err
            w = s["weekly"].setdefault(str(week), {"n": 0, "sae": 0.0})
            w["n"] += 1
            w["sae"] += abs(err)
        done[key] = log.pop(key)
    # graded entries stay 4 more days so the memory store can attach them once the schedule marks the game complete
    cutoff = (now.date() - dt.timedelta(days=4)).isoformat()
    _save(f"projlog_done_{season}.json", {k: v for k, v in done.items() if k.split("|")[0] >= cutoff})
    _save(f"projlog_{season}.json", log)
    _save(SCORES, scores)
    _save(RATIOS, ratios)
    return scores


TIER_MAX = [18, 26, 34, 42, None]          # must match app/data/game_ratio_quantiles.json tiers
RATIOS, RATIO_KEEP, CAL_N = "proj_ratios.json", 6000, 600


def tier_of(base):
    for i, m in enumerate(TIER_MAX):
        if m is None or base <= m:
            return str(i)
    return str(len(TIER_MAX) - 1)


def calibrated_quantiles(hist):
    """Historical tier curves, blended toward OUR projection errors as they accumulate: weight n/(n+600).
    Shape only (rescaled to mean 1): bias belongs to the projection weights, not to the spread."""
    import numpy as np
    ratios = _load(RATIOS, {})
    out = dict(hist, tiers=[])
    probs = (np.arange(100) + 0.5) / 100
    for i, t in enumerate(hist.get("tiers", [])):
        r = np.array(ratios.get(str(i), []), dtype=float)
        q = np.array(t["quantiles"])
        a = len(r) / (len(r) + CAL_N) if len(r) >= 50 else 0.0
        if a:
            e = np.quantile(np.clip(r, 0, 6), probs)
            e = e / max(e.mean(), 1e-6)
            q = a * e + (1 - a) * q
            q = q / q.mean()
        out["tiers"].append(dict(t, quantiles=[round(float(x), 4) for x in q], calibrated_n=int(len(r)), own_weight=round(a, 3)))
    return out


def weights(scores):
    """Inverse-MSE weights, shrunk toward equal until SHRINK_N graded games."""
    srcs = ["rotowire", "model", "ctx"]
    inv = {}
    for s in srcs:
        r = scores.get(s)
        if not r or r["n"] == 0:
            inv[s] = None
            continue
        inv[s] = 1.0 / max(r["sse"] / r["n"], 1e-6)
    known = [v for v in inv.values() if v]
    if not known:
        return {s: 1 / len(srcs) for s in srcs}
    mean_inv = sum(known) / len(known)
    shrunk = {}
    for s in srcs:
        n = (scores.get(s) or {}).get("n", 0)
        a = min(1.0, n / SHRINK_N)
        shrunk[s] = a * (inv[s] or mean_inv) + (1 - a) * mean_inv
    tot = sum(shrunk.values())
    return {s: round(v / tot, 3) for s, v in shrunk.items()}


STACK_MIN_N = 200        # graded games with all three projections before fitted weights are used
SCALE_SHRINK = 500       # games before the mean-bias correction counts fully


def _fit_simplex(y, X, step=0.02):
    """Non-negative weights summing to 1 that minimize the blend's squared error (grid over the simplex: three
    sources, so this is exact to the grid step and needs no solver)."""
    import numpy as np
    g = np.arange(0, 1 + 1e-9, step)
    W = np.array([(a, b, 1 - a - b) for a in g for b in g if a + b <= 1 + 1e-9])
    err = ((y[None, :] - W @ X.T) ** 2).mean(axis=1)
    return W[int(err.argmin())]


def stack_weights(rows):
    """Blend weights from graded games: rows = [date, actual, rotowire, model, ctx].
    Inverse-MSE weighting assumed independent errors, but model and ctx are near-duplicates (error correlation
    0.98), so together they outvoted the best source. Here the weights minimize the BLEND's error directly, and
    are kept only if they beat RotoWire alone on days held out of the fit (leave-one-day-out); otherwise
    RotoWire alone. A shrunk multiplicative scale corrects the blend's average bias."""
    import numpy as np
    n = len(rows)
    rw_only = {"rotowire": 1.0, "model": 0.0, "ctx": 0.0, "scale": 1.0, "n": n}
    if n < STACK_MIN_N:
        return dict(rw_only, basis="too few graded games")
    dates = np.array([r[0] for r in rows])
    y = np.array([r[1] for r in rows], float)
    X = np.array([r[2:5] for r in rows], float)
    oos_stack = oos_rw = 0.0
    days = sorted(set(dates))
    if len(days) >= 2:
        for d in days:
            tr, te = dates != d, dates == d
            w = _fit_simplex(y[tr], X[tr])
            oos_stack += np.abs(y[te] - X[te] @ w).sum()
            oos_rw += np.abs(y[te] - X[te, 0]).sum()
    if len(days) < 2 or oos_stack >= oos_rw:
        w = np.array([1.0, 0.0, 0.0])
        basis = "RotoWire alone (a fitted blend did not beat it on held-out days)"
    else:
        w = _fit_simplex(y, X)
        basis = f"fitted blend (held-out MAE {oos_stack / n:.2f} vs RotoWire {oos_rw / n:.2f})"
    pred = X @ w
    raw = y.sum() / max(pred.sum(), 1e-6)
    scale = 1 + (raw - 1) * n / (n + SCALE_SHRINK)
    return {"rotowire": round(float(w[0]), 3), "model": round(float(w[1]), 3), "ctx": round(float(w[2]), 3),
            "scale": round(float(scale), 4), "n": n, "basis": basis}


def graded_rows(con, season):
    return [list(r) for r in con.execute(
        "SELECT date, fp, proj_rw, proj_model, proj_ctx FROM games WHERE season=? AND proj_rw IS NOT NULL "
        "AND proj_model IS NOT NULL AND proj_ctx IS NOT NULL ORDER BY date", (season,))]


def table(scores, w):
    rows = []
    for src, r in scores.items():
        n = r["n"] or 1
        rows.append({"source": src, "games": r["n"], "mae": round(r["sae"] / n, 2), "rmse": round((r["sse"] / n) ** 0.5, 2),
                     "bias": round(r["bias"] / n, 2), "weight": w.get(src),
                     "weekly": {k: round(v["sae"] / max(v["n"], 1), 2) for k, v in sorted(r["weekly"].items(), key=lambda x: int(x[0]))}})
    rows.sort(key=lambda x: x["mae"])
    return rows
