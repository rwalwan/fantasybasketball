"""Daily: discover/refresh other Lock-In leagues, snapshot matchups, verify Lock-In mode, study finished weeks.
python -m app.league_run   (workflow: .github/workflows/leagues.yml) -> data/state/league_study.json"""
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

from . import experts, leagues, league_study, memory, sleeper
from .run import LEAGUE_ID, current_week

STATE = os.path.join(os.path.dirname(__file__), "..", "data", "state")


def main():
    today = dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    lg = sleeper.league(LEAGUE_ID)
    season = lg["season"]
    sched = sleeper.schedule(season)
    week = current_week(sched, today)
    finals = list(range(1, week))
    found = leagues.discover(LEAGUE_ID, season, today)
    con = leagues.connect()
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='kv'").fetchone():
        con.execute("CREATE TABLE kv(k TEXT PRIMARY KEY, v TEXT)")
    if con.execute("SELECT v FROM kv WHERE k='verify_v'").fetchone() != ("2",):
        con.execute("UPDATE league SET verified=NULL, checked=NULL")      # v1 compared x10 points to FP
        con.execute("INSERT OR REPLACE INTO kv VALUES('verify_v','2')")
    n = leagues.snapshot(con, found, week, today, finals)
    stats = {w: sleeper.week_stats(season, w, final=True) for w in finals}
    for w in finals:
        leagues.verify(con, w, stats[w])
    try:
        prior = sleeper.season_totals(str(int(season) - 1))
    except Exception:
        prior = []
    team_dates = {}
    for g in sched:
        for side in ("home", "away"):
            t = (g.get(side) or {}).get("team")
            if t and g.get("week") in finals:
                team_dates.setdefault(g["week"], {}).setdefault(t, []).append(g["date"])
    proj = {}
    for w in finals:
        try:
            proj[w] = sleeper.week_projections(season, w)
        except Exception:
            proj[w] = []
    try:                                              # the production projection scale (RotoWire x scale)
        scale = experts.stack_weights(experts.graded_rows(memory.connect(), season)).get("scale", 1.0)
    except Exception:
        scale = 1.0
    out = league_study.study(con, finals, stats, prior, team_dates=team_dates, proj_by_week=proj, proj_scale=scale)
    ver = con.execute("SELECT COUNT(*), SUM(verified=1), SUM(verified=0) FROM league").fetchone()
    out.update(at=today, candidates=len(found), snapshot_rows=n,
               verified={"checked": ver[0], "lock_in": ver[1] or 0, "not_lock_in": ver[2] or 0})
    json.dump(out, open(os.path.join(STATE, "league_study.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k not in ("bar_scale", "lock_rate_eligible")}))


if __name__ == "__main__":
    main()
