"""Fit the usage model: how much a player's fantasy output moves when rotation players are out.

Data: 2021-24 box scores (games.parquet) and the player x team-game panel (panel.parquet; within a player's stint,
missing box-score rows = did not play). Usage: python research/usage_fit.py <games.parquet> <panel.parquet> <out.json>

For every game a player (15+ min/game, 20+ games that season) played:
  y        = FP / his season average - 1
  features = minutes of absent rotation players (20+ min/game), in units of 48 minutes, split by
             * own team, same position group     * own team, other groups
             * opponent, same position group (the likely primary defender)   * opponent, other groups
             * opponent rim protection lost: blocks/game of absent opponent rotation players
Position group: the player's most common starting position (G/F/C) in box scores, else from his per-36 profile.
Fitted separately for starters (28+ min/game) and bench players, by least squares; reported with
leave-one-season-out error so we can see whether it predicts at all.
"""
import json
import sys

import numpy as np
import pandas as pd

games, panel = pd.read_parquet(sys.argv[1]), pd.read_parquet(sys.argv[2])
out_path = sys.argv[3]

# --- player-season profile: avg minutes, avg FP, games, position group
pl = games[games.played]
prof = pl.groupby(["season_year", "player"]).agg(gp=("fp", "size"), fpg=("fp", "mean"), mpg=("min", "mean"),
                                                 ast=("ast", "sum"), reb=("reb", "sum"), blk=("blk", "mean"),
                                                 mins=("min", "sum")).reset_index()
pos = pl.dropna(subset=["position"]).groupby(["season_year", "player"]).position.agg(lambda s: s.mode().iloc[0]).rename("start_pos")
prof = prof.join(pos, on=["season_year", "player"])
a36, r36 = prof.ast / prof.mins * 36, prof.reb / prof.mins * 36
stat_pos = np.where(a36 >= 4.5, "G", np.where(r36 >= 9, "C", "F"))
prof["grp"] = prof.start_pos.fillna(pd.Series(stat_pos, index=prof.index))
P = prof.set_index(["season_year", "player"])

# --- who was absent each team-game: rotation players (20+ mpg, 20+ gp) with a panel row and no appearance
pan = panel.drop(columns=["fpg"]).join(P[["mpg", "gp", "grp", "fpg", "blk"]], on=["season_year", "player"])
rot = pan[(pan.mpg >= 20) & (pan.gp >= 20)]
absent = rot[~rot.played]
team_of_game = games.drop_duplicates(["gameId", "team"])[["gameId", "team"]]
opp = team_of_game.merge(team_of_game, on="gameId", suffixes=("", "_opp"))
opp = opp[opp.team != opp.team_opp][["gameId", "team", "team_opp"]]
ab = absent.groupby(["gameId", "team", "grp"]).mpg.sum().div(48).rename("m").reset_index()
# rim protection lost: blocks per game of absent rotation players (affects interior scoring for every position)
rim = absent.groupby(["gameId", "team"]).blk.sum()


def missing(gid_team_grp):
    return ab.set_index(["gameId", "team", "grp"]).m.reindex(gid_team_grp, fill_value=0.0).values


rows = pl.join(P[["mpg", "gp", "grp", "fpg"]], on=["season_year", "player"])
rows = rows[(rows.mpg >= 15) & (rows.gp >= 20) & (rows.fpg > 5)].merge(opp, on=["gameId", "team"])
abt = ab.groupby(["gameId", "team"]).m.sum()
rows["tm_all"] = abt.reindex(list(zip(rows.gameId, rows.team)), fill_value=0.0).values
rows["tm_same"] = missing(list(zip(rows.gameId, rows.team, rows.grp)))
rows["op_all"] = abt.reindex(list(zip(rows.gameId, rows.team_opp)), fill_value=0.0).values
rows["op_same"] = missing(list(zip(rows.gameId, rows.team_opp, rows.grp)))
rows["tm_other"], rows["op_other"] = rows.tm_all - rows.tm_same, rows.op_all - rows.op_same
rows["op_rim"] = rim.reindex(list(zip(rows.gameId, rows.team_opp)), fill_value=0.0).values
rows["y"] = rows.fp / rows.fpg - 1
# Tested and dropped: opponent absences by position (same group = likely primary defender), with or without
# weighting by the absent defender's steals+blocks: leave-one-season-out gain within +/-0.01 FP of nothing.
# Opponent rim protection lost is small but consistent (+1-2% per absent block/game), so it stays.
F = ["tm_same", "tm_other", "op_rim"]
# A player's season average already reflects how often his team is short-handed, so what matters is how many MORE
# minutes are missing tonight than in his typical game: features are centered on his season mean.
league_mean = {f: round(float(rows[f].mean()), 4) for f in F}      # reference for players with little history
for f in F:
    rows[f] = rows[f] - rows.groupby(["season_year", "player"])[f].transform("mean")

out = {"note": __doc__.strip().split("\n")[0], "features": F, "league_mean": league_mean, "groups": {}}
for name, m in (("starter", rows.mpg >= 28), ("bench", rows.mpg < 28)):
    d = rows[m]
    X = np.column_stack([np.ones(len(d))] + [d[f].values for f in F])
    y = d.y.values
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    # leave-one-season-out: does the fit beat 'no adjustment' (y_hat = 0) on an unseen season?
    gain = []
    for s in sorted(d.season_year.unique()):
        tr, te = (d.season_year != s).values, (d.season_year == s).values
        c, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
        pred = X[te][:, 1:] @ c[1:]                     # intercept excluded at prediction: baseline stays the mean
        e0, e1 = d.fp.values[te] - d.fpg.values[te], d.fp.values[te] - d.fpg.values[te] * (1 + pred)
        gain.append({"mae": round(float(np.abs(e0).mean() - np.abs(e1).mean()), 3),
                     "rmse": round(float(np.sqrt((e0 ** 2).mean()) - np.sqrt((e1 ** 2).mean())), 3)})
    affected = (d[["tm_same", "tm_other"]].sum(axis=1) > 0.3).values     # 15+ more teammate minutes out than usual
    out["groups"][name] = {"coef": {f: round(float(c), 4) for f, c in zip(F, coef[1:])}, "n": int(len(d)),
                           "n_with_absence": int(affected.sum()), "loso_mae_gain_fp": gain,
                           "mean_effect_when_teammate_out": round(float((X[affected][:, 1:3] @ coef[1:3]).mean()), 4)}
json.dump(out, open(out_path, "w"), indent=1)
print(json.dumps(out, indent=1))
