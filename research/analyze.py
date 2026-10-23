import numpy as np
import pandas as pd

pd.set_option("display.width", 200)
df = pd.read_parquet("/home/claude/fbb/research/games.parquet")
p = df[df.played].copy()
p["week"] = p.date.dt.to_period("W-SUN")  # Mon-Sun fantasy weeks


def section(t):
    print("\n" + "=" * 8, t, "=" * 8)


# 1. Season value: FP/G, games, total; rank in our scoring vs ESPN standard
section("1. Top 25 by FP/G (min 50 GP), 2023-24, with rank under ESPN standard")
s = p.groupby(["season_year", "player"]).agg(gp=("fp", "size"), fpg=("fp", "mean"), std_fpg=("fp_std", "mean"),
                                             mpg=("min", "mean"), ddr=("dd", "mean"), tdr=("td", "mean"),
                                             reb=("reb", "mean"), ast=("ast", "mean"), pts=("pts", "mean"),
                                             tpm=("tpm", "mean"), to=("to", "mean")).reset_index()
q = s[s.gp >= 50].copy()
q["rank"] = q.groupby("season_year").fpg.rank(ascending=False)
q["std_rank"] = q.groupby("season_year").std_fpg.rank(ascending=False)
q["rank_gain"] = q.std_rank - q["rank"]
print(q[q.season_year == "2023-24"].sort_values("rank").head(25)[
    ["player", "gp", "fpg", "rank", "std_rank", "ddr", "tdr", "reb", "ast", "pts"]].round(2).to_string(index=False))

section("2. Biggest risers / fallers vs ESPN standard (top-150 in either), all 3 seasons pooled")
top = q[(q["rank"] <= 150) | (q.std_rank <= 150)]
print("RISERS");
print(top.sort_values("rank_gain", ascending=False).head(15)[["season_year", "player", "rank", "std_rank", "reb", "ast", "pts", "to"]].round(1).to_string(index=False))
print("FALLERS");
print(top.sort_values("rank_gain").head(15)[["season_year", "player", "rank", "std_rank", "reb", "ast", "pts", "to", "tpm"]].round(1).to_string(index=False))

section("3. Share of fantasy points by source (top-150 players)")
t150 = q[q["rank"] <= 150]
names = set(zip(t150.season_year, t150.player))
pp = p[[k in names for k in zip(p.season_year, p.player)]]
src = pd.Series({"pts": pp.pts.sum(), "3pm": pp.tpm.sum(), "reb": 2 * pp.reb.sum(), "ast": 2 * pp.ast.sum(),
                 "stl": 1.5 * pp.stl.sum(), "blk": 1.5 * pp.blk.sum(), "dd/td": 2 * pp.dd.sum() + 3 * pp.td.sum(),
                 "bonuses": pp.fp.sum() - (pp.pts + pp.tpm + 2 * pp.reb + 2 * pp.ast + 1.5 * pp.stl + 1.5 * pp.blk + 2 * pp.dd + 3 * pp.td).sum()})
print((src / src.sum() * 100).round(1).to_string())

section("4. FP/G by rank tier (replacement level). 12 teams x 10 starters = 120; x15 rostered = 180")
for season, g in q.groupby("season_year"):
    v = g.sort_values("fpg", ascending=False).fpg.values
    print(season, {r: round(v[r - 1], 1) for r in [1, 12, 24, 48, 72, 96, 120, 150, 180, 220]})

section("4b. Position profile: use rebounds/assists proxy. Bigs = reb>=8 & ast<4; creators = ast>=6")
g = q[q["rank"] <= 150]
print("bigs", (g[(g.reb >= 8) & (g.ast < 4)].groupby("season_year").size()).to_dict(),
      "creators", (g[g.ast >= 6].groupby("season_year").size()).to_dict())

