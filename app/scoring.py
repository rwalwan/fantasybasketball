"""Fantasy points from a Sleeper stat line, using the league's own scoring_settings.

Sleeper stores NBA scoring x10 (e.g. pts=10.0 means 1 point per point). We divide by 10 so the app
shows the same numbers you see in the Sleeper app. Verified against week 1 of "we back": 170/170
player-games matched Sleeper's players_points exactly.
"""

BASE_STATS = ("pts", "tpm", "reb", "ast", "stl", "blk", "to", "tf", "ff")
DD_CATS = ("pts", "reb", "ast", "stl", "blk")


def fantasy_points(stats: dict, scoring: dict) -> float:
    s = {k: float(stats.get(k) or 0) for k in set(BASE_STATS) | set(DD_CATS)}
    total = sum(s[k] * scoring.get(k, 0.0) for k in BASE_STATS if k != "to") - s["to"] * abs(scoring.get("to", 0.0))
    tens = sum(1 for k in DD_CATS if s[k] >= 10)
    if tens >= 2:
        total += scoring.get("dd", 0.0)
    if tens >= 3:
        total += scoring.get("td", 0.0)
    if s["pts"] >= 40:
        total += scoring.get("bonus_pt_40p", 0.0)
    if s["pts"] >= 50:
        total += scoring.get("bonus_pt_50p", 0.0)
    if s["reb"] >= 20:
        total += scoring.get("bonus_reb_20p", 0.0)
    if s["ast"] >= 15:
        total += scoring.get("bonus_ast_15p", 0.0)
    return round(total / 10.0, 2)
