"""Lock Desk memory + matchup research.

Builds a SQLite game log (data/state/memory.sqlite) where every player-game carries its context:
minutes vs expected, shot volume, fouls, final margin, rest, back-to-back, which rotation teammates
were out, opponent, home/away, and the projections made before tip. From it we derive, for every
upcoming player-game:

  * opponent vs position   how many fantasy points this opponent allows to G / F / C, relative to
                           those players' own averages (shrunk toward 1.0 until there's a sample;
                           blended with last season's version early on)
  * pace                   both teams' scoring environment vs league average
  * minutes trend          last 3 games' minutes vs his expected minutes (minutes change = real signal)
  * teammates out          rotation teammates listed Out/Doubtful -> vacated minutes and shots
  * rest                   small rest / back-to-back effect on production

Each factor is capped and comes with a plain-English reason. The product becomes the 'ctx'
projection, which is graded against RotoWire and the plain model, so it only gains weight if it
actually predicts better.
"""
import datetime as dt
import json
import math
import os
import sqlite3
from collections import defaultdict

from .scoring import fantasy_points

STATE = os.path.join(os.path.dirname(__file__), "..", "data", "state")
DB = os.path.join(STATE, "memory.sqlite")
GROUP = {"PG": "G", "SG": "G", "SF": "F", "PF": "F", "C": "C"}


