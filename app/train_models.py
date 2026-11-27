"""The models the nightly trainer (app/train.py) keeps current. Each says where its data comes from, how it is fitted,
how it is scored on held-out games, and which numbers are never allowed."""
import json
import os

import numpy as np

from . import availability
from .train import Model, archive, _load_state

# ---------------------------------------------------------------------------------------------------------------
# Play chance of a player's NEXT game when Sleeper lists him with a status (Nov 27).
#
# Before: "Out" was 0% and GTD/DTD/Questionable one pooled rate (~48% a day or more ahead), whatever his recent games.
# Graded Nov 2-25 (availability_log.json, status when the game first became his next game): Out with 0 games missed
# played 31 of 73 (42%), Out with 1 missed 19 of 55 (35%); DTD with 0 missed 65% (n=31) vs 19% with 1+ missed (n=16);
# GTD 78% (n=32) vs 45% (n=11). Sleeper's labels stick between games, so "Out" a day ahead is often last night's
# status. One rate per (status, games missed so far), separately for a day or more ahead ("ahead": the status at first
# sight) and game day ("gameday": the status at the last run before tip), each shrunk toward its status's pooled rate
# (K pseudo-games), which is shrunk toward today's numbers.

GROUP = {"Out": "Out", "Probable": "Probable", "Doubtful": "Doubtful",
         **{s: "Questionable" for s in ("Questionable", "GTD", "DTD", "Day-To-Day")}}
GROUPS = ("Out", "Questionable", "Probable", "Doubtful")
BUCKETS = ("0", "1", "2-3", "4+")
K = 20                  # pseudo-games of the prior behind each rate
STEP_MAX = 0.25         # one promotion moves a rate at most this far
CLIP = (0.01, 0.99)     # a 0% that happens costs a bounded penalty, not infinity


bucket = availability.missed_bucket


def _forced(status, q):
    """A designated player at 0% was zeroed by a 'ruled out' news report: the news rule, not the status, decided."""
    return status in availability.DESIG and q == 0


def avail_records(ctx):
    """Every graded next-game prediction: today's log merged into the archive on the learning branch (the log keeps
    only the newest 3,000)."""
    if "avail" not in ctx["cache"]:
        log = _load_state("availability_log.json", {"graded": []})
        ctx["cache"]["avail"] = archive("avail_graded", log.get("graded", []), key=lambda r: f"{r['date']}|{r['pid']}")
    return ctx["cache"]["avail"]


