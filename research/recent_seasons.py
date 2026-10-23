"""Re-run the core findings on nba_api LeagueGameLog CSVs (one row per player-game played).
Usage: python recent_seasons.py player_logs_2024-25.csv player_logs_2025-26.csv
"""
import sys
import numpy as np
import pandas as pd

S = dict(pts=1.0, tpm=1.0, reb=2.0, ast=2.0, stl=1.5, blk=1.5, to=0.0, dd=2.0, td=3.0,
         pt40=2.0, pt50=3.0, reb20=3.0, ast15=3.0)


def prep(path):
    d = pd.read_csv(path)
    d = d.rename(columns={"PLAYER_NAME": "player", "TEAM_ABBREVIATION": "team", "GAME_ID": "gid", "PTS": "pts",
                          "FG3M": "tpm", "REB": "reb", "AST": "ast", "STL": "stl", "BLK": "blk", "TOV": "to",
                          "MIN": "min", "FGA": "fga", "FGM": "fgm", "FTA": "fta", "FTM": "ftm", "WL": "wl"})
    d["date"] = pd.to_datetime(d.GAME_DATE)
    d = d[d["min"].fillna(0) > 0].copy()
    cats = d[["pts", "reb", "ast", "stl", "blk"]].ge(10).sum(axis=1)
    d["dd"], d["td"] = (cats >= 2).astype(int), (cats >= 3).astype(int)
    d["fp"] = (d.pts + d.tpm + 2 * d.reb + 2 * d.ast + 1.5 * d.stl + 1.5 * d.blk + 2 * d.dd + 3 * d.td
               + 2 * (d.pts >= 40) + 3 * (d.pts >= 50) + 3 * (d.reb >= 20) + 3 * (d.ast >= 15))
    d["fp_std"] = (d.pts + d.tpm - d.fga + 2 * d.fgm - d.fta + d.ftm + d.reb + 2 * d.ast + 4 * d.stl
                   + 4 * d.blk - 2 * d["to"])
    return d


