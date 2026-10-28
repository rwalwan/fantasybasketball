"""Other Lock-In leagues: discovery and daily snapshots (Sleeper's public, read-only API).

Discovery (weekly): start from this league's managers -> every NBA league they're in this season -> those
leagues' managers -> their leagues ... (breadth-first, capped). Keep leagues in Lock-In mode
(settings.game_mode == 1, like ours) with 8+ teams. A league counts as verified Lock-In once a finished week's
starter scores each equal ONE of that player's games (a daily-lineup league would show sums).
Snapshots (daily): each kept league's matchups for the current week (starters, per-player points); finished
weeks are stored once as finals. Only league ids, roster ids and player ids are stored - no usernames.
State: data/state/leagues.sqlite, data/state/other_leagues.json. Sleeper asks for < 1000 calls/minute; this
makes a few hundred per day with a pause between calls.
"""
import datetime as dt
import json
import os
import sqlite3
import time

from . import sleeper


def fantasy_points(stats, scoring):
    """Any Sleeper NBA scoring: every scored stat as given (penalties are stored negative), plus the bonuses.
    (app/scoring.py covers our league's stats only; other leagues may score fgm, fga, ftm, oreb, ...)"""
    special = {"dd", "td", "bonus_pt_40p", "bonus_pt_50p", "bonus_reb_20p", "bonus_ast_15p"}
    s = lambda k: float(stats.get(k) or 0)
    total = sum(s(k) * v for k, v in scoring.items() if k not in special)
    tens = sum(1 for k in ("pts", "reb", "ast", "stl", "blk") if s(k) >= 10)
    total += scoring.get("dd", 0) * (tens >= 2) + scoring.get("td", 0) * (tens >= 3)
    total += scoring.get("bonus_pt_40p", 0) * (s("pts") >= 40) + scoring.get("bonus_pt_50p", 0) * (s("pts") >= 50)
    total += scoring.get("bonus_reb_20p", 0) * (s("reb") >= 20) + scoring.get("bonus_ast_15p", 0) * (s("ast") >= 15)
    return round(total / 10.0, 2)

STATE = os.path.join(os.path.dirname(__file__), "..", "data", "state")
MAX_USERS, MAX_LEAGUES, PAUSE = 600, 250, 0.08


def connect():
    os.makedirs(STATE, exist_ok=True)
    con = sqlite3.connect(os.path.join(STATE, "leagues.sqlite"))
    con.executescript("""
    CREATE TABLE IF NOT EXISTS snap(league TEXT, week INT, day TEXT, final INT, roster INT, matchup INT,
        starters TEXT, players_points TEXT, starters_points TEXT, points REAL, PRIMARY KEY(league, week, day, roster));
    CREATE TABLE IF NOT EXISTS league(league TEXT PRIMARY KEY, teams INT, scoring TEXT, positions TEXT,
        verified INT, checked TEXT);
    """)
    return con


def _sleep():
    time.sleep(PAUSE)


def discover(seed_league, season, today):
    """BFS over managers -> leagues. Returns {league_id: {teams, scoring, positions}} for Lock-In candidates."""
    path = os.path.join(STATE, "other_leagues.json")
    if os.path.exists(path):
        old = json.load(open(path))
        if (dt.date.fromisoformat(today) - dt.date.fromisoformat(old["at"])).days < 7:
            return old["leagues"]
    users = [u["user_id"] for u in sleeper.users(seed_league)]
    seen_users, seen_leagues, keep = set(users), {seed_league}, {}
    queue = list(users)
    while queue and len(seen_users) <= MAX_USERS and len(keep) < MAX_LEAGUES:
        uid = queue.pop(0)
        try:
            lgs = sleeper._get(f"{sleeper.V1}/user/{uid}/leagues/nba/{season}")
        except Exception:
            continue
        _sleep()
        for lg in lgs or []:
            lid = lg.get("league_id")
            if not lid or lid in seen_leagues:
                continue
            seen_leagues.add(lid)
            st = lg.get("settings") or {}
            if st.get("game_mode") == 1 and (lg.get("total_rosters") or 0) >= 8 and lg.get("status") == "in_season":
                keep[lid] = {"teams": lg.get("total_rosters"), "scoring": lg.get("scoring_settings") or {},
                             "positions": lg.get("roster_positions") or []}
                if len(seen_users) < MAX_USERS:
                    try:
                        for u in sleeper._get(f"{sleeper.V1}/league/{lid}/users") or []:
                            if u["user_id"] not in seen_users:
                                seen_users.add(u["user_id"])
                                queue.append(u["user_id"])
                    except Exception:
                        pass
                    _sleep()
    json.dump({"at": today, "users_seen": len(seen_users), "leagues_seen": len(seen_leagues), "leagues": keep},
              open(path, "w"))
    return keep


def snapshot(con, leagues, week, today, final_weeks=()):
    """Store today's matchups for the current week, and finals for finished weeks not stored yet."""
    n = 0
    for lid, info in leagues.items():
        con.execute("INSERT OR IGNORE INTO league VALUES(?,?,?,?,?,?)",
                    (lid, info["teams"], json.dumps(info["scoring"]), json.dumps(info["positions"]), None, None))
        jobs = [(week, today, 0)] + [(w, "final", 1) for w in final_weeks
                                     if not con.execute("SELECT 1 FROM snap WHERE league=? AND week=? AND final=1 LIMIT 1", (lid, w)).fetchone()]
        for w, day, fin in jobs:
            try:
                ms = sleeper.matchups(lid, w) or []
            except Exception:
                continue
            _sleep()
            for m in ms:
                starters = m.get("starters") or []
                pp = m.get("players_points") or {}
                con.execute("INSERT OR REPLACE INTO snap VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (lid, w, day, fin, m.get("roster_id"), m.get("matchup_id"), json.dumps(starters),
                             json.dumps({p: pp.get(p) for p in starters if p in pp}),
                             json.dumps(m.get("starters_points") or []), m.get("points")))
                n += 1
    con.commit()
    return n


def verify(con, week, stat_rows):
    """Mark leagues whose finished-week starter scores each equal one game (Lock-In) vs sums (daily lineups)."""
    games = {}
    for r in stat_rows:
        if r.get("date") and r.get("stats"):
            games.setdefault(r["player_id"], []).append(r["stats"])
    for lid, scoring in con.execute("SELECT league, scoring FROM league WHERE verified IS NULL").fetchall():
        sc = json.loads(scoring)
        one = tot = 0
        for st_json, sp_json in con.execute("SELECT starters, starters_points FROM snap WHERE league=? AND week=? AND final=1", (lid, week)):
            for p, s in zip(json.loads(st_json), json.loads(sp_json)):
                s = (s or 0) / 10                         # Sleeper stores NBA points x10
                g = [fantasy_points(x, sc) for x in games.get(p, [])]
                if len(g) < 2 or not s:
                    continue
                tot += 1
                one += any(abs(x - s) < 0.06 for x in g)
        if tot >= 20:
            con.execute("UPDATE league SET verified=?, checked=? WHERE league=?", (int(one / tot >= 0.9), f"{one}/{tot}", lid))
    con.commit()