class PlayFirst(Model):
    name = "play_first"
    title = "Play chances for players listed Out, GTD/DTD, Probable or Doubtful"
    min_train = 150
    min_hold = 150

    def rows(self, ctx):
        out = []
        for r in avail_records(ctx):
            if r.get("timeline") or r.get("played") is None:
                continue
            if r.get("first"):
                g = GROUP.get(r.get("status"))
                if g and not _forced(r.get("status"), r.get("q")):
                    out.append({"day": r["date"], "h": "ahead", "s": "ahead", "g": g, "b": bucket(r.get("missed")), "y": int(bool(r["played"]))})
                ls, lq = r.get("last_status"), r.get("last_q")
            else:
                # records from before Nov 13 were rewritten on every run, so they carry the status at the last run
                # before tip (review 3, finding 2): a game-day row
                ls, lq = r.get("status"), r.get("q")
            g = GROUP.get(ls)
            if g and not _forced(ls, lq):
                out.append({"day": r["date"], "h": "gameday", "s": "gameday", "g": g, "b": bucket(r.get("missed")), "y": int(bool(r["played"]))})
        return out

    def factory(self, ctx):
        """Today's behavior as explicit rates: Out 0%; the others the self-calibrated designation rates."""
        availability.STATE = ctx["state"]
        availability.calibrate_designations()
        M = availability.M
        gd = M.get("designation_gameday") or M["designation"]
        return {"ahead": {g: {b: (0.0 if g == "Out" else round(M["designation"][g], 3)) for b in BUCKETS} for g in GROUPS},
                "gameday": {g: {b: (0.0 if g == "Out" else round(gd.get(g, M["designation"][g]), 3)) for b in BUCKETS} for g in GROUPS}}

    def fit(self, rows, base):
        out = {}
        for h in ("ahead", "gameday"):
            out[h] = {}
            for g in GROUPS:
                rs = [r for r in rows if r["h"] == h and r["g"] == g]
                prior = float(np.mean(list(base[h][g].values())))
                pooled = (prior * K + sum(r["y"] for r in rs)) / (K + len(rs))
                out[h][g] = {}
                for b in BUCKETS:
                    c = [r["y"] for r in rs if r["b"] == b]
                    out[h][g][b] = round((pooled * K + sum(c)) / (K + len(c)), 3)
        return out

    def loss(self, params, rows):
        p = np.clip(np.array([params[r["h"]][r["g"]][r["b"]] for r in rows], float), *CLIP)
        y = np.array([r["y"] for r in rows], float)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))

    def bounds(self, params):
        for h in ("ahead", "gameday"):
            for g in GROUPS:
                for b in BUCKETS:
                    v = (params.get(h) or {}).get(g, {}).get(b)
                    if v is None or not 0 <= v <= 1:
                        return f"{h} {g} {b} games missed = {v}"
                    if g == "Out" and v > 0.9:
                        return f"Out ({h}, {b} missed) at {v:.0%}"
        return None

    def step(self, old, new):
        return {h: {g: {b: round(old[h][g][b] + float(np.clip(new[h][g][b] - old[h][g][b], -STEP_MAX, STEP_MAX)), 3)
                        for b in BUCKETS} for g in GROUPS} for h in ("ahead", "gameday")}

    def describe(self, old, new):
        ch = []
        for h, word in (("ahead", "a day or more ahead"), ("gameday", "on game day")):
            for g in GROUPS:
                for b in BUCKETS:
                    a, z = old[h][g][b], new[h][g][b]
                    if abs(z - a) >= 0.05:
                        name = "GTD/DTD" if g == "Questionable" else g
                        ch.append(f"{name} after {b} missed games {word}: {a:.0%} to {z:.0%}")
        return ("Changed: " + "; ".join(ch[:6]) + (f"; and {len(ch) - 6} more" if len(ch) > 6 else "") + ".") if ch else ""


# ---------------------------------------------------------------------------------------------------------------
# Return rate after k straight missed games (the "hazard": app/availability.py hazard(), engine hazardK). Factory:
# 2021-24 box scores of top-150 players (research/hazard_refit.py). Learned from this league's own graded next-game
# predictions for players who had already missed k games in a row (any status, no reported timeline, no news zero),
# each rate shrunk 30 games toward the current one. The engine uses it for every game after the next one in an
# absence (the next game itself is PlayFirst's).

HZ_KEYS = [str(k) for k in range(1, 9)] + ["9-12", "13-20", "21+"]
HZ_K = 30
HZ_STEP = 0.10
HZ_LIMITS = (0.02, 0.8)


def hz_key(k):
    k = int(k)
    return str(k) if k <= 8 else "9-12" if k <= 12 else "13-20" if k <= 20 else "21+"


def hz_params(M):
    return {**{str(k): float(M["by_k"][k - 1]) for k in range(1, 9)}, "9-12": float(M["k9_12"]),
            "13-20": float(M["k13_20"]), "21+": float(M.get("k21p", M["k13_20"]))}


def hz_to_model(p):
    """Learned params -> the availability model's own keys (by_k, k9_12, k13_20, k21p)."""
    return {"by_k": [p[str(k)] for k in range(1, 9)], "k9_12": p["9-12"], "k13_20": p["13-20"], "k21p": p["21+"]}