def connect():
    os.makedirs(STATE, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS games(pid TEXT, gid TEXT, date TEXT, season TEXT, team TEXT, opp TEXT, home INT,
        min REAL, fga REAL, pf REAL, pts REAL, reb REAL, ast REAL, fp REAL, team_pts INT, opp_pts INT, margin INT,
        rest INT, b2b INT, out_mates TEXT, exp_min REAL, proj_rw REAL, proj_model REAL, proj_ctx REAL,
        PRIMARY KEY(pid, gid));
    CREATE INDEX IF NOT EXISTS games_date ON games(date);
    CREATE INDEX IF NOT EXISTS games_team ON games(team, date);
    CREATE TABLE IF NOT EXISTS decisions(week INT, date TEXT, slot TEXT, idx INT, pid TEXT, kind TEXT, score REAL, bar REAL,
        ev_call TEXT, mx_call TEXT, p_lock REAL, p_pass REAL, deadline TEXT, made_at TEXT,
        final REAL, cf REAL, regret REAL, followed INT, extra TEXT, PRIMARY KEY(week, idx, pid, kind, date));
    CREATE TABLE IF NOT EXISTS notes(pid TEXT, date TEXT, kind TEXT, tag TEXT, text TEXT, facts TEXT, PRIMARY KEY(pid, date, kind));
    CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
    """)
    return con


def group_of(meta, pid):
    pos = (meta.get(pid) or {}).get("fantasy_positions") or []
    for p in ("C", "PG", "SG", "SF", "PF"):          # bigs first: C eligibility defines the matchup
        if p in pos:
            return GROUP[p]
    return "F"


# --------------------------------------------------------------------------------------------- ingest
def ingest(con, season, week_rows, schedule, scoring, projlog, prior_min, meta=None):
    """week_rows: list of Sleeper per-game stat rows for the season so far."""
    scores, home_of = {}, {}
    for g in schedule:
        for side, other in (("home", "away"), ("away", "home")):
            t = (g.get(side) or {}).get("team")
            if not t:
                continue
            home_of[(g["date"], t)] = side == "home"
            if g.get("status") == "complete":
                scores[(g["date"], t)] = ((g[side] or {}).get("points"), (g[other] or {}).get("points"))
    rows = []
    for r in week_rows:
        st = r.get("stats") or {}
        if str(r.get("player_id", "")).startswith("TEAM_"):
            continue                                     # team-total pseudo players
        if not r.get("date") or not (st.get("min") or 0) > 0 or (r.get("date"), r.get("team")) not in scores:
            continue                                     # final games only
        tp, op = scores[(r["date"], r["team"])]
        pl = projlog.get(f"{r['date']}|{r['player_id']}") or {}
        rows.append((r["player_id"], r.get("game_id"), r["date"], season, r.get("team"), r.get("opponent"),
                     1 if home_of.get((r["date"], r.get("team"))) else 0, float(st.get("min") or 0), float(st.get("fga") or 0),
                     float(st.get("pf") or 0), float(st.get("pts") or 0), float(st.get("reb") or 0), float(st.get("ast") or 0),
                     fantasy_points(st, scoring), tp, op, (tp or 0) - (op or 0), pl.get("rotowire"), pl.get("model"), pl.get("ctx")))
    con.executemany("""INSERT INTO games(pid,gid,date,season,team,opp,home,min,fga,pf,pts,reb,ast,fp,team_pts,opp_pts,margin,proj_rw,proj_model,proj_ctx)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(pid,gid) DO UPDATE SET min=excluded.min, fga=excluded.fga, pf=excluded.pf, pts=excluded.pts, reb=excluded.reb,
          ast=excluded.ast, fp=excluded.fp, team_pts=excluded.team_pts, opp_pts=excluded.opp_pts, margin=excluded.margin,
          proj_rw=COALESCE(games.proj_rw, excluded.proj_rw), proj_model=COALESCE(games.proj_model, excluded.proj_model),
          proj_ctx=COALESCE(games.proj_ctx, excluded.proj_ctx)""", rows)
    con.execute("DELETE FROM games WHERE pid LIKE 'TEAM_%'")
    _derive(con, season, prior_min, meta)
    con.commit()
    return len(rows)


def _derive(con, season, prior_min, meta=None):
    """rest days, back-to-backs, expected minutes (before each game), rotation teammates who were out."""
    team_dates = defaultdict(list)
    for t, d in con.execute("SELECT DISTINCT team, date FROM games WHERE season=? ORDER BY date", (season,)):
        team_dates[t].append(d)
    rest = {}
    for t, ds in team_dates.items():
        for i, d in enumerate(ds):
            r = 4 if i == 0 else min(4, (dt.date.fromisoformat(d) - dt.date.fromisoformat(ds[i - 1])).days)
            rest[(t, d)] = r
    by_player = defaultdict(list)
    for pid, gid, d, t, m in con.execute("SELECT pid, gid, date, team, min FROM games WHERE season=? ORDER BY date", (season,)):
        by_player[pid].append((gid, d, t, m))
    exp = {}
    for pid, gs in by_player.items():
        tot, n = 0.0, 0
        for gid, d, t, m in gs:
            prior = prior_min.get(pid)
            exp[(pid, gid)] = (tot + 4 * prior) / (n + 4) if prior and n < 12 else (tot / n if n else (prior or m))
            tot, n = tot + m, n + 1
    # Rotation teammates who were out: walk each team's dates in order with running minutes per player.
    # Rotation = averaging >= 20 min (3+ games) or, early on, >= 22 min last season (incl. players who
    # haven't played yet this season, from the current roster).
    plays = defaultdict(lambda: defaultdict(list))            # team -> date -> [(pid, gid, min)]
    for pid, gs in by_player.items():
        for gid, d, t, m in gs:
            plays[t][d].append((pid, gid, m))
    roster_prior = defaultdict(set)
    for pid, m in (meta or {}).items():
        if m.get("team") and (prior_min.get(pid) or 0) >= 22:
            roster_prior[m["team"]].add(pid)
    upd = []
    for t, dates in plays.items():
        run = defaultdict(lambda: [0.0, 0])
        for d in sorted(dates):
            rot = {p for p, (tot, n) in run.items() if n >= 3 and tot / n >= 20}
            rot |= {p for p in roster_prior[t] if run[p][1] < 3}
            played = {p for p, _, _ in dates[d]}
            outs = sorted(rot - played)
            for pid, gid, m in dates[d]:
                upd.append((rest.get((t, d), 2), 1 if rest.get((t, d)) == 1 else 0, json.dumps(outs),
                            round(exp[(pid, gid)], 1), pid, gid))
            for pid, gid, m in dates[d]:
                run[pid][0] += m
                run[pid][1] += 1
    con.executemany("UPDATE games SET rest=?, b2b=?, out_mates=?, exp_min=? WHERE pid=? AND gid=?", upd)


# -------------------------------------------------------------------------------------------- context
def _shrink(ratio, n, k):
    return 1 + (ratio - 1) * n / (n + k)


def _cap(f, lo=0.88, hi=1.12):
    return max(lo, min(hi, f))


class Context:
    """Per-matchup adjustment factors with reasons, computed from the memory store."""

    def __init__(self, con, season, meta, baseline, prior_ctx=None, today=None):
        self.meta, self.baseline, self.prior = meta, baseline, prior_ctx or {}
        today = today or dt.date.today().isoformat()
        since = (dt.date.fromisoformat(today) - dt.timedelta(days=60)).isoformat()
        g = con.execute("SELECT pid, date, team, opp, min, fga, fp, team_pts, opp_pts, exp_min, out_mates FROM games WHERE season=? ORDER BY date",
                        (season,)).fetchall()
        self.rows = g
        # opponent vs position: fp / player's baseline, last 60 days
        acc = defaultdict(lambda: [0.0, 0])
        for pid, d, t, o, m, fga, fp, tp, op, em, om in g:
            if d < since:
                continue
            b = baseline(pid)
            if b and b > 8 and m >= 10:
                a = acc[(o, group_of(meta, pid))]
                a[0] += fp / b
                a[1] += 1
        self.dvp = {k: (v[0] / v[1], v[1]) for k, v in acc.items()}
        # pace proxy: average combined score per team game
        pts = defaultdict(list)
        seen = set()
        for pid, d, t, o, m, fga, fp, tp, op, em, om in g:
            if (d, t) not in seen and tp is not None and op is not None:
                seen.add((d, t))
                pts[t].append(tp + op)
        allp = [x for v in pts.values() for x in v]
        self.league_pace = sum(allp) / len(allp) if allp else 228.0
        self.pace = {t: (sum(v) / len(v), len(v)) for t, v in pts.items()}
        self.by_player = defaultdict(list)
        for row in g:
            self.by_player[row[0]].append(row)

    def factors(self, pid, team, opp, rest_days, out_mates_now):
        parts = []
        grp = group_of(self.meta, pid)
        # 1) opponent vs position (blend this season with last season's prior)
        r, n = self.dvp.get((opp, grp), (1.0, 0))
        pr = self.prior.get(f"{opp}|{grp}")
        base = pr if pr else 1.0
        f = _cap(1 + ((r - 1) * n + (base - 1) * 30) / (n + 30 + 40))
        if abs(f - 1) >= 0.02:
            parts.append(("opp", f, f"{opp} allows {abs(f - 1) * 100:.0f}% {'more' if f > 1 else 'fewer'} than usual to {grp}s"))
        # 2) pace
        tp, tn = self.pace.get(team, (self.league_pace, 0))
        op, on = self.pace.get(opp, (self.league_pace, 0))
        pace = math.sqrt(_shrink(tp / self.league_pace, tn, 8) * _shrink(op / self.league_pace, on, 8))
        f2 = _cap(1 + (pace - 1) * 0.8, 0.94, 1.06)
        if abs(f2 - 1) >= 0.015:
            parts.append(("pace", f2, f"{'fast' if f2 > 1 else 'slow'} game environment ({(f2 - 1) * 100:+.0f}%)"))
        # 3) minutes trend: last 3 vs expected
        mine = self.by_player.get(pid, [])
        if len(mine) >= 3:
            last3 = mine[-3:]
            m3 = sum(x[4] for x in last3) / 3
            em = mine[-1][9] or m3
            if em and em > 8:
                f3 = _cap(1 + 0.6 * (m3 / em - 1), 0.9, 1.12)
                if abs(f3 - 1) >= 0.02:
                    parts.append(("minutes", f3, f"minutes {'up' if f3 > 1 else 'down'}: {m3:.0f} over his last 3 vs {em:.0f} expected"))
        # 4) teammates out now (skip anyone already out during his last 3 games: the minutes trend has it)
        recent_out = set()
        for x in mine[-3:]:
            recent_out |= set(json.loads(x[10] or "[]"))
        bump = 0.0
        names = []
        for mate_pid, mate, mate_min in out_mates_now:
            if mate_pid in recent_out:
                continue
            bump += (mate_min / 48.0) * 0.30
            names.append(mate)
        if bump:
            f4 = _cap(1 + bump, 1.0, 1.15)
            parts.append(("mates", f4, f"teammates out ({', '.join(names[:3])}): more minutes and shots to go around"))
        # 5) rest
        if rest_days is not None:
            f5 = 0.985 if rest_days == 1 else (1.01 if rest_days >= 3 else 1.0)
            if f5 != 1.0:
                parts.append(("rest", f5, "second night of a back-to-back" if rest_days == 1 else "2+ days of rest"))
        total = 1.0
        for _, f, _ in parts:
            total *= f
        total = _cap(total, 0.82, 1.2)
        return round(total, 3), [{"k": k, "f": round(f, 3), "why": w} for k, f, w in parts]


def last_season_prior(fetch_week, prev_season, scoring, meta, baseline_prev):
    """Opponent-vs-position ratios from last season's per-game logs (built once, cached in state)."""
    path = os.path.join(STATE, f"ctx_prior_{prev_season}.json")
    if os.path.exists(path):
        return json.load(open(path))
    acc = defaultdict(lambda: [0.0, 0])
    empty = 0
    diag = {"weeks": {}, "baseline_n": len(baseline_prev)}
    for w in range(1, 30):
        try:
            rows = fetch_week(prev_season, w)
            diag["weeks"][w] = len(rows)
        except Exception as e:
            rows = []
            diag["weeks"][w] = f"error: {e}"[:120]
        rows = [r for r in rows if r.get("date") and (r.get("stats") or {}).get("min")]
        if not rows:
            empty += 1
            if empty >= 2:
                break
            continue
        for r in rows:
            b = baseline_prev.get(r["player_id"])
            if not b or b < 8 or (r["stats"].get("min") or 0) < 10:
                continue
            a = acc[f"{r.get('opponent')}|{group_of(meta, r['player_id'])}"]
            a[0] += fantasy_points(r["stats"], scoring) / b
            a[1] += 1
    out = {k: round(v[0] / v[1], 4) for k, v in acc.items() if v[1] >= 30}
    diag["pairs"] = len(acc)
    os.makedirs(STATE, exist_ok=True)
    json.dump(diag, open(os.path.join(STATE, "diag_prior.json"), "w"))
    if out:                                          # only cache a real result
        json.dump(out, open(path, "w"))
    return out
