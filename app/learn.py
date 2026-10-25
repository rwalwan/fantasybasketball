"""Decision log + grading: what the tool told you, what you did, and how it turned out.

Runs after tools/moves.mjs each cycle:
  record()  keeps the latest pre-deadline version of every lock/pass call and lineup move
  grade()   once a week is final: compares each call with the slot's final points (Sleeper
            starters_points) and the counterfactual, and notes whether the call was followed
  export    site/static/learning.json: weekly scorecards, graded calls, running totals
"""
import datetime as dt
import json
import os
import sys

from . import memory, sleeper

ROOT = os.path.join(os.path.dirname(__file__), "..")
LEAGUE_ID = os.environ.get("FBB_LEAGUE_ID", "1400915575915491328")
USER_ID = os.environ.get("FBB_USER_ID", "1388708038000533504")


def _future(t, now):
    return t and dt.datetime.fromisoformat(t.replace("Z", "+00:00")) > now


def record(con, plan, now):
    week = plan.get("week")
    for idx, s in enumerate(plan.get("slots", [])):
        if s["action"] in ("lock", "pass", "confirm", "keep") and s.get("score") is not None:
            dl = (s.get("deadline") or {}).get("tip")
            if dl and not _future(dl, now):
                continue                                    # keep the last call made before the deadline
            m = s.get("matchup") or {}
            call = "lock" if s["action"] in ("lock", "confirm", "keep") else "pass"
            con.execute("""INSERT INTO decisions(week,date,slot,idx,pid,kind,score,bar,ev_call,mx_call,p_lock,p_pass,deadline,made_at,extra)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(week,idx,pid,kind,date) DO UPDATE SET score=excluded.score, bar=excluded.bar,
                ev_call=excluded.ev_call, mx_call=excluded.mx_call, p_lock=excluded.p_lock, p_pass=excluded.p_pass, deadline=excluded.deadline,
                made_at=excluded.made_at, extra=excluded.extra""",
                (week, s.get("gameDate"), s["slot"], idx, s["pid"], "lock-call", s["score"], s.get("bar"), m.get("evCall") or call,
                 call, m.get("pLock"), m.get("pPass"), dl, now.isoformat(timespec="minutes"), json.dumps({"name": s["name"], "detail": s["detail"]})))
        td = s.get("today")
        if td and td.get("move") and _future(td.get("tip"), now):
            con.execute("""INSERT INTO decisions(week,date,slot,idx,pid,kind,score,deadline,made_at,extra) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(week,idx,pid,kind,date) DO UPDATE SET score=excluded.score, made_at=excluded.made_at, extra=excluded.extra""",
                (week, td["tip"][:10], s["slot"], idx, td["pid"], "move", td.get("mu"), td["tip"], now.isoformat(timespec="minutes"),
                 json.dumps({"name": td["name"], "replaces": s.get("pid"), "replaces_name": s.get("name")})))
    con.commit()