class ReturnRate(Model):
    name = "return_rate"
    title = "Return rates after missed games (how soon an injured player comes back)"
    min_train = 150
    min_hold = 100

    def rows(self, ctx):
        out = []
        for r in avail_records(ctx):
            if not r.get("first") or r.get("timeline") or r.get("played") is None or int(r.get("missed") or 0) < 1:
                continue
            if _forced(r.get("status"), r.get("q")):
                continue
            out.append({"day": r["date"], "k": hz_key(r["missed"]), "y": int(bool(r["played"]))})
        return out

    def factory(self, ctx):
        return hz_params(json.load(open(os.path.join(os.path.dirname(__file__), "data", "availability_model.json"))))

    def fit(self, rows, base):
        out = {}
        for key in HZ_KEYS:
            ys = [r["y"] for r in rows if r["k"] == key]
            out[key] = round((base[key] * HZ_K + sum(ys)) / (HZ_K + len(ys)), 3)
        return out

    def loss(self, params, rows):
        p = np.clip(np.array([params[r["k"]] for r in rows], float), *CLIP)
        y = np.array([r["y"] for r in rows], float)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))

    def bounds(self, params):
        for key in HZ_KEYS:
            v = params.get(key)
            if v is None or not HZ_LIMITS[0] <= v <= HZ_LIMITS[1]:
                return f"return rate after {key} missed = {v}"
        return None

    def step(self, old, new):
        return {k: round(old[k] + float(np.clip(new[k] - old[k], -HZ_STEP, HZ_STEP)), 3) for k in HZ_KEYS}

    def describe(self, old, new):
        ch = [f"after {k} missed: {old[k]:.0%} to {new[k]:.0%}" for k in HZ_KEYS if abs(new[k] - old[k]) >= 0.03]
        return ("Changed: " + "; ".join(ch) + ".") if ch else ""


# ---------------------------------------------------------------------------------------------------------------
# Season-level refits: the per-minute baseline and the per-player spread. Their factory fits (research/baseline_fit.py,
# research/volatility_fit.py) used 2021-24 only. These refit them on every season available (app/seasons.py: 2021-23,
# the last two seasons from Sleeper, this season so far), with the NEWEST season that has enough rows as the exam and
# only older seasons in the fit, so the exam is a season the fit never saw. Rows are resampled by player-season.

class SeasonModel(Model):
    row_word = "player checkpoints"

    def exam_words(self, hold, nd):
        s = max(int(r["season"]) for r in hold)
        return f"the {s}-{str(s + 1)[2:]} season, {nd} players"

    def split(self, rows, t):
        names = sorted({r["season"] for r in rows})
        for s in reversed(names):
            hold = [r for r in rows if r["season"] == s]
            if len(hold) >= self.min_hold:
                return [r for r in rows if r["season"] < s], hold
        return [], []


def _weights(rows):
    """Newer seasons count more in a fit: x0.7 per season back."""
    newest = max(int(r["season"]) for r in rows)
    return np.array([0.7 ** (newest - int(r["season"])) for r in rows])


class Baseline(SeasonModel):
    """FP/G = rate x minutes; last season's rate counts as R pseudo-minutes and its minutes as M pseudo-games, both
    scaled by gp_last / (gp_last + c) (app/model.py baseline, engine Book.baseline). Checkpoints after n = 1, 2, 3, 5, 10
    games; target = the mean of his later games (8+). Loss: absolute error in FP/G."""
    name = "baseline"
    title = "Season-start projection (how fast this season's games outweigh last season's)"
    min_train = 300
    min_hold = 200
    GRID = [(R, M, c) for R in (100, 150, 200, 250, 300, 400, 500, 600, 800) for M in (1, 2, 3, 4, 5, 6, 8)
            for c in (0, 5, 10, 15, 20, 30, 40)]
    CAP = {"R": 100, "M": 2, "c": 10}
    LIMITS = {"R": (50, 1000), "M": (0.5, 12), "c": (0, 60)}

    def rows(self, ctx):
        from . import seasons as S
        data = S.load(ctx)
        out = []
        for a, b in S.pairs(data):
            for pid, g in data[b].items():
                lp = data[a].get(pid)
                if not lp or len(lp) < 10:
                    continue
                lfp, lmn = sum(x[1] for x in lp), sum(x[2] for x in lp)
                if lmn <= 0:
                    continue
                fp = [x[1] for x in g]
                mn = [x[2] for x in g]
                for n in (1, 2, 3, 5, 10):
                    if len(g) - n < 8:
                        continue
                    out.append({"day": g[n - 1][0], "season": b, "c": f"{b}|{pid}", "n": n, "fp": sum(fp[:n]),
                                "mn": sum(mn[:n]), "last_rate": lfp / lmn, "last_mpg": lmn / len(lp), "gp_last": len(lp),
                                "target": float(np.mean(fp[n:]))})
        return out

    def factory(self, ctx):
        from .model import BASE
        return {"R": float(BASE["R_minutes"]), "M": float(BASE["M_games"]), "c": float(BASE["c_size"])}

    @staticmethod
    def predict(P, rows):
        n = np.array([r["n"] for r in rows], float)
        fp, mn = np.array([r["fp"] for r in rows]), np.array([r["mn"] for r in rows])
        lr, lm, gl = (np.array([r[k] for r in rows], float) for k in ("last_rate", "last_mpg", "gp_last"))
        w = gl / (gl + P["c"]) if P["c"] else np.ones_like(gl)
        rate = (fp + P["R"] * w * lr) / (mn + P["R"] * w)
        mpg = (mn + P["M"] * w * lm) / (n + P["M"] * w)
        return rate * mpg

    def loss(self, P, rows):
        return np.abs(self.predict(P, rows) - np.array([r["target"] for r in rows]))

    def fit(self, rows, base):
        wt = _weights(rows)
        y = np.array([r["target"] for r in rows])
        best = min(((float(np.average(np.abs(self.predict({"R": R, "M": M, "c": c}, rows) - y), weights=wt)), R, M, c)
                    for R, M, c in self.GRID))
        return {"R": float(best[1]), "M": float(best[2]), "c": float(best[3])}

    def bounds(self, P):
        bad = [f"{k}={P.get(k)}" for k, (lo, hi) in self.LIMITS.items() if P.get(k) is None or not lo <= P[k] <= hi]
        return ", ".join(bad) or None

    def step(self, old, new):
        return {k: round(old[k] + float(np.clip(new[k] - old[k], -cap, cap)), 2) for k, cap in self.CAP.items()}

    def describe(self, old, new):
        words = {"R": "last season's scoring rate counts as {} minutes", "M": "last season's minutes count as {} games",
                 "c": "a short last season is discounted with c = {}"}
        ch = [words[k].format(f"{old[k]:g} to {new[k]:g}") for k in ("R", "M", "c") if old[k] != new[k]]
        return ("Changed: " + "; ".join(ch) + ".") if ch else ""


