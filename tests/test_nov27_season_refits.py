"""Nov 27: the rest of passive learning (phases 2 and 3 of the plan Ryan approved). Four more fitted numbers had been
frozen since a Claude session last refit them:
  * baseline (R/M/c, app/model.py): how fast this season's games outweigh last season's at the start of a season;
  * spread (a/k/m, app/volatility.py): how much of a player's own boom-or-bust spread is real;
  * return_rate (availability by_k...): how soon a player who has missed k games in a row comes back;
  * wins_per_point (engine WINS_PER_SCORE 2.2): what a weekly point is worth in trades, from other leagues' finals;
plus one that was never fitted at all:
  * win_chance (a temperature on the win-chance z-score), from the graded win-chance log.
The nightly trainer now refits each one and promotes it only if it is clearly better on data the fit never saw (the
newest season for the season models; the newest days otherwise), by a capped step, inside hard limits. These tests
build data where the truth is known and check each model's rows, its exam split, its fit and its plumbing into the job.
"""
import datetime as dt, json, os, sqlite3, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from app import train as T, learned
from app import train_models as TM

rng = np.random.default_rng(11)
state, learn = tempfile.mkdtemp(), tempfile.mkdtemp()
T.STATE, T.LEARN = state, learn


def ctx_with(seasons=None, **kw):
    c = {"today": "2026-11-28", "state": state, "learn": learn, "cache": {}}
    if seasons is not None:
        c["cache"]["seasons"] = seasons
    c.update(kw)
    return c


def dates(year, n):
    d0 = dt.date(year, 10, 22)
    return [(d0 + dt.timedelta(days=2 * i)).isoformat() for i in range(n)]


# --- baseline: a world where last season is the whole truth (each player's rate and minutes never change, games are
# noisy), so the right answer is to trust last season more than the factory 200 minutes / 4 games -----------------------
def world(players=150, years=(2021, 2022, 2023, 2024), drift=0.0, noise=0.35, n_games=60):
    out, base = {}, {f"p{i}": (rng.uniform(0.7, 1.3), rng.uniform(18, 36)) for i in range(players)}
    for y in years:
        out[str(y)] = {}
        for pid, (rate, mpg) in base.items():
            rate = rate * (1 + drift * rng.normal())
            gs = []
            for d in dates(y, n_games):
                m = max(1.0, rng.normal(mpg, 3))
                gs.append((d, float(rate * m * (1 + noise * rng.normal()) * 1.0), round(m, 2)))
            out[str(y)][pid] = gs
            base[pid] = (rate, mpg)
    return out

stable = world()
bl = TM.Baseline()
rows = bl.rows(ctx_with(stable))
assert {r["season"] for r in rows} == {"2022", "2023", "2024"}, "a season is a row only when last season exists"
assert {r["n"] for r in rows} == {1, 2, 3, 5, 10}
fit_rows, exam = bl.split(rows, None)
assert {r["season"] for r in exam} == {"2024"} and {r["season"] for r in fit_rows} == {"2022", "2023"}
print("ok: baseline rows come from season pairs; the newest season is the exam, the fit never sees it")
fac = bl.factory(ctx_with(stable))
assert fac == {"R": 200.0, "M": 4.0, "c": 10.0}, fac
f = bl.fit(fit_rows, fac)
assert f["R"] >= 400 and f["M"] >= 5, f
doc = {"models": {}, "log": []}
assert T.run_model(bl, ctx_with(stable), doc, "2026-11-28") == "promoted", doc["log"]
p = doc["models"]["baseline"]["params"]
assert p["R"] == 300 and p["M"] == 6, p                         # capped: R +100, M +2
assert "the 2024-25 season" in doc["log"][-1]["why"], doc["log"][-1]["why"]
print("ok: baseline learns to trust a stable last season more, a capped step at a time:", p)

# a world where each player's rate moves a lot between seasons: last season is worth less, R should not go up
moving = world(drift=0.25, noise=0.15, years=(2022, 2023, 2024))
f2 = bl.fit(bl.split(bl.rows(ctx_with(moving)), None)[0], fac)
assert f2["R"] < f["R"], (f2, f)
print("ok: when players change between seasons, last season gets less weight:", f2)

