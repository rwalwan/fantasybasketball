"""Usage model: projected output when rotation players are out (fitted in research/usage_fit.py, 2021-24).

For each player and each of his team's games in the next few weeks:
  tm_same / tm_other  expected minutes missing from his team's rotation (20+ min/game), in 48-minute units,
                      at his position group / elsewhere. Expected = (1 - play chance) x minutes, using the
                      availability curves (designations, reported timelines, return rates; healthy = history).
  op_rim              expected blocks/game missing from the opponent's rotation (lost rim protection).
Each feature is compared with what's typical in his baseline: his own games this season (which teammates were out,
from the memory store) blended with the league average (8 pseudo-games, like the baseline itself).
  factor = 1 + sum(coef x (feature - reference)), coefficients by role (starter 28+ min, bench), capped at 0.8 and
  +30% (starters) / +60% (bench), the range where the fit stays calibrated.
Tested and dropped: the absent opponent at his position (likely primary defender), by minutes or steals+blocks -
no measurable effect out of sample. Validation on this season's graded games: model MAE 10.15 -> 9.95; RotoWire
already prices teammate injuries (applying this on top of it: 9.007 -> 9.035), so it enters the blend as its own
graded source and is used for future weeks, where RotoWire has no projections.
"""
import json
import os
from collections import defaultdict

from .availability import healthy_at
from .memory import minutes

U = json.load(open(os.path.join(os.path.dirname(__file__), "data", "usage_model.json")))
PSEUDO = 8                        # same shrinkage as the baseline (PRIOR_GAMES)
# Caps from the fit's calibration table (2021-24): predictions track actual lifts up to +57% for bench players
# (n = 120 in that bin, actual +62%); starters' predictions never exceed ~+30% (one case beyond).
CAP = {"starter": 1.3, "bench": 1.6}
role_of = lambda x: "starter" if x["mpg"] >= 28 else "bench"


def profiles(season_rows, prev_rows):
    """pid -> {mpg, bpg, grp} from this season's game rows (3+ games) else last season's totals."""
    acc = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])          # games, min, blk, reb, ast
    for r in season_rows:
        st = r.get("stats") or {}
        m = minutes(st)
        if not r.get("date") or not m > 0:
            continue
        a = acc[r["player_id"]]
        a[0] += 1; a[1] += m; a[2] += st.get("blk") or 0; a[3] += st.get("reb") or 0; a[4] += st.get("ast") or 0
    prev = {}
    for r in prev_rows or []:
        st = r.get("stats") or {}
        gp = st.get("gp") or 0
        if gp >= 10:
            prev[r["player_id"]] = [gp, minutes(st), st.get("blk") or 0, st.get("reb") or 0, st.get("ast") or 0]
    out = {}
    for pid in set(acc) | set(prev):
        a = acc.get(pid)
        g, mins, blk, reb, ast = a if a and a[0] >= 3 else prev.get(pid, a)
        if not g or not mins:
            continue
        a36, r36 = ast / mins * 36, reb / mins * 36
        out[pid] = {"mpg": mins / g, "bpg": blk / g, "grp": "G" if a36 >= 4.5 else "C" if r36 >= 9 else "F"}
    return out


def build(con, season, meta, prof, team_dates, dates_ahead, avail, pids, names=None):
    """{(pid, date): (factor, [reasons])} for every pid's team games among dates_ahead."""
    lm = U["league_mean"]
    team_of = {p: (meta.get(p) or {}).get("team") for p in prof}
    rotation = defaultdict(list)
    for p, x in prof.items():
        if team_of.get(p) and x["mpg"] >= 20:
            rotation[team_of[p]].append(p)
    # reference: what was typical in his games this season (memory store), shrunk to the league mean
    realized = defaultdict(lambda: [0.0, 0.0, 0])
    for pid, om in con.execute("SELECT pid, out_mates FROM games WHERE season=?", (season,)):
        x = prof.get(pid)
        if not x:
            continue
        r = realized[pid]
        for o in json.loads(om or "[]"):
            m = prof.get(o, {}).get("mpg", 24) / 48
            r[0 if prof.get(o, {}).get("grp") == x["grp"] else 1] += m
        r[2] += 1

    def miss(p, d, j):
        a = (avail or {}).get(p)
        if a and d in a["q"]:
            return 1 - a["q"][d]
        return 1 - healthy_at(j + 1)

    out = {}
    for p in pids:
        x, t = prof.get(p), team_of.get(p)
        if not x or not t:
            continue
        g = U["groups"]["starter" if x["mpg"] >= 28 else "bench"]["coef"]
        rs, ro, n = realized.get(p, [0.0, 0.0, 0])
        ref_same = (rs + PSEUDO * lm["tm_same"]) / (n + PSEUDO)
        ref_other = (ro + PSEUDO * lm["tm_other"]) / (n + PSEUDO)
        days = sorted(d for d in team_dates.get(t, {}) if d in dates_ahead)
        for j, d in enumerate(days):
            same = other = 0.0
            why = []
            for m in rotation[t]:
                if m == p:
                    continue
                mm = miss(m, d, j) * prof[m]["mpg"] / 48
                if prof[m]["grp"] == x["grp"]:
                    same += mm
                else:
                    other += mm
                if mm * 48 >= 10 and names:
                    why.append((mm * (g["tm_same"] if prof[m]["grp"] == x["grp"] else g["tm_other"]), names(m)))
            opp = team_dates[t][d].get("opp")
            rim = sum(miss(m, d, j) * prof[m]["bpg"] for m in rotation.get(opp, []))
            f = 1 + g["tm_same"] * (same - ref_same) + g["tm_other"] * (other - ref_other) + g["op_rim"] * (rim - lm["op_rim"])
            f = max(0.8, min(CAP[role_of(x)], f))
            reasons = [f"{nm} likely out" for _, nm in sorted(why, reverse=True)[:3]]
            if names and g["op_rim"] * (rim - lm["op_rim"]) >= 0.01:
                reasons.append(f"{opp} missing rim protection")
            out[(p, d)] = (f, reasons)
    # a baseline already reflects how often teams are short-handed, so across the league the adjustments must
    # average out to 1: the reference (realized absences, incl. rest days) runs higher than tonight's expected
    # absences, which would otherwise shift every projection down
    # (per role: starter and bench coefficients differ, so a shared shift would move one role against the other)
    role = {p: "starter" if prof[p]["mpg"] >= 28 else "bench" for p, _ in out}
    for r in ("starter", "bench"):
        keys = [k for k in out if role[k[0]] == r]
        if keys:
            mean = sum(out[k][0] for k in keys) / len(keys)
            for k in keys:
                out[k] = (round(max(0.8, min(CAP[r], out[k][0] / mean)), 3), out[k][1])
    return out