def _tier_table():
    q = json.load(open(os.path.join(os.path.dirname(__file__), "data", "game_ratio_quantiles.json")))
    return [(t.get("max"), float(np.std(t["quantiles"]))) for t in q["tiers"]]


class Spread(SeasonModel):
    """Per-player game-to-game spread (app/volatility.py): r = sd(FP / his mean) / his tier's sd;
    prior = m + a (r_last - m); r_hat = prior + (r_now - prior) n / (n + k). Checkpoints n = 0, 5, 10, 20, 30, 40 games
    into a season of 35+ games (mean 15+), target = the spread of the rest of his season (15+ games).
    Loss: squared error of r (as in its first fit)."""
    name = "spread"
    title = "Boom-or-bust spread per player (how much of a player's own spread is real)"
    min_train = 300
    min_hold = 200
    GRID = [(a, k, m) for a in np.round(np.arange(0, 1.01, 0.05), 2) for k in (5, 10, 20, 30, 40, 60, 80, 120, 160, 240, 320)
            for m in np.round(np.arange(0.84, 1.061, 0.02), 2)]
    CAP = {"a": 0.1, "k": 40, "m": 0.04}
    LIMITS = {"a": (0, 1), "k": (5, 400), "m": (0.8, 1.1)}

    def rows(self, ctx):
        from . import seasons as S
        data = S.load(ctx)
        tiers = _tier_table()
        tsd = lambda mu: next(sd for mx, sd in tiers if mx is None or mu <= mx)
        ratio = lambda x: float((x / x.mean()).std() / tsd(x.mean())) if x.mean() > 0 else 1.0
        out = []
        for a, b in S.pairs(data):
            for pid, g in data[b].items():
                x = np.array([v[1] for v in g], float)
                if len(x) < 35 or x.mean() < 15:
                    continue
                prev = data[a].get(pid)
                px = np.array([v[1] for v in prev], float) if prev else None
                r_prev = ratio(px) if px is not None and len(px) >= 20 and px.mean() >= 10 else None
                for n in (0, 5, 10, 20, 30, 40):
                    fut = x[n:]
                    if len(fut) < 15:
                        continue
                    out.append({"day": g[n][0], "season": b, "c": f"{b}|{pid}", "n": n, "r_prev": r_prev,
                                "r_cur": ratio(x[:n]) if n >= 5 else None, "r_fut": ratio(fut)})
        return out

    def factory(self, ctx):
        M = json.load(open(os.path.join(os.path.dirname(__file__), "data", "volatility_model.json")))
        return {"a": float(M["a_prev"]), "k": float(M["k_games"]), "m": float(M["m_typical"])}

    @staticmethod
    def arrays(rows):
        f = lambda k: np.array([np.nan if r[k] is None else r[k] for r in rows], float)
        return f("r_prev"), f("r_cur"), np.array([r["n"] for r in rows], float)

    @classmethod
    def predict(cls, P, rows, arr=None):
        rp, rc, n = arr or cls.arrays(rows)
        prior = np.where(np.isnan(rp), P["m"], P["m"] + P["a"] * (rp - P["m"]))
        cur = np.where(np.isnan(rc), prior, rc)
        w = np.where(n >= 5, n / (n + P["k"]), 0.0)
        return prior + (cur - prior) * w

    def loss(self, P, rows):
        return (self.predict(P, rows) - np.array([r["r_fut"] for r in rows])) ** 2

    def fit(self, rows, base):
        wt = _weights(rows)
        y = np.array([r["r_fut"] for r in rows])
        arr = self.arrays(rows)
        best = min(((float(np.average((self.predict({"a": a, "k": k, "m": m}, rows, arr) - y) ** 2, weights=wt)), a, k, m)
                    for a, k, m in self.GRID))
        return {"a": float(best[1]), "k": float(best[2]), "m": float(best[3])}

    bounds = Baseline.bounds

    def step(self, old, new):
        return {k: round(old[k] + float(np.clip(new[k] - old[k], -cap, cap)), 3) for k, cap in self.CAP.items()}

    def describe(self, old, new):
        words = {"a": "share of last season's spread carried over", "k": "games before this season's spread counts half",
                 "m": "typical player's spread"}
        ch = [f"{words[k]}: {old[k]:g} to {new[k]:g}" for k in ("a", "k", "m") if old[k] != new[k]]
        return ("Changed: " + "; ".join(ch) + ".") if ch else ""