# --- spread: every player's true spread is the same (r = 1 for all), so his own past spread is noise: a -> 0 --------
def spread_world(years=(2022, 2023, 2024), players=220, own=False):
    out = {}
    sd = {f"s{i}": (rng.uniform(0.6, 1.5) if own else 1.0) for i in range(players)}
    tiers = TM._tier_table()
    for y in years:
        out[str(y)] = {}
        for pid in sd:
            mu = rng.uniform(18, 45)
            t = next(s for mx, s in tiers if mx is None or mu <= mx)
            x = np.maximum(0.0, mu * (1 + sd[pid] * t * rng.normal(size=60)))
            out[str(y)][pid] = [(d, float(v), 30.0) for d, v in zip(dates(y, 60), x)]
    return out

sp = TM.Spread()
flat = sp.rows(ctx_with(spread_world()))
assert {r["n"] for r in flat} == {0, 5, 10, 20, 30, 40} and all(r["r_cur"] is None for r in flat if r["n"] == 0)
ff = sp.fit(sp.split(flat, None)[0], sp.factory(None))
real = sp.rows(ctx_with(spread_world(own=True)))
fr = sp.fit(sp.split(real, None)[0], sp.factory(None))
assert ff["a"] < fr["a"] and ff["k"] > fr["k"], (ff, fr)
print("ok: spread learns how much of a player's own spread is real:", ff, "vs", fr)
assert sp.bounds({"a": 0.2, "k": 120, "m": 0.98}) is None and sp.bounds({"a": 0.2, "k": 120, "m": 1.3})
assert sp.step({"a": 0.2, "k": 120, "m": 0.98}, {"a": 0.9, "k": 5, "m": 0.8}) == {"a": 0.3, "k": 80, "m": 0.94}
print("ok: spread limits and step caps")

# --- return rate: players back after 1 missed game 75% of the time, factory says 50% ----------------------------------
fac_rr = TM.ReturnRate().factory(None)
assert set(fac_rr) == set(TM.HZ_KEYS) and TM.hz_to_model(fac_rr)["by_k"][0] == fac_rr["1"]
graded = []
d0 = dt.date(2026, 11, 1)
for i in range(26):
    day = (d0 + dt.timedelta(days=i)).isoformat()
    for j in range(14):
        graded.append({"date": day, "pid": f"r{i}_{j}", "first": True, "status": "Out", "q": 0.1, "missed": 1,
                       "timeline": False, "played": bool(rng.random() < 0.75)})
    graded.append({"date": day, "pid": f"t{i}", "first": True, "status": "Out", "q": 0.0, "missed": 3,
                   "timeline": True, "played": True})              # a reported timeline: not a return-rate row
json.dump({"open": {}, "graded": graded}, open(os.path.join(state, "availability_log.json"), "w"))
rr = TM.ReturnRate()
rrows = rr.rows(ctx_with())
assert len(rrows) == 26 * 14 and {r["k"] for r in rrows} == {"1"}
doc = {"models": {}, "log": []}
res = T.run_model(rr, ctx_with(), doc, "2026-11-28")
assert fac_rr["1"] < 0.6, fac_rr
assert res == "promoted", doc["log"]
got = doc["models"]["return_rate"]["params"]
assert got["1"] == round(fac_rr["1"] + 0.10, 3), (fac_rr["1"], got["1"])            # capped step
assert got["5"] == fac_rr["5"], "keys with no data keep their rate"
print("ok: return rates learn from graded games after k missed, timelines left out")

# --- wins per point: other leagues' final weeks ------------------------------------------------------------------------
con = sqlite3.connect(os.path.join(state, "leagues.sqlite"))
con.execute("CREATE TABLE league (league TEXT, verified INT)")
con.execute("CREATE TABLE snap (league TEXT, week INT, matchup INT, roster INT, points REAL, final INT)")
true_wps = 3.0
for L in range(40):
    lg = f"L{L}"
    con.execute("INSERT INTO league VALUES (?, ?)", (lg, 0 if L == 39 else 1))
    for wk in range(1, 6):
        for mid in range(1, 6):
            a = rng.normal(1500, 120)
            # margins spread so that P(|margin| < H S) = 2 H true_wps: uniform on +-S / (2 true_wps)
            m = rng.uniform(-1, 1) * 1500 / (2 * true_wps)
            for ro, pts in ((2 * mid, a), (2 * mid + 1, a + m)):
                con.execute("INSERT INTO snap VALUES (?,?,?,?,?,1)", (lg, wk, mid, ro, float(pts)))
        con.execute("INSERT INTO snap VALUES (?,?,?,?,?,0)", (lg, wk, 9, 99, 1.0))     # not final: ignored
