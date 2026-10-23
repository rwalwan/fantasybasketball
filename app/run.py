"""Entry point: python -m app.run  ->  writes site/data.json (the dashboard reads it)."""
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

from . import sleeper
from .engine import WeekPlan
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

    manual = load_manual_locks(week)
    plan = WeekPlan(book, sched, week, today, lg["roster_positions"], mine, my_m, rosters).build(manual)
    waivers, worst = WeekPlan(book, sched, week, today, lg["roster_positions"], mine, my_m, rosters).waivers(sleeper.trending_adds())

    opp_owner = next((r.get("owner_id") for r in rosters if opp_m and r["roster_id"] == opp_m["roster_id"]), None)
    out = dict(generated=dt.datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%a %b %d, %I:%M %p PT"),
               league=lg["name"], week=week, today=today, plan=plan, waivers=waivers, worst_bench=worst,
               score=dict(me=(my_m.get("points") or 0) / 10, opp=((opp_m or {}).get("points") or 0) / 10,
                          opp_name=users.get(opp_owner, "Opponent")),
               faab_left=lg["settings"].get("waiver_budget", 100) - (mine.get("settings") or {}).get("waiver_budget_used", 0))
    os.makedirs(os.path.join(ROOT, "site"), exist_ok=True)
    with open(os.path.join(ROOT, "site", "data.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"week {week}, {len(plan['slots'])} slots, {plan['unlocked']} unlocked, {len(waivers)} waiver targets")
    return out


def current_week(sched, today):
    weeks = sorted({(g["date"], g["week"]) for g in sched if g.get("week")})
    past = [w for d, w in weeks if d <= today]
    return past[-1] if past else weeks[0][1]


def load_manual_locks(week):
    path = os.path.join(ROOT, "data", f"locks_w{week}.json")
    return json.load(open(path)) if os.path.exists(path) else {}


if __name__ == "__main__":
    main()