section("5. Team games per Mon-Sun week (regular season)")
tg = df.drop_duplicates(["gameId", "team"]).copy()
tg["week"] = tg.date.dt.to_period("W-SUN")
gpw = tg.groupby(["season_year", "week", "team"]).size()
print(gpw.groupby(level=0).value_counts().unstack(fill_value=0))
dow = tg.date.dt.day_name().value_counts()
print("Team-games by weekday (all seasons):", dow.to_dict())

section("6. Weekly consistency of top-100 players: weekly FP total CV and correlation of weekly FP/G")
w = p.groupby(["season_year", "player", "week"]).agg(fp=("fp", "sum"), g=("fp", "size"), fpg=("fp", "mean")).reset_index()
t100 = set(zip(q[q["rank"] <= 100].season_year, q[q["rank"] <= 100].player))
w100 = w[[k in t100 for k in zip(w.season_year, w.player)]]
cv = w100.groupby(["season_year", "player"]).fpg.agg(lambda x: x.std() / x.mean())
print("median CV of weekly FP/G:", round(cv.median(), 3))
gm = p[[k in t100 for k in zip(p.season_year, p.player)]]
gcv = gm.groupby(["season_year", "player"]).fp.agg(lambda x: x.std() / x.mean())
print("median CV of single-game FP:", round(gcv.median(), 3))
# share of weekly total explained by games played
print("corr(weekly FP total, games played) top-100:", round(w100.fp.corr(w100.g), 3))

section("7. Back-to-backs: FP/G and DNP rate on 2nd night vs other games (top-100 players)")
a = df.sort_values("date").copy()
a["prev"] = a.groupby(["season_year", "team"]).date.shift(0)
team_dates = df.drop_duplicates(["team", "date"])[["team", "date"]].sort_values(["team", "date"])
team_dates["b2b2"] = team_dates.groupby("team").date.diff().dt.days.eq(1)
a = a.merge(team_dates, on=["team", "date"], how="left")
a100 = a[[k in t100 for k in zip(a.season_year, a.player)]]
dnp = a100.assign(dnp=~a100.played).groupby("b2b2").agg(dnp_rate=("dnp", "mean"))
fpg = a100[a100.played].groupby("b2b2").fp.mean()
print(pd.concat([dnp, fpg.rename("fp_when_played")], axis=1).round(3))
# for stars (top 30)
t30 = set(zip(q[q["rank"] <= 30].season_year, q[q["rank"] <= 30].player))
a30 = a[[k in t30 for k in zip(a.season_year, a.player)]]
print("top-30 DNP rate by b2b2:", a30.assign(dnp=~a30.played).groupby("b2b2").dnp.mean().round(3).to_dict())
print("top-30 DNP comments on b2b2:", a30[(~a30.played) & a30.b2b2].comment.fillna("").str[:25].value_counts().head(6).to_dict())

section("8. Late season (from Mar 15): DNP rate and FP/G vs earlier, top-100 players")
a100 = a100.copy()
a100["late"] = (a100.date.dt.month == 3) & (a100.date.dt.day >= 15) | (a100.date.dt.month == 4)
print(a100.assign(dnp=~a100.played).groupby("late").agg(dnp=("dnp", "mean")).join(
    a100[a100.played].groupby("late").agg(fpg=("fp", "mean"), mpg=("min", "mean"))).round(3))
# by team record proxy: teams' final win%
games = df.drop_duplicates(["gameId", "team"])[["gameId", "team", "season_year", "plusMinusPoints"]]
# team plus-minus at team level per game: use player sum /5
tm = df.groupby(["season_year", "gameId", "team"]).plusMinusPoints.sum().div(5).reset_index()
tm["win"] = tm.plusMinusPoints > 0
wp = tm.groupby(["season_year", "team"]).win.mean().rename("winpct").reset_index()
a100 = a100.merge(wp, on=["season_year", "team"], how="left")
a100["bucket"] = pd.cut(a100.winpct, [0, .4, .6, 1], labels=["bad(<.40)", "mid", "good(>.60)"])
print(a100[a100.late].assign(dnp=lambda x: ~x.played).groupby("bucket", observed=True).dnp.mean().round(3).to_dict(),
      "<- late-season DNP rate by team quality")
