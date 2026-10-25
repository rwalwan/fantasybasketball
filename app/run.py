"""Entry point: python -m app.run  ->  writes site/data.json (the dashboard reads it)."""
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

import requests

from . import espn, sleeper
from . import experts
from . import news as newsmod
from . import memory, insights
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
    season_rows = []
    for w in range(1, week + 1):
        rows = sleeper.week_stats(season, w, final=w < week)
        season_rows += rows
        book.add_stat_rows(rows)
    book.add_projections(sleeper.week_projections(season, week))
    prev = str(int(season) - 1)
    prior_min = {}
    try:
        prev_rows = sleeper.season_totals(prev)
        book.add_prior_season(prev_rows)
        for r in prev_rows:
            st = r.get("stats") or {}
            if (st.get("gp") or 0) >= 10:
                prior_min[r["player_id"]] = (st.get("min") or 0) / st["gp"]
    except Exception as e:  # prior season is a nice-to-have
        print("prior season unavailable:", e, file=sys.stderr)

    # memory: every final game with its context; then matchup context for every upcoming game
    con = memory.connect()
    try:
        projlog = json.load(open(os.path.join(ROOT, "data", "state", f"projlog_{season}.json")))
    except Exception:
        projlog = {}
    n_ing = memory.ingest(con, season, season_rows, sched, lg["scoring_settings"], projlog, prior_min, meta)
    try:
        prior_ctx = memory.last_season_prior(lambda s_, w_: sleeper.week_stats(s_, w_, final=True), prev,
                                             lg["scoring_settings"], meta, book.prior)
    except Exception as e:
        print("last-season context unavailable:", e, file=sys.stderr)
        prior_ctx = {}
    ctx_out = build_context(con, season, meta, book, sched, week, today, prior_ctx, prior_min)
    print(f"memory: {n_ing} final games stored, context for {len(ctx_out)} upcoming player-games")

    # record who is starting right now for every game that hasn't tipped (lock eligibility)
    days = week_dates(sched, week)
    tips = espn.tip_times([d for d in days if d >= (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()])
    tg = team_game_dates(sched)
    slots = [s for s in lg["roster_positions"] if s not in ("BN", "IR")]
    tracker = LineupTracker(season, week)
    backend = fetch_backend(season, week)
    if backend.get("kick"):
        os.makedirs(os.path.join(ROOT, "data", "state"), exist_ok=True)
        with open(os.path.join(ROOT, "data", "state", "kick.json"), "w") as f:
            json.dump(backend["kick"], f)
    tracker.snaps.update(backend.get("lineups") or {})          # minute-level records win
    tracker.overrides.update(backend.get("elig") or {})
    tracker.record(slots, my_m.get("starters") or [], mine.get("players") or [], book.team,
                   lambda team: sorted(d for d in tg.get(team, {}) if d in days), tips)

    manual = {**load_manual_locks(week), **(backend.get("locks") or {})}

    # grade projection sources and learn blend weights before planning
    scores = experts.update(book, season, week, tips)
    book.w = experts.weights(scores)
    wp = WeekPlan(book, sched, week, today, lg["roster_positions"], mine, my_m, rosters, tracker.eligible, tips)
    plan = wp.build(manual)
    waivers, worst = wp.waivers(sleeper.trending_adds())
    # news + expert claims (AI extraction via OpenRouter when OPENROUTER_API_KEY is set)
    news_out, claims_out = {"items": [], "mine": []}, {"experts": [], "consensus": {}, "recent": []}
    try:
        fa_ids = [w["pid"] for w in waivers]
        items, claims = newsmod.collect(meta, mine.get("players") or [], fa_ids, today)
        claims = newsmod.grade(claims, book, today)
        table = newsmod.experts_table(claims)
        cons = newsmod.consensus(claims, table, today)
        news_out = {"items": [{k: n.get(k) for k in ("title", "summary", "source", "link", "at", "player", "status", "kind")}
                              for n in reversed(items[-80:])],
                    "mine": newsmod.impact(items, mine.get("players") or [], fa_ids, book)}
        claims_out = {"experts": table, "consensus": cons, "recent": claims[-60:][::-1]}
        for w in waivers:
            c = cons.get(w["pid"])
            w["experts"] = {"bull_share": c["bull_share"], "n": c["n"]} if c else None
        print(f"news: {len(items)} items, {len(claims)} claims, {len(table)} experts")
    except Exception as e:
        print("news/experts failed:", e, file=sys.stderr)


    opp_owner = next((r.get("owner_id") for r in rosters if opp_m and r["roster_id"] == opp_m["roster_id"]), None)
    out = dict(generated=dt.datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%a %b %d, %I:%M %p PT"),
               league=lg["name"], week=week, today=today, plan=plan, waivers=waivers, worst_bench=worst,
               score=dict(me=(my_m.get("points") or 0) / 10, opp=((opp_m or {}).get("points") or 0) / 10,
                          opp_name=users.get(opp_owner, "Opponent")),
               faab_left=lg["settings"].get("waiver_budget", 100) - (mine.get("settings") or {}).get("waiver_budget_used", 0))
    os.makedirs(os.path.join(ROOT, "site"), exist_ok=True)
    export_static(book, season, week, meta, lg)
    with open(os.path.join(ROOT, "site", "static", "experts.json"), "w") as f:
        json.dump({"weights": book.w, "sources": experts.table(scores, book.w)}, f, separators=(",", ":"))
    # insights: why games went the way they did, role trends, injury openings
    ins_out = {"notes": [], "trends": [], "openings": []}
    try:
        mine_ids = set(mine.get("players") or [])
        rostered = {p for r in rosters for p in (r.get("players") or [])}
        watch = mine_ids | {w["pid"] for w in waivers[:15]}
        llm = newsmod.llm_json if os.environ.get("OPENROUTER_API_KEY") else None
        insights.why_notes(con, season, meta, watch, today, llm=llm)
        tr = insights.trends(con, season, meta)
        ins_out = {"notes": insights.recent_notes(con, watch, 40),
                   "trends": [dict(t, mine=t["pid"] in mine_ids, rostered=t["pid"] in rostered) for t in tr
                              if t["pid"] in mine_ids or t["pid"] not in rostered or len(tr) < 40][:60],
                   "openings": insights.openings(con, season, meta, rostered)[:20]}
    except Exception as e:
        print("insights failed:", e, file=sys.stderr)
    con.close()

    for name, obj in (("news", news_out), ("claims", claims_out), ("insights", ins_out), ("context", ctx_out)):
        with open(os.path.join(ROOT, "site", "static", f"{name}.json"), "w") as f:
            json.dump(obj, f, separators=(",", ":"))
    with open(os.path.join(ROOT, "site", "static", "tips.json"), "w") as f:
        json.dump({f"{d}|{t}": v for (d, t), v in tips.items()}, f, separators=(",", ":"))
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


def build_context(con, season, meta, book, sched, week, today, prior_ctx, prior_min):
    """Matchup context factors for every projected game from today through the end of this week."""
    days = set(week_dates(sched, week))
    tg = team_game_dates(sched)
    ctx = memory.Context(con, season, meta, book.baseline, prior_ctx, today)
    avg_min = {}
    for pid, rows in ctx.by_player.items():
        avg_min[pid] = sum(r[4] for r in rows) / len(rows)
    out_by_team = {}
    for pid, m in meta.items():
        t = m.get("team")
        mm = avg_min.get(pid) or prior_min.get(pid) or 0
        if t and m.get("injury_status") in ("Out", "Doubtful", "IR", "Suspended") and mm >= 20:
            nm = f"{m.get('first_name', '')} {m.get('last_name', '')}".strip()
            out_by_team.setdefault(t, []).append((pid, nm, mm))
    out = {}
    book.ctx = {}
    for (pid, date) in list(book.proj):
        if date not in days or date < today:
            continue
        team = book.team(pid)
        info = (tg.get(team) or {}).get(date)
        if not team or not info:
            continue
        team_days = sorted(tg.get(team, {}))
        i = team_days.index(date)
        rest = 4 if i == 0 else min(4, (dt.date.fromisoformat(date) - dt.date.fromisoformat(team_days[i - 1])).days)
        mates = [x for x in out_by_team.get(team, []) if x[0] != pid]
        if (meta.get(pid) or {}).get("injury_status") in ("Out", "IR"):
            continue
        f, parts = ctx.factors(pid, team, info["opp"], rest, mates)
        book.ctx[(pid, date)] = f
        out[f"{pid}|{date}"] = {"f": f, "parts": parts, "opp": info["opp"], "rest": rest}
    return out


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