def grade(con, season, current_week, lineups_by_week):
    """Grade every ungraded decision from finished weeks."""
    weeks = [w for (w,) in con.execute("SELECT DISTINCT week FROM decisions WHERE regret IS NULL AND week < ?", (current_week,))]
    if not weeks:
        return 0
    rosters = sleeper.rosters(LEAGUE_ID)
    mine = next(r for r in rosters if r.get("owner_id") == USER_ID)
    fp = {}
    for pid, d, f in con.execute("SELECT pid, date, fp FROM games WHERE season=?", (season,)):
        fp[(pid, d)] = f
    n = 0
    for w in weeks:
        mu = next(m for m in sleeper.matchups(LEAGUE_ID, w) if m["roster_id"] == mine["roster_id"])
        starters, spts = mu.get("starters") or [], mu.get("starters_points") or []
        final_by_pid = {p: (spts[i] / 10 if i < len(spts) else None) for i, p in enumerate(starters)}
        for (idx, pid, kind, d, score, ev_call, mx_call, extra) in con.execute(
                "SELECT idx, pid, kind, date, score, ev_call, mx_call, extra FROM decisions WHERE week=? AND regret IS NULL", (w,)).fetchall():
            if kind == "lock-call":
                final = final_by_pid.get(pid)
                if final is None:
                    final = spts[idx] / 10 if idx < len(spts) else None
                later = sorted((dd, f) for (p, dd), f in fp.items() if p == pid and dd > (d or ""))
                cf = later[0][1] if later else 0.0                 # what waiting on him would have produced
                if mx_call == "lock":
                    followed = int(final is not None and abs(final - score) < 0.05)
                    regret = cf - score                            # > 0: locking cost points
                else:
                    followed = int(final is not None and abs(final - score) >= 0.05)
                    regret = score - (final if final is not None else cf)   # > 0: waiting cost points
                con.execute("UPDATE decisions SET final=?, cf=?, regret=?, followed=? WHERE week=? AND idx=? AND pid=? AND kind=? AND date=?",
                            (final, cf, round(regret, 1), followed, w, idx, pid, kind, d))
            elif kind == "move":
                x = json.loads(extra or "{}")
                snap = (lineups_by_week.get(w) or {}).get(f"{d}|{pid}") or {}
                followed = int(snap.get("slot") is not None)
                mine_fp = fp.get((pid, d), 0.0)
                theirs = fp.get((x.get("replaces"), d), 0.0)
                con.execute("UPDATE decisions SET final=?, cf=?, regret=?, followed=? WHERE week=? AND idx=? AND pid=? AND kind=? AND date=?",
                            (mine_fp, theirs, round(theirs - mine_fp, 1), followed, w, idx, pid, kind, d))
            n += 1
    con.commit()
    return n


def export(con):
    rows = con.execute("""SELECT week, date, slot, pid, kind, score, bar, ev_call, mx_call, p_lock, p_pass, final, cf, regret, followed, extra
                          FROM decisions ORDER BY week DESC, date DESC""").fetchall()
    weeks = {}
    graded = []
    for (w, d, slot, pid, kind, score, bar, evc, mxc, pl, pp, final, cf, regret, fol, extra) in rows:
        x = json.loads(extra or "{}")
        wk = weeks.setdefault(w, {"week": w, "calls": 0, "graded": 0, "followed": 0, "good": 0, "points_lost": 0.0, "points_saved": 0.0})
        wk["calls"] += 1
        if regret is None:
            continue
        wk["graded"] += 1
        wk["followed"] += fol or 0
        if regret <= 0:
            wk["good"] += 1
            wk["points_saved"] += -regret
        else:
            wk["points_lost"] += regret
        graded.append({"week": w, "date": d, "slot": slot, "kind": kind, "name": x.get("name"), "call": mxc or "move",
                       "score": score, "final": final, "cf": cf, "regret": regret, "followed": bool(fol),
                       "replaces": x.get("replaces_name")})
    for wk in weeks.values():
        wk["points_lost"] = round(wk["points_lost"], 1)
        wk["points_saved"] = round(wk["points_saved"], 1)
    return {"weeks": sorted(weeks.values(), key=lambda x: -x["week"]), "graded": graded[:80]}


def main():
    path = os.path.join(ROOT, "site", "static", "plan.json")
    try:
        plan = json.load(open(path))
    except Exception as e:
        print("no plan.json:", e)
        return
    con = memory.connect()
    now = dt.datetime.now(dt.timezone.utc)
    record(con, plan, now)
    try:
        lg = sleeper.league(LEAGUE_ID)
        season = lg["season"]
        state = os.path.join(ROOT, "data", "state")
        lineups = {}
        for f in os.listdir(state):
            if f.startswith(f"lineups_{season}_w") and f.endswith(".json"):
                lineups[int(f.split("_w")[1].split(".")[0])] = json.load(open(os.path.join(state, f)))
        print("graded decisions:", grade(con, season, plan.get("week"), lineups))
    except Exception as e:
        print("grading failed:", e, file=sys.stderr)
    out = export(con)
    out["outlook"] = plan.get("outlook")
    with open(os.path.join(ROOT, "site", "static", "learning.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    con.close()


if __name__ == "__main__":
    main()
