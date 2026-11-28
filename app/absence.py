"""Teammate absences -> minutes -> projection (Nov 28).

The case: Fri Nov 27, Neemias Queta sat on Ryan's bench and scored 70.5. Mitchell Robinson, the other Boston center,
had been out four games (COVID). Queta played 22 min / 30.4 FP a game with Robinson and 29 min / 41.6 FP in the five
games without him, but the app still projected him at 34.9 and started Derrick White (34.8) in UTIL. Robinson plays
17.5 min, under the 20-minute line every teammate-absence path used, so his absence was invisible; and the usage
model (app/usage.py) is gated off on every horizon because it made projections worse.

This model works on minutes, the thing an absence actually moves:
  1. A player's on/off record with each teammate this season (games for his current team): his minutes in games the
     teammate played and in games he sat.
  2. The minutes he gains when that teammate sits = his own on/off difference, shrunk toward a prior (a share of the
     teammate's minutes: more for the same position group). n_eff = n_on*n_off/(n_on+n_off) games of evidence, k games
     of prior.
  3. His season minutes already include the games that teammate missed (fraction fa). Tonight's expected minutes =
     season minutes + sum over teammates of (P(teammate sits tonight) - fa) x gain. So a boost lasts exactly as long as
     the teammate stays out and turns into a cut when he returns, and nothing is counted twice.
  4. factor = (expected minutes / season minutes) ^ e. It multiplies the model's baseline (the model and matchup
     sources of the blend; RotoWire already prices injuries).
Fitted on 2021-24 box scores (research/absence_fit.py -> app/data/absence_model.json), checked on this season's graded
games before it shipped (SYSTEM.md section 8).
"""
import json
import os

PARAMS = json.load(open(os.path.join(os.path.dirname(__file__), "data", "absence_model.json")))
MIN_GAMES = 5          # games with his current team before his on/off record is used at all
MIN_MPG = 10           # teammates who play less than this don't move anyone's minutes measurably
MAX_MIN = 42.0


def terms(p, team_days, before, mates):
    """p's on/off record with each candidate teammate.
    team_days: {date: {pid: minutes}} for p's team this season (who played that night); only dates < before count.
    mates: {A: (mpg, same position group)} for his teammates.
    Returns (season minutes, games, [(A, fa, n_on, n_off, d_obs, mpg, same, n_st, d_st)]) or None with too few games.
    n_st, d_st: the current streak - his most recent games in a row without that teammate - and his minutes in it
    over his minutes with him."""
    days = [d for d in sorted(team_days) if d < before and p in team_days[d]]
    if len(days) < MIN_GAMES:
        return None
    mins = [team_days[d][p] for d in days]
    m_hist = sum(mins) / len(mins)
    out = []
    for a, (mpg, same) in mates.items():
        if a == p or not mpg or mpg < MIN_MPG:
            continue
        on = [m for d, m in zip(days, mins) if a in team_days[d]]
        off = [m for d, m in zip(days, mins) if a not in team_days[d]]
        st = []
        for d, m in zip(reversed(days), reversed(mins)):
            if a in team_days[d]:
                break
            st.append(m)
        m_on = sum(on) / len(on) if on else None
        d_obs = (sum(off) / len(off) - m_on) if on and off else 0.0
        d_st = (sum(st) / len(st) - m_on) if on and st else 0.0
        out.append((a, len(off) / len(days), len(on), len(off), d_obs, mpg, bool(same), len(st) if on else 0, d_st))
    return m_hist, len(days), out


def gain(n_on, n_off, d_obs, mpg, same, n_st, d_st, prm=PARAMS):
    """Minutes he gains when this teammate sits: his own on/off difference, with the games of the current streak
    counting `streak` times (a lasting absence shows his new role; a scattered rest night says little), shrunk toward
    a flat share of the teammate's minutes (more at the same position) with k games of weight."""
    prior = (prm["share_same"] if same else prm["share_other"]) * mpg
    wst = prm.get("streak", 1.0) - 1
    off_w = n_off + wst * n_st
    d_w = (n_off * d_obs + wst * n_st * d_st) / off_w if off_w else 0.0
    neff = n_on * off_w / (n_on + off_w) if n_on and off_w else 0.0
    d = (neff * d_w + prm["k"] * prior) / (neff + prm["k"])
    return max(-0.5 * mpg, min(mpg, d))


def shift(m_hist, tl, miss, prm=PARAMS):
    """miss: {A: P(A sits tonight)} (1 = out or gone from the team). Returns (factor, expected minutes,
    [(A, minutes added, gain, n_off, n_on)] biggest first)."""
    if not m_hist or m_hist < 8:
        return 1.0, m_hist, []
    tot, why = 0.0, []
    for a, fa, n_on, n_off, d_obs, mpg, same, n_st, d_st in tl:
        x = miss.get(a, 0.0) - fa
        if abs(x) < 1e-9:
            continue
        d = gain(n_on, n_off, d_obs, mpg, same, n_st, d_st, prm)
        tot += x * d
        why.append((a, x * d, d, n_off, n_on))
    m = max(0.5 * m_hist, min(MAX_MIN, m_hist + tot))
    f = max(prm["lo"], min(prm["hi"], (m / m_hist) ** prm["e"]))
    why.sort(key=lambda w: -abs(w[1]))
    return f, m, why


