"""Entry point: python -m app.run  ->  writes site/data.json (the dashboard reads it)."""
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

import requests

from . import espn, sleeper
from .alerts import send_alerts
from .engine import WeekPlan, team_game_dates, week_dates
from .lineups import LineupTracker
from .model import PlayerBook

LEAGUE_ID = os.environ.get("FBB_LEAGUE_ID", "1400915575915491328")
USER_ID = os.environ.get("FBB_USER_ID", "1388708038000533504")
ROOT = os.path.join(os.path.dirname(__file__), "..")


def main():
    today = os.environ.get("FBB_TODAY") or dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    lg = sleeper.league(LEAGUE_ID)
    season = lg["season"]
    sched = sleeper.schedule(season)
    week = int(os.environ.get("FBB_WEEK") or current_week(sched, today))
    meta = sleeper.players()
    rosters = sleeper.rosters(LEAGUE_ID)
    users = {u["user_id"]: u.get("display_name") for u in sleeper.users(LEAGUE_ID)}
    mine = next(r for r in rosters if r.get("owner_id") == USER_ID)
    mus = sleeper.matchups(LEAGUE_ID, week)
    my_m = next(m for m in mus if m["roster_id"] == mine["roster_id"])
    opp_m = next((m for m in mus if m["matchup_id"] == my_m["matchup_id"] and m["roster_id"] != mine["roster_id"]), None)

    book = PlayerBook(lg["scoring_settings"], meta)
    for w in range(1, week + 1):
        book.add_stat_rows(sleeper.week_stats(season, w, final=w < week))
    book.add_projections(sleeper.week_projections(season, week))
    try:
        book.add_prior_season(sleeper.season_totals(str(int(season) - 1)))
    except Exception as e:  # prior season is a nice-to-have
        print("prior season unavailable:", e, file=sys.stderr)

    # record who is starting right now for every game that hasn't tipped (lock eligibility)
    days = week_dates(sched, week)
    tips = espn.tip_times([d for d in days if d >= (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()])
    tg = team_game_dates(sched)
    slots = [s for s in lg["roster_positions"] if s not in ("BN", "IR")]
    tracker = LineupTracker(season, week)
    backend = fetch_backend(season, week)
    tracker.snaps.update(backend.get("lineups") or {})          # minute-level records win
    tracker.overrides.update(backend.get("elig") or {})
    tracker.record(slots, my_m.get("starters") or [], mine.get("players") or [], book.team,
                   lambda team: sorted(d for d in tg.get(team, {}) if d in days), tips)

    manual = {**load_manual_locks(week), **(backend.get("locks") or {})}
    wp = WeekPlan(book, sched, week, today, lg["roster_positions"], mine, my_m, rosters, tracker.eligible, tips)
    plan = wp.build(manual)
    waivers, worst = wp.waivers(sleeper.trending_adds())
    try:
        print("alerts sent:", send_alerts(plan, waivers, book, tips, today))
    except Exception as e:
        print("alerts failed:", e, file=sys.stderr)

    opp_owner = next((r.get("owner_id") for r in rosters if opp_m and r["roster_id"] == opp_m["roster_id"]), None)
    out = dict(generated=dt.datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%a %b %d, %I:%M %p PT"),
               league=lg["name"], week=week, today=today, plan=plan, waivers=waivers, worst_bench=worst,
               score=dict(me=(my_m.get("points") or 0) / 10, opp=((opp_m or {}).get("points") or 0) / 10,
                          opp_name=users.get(opp_owner, "Opponent")),
               faab_left=lg["settings"].get("waiver_budget", 100) - (mine.get("settings") or {}).get("waiver_budget_used", 0))
    os.makedirs(os.path.join(ROOT, "site"), exist_ok=True)
    export_static(book, season, week, meta, lg)
    with open(os.path.join(ROOT, "site", "data.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"week {week}, {len(plan['slots'])} slots, {plan['unlocked']} unlocked, {len(waivers)} waiver targets")
    return out


def export_static(book, season, week, meta, lg):
    """Slow-changing inputs for the live browser app (site/static/*.json)."""
    out_dir = os.path.join(ROOT, "site", "static")
    os.makedirs(out_dir, exist_ok=True)
    gl = {pid: [[g[0], g[1], round(g[2] or 0, 1), g[3]] for g in gs] for pid, gs in book.games.items()}
    keep = {pid for pid in gl} | set(book.prior) | {p for (p, _d) in book.proj}
    players = {}
    for pid in keep:
        m = meta.get(pid) or {}
        if not m.get("team"):
            continue
        players[pid] = [f"{m.get('first_name', '')} {m.get('last_name', '')}".strip(), m.get("team"),
                        m.get("fantasy_positions") or [], m.get("injury_status")]
    with open(os.path.join(os.path.dirname(__file__), "data", "game_ratio_quantiles.json")) as f:
        quantiles = json.load(f)
    for name, obj in (("quantiles", quantiles),
                      ("gamelog", dict(season=season, week=week, games=gl)),
                      ("priors", {p: round(v, 1) for p, v in book.prior.items()}),
                      ("players", players),
                      ("league", dict(scoring=lg["scoring_settings"], roster_positions=lg["roster_positions"]))):
        with open(os.path.join(out_dir, f"{name}.json"), "w") as f:
            json.dump(obj, f, separators=(",", ":"))


def current_week(sched, today):
    weeks = sorted({(g["date"], g["week"]) for g in sched if g.get("week")})
    past = [w for d, w in weeks if d <= today]
    return past[-1] if past else weeks[0][1]


def fetch_backend(season, week):
    url = os.environ.get("WORKER_URL")
    if not url:
        return {}
    try:
        r = requests.get(f"{url.rstrip('/')}/state", params={"season": season, "week": week}, timeout=20)
        return r.json() if r.ok else {}
    except Exception as e:
        print("backend unavailable:", e, file=sys.stderr)
        return {}


def load_manual_locks(week):
    path = os.path.join(ROOT, "data", "state", f"locks_w{week}.json")
    return json.load(open(path)) if os.path.exists(path) else {}


if __name__ == "__main__":
    main()
