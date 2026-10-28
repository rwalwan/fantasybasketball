"""Other leagues' scoring: the generic scorer must agree with ours on our settings (incl. turnovers stored as 0)
and handle stats our league doesn't score (fgm/fga, negative turnovers)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import leagues, scoring
ours = {"ast": 20.0, "blk": 15.0, "bonus_ast_15p": 30.0, "bonus_pt_40p": 20.0, "bonus_pt_50p": 30.0, "bonus_reb_20p": 30.0,
        "dd": 20.0, "ff": 0.0, "pts": 10.0, "reb": 20.0, "stl": 15.0, "td": 30.0, "tf": 0.0, "to": 0.0, "tpm": 10.0}
for st in ({"pts": 31, "reb": 12, "ast": 10, "stl": 2, "blk": 1, "to": 4, "tpm": 3}, {"pts": 52, "reb": 21, "ast": 3}):
    assert leagues.fantasy_points(st, ours) == scoring.fantasy_points(st, ours)
other = {"pts": 10.0, "fgm": 20.0, "fga": -10.0, "to": -10.0, "reb": 12.0}
assert leagues.fantasy_points({"pts": 20, "fgm": 8, "fga": 15, "to": 3, "reb": 5}, other) == round((200 + 160 - 150 - 30 + 60) / 10, 2)
print("ok: leagues scoring")
