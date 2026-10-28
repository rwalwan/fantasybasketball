"""Refit P(plays next game | missed k straight) for review finding 5.
Fixes vs the original fit: (1) a player's last stint runs to his TEAM's last game, so absences that never ended
(season-ending injuries) enter as censored instead of vanishing; (2) absences containing a coach's decision,
rest, personal or suspension entry are dropped (not injuries).
Review 2, finding 5: (3) health-and-safety protocol stays (fixed length, 2021-22) and return-to-competition
reconditioning are not injuries either (concussion protocol is); (4) end-of-season shutdowns look like season-ending
injuries, so the last stint is observed only up to the team's 15th-to-last game: absences that reach it are
censored there, and absences starting after it are left out. At-risk counts are printed for every k."""
import json, sys
import numpy as np, pandas as pd
df = pd.read_parquet(sys.argv[1])
p = df[df.played]
s = p.groupby(["season_year", "player"]).agg(gp=("fp", "size"), fpg=("fp", "mean")).reset_index()
s["rank"] = s[s.gp >= 40].groupby("season_year").fpg.rank(ascending=False)
top = set(map(tuple, s[s["rank"] <= 150][["season_year", "player"]].values))
tg = df.drop_duplicates(["season_year", "team", "gameId"])[["season_year", "team", "gameId", "date"]].sort_values("date")
TAIL = 15
team_end = tg.groupby(["season_year", "team"]).date.apply(lambda d: sorted(d)[-TAIL])   # 15th-to-last game
rows = df[[tuple(x) in top for x in df[["season_year", "player"]].values]]
span = rows.groupby(["season_year", "player", "team"]).date.agg(["min", "max"]).reset_index()
last_team = span.sort_values("max").groupby(["season_year", "player"]).tail(1)
span = span.merge(last_team[["season_year", "player", "team"]].assign(last=True), how="left", on=["season_year", "player", "team"])
cut = [team_end[(a, b)] for a, b in zip(span.season_year, span.team)]
span["end"] = np.where(span["last"].eq(True), cut, np.minimum(span["max"].values, np.array(cut, dtype=span["max"].dtype)))
NON_INJ = r"Coach|Rest|Personal|Suspension|SUSPENSION|Trade|Not With Team|Health and Safety|Reconditioning|RECONDITIONING"
runs = []
for _, r in span.iterrows():
    g = tg[(tg.season_year == r.season_year) & (tg.team == r.team) & (tg.date >= r["min"]) & (tg.date <= r["end"])]
    me = rows[(rows.season_year == r.season_year) & (rows.player == r.player) & (rows.team == r.team)].set_index("gameId")
    pl, bad = [], []
    for gid in g.gameId:
        if gid in me.index:
            x = me.loc[gid]; x = x.iloc[0] if isinstance(x, pd.DataFrame) else x
            pl.append(bool(x.played)); bad.append(isinstance(x.comment, str) and bool(pd.Series([x.comment]).str.contains(NON_INJ).iloc[0]))
        else:
            pl.append(False); bad.append(False)
    i, n = 0, len(pl)
    while i < n:
        if not pl[i]:
            j = i
            while j < n and not pl[j]:
                j += 1
            if i > 0 and not any(bad[i:j]):
                runs.append((j - i, j == n))
            i = j
        else:
            i += 1
R = pd.DataFrame(runs, columns=["L", "cens"])
def haz(lo, hi):
    at = ret = 0
    for k in range(lo, hi + 1):
        a = R[R.L >= k]; at += len(a); ret += len(a[(a.L == k) & ~a.cens])
    return (ret / at if at else None), at
out = {"by_k": [round(haz(k, k)[0], 3) for k in range(1, 9)], "k9_12": round(haz(9, 12)[0], 3),
       "k13_20": round(haz(13, 20)[0], 3), "k21p": round(haz(21, 82)[0], 3), "k13p": round(haz(13, 82)[0], 3),
       "n_runs": len(R), "n_censored": int(R.cens.sum()),
       "at_risk": {**{str(k): haz(k, k)[1] for k in range(1, 9)}, "9-12": haz(9, 12)[1], "13-20": haz(13, 20)[1], "21+": haz(21, 82)[1]}}
print(json.dumps(out))
