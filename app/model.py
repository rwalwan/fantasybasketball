"""Per-player projections and play probabilities for the current week."""
from collections import defaultdict

from .scoring import fantasy_points

# Probability a player suits up, by Sleeper injury_status (applies to his next game).
STATUS_Q = {None: 0.92, "": 0.92, "Probable": 0.9, "Day-To-Day": 0.75, "GTD": 0.6, "Questionable": 0.55,
            "Doubtful": 0.2, "Out": 0.0, "IR": 0.0, "Suspended": 0.0, "NA": 0.0, "DNR": 0.0, "COV": 0.0}
B2B_FACTOR = 0.86       # second night of a back-to-back: miss rate 14% -> 20% (research, 5 seasons)
PRIOR_GAMES = 8         # shrink this season's average toward last season's with this many pseudo-games
RETURN_RAMP = (0.83, 0.90)  # first / second game back from a 5+ game absence, share of normal production


class PlayerBook:
    """Everything known about each player: this season's game logs, last season's average, projections."""

    def __init__(self, scoring, players_meta):
        self.scoring = scoring
        self.meta = players_meta
        self.games = defaultdict(list)      # pid -> [(date, fp, min, game_id)]
        self.prior = {}                      # pid -> last season FP/G
        self.proj = {}                       # (pid, date) -> projected FP from Sleeper/RotoWire
        self.w = {"rotowire": 0.5, "model": 0.5}  # source weights, learned from graded accuracy (experts.py)

    def add_stat_rows(self, rows):
        seen = {(pid, g[3]) for pid, gs in self.games.items() for g in gs}
        for r in rows:
            st = r.get("stats") or {}
            if not r.get("date") or not st or not (st.get("min") or 0) > 0:
                continue
            key = (r["player_id"], r.get("game_id"))
            if key in seen:
                continue
            seen.add(key)
            self.games[r["player_id"]].append((r["date"], fantasy_points(st, self.scoring), st.get("min"), r.get("game_id")))
        for gs in self.games.values():
            gs.sort()

    def add_prior_season(self, rows):
        for r in rows:
            st = r.get("stats") or {}
            gp = st.get("gp") or 0
            if gp >= 10:
                per_game = {k: (st.get(k) or 0) / gp for k in ("pts", "tpm", "reb", "ast", "stl", "blk", "to")}
                self.prior[r["player_id"]] = fantasy_points(per_game, self.scoring)

    def add_projections(self, rows):
        for r in rows:
            if r.get("date") and r.get("stats"):
                self.proj[(r["player_id"], r["date"])] = fantasy_points(r["stats"], self.scoring)

    # ---- derived numbers -------------------------------------------------------------------------
    def name(self, pid):
        m = self.meta.get(pid, {})
        return f"{m.get('first_name', '')} {m.get('last_name', '')}".strip() or pid

    def positions(self, pid):
        return self.meta.get(pid, {}).get("fantasy_positions") or []

    def team(self, pid):
        return self.meta.get(pid, {}).get("team")

    def status(self, pid):
        return self.meta.get(pid, {}).get("injury_status")

    def season_avg(self, pid):
        g = self.games.get(pid, [])
        return sum(x[1] for x in g) / len(g) if g else None

    def baseline(self, pid):
        """Shrunk per-game average: this season blended with last season (or projection if no history)."""
        g = self.games.get(pid, [])
        cur = self.season_avg(pid)
        prior = self.prior.get(pid)
        if prior is None:
            future = [v for (p, _), v in self.proj.items() if p == pid]
            prior = sum(future) / len(future) if future else (cur if cur is not None else 0.0)
        if cur is None:
            return prior
        n = len(g)
        return (n * cur + PRIOR_GAMES * prior) / (n + PRIOR_GAMES)

    def game_mu(self, pid, date):
        """Projected fantasy points for one game if he plays: sources blended by their graded accuracy."""
        base = self.baseline(pid)
        p = self.proj.get((pid, date))
        f = getattr(self, "ctx", {}).get((pid, date))
        srcs = [(self.w.get("model", 1 / 3), base)]
        if f:
            srcs.append((self.w.get("ctx", 1 / 3), base * f))
        if p is not None and p > 0:
            srcs.append((self.w.get("rotowire", 1 / 3), p))
        tw = sum(w for w, _ in srcs)
        return round(sum(w * v for w, v in srcs) / tw, 1)

    def play_prob(self, pid, date, days_ahead, b2b):
        st = self.status(pid)
        q = STATUS_Q.get(st, 0.85)
        if st in ("Out", "IR", "Suspended", "NA", "DNR", "COV") and days_ahead >= 3:
            q = 0.25                     # unknown return date: some chance he's back later in the week
        elif st in ("Questionable", "Doubtful", "GTD", "Day-To-Day") and days_ahead >= 2:
            q = max(q, 0.75)
        if b2b:
            q *= B2B_FACTOR
        return round(q, 2)
