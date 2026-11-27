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


MODELS = [PlayFirst()]
