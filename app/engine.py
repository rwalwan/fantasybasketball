"""Schedule helpers shared by the job, and the free-agent watch list (the week plan itself is site/engine.js)."""
import datetime as dt



def week_dates(schedule, week):
    dates = sorted({g["date"] for g in schedule if g.get("week") == week})
    if not dates:
        return []
    start = dt.date.fromisoformat(dates[0])
    start -= dt.timedelta(days=start.weekday())          # Monday
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(7)]


def team_game_dates(schedule):
    out = {}
    for g in schedule:
        for side in ("home", "away"):
            t = (g.get(side) or {}).get("team")
            if t:
                out.setdefault(t, {})[g["date"]] = {"opp": (g.get("away" if side == "home" else "home") or {}).get("team", ""),
                                                   "home": side == "home", "status": g.get("status")}
    return out


def free_agent_watch(book, rostered, limit=25):
    """Unrostered players in a rotation (games or projections this season, 15+ FP/G, not Out), best first: the
    players whose news and expert takes are worth collecting. (The Python week plan that also lived here was a
    second copy of site/engine.js and was removed: review 2, F9 refinement.)"""
    out = []
    for pid, m in book.meta.items():
        if pid in rostered or not m.get("team") or m.get("active") is False or m.get("injury_status") in ("Out", "IR"):
            continue
        if not book.games.get(pid) and not any(k[0] == pid for k in book.proj):
            continue
        base = book.baseline(pid)
        if base >= 15:
            out.append({"pid": pid, "fpg": round(base, 1)})
    out.sort(key=lambda r: -r["fpg"])
    return out[:limit]
