"""Nightly trainer: refit each model, and promote a new version only if it wins on games it never saw.

Runs in the Train models workflow (.github/workflows/train.yml) once a night, after the night's games are final.
For every model in MODELS:

  1. Watch. A model promoted in the last WATCH_DAYS days is graded against the version it replaced on every game
     graded since. Clearly worse (95% interval of the loss difference above 0, 3+ days) -> reverted at once; at the
     end of the watch, worse at all (mean above 0) -> reverted. No new promotion while a model is being watched.
  2. Gate. A candidate is fitted on rows dated before the last HOLD_DAYS days and moved from the current version by
     at most the model's step cap. It is scored against the current version on the held-out days (the same rows,
     paired). Promoted only if the loss difference's 95% interval (resampling whole days) is entirely below 0, every
     number is inside the model's hard limits, and there are enough rows. The version that goes live is the same
     step toward a fit on ALL rows (checked against the limits again), so the newest games count too.
  3. Log. Every outcome (promoted, kept current, reverted, kept after watch, skipped) goes to learned.json's log, which
     the Insights tab shows; promotions and reverts also go in the morning brief.

Learned numbers and training history: data/learning/ (the `learning` branch, real git history, one commit per night;
tools/learning.sh). The trainer reads saved state (grades) but never writes it, so it can't race the 15-minute job;
that job copies learned.json from the branch into data/state each run (tools/learning.sh pull), where app/learned.py
reads it. LEARNING=off in the environment skips the run.
"""
import datetime as dt
import json
import os
import sys

import numpy as np

from . import learned

ROOT = os.path.join(os.path.dirname(__file__), "..")
STATE = os.path.join(ROOT, "data", "state")
LEARN = os.environ.get("LEARN_DIR") or os.path.join(ROOT, "data", "learning")
HOLD_DAYS = 14          # the newest days are the exam; the fit never sees them (half the days while history is short)
WATCH_DAYS = 7          # after a promotion, the old version is graded alongside the new one this long
MIN_HOLD_DAYS = 5       # an exam needs at least this many distinct days
BOOT = 2000
LOG_KEEP = 300


def day_boot(diff, days, B=BOOT, seed=7):
    """Mean of per-row differences and its 95% interval, resampling whole days (games on one night share news,
    rest decisions and injury waves, so rows are not independent), or whole clusters when rows carry a "c" key (a
    player-season, a league). -> (mean, lo, hi, n_clusters)"""
    diff = np.asarray(diff, float)
    uniq = sorted(set(days))
    if not uniq:
        return 0.0, 0.0, 0.0, 0
    ix = {d: i for i, d in enumerate(uniq)}
    di = np.array([ix[d] for d in days])
    sums = np.bincount(di, weights=diff, minlength=len(uniq))
    cnts = np.bincount(di, minlength=len(uniq)).astype(float)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(uniq), (B, len(uniq)))
    boot = sums[pick].sum(1) / np.maximum(cnts[pick].sum(1), 1)
    return float(diff.mean()), float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975)), len(uniq)


class Model:
    """One learnable piece. Subclasses fill in the data, the fit, the loss and the safety limits."""
    name = ""
    title = ""                # plain words for the site and the brief
    min_train = 100           # rows the fit needs
    min_hold = 100            # rows the exam needs

    def rows(self, ctx):      # [{"day": "YYYY-MM-DD", ...}]
        raise NotImplementedError

    def factory(self, ctx):   # params that reproduce today's behavior without learned numbers
        raise NotImplementedError

    def fit(self, rows, base):
        raise NotImplementedError

    def loss(self, params, rows):   # per-row loss, lower is better
        raise NotImplementedError

    def bounds(self, params):       # None if every number is sane, else the reason
        return None

    def step(self, old, new):       # move from old toward new, capped
        return new

    def describe(self, old, new):   # plain words: what changed
        return ""

    def split(self, rows, t):       # (fit rows, exam rows); default: the newest days are the exam
        return split(rows, t)

    row_word = "games"

    def exam_words(self, hold, nd):  # plain words for the exam set (nd = days, or clusters when rows carry "c")
        return f"last {len({r['day'] for r in hold})} days"


