"""Per-game box scores for the season-level refits (app/train_models.py Baseline, Spread), in one shape:
{season: {pid: [(date, fp, minutes), ...]}} with every game the player played (minutes > 0), in date order, scored in
the league's format. Seasons are named by the year they start ("2025" = 2025-26, Sleeper's own naming).

Sources, oldest first:
  * 2021-23: research/data/games.parquet (NBA box scores already scored the "we back" way; NBA player ids, prefixed
    "nba:", so they never pair with a Sleeper-id season);
  * the two seasons before this one: Sleeper's per-game stats (the same feed the job reads), fetched once and kept on
    the learning branch as seasons/<season>.json.gz so they never need fetching again;
  * this season: memory.sqlite's graded games (data/state), which the 15-minute job keeps up to date.
"""
import gzip
import json
import os
import sqlite3

from . import memory, sleeper
from .scoring import fantasy_points

ROOT = os.path.join(os.path.dirname(__file__), "..")
PARQUET = os.path.join(ROOT, "research", "data", "games.parquet")
LEAGUE_ID = os.environ.get("FBB_LEAGUE_ID", "1400915575915491328")


def research_seasons(path=PARQUET):
    import pandas as pd                                   # only the nightly trainer has pandas installed
    g = pd.read_parquet(path, columns=["season_year", "pid", "date", "fp", "min", "played"])
    g = g[g.played].sort_values("date")
    out = {}
    for (sy, pid), d in g.groupby(["season_year", "pid"]):
        out.setdefault(str(sy)[:4], {})[f"nba:{pid}"] = [(str(x)[:10], float(f), float(m)) for x, f, m in zip(d.date, d.fp, d["min"])]
    return out


def from_sleeper(season, scoring, weeks=range(1, 31)):
    """One past season from Sleeper's weekly per-game stats. Stops after three weeks in a row with no rows."""
    out, seen, empty = {}, set(), 0
    for w in weeks:
        try:
            rows = sleeper.week_stats(season, w, final=True) or []
        except Exception:
            rows = []
        empty = 0 if rows else empty + 1
        if empty >= 3:
            break
        for r in rows:
            st = r.get("stats") or {}
            pid = str(r.get("player_id") or "")
            mins = memory.minutes(st)
            if not r.get("date") or not pid or pid.startswith("TEAM_") or not mins > 0:
                continue
            key = (pid, r.get("game_id") or r["date"])
            if key in seen:
                continue
            seen.add(key)
            out.setdefault(pid, []).append((r["date"], fantasy_points(st, scoring), round(mins, 2)))
    for gs in out.values():
        gs.sort()
    return out


def stored(learn, season):
    path = os.path.join(learn, "seasons", f"{season}.json.gz")
    if os.path.exists(path):
        with gzip.open(path, "rt") as f:
            return {p: [tuple(x) for x in gs] for p, gs in json.load(f).items()}
    return None


def store(learn, season, data):
    os.makedirs(os.path.join(learn, "seasons"), exist_ok=True)
    with gzip.open(os.path.join(learn, "seasons", f"{season}.json.gz"), "wt") as f:
        json.dump(data, f, separators=(",", ":"), sort_keys=True)


def current(state):
    """(season, {pid: games}) from memory.sqlite, or (None, {})."""
    path = os.path.join(state, "memory.sqlite")
    if not os.path.exists(path):
        return None, {}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        season = con.execute("SELECT MAX(season) FROM games").fetchone()[0]
        out = {}
        for pid, d, fp, mn in con.execute("SELECT pid, date, fp, min FROM games WHERE season=? AND min > 0 AND fp IS NOT NULL "
                                          "ORDER BY date", (season,)):
            out.setdefault(str(pid), []).append((d, float(fp), float(mn)))
        return season, out
    finally:
        con.close()


def load(ctx):
    """{season: {pid: games}} for every season available (cached per run in ctx)."""
    if "seasons" in ctx["cache"]:
        return ctx["cache"]["seasons"]
    out = {}
    try:
        out.update(research_seasons())
    except Exception as e:
        print("seasons: research box scores unavailable:", e)
    cur, games = current(ctx["state"])
    if cur:
        out[str(cur)] = games
        scoring = None
        for s in (str(int(cur) - 2), str(int(cur) - 1)):
            data = stored(ctx["learn"], s)
            if data is None:
                try:
                    scoring = scoring or sleeper.league(LEAGUE_ID)["scoring_settings"]
                    data = from_sleeper(s, scoring)
                except Exception as e:
                    print(f"seasons: {s} unavailable from Sleeper:", e)
                    data = {}
                if sum(len(v) for v in data.values()) > 10000:       # a whole season (~25k player-games), keep it
                    store(ctx["learn"], s, data)
            out[s] = data
            print(f"seasons: {s}: {len(data)} players, {sum(len(v) for v in data.values())} games")
    ctx["cache"]["seasons"] = out
    return out


def pairs(seasons):
    """(previous, current) season names that share player ids (consecutive years, same id system)."""
    names = sorted(seasons)
    return [(a, b) for a, b in zip(names, names[1:]) if int(b) == int(a) + 1
            and any(p in seasons[a] for p in list(seasons[b])[:200])]
