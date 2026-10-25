"""Insights from the memory store: why games went the way they did, role trends, injury openings.

* why notes   For a player's final game, split (actual - projection) into minutes vs per-minute
              production, flag blowouts / foul trouble / teammates in or out, and tag the result as
              noise (variance) or signal (a real role change). Optional AI one-liner from those facts.
* trends      Minutes-based role changes (fantasy points are too noisy: game-to-game residuals barely
              carry over, minutes do). Up/down when the last 4 games sit >= 5 min off his expectation.
* openings    For rotation players currently Out/Doubtful, which teammates absorbed minutes when he sat
              before (with/without splits), falling back to a position-based estimate.
"""
import datetime as dt
import json
from collections import defaultdict

from .memory import group_of

OUT = {"Out", "Doubtful", "IR", "Suspended"}


def _name(meta, pid):
    m = meta.get(pid) or {}
    return f"{m.get('first_name', '')} {m.get('last_name', '')}".strip() or pid


def player_rows(con, season):
    by = defaultdict(list)
    for r in con.execute("""SELECT pid, date, team, opp, min, fga, pf, fp, margin, exp_min, out_mates,
                                   COALESCE(proj_ctx, proj_model, proj_rw) FROM games WHERE season=? ORDER BY date""", (season,)):
        by[r[0]].append(r)
    return by


def why_notes(con, season, meta, pids, today, llm=None, days=3):
    by = player_rows(con, season)
    since = (dt.date.fromisoformat(today) - dt.timedelta(days=days)).isoformat()
    have = {(p, d) for p, d in con.execute("SELECT pid, date FROM notes WHERE kind='why'")}
    out = []
    for pid in pids:
        rows = by.get(pid, [])
        if not rows:
            continue
        tot_fp = sum(r[7] for r in rows)
        tot_min = sum(r[4] for r in rows) or 1
        fpm = tot_fp / tot_min
        for i, (p, d, team, opp, m, fga, pf, fp, margin, em, om, proj) in enumerate(rows):
            if d < since or (pid, d) in have:
                continue
            proj = proj or (em or m) * fpm
            res = fp - proj
            if abs(res) < max(8.0, 0.25 * proj):
                continue
            em = em or m
            min_eff = (m - em) * fpm
            prev_out = set(json.loads(rows[i - 1][10] or "[]")) if i else set()
            now_out = set(json.loads(om or "[]"))
            facts = {"player": _name(meta, pid), "date": d, "opponent": opp, "fantasy_points": round(fp, 1),
                     "projection": round(proj, 1), "difference": round(res, 1), "minutes": round(m, 1),
                     "expected_minutes": round(em, 1), "points_from_minutes_change": round(min_eff, 1),
                     "points_from_per_minute_production": round(res - min_eff, 1), "shots": int(fga), "fouls": int(pf),
                     "final_margin": margin, "teammates_newly_out": [_name(meta, x) for x in now_out - prev_out][:3],
                     "teammates_back": [_name(meta, x) for x in prev_out - now_out][:3]}
            blowout = abs(margin or 0) >= 20 and m < em - 4
            fouls = pf >= 5 and m < em - 3
            role = abs(m - em) >= 6 and not blowout and not fouls
            tag = "signal" if role or facts["teammates_newly_out"] or facts["teammates_back"] else "noise"
            facts.update(blowout=blowout, foul_trouble=fouls, tag=tag)
            text = None
            if llm:
                try:
                    x = llm("You explain one NBA fantasy game in ONE sentence (max 28 words) from the facts given. "
                            "Lead with the main cause (minutes, efficiency, blowout, fouls, teammates). Say whether it "
                            "looks like a one-off or a role change, per the 'tag' field. Reply as JSON {\"text\": \"...\"}.",
                            json.dumps(facts))
                    text = (x or {}).get("text")
                except Exception as e:
                    print("why note llm failed:", e)
            if not text:
                cause = ("a blowout cut his minutes" if blowout else "foul trouble" if fouls else
                         f"minutes {'up' if m > em else 'down'} ({m:.0f} vs {em:.0f})" if abs(m - em) >= 4 else
                         f"{'hot' if res > 0 else 'cold'} per-minute production")
                text = f"{res:+.1f} vs projection ({fp:.1f} vs {proj:.1f}): {cause}. Looks like {'a role change' if tag == 'signal' else 'a one-off'}."
            con.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?,?,?,?)", (pid, d, "why", tag, text, json.dumps(facts)))
            out.append({"pid": pid, "date": d, "tag": tag, "text": text, **facts})
    con.commit()
    return out


