"""Review 2, F9 refinement: the unused Python week plan (a second copy of site/engine.js) still ran every job and
wrote site/data.json, a parity trap. It's gone; the job keeps only the free-agent watch list it actually used."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import engine, model
ROOT = os.path.join(os.path.dirname(__file__), "..")
assert not hasattr(engine, "WeekPlan"), "the week plan lives in site/engine.js only"
assert "data.json" not in open(os.path.join(ROOT, "app", "run.py")).read()

b = model.PlayerBook({"pts": 1.0}, {"A": {"team": "AAA"}, "B": {"team": "BBB"}, "C": {"team": "CCC", "injury_status": "Out"}, "R": {"team": "AAA"}})
for p, pts in (("A", 30), ("B", 10), ("C", 40), ("R", 50)):
    b.games[p] = [("2026-10-25", pts, 30, "g")]
b.baseline = lambda p: {"A": 30, "B": 10, "C": 40, "R": 50}[p]
assert [r["pid"] for r in engine.free_agent_watch(b, {"R"})] == ["A"], "unrostered, in a rotation, 15+ FP/G, not Out"
print("ok: review 2 F9")
