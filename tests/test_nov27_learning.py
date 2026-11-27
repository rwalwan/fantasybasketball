"""Nov 27: passive learning. Before, the fitted numbers only changed when a Claude session refit them, and graded
predictions were recorded but never fed back. The nightly trainer (app/train.py) refits each model and promotes a new
version only if it is clearly better on held-out days, inside hard limits, moved by a capped step; it then watches
the new version for 7 days and reverts it automatically if it does worse. These tests pin that machinery:
  1. a clearly better refit is promoted (and the live version is a capped step toward the fit);
  2. a refit that is not clearly better, or breaks a limit, is not;
  3. a promoted version that does worse on new games is reverted, one that doesn't is kept after the watch;
  4. LEARNING=off trains nothing and makes the job ignore learned numbers;
  5. the archive keeps every graded record once (the state log keeps only the newest 3,000).
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from app import train as T, learned


class Coin(T.Model):
    """Toy model: one probability p for Bernoulli rows; step cap 0.2; limit p <= 0.9."""
    name, title, min_train, min_hold = "coin", "coin", 50, 50

    def __init__(self, rows): self._rows = rows
    def rows(self, ctx): return self._rows
    def factory(self, ctx): return {"p": 0.1}
    def fit(self, rows, base): return {"p": (base["p"] * 20 + sum(r["y"] for r in rows)) / (20 + len(rows))}
    def loss(self, P, rows):
        p = np.clip(P["p"], .01, .99); y = np.array([r["y"] for r in rows], float)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))
    def bounds(self, P): return None if P["p"] <= 0.9 else f"p={P['p']}"
    def step(self, o, n): return {"p": round(o["p"] + float(np.clip(n["p"] - o["p"], -0.2, 0.2)), 4)}


def days(start, n):
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def make(rate, ds, per=20, seed=1):
    rng = np.random.default_rng(seed)
    return [{"day": d, "y": int(rng.random() < rate)} for d in ds for _ in range(per)]


# 1) truth 0.5, factory says 0.1: promoted, live p is a 0.2 step (0.3), watched for 7 days
rows = make(0.5, days("2026-11-01", 30))
doc = {"models": {}, "log": []}
assert T.run_model(Coin(rows), {}, doc, "2026-12-01") == "promoted", doc["log"]
e = doc["models"]["coin"]
assert e["params"] == {"p": 0.3} and e["previous"] == {"p": 0.1} and e["status"] == "watching", e
assert e["watch_until"] == "2026-12-08", e
assert doc["log"][-1]["event"] == "promoted" and doc["log"][-1]["ci"][0] > 0, doc["log"][-1]
print("ok: a clearly better refit is promoted by a capped step and watched")

# no new promotion while watching
assert T.run_model(Coin(rows), {}, doc, "2026-12-02") == "watching"
print("ok: no new promotion during the watch")

# 2) truth equals the factory: not promoted
doc2 = {"models": {}, "log": []}
assert T.run_model(Coin(make(0.1, days("2026-11-01", 30), seed=2)), {}, doc2, "2026-12-01") == "kept current"
assert "coin" not in doc2["models"]
print("ok: a refit that isn't clearly better is not promoted")

# a fit that breaks a limit (truth 1.0, would step past 0.9 from 0.85) is not promoted
doc3 = {"models": {"coin": {"params": {"p": 0.85}, "status": "kept", "since": "2026-10-01"}}, "log": []}
assert T.run_model(Coin([{"day": d, "y": 1} for d in days("2026-11-01", 30) for _ in range(20)]), {}, doc3, "2026-12-01") == "kept current"
assert doc3["models"]["coin"]["params"] == {"p": 0.85} and "safety limit" in doc3["log"][-1]["why"], doc3["log"]
print("ok: a fit outside the hard limits is not promoted")

# too little data: skipped, nothing changes
doc4 = {"models": {}, "log": []}
assert T.run_model(Coin(make(0.5, days("2026-11-25", 3))), {}, doc4, "2026-12-01") == "skipped"
print("ok: not enough data -> skipped")

# 3) after promotion the truth turns out to be the old 0.1 (new games): clearly worse -> reverted, cooldown
post = make(0.1, days("2026-12-01", 5), per=40, seed=3)
assert T.run_model(Coin(rows + post), {}, doc, "2026-12-06") == "reverted", doc["log"][-1]
assert doc["models"]["coin"]["params"] == {"p": 0.1} and doc["models"]["coin"]["status"] == "kept"
assert T.run_model(Coin(rows + post), {}, doc, "2026-12-07") == "cooldown"
print("ok: a promoted version that does worse is reverted, then a cooldown")

# ... and one that holds up is kept when the watch ends
doc5 = {"models": {}, "log": []}
T.run_model(Coin(rows), {}, doc5, "2026-12-01")
post = make(0.5, days("2026-12-01", 8), per=30, seed=4)
assert T.run_model(Coin(rows + post), {}, doc5, "2026-12-05") == "watching"
assert T.run_model(Coin(rows + post), {}, doc5, "2026-12-08") == "kept after watch", doc5["log"][-1]
assert doc5["models"]["coin"]["status"] == "kept" and doc5["models"]["coin"]["params"] == {"p": 0.3}
print("ok: a version that holds up is kept after the 7-day watch")

# rows dated today or later never count (today's games aren't final)
doc6 = {"models": {}, "log": []}
assert T.run_model(Coin(make(0.5, days("2026-12-01", 30))), {}, doc6, "2026-12-01") == "skipped"
print("ok: only finished days are used")

# 4) LEARNING=off
tmp = tempfile.mkdtemp()
json.dump({"models": {"coin": {"params": {"p": 0.3}}}, "log": []}, open(os.path.join(tmp, "learned.json"), "w"))
assert learned.get("coin", tmp) == {"p": 0.3}
os.environ["LEARNING"] = "off"
try:
    assert learned.get("coin", tmp) is None
    T.LEARN = tempfile.mkdtemp()
    assert T.main(today="2026-12-01", models=[Coin(rows)]) == {}
    assert not os.path.exists(os.path.join(T.LEARN, "learned.json"))
finally:
    del os.environ["LEARNING"]
assert learned.get("coin", os.path.join(tmp, "nope")) is None            # no file = factory
open(os.path.join(tmp, "learned.json"), "w").write("{bad")
assert learned.get("coin", tmp) is None                                  # corrupt = factory in the job
print("ok: LEARNING=off, a missing or corrupt file -> factory numbers")

# main writes the learned file on the learning branch and logs each model
T.LEARN = tempfile.mkdtemp()
res = T.main(today="2026-12-01", models=[Coin(rows)])
assert res == {"coin": "promoted"}, res
d = json.load(open(os.path.join(T.LEARN, "learned.json")))
assert d["models"]["coin"]["params"] == {"p": 0.3} and d["log"][-1]["event"] == "promoted"
print("ok: main writes learned.json on the learning branch")

# 5) archive: dedup by key, keeps older records the state log dropped
T.LEARN = tempfile.mkdtemp()
a = T.archive("x", [{"k": 1}, {"k": 2}], key=lambda r: r["k"])
b = T.archive("x", [{"k": 2}, {"k": 3}], key=lambda r: r["k"])
assert [r["k"] for r in a] == [1, 2] and sorted(r["k"] for r in b) == [1, 2, 3]
assert len(open(os.path.join(T.LEARN, "x.jsonl")).read().splitlines()) == 3
print("ok: archive keeps every record once")

# the morning brief mentions promotions and rollbacks from the last 24 hours only
import datetime as dt
from app.alerts import learned_lines
now = dt.datetime(2026, 12, 2, 15, 0, tzinfo=dt.timezone.utc)
lines = learned_lines(now, {"log": [{"at": "2026-12-02T10:40+00:00", "event": "promoted", "title": "Play chance"},
                                    {"at": "2026-12-02T10:40+00:00", "event": "kept current", "title": "Other"},
                                    {"at": "2026-11-30T10:40+00:00", "event": "reverted", "title": "Old"}]})
assert lines == ["Learned: Play chance (watched for 7 days)"], lines
print("ok: morning brief lines")
