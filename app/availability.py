"""Will he play? Per-game play probabilities for every injured/questionable player, through the end of the season.

Data, not guesses (app/data/availability_model.json):
  * Next game, by official designation: Probable 86.6%, Questionable 48.3%, Doubtful 4.2%, Out 0%
    (first official-report designation vs. minutes played, 2,007 player-games, 2026).
  * After that, the empirical return hazard: P(plays next game | has missed k straight), from 2021-24 box scores
    of top-150 players: 54% after 1 miss, 32% after 2, 27% after 3, ... about 15% per game after 9+.
  * A reported timeline beats both: if the latest injury news says "out 2-4 weeks", he is out until the early
    end, his return is spread evenly over the games in the window, and he is back after it. "At least a week"
    (no upper end) switches to the empirical hazard once the minimum has passed.
  * Once back: the normal 92% healthy play rate (rest days, minor knocks), b2b handled by the engine.

Every prediction for a next game is logged and graded when the game is final (data/state/availability_log.json),
so the designation and hazard numbers can be checked against this league's own players as the season runs.
"""
import datetime as dt
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
STATE = os.path.join(ROOT, "data", "state")
M = json.load(open(os.path.join(os.path.dirname(__file__), "data", "availability_model.json")))
INJ = {"Out", "IR", "Suspended", "Doubtful", "Questionable", "GTD", "DTD", "Day-To-Day", "Probable", "PUP", "NA"}
OUTISH = {"Out", "IR", "Suspended", "PUP", "NA"}
# Sleeper's informal labels map to the closest official designation we have data for
DESIG = {"Probable": "Probable", "Questionable": "Questionable", "GTD": "Questionable", "DTD": "Questionable",
         "Day-To-Day": "Questionable", "Doubtful": "Doubtful"}


def hazard(k):
    """P(plays the next game | has missed k straight games), k >= 1."""
    if k <= 8:
        return M["by_k"][k - 1]
    return M["k9_12"] if k <= 12 else M["k13_20"]


def _load(name, dflt):
    try:
        return json.load(open(os.path.join(STATE, name)))
    except Exception:
        return dflt


def build(book, meta, team_dates, today, is_final, pids):
    """{pid: {status, missed, timeline, basis, q: {date: prob}}} for injured players among `pids`."""
    timelines = _load("timelines.json", {})
    out = {}
    for pid in pids:
        m = meta.get(pid) or {}
        team, st = m.get("team"), m.get("injury_status")
        tl = timelines.get(pid)
        if not team:
            continue
        played = [g[0] for g in book.done(pid)]
        # a timeline only applies if he hasn't played since it was reported
        if tl and played and played[-1] >= tl["at"][:10]:
            tl = None
        if st not in INJ and not tl:
            continue
        dates = sorted(team_dates.get(team, {}))
        past = [d for d in dates if d < today and is_final(d, team)]
        last = played[-1] if played else None
        missed = len([d for d in past if last is None or d > last])
        # hurt before this season's games began (no games yet): count the absence from Sleeper's injury start date,
        # at the league's pace of 82 games per ~174 days, so a long-term injury isn't treated like a fresh one
        isd = m.get("injury_start_date")
        if last is None and isd and dates and isd < dates[0]:
            days_out = (dt.date.fromisoformat(today) - dt.date.fromisoformat(isd[:10])).days
            missed = max(missed, round(days_out * 82 / 174))
        upcoming = [d for d in dates if d >= today and not is_final(d, team)]
        q, basis = {}, None
        if tl and (tl.get("out_min_days") is not None):
            t0 = dt.date.fromisoformat(tl["at"][:10])
            e0 = (t0 + dt.timedelta(days=int(tl["out_min_days"]))).isoformat()
            e1 = (t0 + dt.timedelta(days=int(tl["out_max_days"]))).isoformat() if tl.get("out_max_days") is not None else None
            window = [d for d in upcoming if e0 <= d <= e1] if e1 else []
            S, k = 1.0, missed
            for d in upcoming:
                if d < e0:
                    back = 0.0
                    k += 1
                elif e1 and d <= e1:
                    i = window.index(d) + 1
                    back = i / len(window)                     # return spread evenly across the reported window
                elif e1:
                    back = 1.0
                else:                                          # minimum passed, no upper end: empirical hazard
                    r = hazard(max(1, k))
                    S *= 1 - r
                    back = 1 - S
                    k += 1
                q[d] = round(back * M["healthy"], 3)
            basis = f"reported timeline ({tl.get('source')}, {tl['at'][:10]}): {tl.get('summary') or ''}".strip()
        else:
            S, k = 1.0, missed
            for j, d in enumerate(upcoming):
                if j == 0 and st in DESIG:
                    p = M["designation"][DESIG[st]]
                    q[d] = round(p, 3)
                    S = 1 - p
                    k = max(k, 0) + 1
                    continue
                if j == 0 and st in OUTISH:
                    r = 0.0
                else:
                    r = hazard(max(1, k))
                S *= 1 - r                                     # S = still out
                q[d] = round((1 - S) * M["healthy"], 3)
                k += 1
            basis = (f"{st}: next game {round(M['designation'].get(DESIG.get(st, ''), 0) * 100) if st in DESIG else 0}% by designation, "
                     f"then the historical return rate after {missed} missed game(s)") if st in DESIG or st in OUTISH else None
        if q:
            out[pid] = {"status": st, "missed": missed, "timeline": tl, "basis": basis, "q": q}
    return out


def log_and_grade(avail, book, is_final, today):
    """Log each player's next-game probability; grade logged games once final. Returns calibration by bucket."""
    log = _load("availability_log.json", {"open": {}, "graded": []})
    for pid, a in avail.items():
        nxt = min(a["q"]) if a["q"] else None
        if nxt:
            log["open"][f"{nxt}|{pid}"] = {"q": a["q"][nxt], "status": a["status"], "missed": a["missed"],
                                           "timeline": bool(a["timeline"])}
    for key in list(log["open"]):
        date, pid = key.split("|")
        team = book.team(pid)
        if not is_final(date, team):
            continue
        rec = log["open"].pop(key)
        rec.update(date=date, pid=pid, played=any(g[0] == date for g in book.done(pid)))
        log["graded"].append(rec)
    log["graded"] = log["graded"][-3000:]
    buckets = {}
    for r in log["graded"]:
        b = f"{int(min(r['q'], 0.999) * 5) * 20}-{int(min(r['q'], 0.999) * 5) * 20 + 20}%"
        x = buckets.setdefault(b, {"n": 0, "pred": 0.0, "played": 0})
        x["n"] += 1
        x["pred"] += r["q"]
        x["played"] += r["played"]
    log["calibration"] = {b: {"n": x["n"], "predicted": round(x["pred"] / x["n"], 3), "actual": round(x["played"] / x["n"], 3)}
                          for b, x in sorted(buckets.items())}
    os.makedirs(STATE, exist_ok=True)
    json.dump(log, open(os.path.join(STATE, "availability_log.json"), "w"))
    return log["calibration"]