def team_days_from(con, season):
    """{team: {date: {pid: minutes}}} from the memory store (final games this season)."""
    out = {}
    for pid, d, t, m in con.execute("SELECT pid, date, team, min FROM games WHERE season=? AND min > 0", (season,)):
        out.setdefault(t, {}).setdefault(d, {})[pid] = m
    return out


def build(con, season, meta, prof, team_dates, dates_ahead, avail, pids, names, healthy_at, today):
    """{(pid, date): (factor, [reasons])} for every pid's team games among dates_ahead.
    prof: usage.profiles() (mpg and position group, this season or last); avail: availability_now players
    ({pid: {q: {date: p}}}); healthy_at(n): play chance of an undesignated player n games ahead."""
    td = team_days_from(con, season)
    team_of = {p: (meta.get(p) or {}).get("team") for p in set(prof) | set(pids)}
    # candidates per team: everyone who played for it this season, plus its current roster (a teammate who hasn't
    # played yet counts as absent in every game so far, so his return takes minutes away)
    played_for = {t: {a for day in days.values() for a in day} for t, days in td.items()}
    roster = {}
    for a, t in team_of.items():
        if t:
            roster.setdefault(t, set()).add(a)
    out = {}
    for p in pids:
        t, x = team_of.get(p), prof.get(p)
        if not t or not x or t not in td:
            continue
        cands = (played_for.get(t, set()) | roster.get(t, set())) - {p}
        mates = {a: (prof[a]["mpg"], prof[a]["grp"] == x["grp"]) for a in cands if a in prof}
        r = terms(p, td[t], today, mates)
        if not r:
            continue
        m_hist, n, tl = r
        days = sorted(d for d in team_dates.get(t, {}) if d in dates_ahead)
        for j, d in enumerate(days):
            miss = {}
            for a, *_ in tl:
                if team_of.get(a) != t:
                    miss[a] = 1.0                     # traded or released: his minutes are gone for good
                    continue
                av = (avail or {}).get(a)
                miss[a] = 1 - av["q"][d] if av and d in av.get("q", {}) else 1 - healthy_at(j + 1)
            f, m, why = shift(m_hist, tl, miss)
            reasons = []
            for a, add, g, n_off, n_on in why[:3]:
                if abs(add) < 1.5:
                    break
                nm = names(a) if names else a
                if add > 0:
                    reasons.append(f"{nm} {'out' if miss.get(a, 0) >= 0.9 else 'may sit'}: +{add:.0f} min "
                                   f"({g:+.0f} min when he sits, {n_off} game{'s' * (n_off != 1)} this season)")
                else:
                    reasons.append(f"{nm} back: {add:.0f} min")
            out[(p, d)] = (round(f, 3), reasons, round(m, 1), round(m_hist, 1))
    return out


def walk_factors(con, season, prm=PARAMS):
    """{(pid, date): factor} for every final game of the season, each computed only from earlier games, with the
    teammates who actually sat that night (what the upside model learns from: app/train_models.py Upside,
    research/boom_fit.py). Production uses play chances instead of who sat, so this is the factor with a perfect
    injury report."""
    rows = con.execute("SELECT pid, date, team, min, reb, ast FROM games WHERE season=? AND min > 0", (season,)).fetchall()
    acc = {}
    for p, d, t, m, reb, ast in rows:
        a = acc.setdefault(p, [0.0, 0.0, 0.0])
        a[0] += m; a[1] += reb or 0; a[2] += ast or 0
    # position group from the season's per-36 profile (the production rule, app/usage.py profiles)
    grp = {p: ("G" if a[2] / a[0] * 36 >= 4.5 else "C" if a[1] / a[0] * 36 >= 9 else "F") for p, a in acc.items() if a[0] > 0}
    td = {}
    for p, d, t, m, *_ in rows:
        td.setdefault(t, {}).setdefault(d, {})[p] = m
    out = {}
    for t, days in td.items():
        seen = {}
        for d in sorted(days):
            mpg = {a: sum(v) / len(v) for a, v in seen.items() if len(v) >= 3}
            for p in days[d]:
                if len(seen.get(p, ())) < MIN_GAMES:
                    continue
                r = terms(p, days, d, {a: (mpg[a], grp.get(a) == grp.get(p)) for a in mpg if a != p})
                if r:
                    m_hist, _, tl = r
                    out[(p, d)] = shift(m_hist, tl, {a: 0.0 if a in days[d] else 1.0 for a, *_ in tl}, prm)[0]
            for p, m in days[d].items():
                seen.setdefault(p, []).append(m)
    return out