def report(path):
    p = prep(path)
    season = path.split("_")[-1].replace(".csv", "")
    print(f"\n################ {season}: {len(p)} player-games ################")
    s = p.groupby("player").agg(gp=("fp", "size"), fpg=("fp", "mean"), std=("fp_std", "mean"), reb=("reb", "mean"),
                                ast=("ast", "mean"), pts=("pts", "mean"), ddr=("dd", "mean")).reset_index()
    q = s[s.gp >= 40].copy()
    q["rank"] = q.fpg.rank(ascending=False)
    q["std_rank"] = q["std"].rank(ascending=False)
    print("Top 15:\n", q.sort_values("rank").head(15)[["player", "gp", "fpg", "rank", "std_rank", "reb", "ast", "pts"]].round(1).to_string(index=False))
    v = q.sort_values("fpg", ascending=False).fpg.values
    print("FP/G at rank:", {r: round(float(v[r - 1]), 1) for r in [1, 12, 24, 48, 72, 96, 120, 150, 180]})
    t150 = set(q[q["rank"] <= 150].player)
    pp = p[p.player.isin(t150)]
    parts = {"pts": pp.pts.sum(), "3pm": pp.tpm.sum(), "reb": 2 * pp.reb.sum(), "ast": 2 * pp.ast.sum(),
             "stl": 1.5 * pp.stl.sum(), "blk": 1.5 * pp.blk.sum()}
    tot = pp.fp.sum()
    print("FP share %:", {k: round(100 * x / tot, 1) for k, x in parts.items()}, "other", round(100 * (1 - sum(parts.values()) / tot), 1))
    print("Rebound-first bigs in top 150:", int(((q["rank"] <= 150) & (q.reb >= 8) & (q.ast < 4)).sum()))

    # availability panel
    tg = p.drop_duplicates(["team", "gid"])[["team", "gid", "date"]].sort_values("date")
    tg["b2b2"] = tg.groupby("team").date.diff().dt.days.eq(1)
    wins = p.drop_duplicates(["team", "gid"]).assign(w=lambda x: x.wl.eq("W")).groupby("team").w.mean().rename("winpct")
    span = p.groupby(["player", "team"]).date.agg(["min", "max"]).reset_index()
    pan = span.merge(tg, on="team")
    pan = pan[(pan.date >= pan["min"]) & (pan.date <= pan["max"])]
    pan = pan.merge(p[["player", "team", "gid", "fp", "min"]].rename(columns={"min": "mins"}), on=["player", "team", "gid"], how="left")
    pan["played"] = pan.fp.notna()
    pan = pan.merge(q[["player", "rank"]], on="player", how="left").join(wins, on="team")
    pan["late"] = ((pan.date.dt.month == 3) & (pan.date.dt.day >= 15)) | (pan.date.dt.month == 4)
    pan["bucket"] = pd.cut(pan.winpct, [0, .4, .6, 1], labels=["bad", "mid", "good"])
    top = pan[pan["rank"] <= 100]
    miss = lambda g: round(1 - g.played.mean(), 3)
    print("Top-100 miss rate:", miss(top), "| b2b2:", miss(top[top.b2b2]), "other:", miss(top[~top.b2b2]),
          "| top-30 b2b2:", miss(pan[(pan["rank"] <= 30) & pan.b2b2]))
    print("Late-season miss by team:", {b: miss(top[top.late & (top.bucket == b)]) for b in ["bad", "mid", "good"]},
          "| April:", {b: miss(top[(top.date.dt.month == 4) & (top.bucket == b)]) for b in ["bad", "mid", "good"]},
          "| earlier:", {b: miss(top[~top.late & (top.bucket == b)]) for b in ["bad", "mid", "good"]})

    # return ramp
    c = pan[pan["rank"] <= 150].sort_values(["player", "date"]).copy()
    c["miss"] = (~c.played).astype(int)
    c["blk"] = (c.miss != c.groupby("player").miss.shift()).astype(int).groupby(c.player).cumsum()
    c["runlen"] = c.groupby(["player", "blk"]).miss.transform("sum")
    c["prev_run"] = c.groupby("player").runlen.shift().where(c.groupby("player").miss.shift().eq(1), 0)
    c["ret"] = (c.played & (c.prev_run >= 5)).astype(int).groupby(c.player).cumsum()
    c["since"] = c[c.played].groupby(["player", "ret"]).cumcount()
    avg = c[c.played].groupby("player").agg(am=("mins", "mean"), af=("fp", "mean"))
    c = c.join(avg, on="player")
    r = c[(c.ret > 0) & c.played & (c.since <= 3)]
    print("Return ramp (n, min ratio, fp ratio):", {int(k): (len(g), round((g.mins / g.am).mean(), 2), round((g.fp / g.af).mean(), 2)) for k, g in r.groupby("since")})

    # teammate bump
    t30 = pan[(pan["rank"] <= 30) & ~pan.played][["team", "gid"]].drop_duplicates().assign(out=True)
    tm = pan[(pan["rank"] > 30) & (pan["rank"] <= 200) & pan.played].merge(t30, on=["team", "gid"], how="left")
    tm["out"] = tm.out.fillna(False).astype(bool)
    g = tm.groupby(["player", "out"]).fp.mean().unstack().dropna()
    print("Teammate bump when top-30 sits: median", round(float((g[True] / g[False]).median()), 3), "n", len(g))

    # lock-in values
    V = []
    for name in q[q["rank"] <= 150].player:
        x = p[p.player == name].fp.values
        if len(x) < 40:
            continue
        vals = [x.mean()]
        for k in range(2, 6):
            vals.append(np.maximum(x, vals[-1]).mean())
        V.append([v / x.mean() for v in vals])
    print("Lock-in value by games (median x avg):", np.round(np.median(np.array(V), axis=0), 3).tolist(), "n", len(V))

    # predictors
    b = p.sort_values("date").copy()
    gb = b.groupby("player")
    b["n"] = gb.cumcount()
    b["sa"] = gb.fp.transform(lambda x: x.shift().expanding().mean())
    b["l5"] = gb.fp.transform(lambda x: x.shift().rolling(5).mean())
    b["l1"] = gb.fp.shift()
    b["m5"] = gb["min"].transform(lambda x: x.shift().rolling(5).mean())
    b["fpm"] = gb.fp.transform(lambda x: x.shift().expanding().sum()) / gb["min"].transform(lambda x: x.shift().expanding().sum())
    b["mr"] = b.m5 * b.fpm
    e = b[(b.n >= 10) & (b.sa >= 25)].dropna(subset=["sa", "l5", "l1", "mr"])
    mae = lambda c: round(float(np.mean(np.abs(e.fp - c))), 2)
    print("MAE: last1", mae(e.l1), "last5", mae(e.l5), "season", mae(e.sa), "min x rate", mae(e.mr), "blend", mae(0.5 * e.mr + 0.5 * e.sa))
    e = e.assign(res=e.fp - e.sa)
    e["pres"] = e.groupby("player").res.shift()
    print("Residual autocorrelation:", round(float(e[["res", "pres"]].corr().iloc[0, 1]), 3))


for f in sys.argv[1:]:
    report(f)
