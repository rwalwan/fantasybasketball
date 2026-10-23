"""Availability analysis on a full player x team-game panel (box scores omit inactive players)."""
import numpy as np
import pandas as pd

df = pd.read_parquet("/home/claude/fbb/research/games.parquet")
p = df[df.played]

# player seasons: rank in FP/G among 50+ GP
s = p.groupby(["season_year", "player"]).agg(gp=("fp", "size"), fpg=("fp", "mean")).reset_index()
s["rank"] = s[s.gp >= 40].groupby("season_year").fpg.rank(ascending=False)

team_games = df.drop_duplicates(["season_year", "team", "gameId"])[["season_year", "team", "gameId", "date"]]
team_games = team_games.sort_values("date")
team_games["b2b2"] = team_games.groupby(["season_year", "team"]).date.diff().dt.days.eq(1)

# spans: each player-team stint from first to last appearance (rows of any kind)
span = df.groupby(["season_year", "player", "team"]).date.agg(["min", "max"]).reset_index()
panel = span.merge(team_games, on=["season_year", "team"])
panel = panel[(panel.date >= panel["min"]) & (panel.date <= panel["max"])]
panel = panel.merge(p[["season_year", "player", "team", "gameId", "fp", "min"]].rename(columns={"min": "mins"}),
                    on=["season_year", "player", "team", "gameId"], how="left")
panel["played"] = panel.fp.notna()
panel = panel.merge(s[["season_year", "player", "rank", "fpg"]], on=["season_year", "player"], how="left")

# team win pct
tm = df.groupby(["season_year", "gameId", "team"]).plusMinusPoints.sum().reset_index()
tm["win"] = tm.plusMinusPoints > 0
wp = tm.groupby(["season_year", "team"]).win.mean().rename("winpct").reset_index()
panel = panel.merge(wp, on=["season_year", "team"], how="left")
panel["late"] = ((panel.date.dt.month == 3) & (panel.date.dt.day >= 15)) | (panel.date.dt.month == 4)
panel["bucket"] = pd.cut(panel.winpct, [0, .4, .6, 1], labels=["bad<.40", "mid", "good>.60"])

top = panel[panel["rank"] <= 100]
print("Top-100 players, share of team games missed (within their stint):", round(1 - top.played.mean(), 3))
print("by tier:", panel[panel["rank"] <= 150].assign(tier=lambda x: pd.cut(x["rank"], [0, 30, 75, 150]))
      .groupby("tier", observed=True).played.mean().rsub(1).round(3).to_dict())
print("\nBack-to-back 2nd night miss rate (top-100):", top.groupby("b2b2").played.mean().rsub(1).round(3).to_dict())
t30 = panel[panel["rank"] <= 30]
print("Back-to-back 2nd night miss rate (top-30):", t30.groupby("b2b2").played.mean().rsub(1).round(3).to_dict())
print("\nMiss rate early vs late season (top-100):", top.groupby("late").played.mean().rsub(1).round(3).to_dict())
print("Late-season miss rate by team quality:", top[top.late].groupby("bucket", observed=True).played.mean().rsub(1).round(3).to_dict())
print("Earlier miss rate by team quality:", top[~top.late].groupby("bucket", observed=True).played.mean().rsub(1).round(3).to_dict())
apr = top[top.date.dt.month == 4]
print("April miss rate by team quality:", apr.groupby("bucket", observed=True).played.mean().rsub(1).round(3).to_dict())

# injury return ramp: absences of 5+ consecutive team games
c = panel[panel["rank"] <= 150].sort_values(["season_year", "player", "date"]).copy()
c["miss"] = (~c.played).astype(int)
key = ["season_year", "player"]
c["blk"] = (c.miss != c.groupby(key).miss.shift()).astype(int).groupby([c.season_year, c.player]).cumsum()
runlen = c.groupby(key + ["blk"]).miss.transform("sum")
c["prev_absence"] = np.where(c.miss.eq(0) & c.groupby(key).miss.shift().eq(1),
                             c.groupby(key).apply(lambda g: (g.miss * runlen.loc[g.index]).shift()).reset_index(level=[0, 1], drop=True), 0)
c["ret_id"] = (c.prev_absence >= 5).astype(int).groupby([c.season_year, c.player]).cumsum()
c["since"] = c.groupby(key + ["ret_id"]).cumcount()
avg = c[c.played].groupby(key).agg(avg_min=("mins", "mean"), avg_fp=("fp", "mean"))
c = c.join(avg, on=key)
r = c[(c.ret_id > 0) & c.played & (c.since <= 7)]
print("\nReturn from 5+ game absence (top-150): minutes and FP vs player's season average")
print(r.groupby("since").apply(lambda g: pd.Series({"n": len(g), "min_ratio": (g.mins / g.avg_min).mean(),
                                                     "fp_ratio": (g.fp / g.avg_fp).mean()})).round(3))
print("absences 5+ games count:", int((c.prev_absence >= 5).sum()))

# effect on teammates: when a top-30 player misses, FP change for teammates (top-150 teammates)
miss30 = t30[~t30.played][["season_year", "team", "gameId"]].drop_duplicates()
miss30["star_out"] = True
tmates = panel[(panel["rank"] > 30) & (panel["rank"] <= 200) & panel.played].merge(miss30, on=["season_year", "team", "gameId"], how="left")
tmates["star_out"] = tmates.star_out.fillna(False)
g = tmates.groupby(["season_year", "player", "star_out"]).fp.mean().unstack()
g = g.dropna()
print("\nTeammate FP/G when a top-30 teammate sits vs plays: median ratio", round((g[True] / g[False]).median(), 3),
      "| share of teammates gaining >10%:", round(((g[True] / g[False]) > 1.1).mean(), 3), "n=", len(g))
panel.to_parquet("/home/claude/fbb/research/panel.parquet")