# ---------------------------------------------------------------------------------------------------------------
# Other leagues and matchups.

def _week_end(ctx, season, week):
    """Last date of a fantasy week (for ordering rows in time). ctx["week_end"] (tests) or Sleeper's schedule."""
    if "week_end" in ctx:
        return ctx["week_end"](week)
    if "sched" not in ctx["cache"]:
        from . import sleeper
        ctx["cache"]["sched"] = sleeper.schedule(season)
    from .engine import week_dates
    ds = week_dates(ctx["cache"]["sched"], week)
    return ds[-1] if ds else None


def _season(ctx):
    from . import seasons as S
    return S.current(ctx["state"])[0] if "season" not in ctx else ctx["season"]


# Wins per point of weekly score (engine WINS_PER_SCORE, trade values in expected wins). Factory: 2.2, measured once on
# Nov 15 as the density of final margins at a tie, per unit of a typical team's weekly score S, in 1,155 matchups of 72
# other Lock-In leagues. Learned the same way from every finished week in the leagues the daily study tracks
# (leagues.sqlite): a matchup "is close" if |margin| < H x S (S = the league-week's median team score), which happens
# with chance 2 H x density. Scored by log loss of that chance on held-out weeks, resampled by league.
H = 0.04
WPS_K = 200


class WinsPerPoint(Model):
    name = "wins_per_point"
    title = "Wins per point (how much a weekly point is worth in trades), from other leagues' final scores"
    min_train = 300
    min_hold = 150
    row_word = "matchups"

    def exam_words(self, hold, nd):
        return f"the newest {len({r['day'] for r in hold})} weeks, {nd} leagues"

    def rows(self, ctx):
        import sqlite3
        path = os.path.join(ctx["state"], "leagues.sqlite")
        if not os.path.exists(path):
            return []
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            snap = con.execute("SELECT s.league, s.week, s.matchup, s.points FROM snap s JOIN league l ON l.league = s.league "
                               "WHERE s.final = 1 AND l.verified = 1 AND s.points IS NOT NULL").fetchall()
        finally:
            con.close()
        season = _season(ctx)
        by = {}
        for lg, wk, mid, pts in snap:
            by.setdefault((lg, wk), {}).setdefault(mid, []).append(float(pts))
        out, ends = [], {}
        for (lg, wk), ms in by.items():
            allp = [p for v in ms.values() for p in v]
            if len(allp) < 4:
                continue
            S = float(np.median(allp))
            if S <= 0:
                continue
            if wk not in ends:
                ends[wk] = _week_end(ctx, season, wk)
            if not ends[wk]:
                continue
            for mid, v in ms.items():
                if mid is None or len(v) != 2:
                    continue
                out.append({"day": ends[wk], "c": lg, "y": int(abs(v[0] - v[1]) < H * S)})
        return out

    def factory(self, ctx):
        return {"wps": 2.2}

    def fit(self, rows, base):
        p0 = 2 * H * base["wps"]
        share = (p0 * WPS_K + sum(r["y"] for r in rows)) / (WPS_K + len(rows))
        return {"wps": round(share / (2 * H), 3)}

    def loss(self, P, rows):
        p = float(np.clip(2 * H * P["wps"], *CLIP))
        y = np.array([r["y"] for r in rows], float)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))

    def bounds(self, P):
        v = P.get("wps")
        return None if v is not None and 1.2 <= v <= 4.0 else f"wins per point = {v}"

    def step(self, old, new):
        return {"wps": round(old["wps"] + float(np.clip(new["wps"] - old["wps"], -0.3, 0.3)), 3)}

    def describe(self, old, new):
        return f"Changed: {old['wps']:g} to {new['wps']:g} wins per unit of a team's weekly score."