def split(rows, t):
    """(train, exam). The exam is the last HOLD_DAYS days, or the newer half of the days while history is shorter
    than twice that. Rows with a stratum key "s" (kinds of rows whose history starts on different dates) are split
    stratum by stratum, so a newer kind of row still gets days in both halves."""
    train, hold = [], []
    for s in sorted({r.get("s", "") for r in rows}):
        rs = [r for r in rows if r.get("s", "") == s]
        days = sorted({r["day"] for r in rs})
        cut = (t - dt.timedelta(days=HOLD_DAYS)).isoformat()
        if len(days) < 2 * HOLD_DAYS and days:
            cut = max(cut, days[len(days) // 2])
        train += [r for r in rs if r["day"] < cut]
        hold += [r for r in rs if r["day"] >= cut]
    return train, hold


def _err(mean, lo, hi):
    """Plain words for a loss difference (new minus current; below 0 = better), its interval in the same direction as
    the word: 'average prediction error down 0.140 (95% interval 0.049 to 0.228)', 'up 0.019 (95% interval -0.004 to
    +0.043)'."""
    word, (a, b) = ("down", (-hi, -lo)) if mean < 0 else ("up", (lo, hi))
    span = f"{a:.3f} to {b:.3f}" if a >= 0 else f"{a:+.3f} to {b:+.3f}"
    return f"average prediction error {word} {abs(mean):.3f} (95% interval {span})"


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")


QUIET = ("kept current", "skipped")


def _log(doc, model, event, why, **kw):
    log = doc.setdefault("log", [])
    # a nightly "no change" repeats itself: keep only the newest one in a row per model, so the log shows changes
    last = next((e for e in reversed(log) if e.get("model") == model.name), None)
    if event in QUIET and last is not None and last.get("event") == event:
        log.remove(last)
    log.append({"at": _now(), "model": model.name, "title": model.title, "event": event,
                                      "why": why, **kw})
    del log[:-LOG_KEEP]


def run_model(model, ctx, doc, today):
    """Watch, then gate, one model. Mutates doc (the learned file). Returns the event name."""
    ms = doc.setdefault("models", {})
    entry = ms.get(model.name)
    rows = [r for r in model.rows(ctx) if r["day"] < today]        # only finished days
    t = dt.date.fromisoformat(today)

    if entry and entry.get("status") == "watching" and entry.get("previous") is not None:
        post = [r for r in rows if r["day"] >= entry["since"]]
        if post:
            d = model.loss(entry["params"], post) - model.loss(entry["previous"], post)
            mean, lo, hi, nd = day_boot(d, [r.get("c", r["day"]) for r in post])
        else:
            mean = lo = hi = 0.0
            nd = 0
        over = today >= entry["watch_until"]
        if (nd >= 3 and lo > 0) or (over and len(post) >= model.min_hold and mean > 0):
            why = (f"the new version did worse on {len(post)} {model.row_word} graded since {entry['since']} "
                   f"({_err(mean, lo, hi)}); back to the previous version")
            ms[model.name] = {"params": entry["previous"], "previous": None, "since": today, "status": "kept",
                              "watch_until": None, "cooldown_until": (t + dt.timedelta(days=WATCH_DAYS)).isoformat(),
                              "title": model.title}
            _log(doc, model, "reverted", why, n=len(post), gain=round(-mean, 5), ci=[round(-hi, 5), round(-lo, 5)])
            return "reverted"
        if not over:
            return "watching"
        entry.update(status="kept", previous=entry["previous"], watch_until=None)
        _log(doc, model, "kept after watch",
             f"graded on {len(post)} {model.row_word} since {entry['since']}: not worse than the version it replaced"
             + (f" ({_err(mean, lo, hi)})" if post else " (no games graded yet)"), n=len(post))
        return "kept after watch"
    if entry and entry.get("cooldown_until") and today < entry["cooldown_until"]:
        return "cooldown"

    champ = entry["params"] if entry else model.factory(ctx)
    train, hold = model.split(rows, t)
    hold_days = len({r.get("c", r["day"]) for r in hold})
    if len(train) < model.min_train or len(hold) < model.min_hold or hold_days < MIN_HOLD_DAYS:
        why = (f"not enough graded data yet ({len(train)} rows to fit, {len(hold)} to test over "
               f"{len({r['day'] for r in hold})} days)")
        _log(doc, model, "skipped", why)
        return "skipped"
    cand = model.step(champ, model.fit(train, champ))
    bad = model.bounds(cand)
    if bad:
        _log(doc, model, "kept current", f"the fitted numbers broke a safety limit: {bad}")
        return "kept current"
    if cand == champ:
        _log(doc, model, "kept current", f"a refit on {len(train)} {model.row_word} came out at the current numbers")
        return "kept current"
    d = model.loss(cand, hold) - model.loss(champ, hold)
    mean, lo, hi, nd = day_boot(d, [r.get("c", r["day"]) for r in hold])
    stats = dict(n=len(hold), days=nd, gain=round(-mean, 5), ci=[round(-hi, 5), round(-lo, 5)])
    if not hi < 0:
        _log(doc, model, "kept current", f"a refit was not clearly better on {len(hold)} {model.row_word} it never saw "
             f"({model.exam_words(hold, nd)}): "
             f"{_err(mean, lo, hi)}", **stats)
        return "kept current"
    live = model.step(champ, model.fit(rows, champ))
    bad = model.bounds(live)
    if bad:
        _log(doc, model, "kept current", f"passed the test, but the refit on all data broke a safety limit: {bad}", **stats)
        return "kept current"
    ms[model.name] = {"params": live, "previous": champ, "since": today, "status": "watching", "title": model.title,
                      "watch_until": (t + dt.timedelta(days=WATCH_DAYS)).isoformat()}
    _log(doc, model, "promoted", f"better on {len(hold)} {model.row_word} it never saw ({model.exam_words(hold, nd)}): "
         f"{_err(mean, lo, hi)}. "
         f"{model.describe(champ, live)}".strip(), **stats)
    return "promoted"


# ---------------------------------------------------------------------------------------------------------------
# Training history (the `learning` branch, checked out at data/learning)

def archive(name, records, key):
    """Append records to data/learning/<name>.jsonl, skipping keys already there. Returns every record."""
    os.makedirs(LEARN, exist_ok=True)
    path = os.path.join(LEARN, f"{name}.jsonl")
    have, out = set(), []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    have.add(key(r))
                    out.append(r)
    new = [r for r in records if key(r) not in have]
    for r in new:
        have.add(key(r))
    if new:
        with open(path, "a") as f:
            for r in sorted(new, key=key):
                f.write(json.dumps(r, separators=(",", ":"), sort_keys=True) + "\n")
    return out + new


def _load_state(name, dflt):
    try:
        with open(os.path.join(STATE, name)) as f:
            return json.load(f)
    except FileNotFoundError:
        return dflt


def _models():
    from .train_models import MODELS
    return MODELS


def main(today=None, models=None):
    if not learned.enabled():
        print("learning is off (LEARNING=off); nothing trained")
        return {}
    today = today or os.environ.get("FBB_TODAY") or dt.datetime.now(dt.timezone.utc).date().isoformat()
    # the learning branch holds the true copy; the 15-minute job copies it into data/state (tools/learning.sh pull)
    path = os.path.join(LEARN, learned.FILE)
    doc = json.load(open(path)) if os.path.exists(path) else {"models": {}, "log": []}   # corrupt = fail loudly
    ctx = {"today": today, "state": STATE, "learn": LEARN, "cache": {}}
    out = {}
    for m in models or _models():
        try:
            out[m.name] = run_model(m, ctx, doc, today)
        except Exception as e:                       # one broken model must not stop the others
            import traceback
            traceback.print_exc()
            _log(doc, m, "skipped", f"training failed: {type(e).__name__}: {e}"[:300])
            out[m.name] = "failed"
        print(f"{m.name}: {out[m.name]}")
    doc["updated"] = _now()
    os.makedirs(LEARN, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
    os.replace(tmp, path)
    return out


if __name__ == "__main__":
    res = main()
    sys.exit(1 if res and all(v == "failed" for v in res.values()) else 0)