def recent_notes(con, pids=None, limit=60):
    q = "SELECT pid, date, tag, text, facts FROM notes WHERE kind='why' ORDER BY date DESC LIMIT ?"
    rows = con.execute(q, (limit * 4,)).fetchall()
    out = []
    for pid, d, tag, text, facts in rows:
        if pids is not None and pid not in pids:
            continue
        f = json.loads(facts)
        out.append({"pid": pid, "date": d, "tag": tag, "text": text, "player": f.get("player"),
                    "diff": f.get("difference"), "fp": f.get("fantasy_points"), "proj": f.get("projection")})
        if len(out) >= limit:
            break
    return out


def trends(con, season, meta, pids=None):
    by = player_rows(con, season)
    out = []
    for pid, rows in by.items():
        if pids is not None and pid not in pids:
            continue
        if len(rows) < 5:
            continue
        last4 = rows[-4:]
        em = last4[0][9] or (sum(r[4] for r in rows[:-4]) / max(1, len(rows) - 4))
        m4 = sum(r[4] for r in last4) / 4
        above = sum(1 for r in last4 if r[4] >= em + 3)
        below = sum(1 for r in last4 if r[4] <= em - 3)
        if m4 - em >= 5 and above >= 3:
            direction = "up"
        elif em - m4 >= 5 and below >= 3:
            direction = "down"
        else:
            continue
        before_out = set(json.loads(rows[-5][10] or "[]"))
        recent_out = set().union(*[set(json.loads(r[10] or "[]")) for r in last4])
        why = f"minutes {m4:.0f} over his last 4 vs {em:.0f} before"
        new_out = recent_out - before_out
        if direction == "up" and new_out:
            why += f", with {', '.join(_name(meta, x) for x in list(new_out)[:2])} out"
        fp4 = sum(r[7] for r in last4) / 4
        out.append({"pid": pid, "player": _name(meta, pid), "team": rows[-1][2], "dir": direction,
                    "min4": round(m4, 1), "exp": round(em, 1), "fp4": round(fp4, 1), "why": why})
    out.sort(key=lambda x: -abs(x["min4"] - x["exp"]))
    return out


def openings(con, season, meta, rostered):
    """Rotation players currently out -> who gains, from with/without splits when available."""
    by = player_rows(con, season)
    avg_min = {p: sum(r[4] for r in rs) / len(rs) for p, rs in by.items() if rs}
    team_of = {p: (meta.get(p) or {}).get("team") for p in meta}
    out = []
    for pid, m in meta.items():
        if m.get("injury_status") not in OUT or not m.get("team") or avg_min.get(pid, 0) < 24:
            continue
        team = m["team"]
        mates = [p for p, rs in by.items() if p != pid and team_of.get(p) == team and rs]
        gains = []
        for mate in mates:
            rs = [r for r in by[mate] if r[2] == team]
            without = [r for r in rs if pid in json.loads(r[10] or "[]")]
            with_ = [r for r in rs if pid not in json.loads(r[10] or "[]")]
            if len(without) >= 2 and len(with_) >= 2:
                dm = sum(r[4] for r in without) / len(without) - sum(r[4] for r in with_) / len(with_)
                dfp = sum(r[7] for r in without) / len(without) - sum(r[7] for r in with_) / len(with_)
                basis = f"{len(without)} games without him"
            else:
                same = group_of(meta, mate) == group_of(meta, pid)
                dm = avg_min[pid] * (0.25 if same else 0.08) * min(1, avg_min.get(mate, 0) / 20)
                rate = (sum(r[7] for r in rs) / max(1, sum(r[4] for r in rs))) if rs else 0.9
                dfp = dm * rate
                basis = "estimate (no games without him yet)"
            if dfp > 1.5:
                gains.append({"pid": mate, "player": _name(meta, mate), "dmin": round(dm, 1), "dfp": round(dfp, 1),
                              "rostered": mate in rostered, "basis": basis})
        gains.sort(key=lambda g: -g["dfp"])
        if gains:
            out.append({"pid": pid, "player": _name(meta, pid), "team": team, "status": m.get("injury_status"),
                        "min": round(avg_min[pid], 1), "gainers": gains[:4]})
    out.sort(key=lambda o: -o["min"])
    return out