con.commit(); con.close()
wk_end = lambda w: (dt.date(2026, 10, 26) + dt.timedelta(days=7 * w)).isoformat()
wp = TM.WinsPerPoint()
wrows = wp.rows(ctx_with(week_end=wk_end, season="2026"))
assert len(wrows) == 39 * 5 * 5, len(wrows)                       # unverified league and non-final rows left out
assert len({r["day"] for r in wrows}) == 5
fitw = wp.fit(wrows, {"wps": 2.2})
assert 2.5 < fitw["wps"] < 3.3, fitw
assert wp.step({"wps": 2.2}, fitw) == {"wps": 2.5}
assert wp.bounds({"wps": 5.0}) and wp.bounds({"wps": 2.2}) is None
print("ok: wins per point is measured from other leagues' close finals:", fitw)

# --- win chance: predictions too timid (favorites win more than predicted) ----------------------------------------------
from statistics import NormalDist
N = NormalDist()
log = {"open": {}, "graded": []}
for i in range(30):
    day = (dt.date(2026, 10, 25) + dt.timedelta(days=i)).isoformat()
    for mid in range(1, 7):
        z = rng.normal(0, 1)
        p_raw = N.cdf(z / 1.6)                                    # logged chance is too close to 50%
        log["graded"].append({"day": day, "week": i // 7 + 1, "mid": mid, "p_a": p_raw,
                              "a_won": bool(rng.random() < N.cdf(z))})
json.dump(log, open(os.path.join(state, "winprob_log.json"), "w"))
wc = TM.WinChance()
wcr = wc.rows(ctx_with())
assert len(wcr) == 180
t = wc.fit(wcr, {"t": 1.0})["t"]
assert isinstance(t, float) and t > 1.1, t
assert wc.step({"t": 1.0}, {"t": 1.6}) == {"t": 1.25}
print("ok: win chance learns a temperature above 1 when favorites win more than predicted:", t)

# --- the job puts the learned numbers where they are used ---------------------------------------------------------------
from app import run, model, volatility
json.dump({"models": {"baseline": {"params": {"R": 300.0, "M": 6.0, "c": 10.0}},
                      "spread": {"params": {"a": 0.3, "k": 80.0, "m": 0.94}},
                      "wins_per_point": {"params": {"wps": 2.5}}, "win_chance": {"params": {"t": 1.25}}}, "log": []},
          open(os.path.join(state, "learned.json"), "w"))
old_state, old_root = learned.STATE, run.ROOT
learned.STATE, run.ROOT = state, tempfile.mkdtemp()
keep_b = dict(model.BASE); keep_v = dict(volatility.M)
try:
    run.apply_learned()
    assert (model.BASE["R_minutes"], model.BASE["M_games"]) == (300.0, 6.0)
    assert (volatility.M["a_prev"], volatility.M["k_games"]) == (0.3, 80.0)
    out = json.load(open(os.path.join(run.ROOT, "site", "static", "learned.json")))
    assert out == {"baseline": {"R": 300.0, "M": 6.0, "c": 10.0}, "wins_per_score": 2.5, "win_temp": 1.25}, out
    os.environ["LEARNING"] = "off"
    model.BASE.update(keep_b); volatility.M.update(keep_v)
    run.apply_learned()
    assert model.BASE["R_minutes"] == keep_b["R_minutes"]
    assert json.load(open(os.path.join(run.ROOT, "site", "static", "learned.json"))) == {}
finally:
    os.environ.pop("LEARNING", None)
    learned.STATE, run.ROOT = old_state, old_root
    model.BASE.clear(); model.BASE.update(keep_b); volatility.M.clear(); volatility.M.update(keep_v)
print("ok: the job applies learned baseline/spread and writes learned.json for the page; LEARNING=off ignores them")