print(a100[~a100.late].assign(dnp=lambda x: ~x.played).groupby("bucket", observed=True).dnp.mean().round(3).to_dict(),
      "<- earlier-season DNP rate by team quality")
# April only
a100["april"] = a100.date.dt.month == 4
print("April DNP by bucket:", a100[a100.april].assign(dnp=lambda x: ~x.played).groupby("bucket", observed=True).dnp.mean().round(3).to_dict())

section("9. Prediction: what best predicts next game FP? (players with >=10 prior games)")
b = p.sort_values("date").copy()
gb = b.groupby(["season_year", "player"]).fp
b["n"] = gb.cumcount()
b["season_avg"] = gb.transform(lambda x: x.shift().expanding().mean())
b["last5"] = gb.transform(lambda x: x.shift().rolling(5).mean())
b["last10"] = gb.transform(lambda x: x.shift().rolling(10).mean())
b["last1"] = gb.shift()
b["min_last5"] = b.groupby(["season_year", "player"])["min"].transform(lambda x: x.shift().rolling(5).mean())
b["fpm_season"] = b.groupby(["season_year", "player"]).apply(
    lambda g: (g.fp.shift().expanding().sum() / g["min"].shift().expanding().sum())).reset_index(level=[0, 1], drop=True)
b["min_x_rate"] = b.min_last5 * b.fpm_season
e = b[(b.n >= 10)].dropna(subset=["season_avg", "last5", "last10", "last1", "min_x_rate"])
e = e[e.season_avg >= 25]
for c in ["last1", "last5", "last10", "season_avg", "min_x_rate"]:
    print(f"{c:12s} MAE {np.mean(np.abs(e.fp - e[c])):.2f}")
for wgt in [0.3, 0.5, 0.7]:
    blend = wgt * e.min_x_rate + (1 - wgt) * e.season_avg
    print(f"blend {wgt} min_x_rate + season_avg MAE {np.mean(np.abs(e.fp - blend)):.2f}")
# hot hand: residual persistence
e = e.assign(res=e.fp - e.season_avg)
e["prev_res"] = e.groupby(["season_year", "player"]).res.shift()
print("corr(prev game residual, this game residual):", round(e[["res", "prev_res"]].corr().iloc[0, 1], 3))

section("10. Injury return: games after an absence of 5+ team games (top-150). Minutes vs season avg")
c = a[[k in names for k in zip(a.season_year, a.player)]].sort_values("date").copy()
c["miss"] = (~c.played).astype(int)
c["run"] = c.groupby(["season_year", "player"]).miss.transform(lambda x: x.groupby((x != x.shift()).cumsum()).cumsum())
c["prev_run"] = c.groupby(["season_year", "player"]).run.shift()
c["return_game"] = c.played & (c.prev_run >= 5)
c["ret_idx"] = np.nan
idx = c.groupby(["season_year", "player"]).return_game.cumsum()
c["since_return"] = c.groupby(["season_year", "player", idx]).cumcount()
avg_min = c[c.played].groupby(["season_year", "player"])["min"].mean().rename("avg_min")
avg_fp = c[c.played].groupby(["season_year", "player"]).fp.mean().rename("avg_fp")
c = c.join(avg_min, on=["season_year", "player"]).join(avg_fp, on=["season_year", "player"])
r = c[(idx > 0) & c.played & (c.since_return <= 5)]
print((r.groupby("since_return").apply(lambda g: pd.Series({"n": len(g), "min_ratio": (g["min"] / g.avg_min).mean(),
                                                           "fp_ratio": (g.fp / g.avg_fp).mean()}))).round(3))

section("11. Double-double rates and what a DD is worth (top-150)")
print(t150.sort_values("ddr", ascending=False).groupby("season_year").head(5)[["season_year", "player", "ddr", "tdr", "fpg"]].round(2).to_string(index=False))
