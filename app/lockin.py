"""Lock-In decision math.

In Sleeper Lock-In mode each starter slot scores ONE game per week: after a starter plays you either
lock that game or pass. A slot never locked falls back to its player's final game of the week
(0 if he sits). This is an optimal-stopping problem.

For a player with upcoming games g_1..g_n (each with projected mean mu_j and play probability q_j),
the value of reaching game j still unlocked is
    W_{n+1} = 0
    W_j     = q_j * E[max(X_j, W_{j+1})] + (1 - q_j) * W_{j+1}       for j < n
    W_n     = q_n * E[X_n]                                         (last game is forced)
and after game j you should lock iff score_j >= W_{j+1}.

X_j = mu_j * R where R is the empirical distribution of (single-game FP / season average) for top-150
players, 2021-24 (research/lockin.py). Thresholds this produces: 1.13x avg with 2 games left,
1.21x with 3, 1.26x with 4 (identical in 2024-25 and 2025-26).
"""
import json
import os
from dataclasses import dataclass, field

import numpy as np

_Q = np.array(json.load(open(os.path.join(os.path.dirname(__file__), "data", "game_ratio_quantiles.json")))["quantiles"])


def expected_max(mu: float, floor: float) -> float:
    """E[max(mu * R, floor)] using the empirical game-spread quantiles."""
    if mu <= 0:
        return floor
    return float(np.mean(np.maximum(mu * _Q, floor)))


def percentile_range(mu: float, lo=10, hi=90):
    idx = lambda p: min(len(_Q) - 1, max(0, int(round(p))))
    return round(mu * _Q[idx(lo)], 1), round(mu * _Q[idx(hi)], 1)


@dataclass
class Game:
    date: str
    mu: float          # projected fantasy points if he plays
    q: float           # probability he plays
    opponent: str = ""
    b2b: bool = False


def continuation_values(games: list[Game]) -> list[float]:
    """W_j for each upcoming game j (value of arriving at game j unlocked), plus W_{n+1}=0 at the end."""
    n = len(games)
    W = [0.0] * (n + 1)
    for j in range(n - 1, -1, -1):
        g = games[j]
        if j == n - 1:
            W[j] = g.q * g.mu
        else:
            W[j] = g.q * expected_max(g.mu, W[j + 1]) + (1 - g.q) * W[j + 1]
    return W


def lock_bar(games_after: list[Game]) -> float:
    """Score a just-finished game must reach to be worth locking, given the player's remaining games."""
    if not games_after:
        return 0.0
    return continuation_values(games_after)[0]


@dataclass
class SlotDecision:
    slot: str
    player_id: str | None
    action: str                 # "lock", "pass", "start", "swap", "locked", "empty", "fallback-risk"
    detail: str
    score: float | None = None
    bar: float | None = None
    extras: dict = field(default_factory=dict)


ELIGIBLE = {
    "PG": {"PG"}, "SG": {"SG"}, "G": {"PG", "SG"}, "SF": {"SF"}, "PF": {"PF"}, "F": {"SF", "PF"},
    "C": {"C"}, "UTIL": {"PG", "SG", "SF", "PF", "C"},
}


def eligible(slot: str, positions) -> bool:
    return bool(ELIGIBLE.get(slot, set()) & set(positions or []))
