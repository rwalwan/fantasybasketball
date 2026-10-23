"""Lock-In mode: each starter's weekly score is ONE game you lock after it is played.
Optimal stopping: with k games left, lock now if score >= V(k-1), where V(1)=E[X], V(k)=E[max(X, V(k-1))].
Uses each player's own empirical game distribution (top-150 player-seasons)."""
import numpy as np
import pandas as pd

df = pd.read_parquet("/home/claude/fbb/research/games.parquet")
p = df[df.played]
s = p.groupby(["season_year", "player"]).fp.agg(["mean", "size"]).reset_index()
s = s[s["size"] >= 50]
s["rank"] = s.groupby("season_year")["mean"].rank(ascending=False)
top = s[s["rank"] <= 150]

rows = []
for _, r in top.iterrows():
    x = np.sort(p[(p.season_year == r.season_year) & (p.player == r.player)].fp.values)
    V = [x.mean()]
    for k in range(2, 6):
        V.append(np.maximum(x, V[-1]).mean())
    prophet = [np.mean([np.max(np.random.choice(x, k)) for _ in range(2000)]) for k in range(1, 6)]
    rows.append(dict(player=r.player, season=r.season_year, rank=r["rank"], mean=x.mean(),
                     **{f"V{k}": V[k - 1] for k in range(1, 6)}, **{f"max{k}": prophet[k - 1] for k in range(1, 6)},
                     **{f"thr{k}": V[k - 2] if k > 1 else 0 for k in range(2, 6)}))
R = pd.DataFrame(rows)
print("Expected locked score / player's average, by games available that week (optimal thresholds)")
print((R[[f"V{k}" for k in range(1, 6)]].div(R["mean"], axis=0)).median().round(3).to_string())
print("Perfect hindsight (best game of k) / average")
print((R[[f"max{k}" for k in range(1, 6)]].div(R["mean"], axis=0)).median().round(3).to_string())
print("\nLock threshold as multiple of the player's average, with N games still to come after this one:")
for k, c in zip(range(2, 6), ["V1", "V2", "V3", "V4"]):
    print(f"  {k-1} game(s) left -> lock if score >= {np.median(R[c] / R['mean']):.2f} x average")
print("\nNaive 'lock first game' = 1.00x; 'always wait for last game' = 1.00x (and zero if he sits).")

# Value of a 4-game week vs 2-game week in points, for a tier-2 player (~50 FP/G)
m = 50
r2 = np.median(R.V2 / R["mean"]); r4 = np.median(R.V4 / R["mean"]); r3 = np.median(R.V3 / R["mean"])
print(f"\nFor a 50 FP/G player: 2 games ~{m*r2:.1f}, 3 games ~{m*r3:.1f}, 4 games ~{m*r4:.1f} locked FP")

# DNP risk: if he sits the last game and you hadn't locked, slot scores the final-game result (0).
R.to_csv("/home/claude/fbb/research/lockin_values.csv", index=False)