# Win chance (engine pWin: normal approximation of my final vs theirs). The log (tools/moves.mjs, winprob_log.json)
# keeps one prediction per matchup per stage of the week for every matchup in the league, from each team's own plan,
# and grades it once the week has settled. A temperature t rescales the z-score: p' = Phi(t Phi^-1(p)); t > 1 = the
# ranges were too wide (favorites won more than predicted), t < 1 = too narrow. Learned on the raw logged
# predictions (the log is never tempered), applied to the page's win chance and the trade check. Scored by log loss
# on held-out days, resampled by matchup.
from statistics import NormalDist
_N = NormalDist()


class WinChance(Model):
    name = "win_chance"
    title = "Win chance calibration (are the projected ranges too wide or too narrow?)"
    min_train = 60
    min_hold = 40
    row_word = "matchup predictions"

    def exam_words(self, hold, nd):
        return f"last {len({r['day'] for r in hold})} days, {nd} matchups"
    GRID = [round(float(x), 2) for x in np.arange(0.5, 2.001, 0.05)]

    def rows(self, ctx):
        log = _load_state("winprob_log.json", {"graded": []})
        out = []
        for x in log.get("graded", []):
            if x.get("a_won") is None or x.get("p_a") is None or not x.get("day"):
                continue
            out.append({"day": x["day"], "c": f"{x['week']}|{x['mid']}", "z": _N.inv_cdf(min(max(x["p_a"], 0.001), 0.999)),
                        "y": int(bool(x["a_won"]))})
        return out

    def factory(self, ctx):
        return {"t": 1.0}

    def loss(self, P, rows):
        z = np.array([r["z"] for r in rows]) * P["t"]
        p = np.clip(np.array([_N.cdf(v) for v in z]), *CLIP)
        y = np.array([r["y"] for r in rows], float)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))

    def fit(self, rows, base):
        return {"t": float(min(self.GRID, key=lambda t: float(self.loss({"t": t}, rows).mean())))}

    def bounds(self, P):
        v = P.get("t")
        return None if v is not None and 0.5 <= v <= 2.0 else f"temperature = {v}"

    def step(self, old, new):
        return {"t": round(old["t"] + float(np.clip(new["t"] - old["t"], -0.25, 0.25)), 2)}

    def describe(self, old, new):
        return (f"Changed: win-chance z-scores x{old['t']:g} to x{new['t']:g} "
                + ("(favorites win more often than the ranges said)." if new["t"] > old["t"] else "(upsets happen more often than the ranges said)."))


MODELS = [PlayFirst(), ReturnRate(), Baseline(), Spread(), WinsPerPoint(), WinChance()]
