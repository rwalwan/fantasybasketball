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
    return out


def update(book, season, week, tips, now=None):
    """Log projections for untipped games this week; grade finished ones. Returns the scores table."""
    now = now or dt.datetime.now(dt.timezone.utc)
    log = _load(f"projlog_{season}.json", {})
    scores = _load("expert_scores.json", {})

    # 1) log: every projected game for a player who has a scheduled game and hasn't tipped
    for (pid, date) in list(book.proj):
        team = book.team(pid)
        tip = tips.get((date, team))
        if not tip or dt.datetime.fromisoformat(tip.replace("Z", "+00:00")) <= now:
            continue
        log[f"{date}|{pid}"] = source_projections(book, pid, date)

    # 2) grade: entries whose game now has a stat line (or is 2+ days old with none: DNP, drop it)
    played = {(pid, g[0]): g[1] for pid, gs in book.games.items() for g in gs}
    today = now.date().isoformat()
    for key in list(log):
        date, pid = key.split("|")
        actual = played.get((pid, date))
        if actual is None:
            if date < (now.date() - dt.timedelta(days=2)).isoformat():
                del log[key]
            continue
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
        del log[key]
    _ = today
    _save(f"projlog_{season}.json", log)
    _save("expert_scores.json", scores)
    return scores


def weights(scores):
    """Inverse-MSE weights, shrunk toward equal until SHRINK_N graded games."""
    srcs = ["rotowire", "model"]
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


def table(scores, w):
    rows = []
    for src, r in scores.items():
        n = r["n"] or 1
        rows.append({"source": src, "games": r["n"], "mae": round(r["sae"] / n, 2), "rmse": round((r["sse"] / n) ** 0.5, 2),
                     "bias": round(r["bias"] / n, 2), "weight": w.get(src),
                     "weekly": {k: round(v["sae"] / max(v["n"], 1), 2) for k, v in sorted(r["weekly"].items(), key=lambda x: int(x[0]))}})
    rows.sort(key=lambda x: x["mae"])
    return rows
