"""Thin client for Sleeper's public, read-only API (no key needed).

Documented: api.sleeper.app/v1/...  Undocumented but public: api.sleeper.com/{stats,projections,schedule}/nba/...
Everything is cached to disk so a scheduled run only re-downloads what changes.
"""
import json
import os
import time

import requests

V1 = "https://api.sleeper.app/v1"
V2 = "https://api.sleeper.com"
CACHE = os.environ.get("FBB_CACHE", os.path.join(os.path.dirname(__file__), "..", "data", "cache"))
UA = "we-back-fantasy-assistant (github.com/rwalwan/fantasybasketball)"


def _get(url: str, cache_name: str | None = None, max_age_s: float = 0):
    if cache_name:
        path = os.path.join(CACHE, cache_name)
        if max_age_s and os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_s:
            with open(path) as f:
                return json.load(f)
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
            r.raise_for_status()
            data = r.json()
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    if cache_name:
        os.makedirs(CACHE, exist_ok=True)
        with open(os.path.join(CACHE, cache_name), "w") as f:
            json.dump(data, f)
    return data


def state():
    return _get(f"{V1}/state/nba")


def league(league_id):
    return _get(f"{V1}/league/{league_id}", f"league_{league_id}.json", 3600)


def users(league_id):
    return _get(f"{V1}/league/{league_id}/users", f"users_{league_id}.json", 3600)


def rosters(league_id):
    return _get(f"{V1}/league/{league_id}/rosters")


def matchups(league_id, week):
    return _get(f"{V1}/league/{league_id}/matchups/{week}")


def transactions(league_id, week):
    return _get(f"{V1}/league/{league_id}/transactions/{week}")


def players():
    """~2.5 MB map of player_id -> metadata (positions, team, injury status). Refreshed every 6 h."""
    return _get(f"{V1}/players/nba", "players_nba.json", 6 * 3600)


def trending_adds(hours=24, limit=50):
    return _get(f"{V1}/players/nba/trending/add?lookback_hours={hours}&limit={limit}")


def schedule(season):
    return _get(f"{V2}/schedule/nba/regular/{season}", f"schedule_{season}.json", 3 * 3600)


def week_stats(season, week, final=False):
    """Per-game stat rows (one per player per game, with date and game_id)."""
    name = f"stats_{season}_w{week}.json"
    return _get(f"{V2}/stats/nba/{season}/{week}?season_type=regular", name, 10 ** 9 if final else 0)


def week_projections(season, week):
    """Per-game projections (company: rotowire), one row per player per scheduled game."""
    return _get(f"{V2}/projections/nba/{season}/{week}?season_type=regular", f"proj_{season}_w{week}.json", 1800)


def season_totals(season):
    return _get(f"{V2}/stats/nba/{season}?season_type=regular", f"season_{season}.json", 12 * 3600)
