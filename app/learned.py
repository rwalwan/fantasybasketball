"""Learned numbers: what the nightly trainer (app/train.py) has promoted, read by the 15-minute job.

data/state/learned.json: a copy of learned.json from the `learning` branch (written only by app/train.py, full git
history), refreshed at the start of every 15-minute run by tools/learning.sh pull:
  {"models": {"<name>": {"params": {...}, "since": "YYYY-MM-DD", "previous": {...} | null,
                         "watch_until": "YYYY-MM-DD" | null, "status": "watching" | "kept"}},
   "log": [{"at": iso, "model": name, "event": "promoted" | "kept current" | "reverted" | "kept after watch" | "skipped",
            "why": "...", ...}]}

No file, an unknown model, or LEARNING=off in the environment = the factory numbers (app/data/*.json and the
existing self-calibration). Nothing here ever changes code; it only supplies fitted numbers.
"""
import json
import os

STATE = os.path.join(os.path.dirname(__file__), "..", "data", "state")
FILE = "learned.json"


def enabled():
    return (os.environ.get("LEARNING") or "").strip().lower() != "off"


def load(state=None):
    """The whole learned file, or an empty one. A corrupt file counts as absent here (state.sh repairs it from the
    backup); the trainer, which writes it, fails loudly instead."""
    try:
        with open(os.path.join(state or STATE, FILE)) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {"models": {}, "log": []}


def get(name, state=None):
    """Promoted params of one model, or None (factory behavior)."""
    if not enabled():
        return None
    m = (load(state).get("models") or {}).get(name)
    return (m or {}).get("params")


def summary(state=None, n=20):
    """For the site (learning.json) and the morning brief: each model's state and the newest log entries."""
    d = load(state)
    return {"enabled": enabled(),
            "models": {k: {kk: v.get(kk) for kk in ("since", "status", "watch_until", "title")} for k, v in (d.get("models") or {}).items()},
            "log": list(reversed(d.get("log") or []))[:n]}
