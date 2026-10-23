"""Load NBA player box scores and re-score them in the 'we back' Sleeper format."""
import glob
import numpy as np
import pandas as pd

SRC = "/home/claude/nocturnebear/nba-data-2010-2024"
SEASONS = ["2021-22", "2022-23", "2023-24"]

# Sleeper league "we back" scoring, divided by 10 (Sleeper stores them x10).
SCORING = dict(pts=1.0, tpm=1.0, reb=2.0, ast=2.0, stl=1.5, blk=1.5, to=0.0,
               dd=2.0, td=3.0, pt40=2.0, pt50=3.0, reb20=3.0, ast15=3.0)


def minutes(s):
    if not isinstance(s, str) or ":" not in s:
        return 0.0
    m, sec = s.split(":")[:2]
    try:
        return float(m) + float(sec) / 60
    except ValueError:
        return 0.0


def load():
    parts = sorted(glob.glob(f"{SRC}/regular_season_box_scores_2010_2024_part_*.csv"))
    df = pd.concat([pd.read_csv(p, low_memory=False) for p in parts], ignore_index=True)
    df = df[df.season_year.isin(SEASONS)].copy()
    df = df.rename(columns={"points": "pts", "threePointersMade": "tpm", "reboundsTotal": "reb",
                            "assists": "ast", "steals": "stl", "blocks": "blk", "turnovers": "to",
                            "personName": "player", "personId": "pid", "teamTricode": "team"})
    df["date"] = pd.to_datetime(df.game_date)
    df["min"] = df["minutes"].map(minutes)
    df["played"] = df["min"] > 0
    cats = df[["pts", "reb", "ast", "stl", "blk"]].ge(10).sum(axis=1)
    df["dd"] = (cats >= 2).astype(int)
    df["td"] = (cats >= 3).astype(int)
    df["fp"] = score(df)
    df["fp_std"] = standard_points(df)
    return df


def score(df, s=SCORING):
    # Assumes stacked bonuses (a 50-pt game earns both 40+ and 50+; a TD also counts as a DD).
    return (df.pts * s["pts"] + df.tpm * s["tpm"] + df.reb * s["reb"] + df.ast * s["ast"]
            + df.stl * s["stl"] + df.blk * s["blk"] - df["to"] * s["to"]
            + df.dd * s["dd"] + df.td * s["td"]
            + (df.pts >= 40) * s["pt40"] + (df.pts >= 50) * s["pt50"]
            + (df.reb >= 20) * s["reb20"] + (df.ast >= 15) * s["ast15"])


def standard_points(df):
    """ESPN default points scoring, for comparison."""
    return (df.pts + df.tpm - df.fieldGoalsAttempted + 2 * df.fieldGoalsMade - df.freeThrowsAttempted
            + df.freeThrowsMade + df.reb + 2 * df.ast + 4 * df.stl + 4 * df.blk - 2 * df["to"])


if __name__ == "__main__":
    df = load()
    df.to_parquet("/home/claude/fbb/research/games.parquet")
    print(df.groupby("season_year").agg(rows=("fp", "size"), played=("played", "sum")))
