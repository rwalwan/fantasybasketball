"""Phone alerts via ntfy (free push app). Topic name comes from the NTFY_TOPIC secret.

Sent at most once each (deduped in data/state/alerts.json):
  * lock reminder ~1 h before tip when a slot has a lock decision pending
  * a starter ruled Out/Doubtful before his game today
  * a morning brief once a day (first run after 8 AM PT)
"""
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

import requests

STATE = os.path.join(os.path.dirname(__file__), "..", "data", "state", "alerts.json")
SITE = "https://rwalwan.github.io/fantasybasketball/"
PT = ZoneInfo("America/Los_Angeles")


def _load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def _save(sent):
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat()
    sent = {k: v for k, v in sent.items() if v >= cutoff}
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(sent, open(STATE, "w"), indent=1, sort_keys=True)


def push(topic, title, body, priority="default", tags=""):
    requests.post(f"https://ntfy.sh/{topic}", data=body.encode(), timeout=20,
                  headers={"Title": title.encode("utf-8").decode("latin-1", "ignore"), "Priority": priority,
                           "Tags": tags, "Click": SITE})


def tip_pt(tip):
    return dt.datetime.fromisoformat(tip.replace("Z", "+00:00")).astimezone(PT).strftime("%-I:%M %p")


def _ts(t):
    return dt.datetime.fromisoformat(t.replace("Z", "+00:00"))


def main():
    """Alerts from the site's own engine output (site/static/plan.json + moves.json, written by tools/moves.mjs),
    so a phone alert always matches what the page says."""
    topic = os.environ.get("NTFY_TOPIC")
    root = os.path.join(os.path.dirname(__file__), "..", "site", "static")
    try:
        plan = json.load(open(os.path.join(root, "plan.json")))
    except Exception as e:
        print("no plan.json, skipping alerts:", e)
        return 0
    try:
        moves = json.load(open(os.path.join(root, "moves.json")))
    except Exception:
        moves = {"adds": []}
    if not topic:
        return 0
    now = dt.datetime.now(dt.timezone.utc)
    local = now.astimezone(PT)
    sent, n = _load(), 0

    def once(key, *args, **kw):
        nonlocal n
        if key in sent:
            return
        push(topic, *args, **kw)
        sent[key] = now.isoformat()
        n += 1

    def within(t, lo, hi):
        if not t:
            return False
        m = (_ts(t) - now).total_seconds() / 60
        return lo < m <= hi

    # 1) lock decisions: within 75 min of the player's next tip (the lock window closes at that tip)
    for s in plan["slots"]:
        tip = (s.get("deadline") or {}).get("tip")
        if s["action"] == "lock" and within(tip, 0, 75):
            once(f"lock|{s['pid']}|{tip}", f"Lock {s['name']} before {tip_pt(tip)}", f"{s['slot']}: {s['detail']}",
                 priority="high", tags="lock")
        if s["action"] == "confirm" and within(tip, 0, 75):
            once(f"confirm|{s['pid']}|{tip}", f"Check {s['name']} before {tip_pt(tip)}",
                 f"{s['detail']} Answer on the Locks tab.", priority="high", tags="question")
        if s["action"] == "fallback-risk":
            once(f"fallback|{s['pid']}|{plan.get('week')}", f"{s['slot']} slot has no games left",
                 s["detail"], priority="high", tags="warning")

    # 2) lineup moves (includes relief swaps once the first game is final): within 60 min of the new player's tip
    for x in plan["lineup"]:
        if x.get("move") and x.get("pid") and within(x.get("tip"), 0, 60):
            who = f" (for {x['currentName']})" if x.get("currentName") and x.get("current") != x["pid"] else ""
            once(f"move|{x['pid']}|{x['tip']}", f"Start {x['name']} at {x['slot']}",
                 f"Put {x['name']} in {x['slot']}{who} before {tip_pt(x['tip'])} vs {x.get('opp', '')}.",
                 priority="high", tags="arrows_counterclockwise")

    # 3) a starter ruled Out/Doubtful whose game is today and hasn't tipped
    for s in plan["slots"]:
        tip = (s.get("deadline") or {}).get("tip")
        if s.get("status") in ("Out", "Doubtful") and s["action"] != "locked" and within(tip, 0, 12 * 60) \
                and _ts(tip).astimezone(PT).date() == local.date():
            once(f"out|{s['pid']}|{tip}", f"{s['name']} is {s['status']} tonight",
                 f"He's in your {s['slot']} slot and tips at {tip_pt(tip)}. Swap in a bench player who plays today.",
                 priority="high", tags="warning")

    # 4) morning brief: once per Pacific day, only between 7 and 11 AM PT
    if 7 <= local.hour < 11:
        lines = []
        dec = [s for s in plan["slots"] if s["action"] in ("lock", "confirm")]
        if dec:
            lines.append("Decide: " + "; ".join(f"{s['action'].title()} {s['name']}" + (f" ({s['score']:.1f})" if s.get("score") else "") for s in dec))
        mv = [x for x in plan["lineup"] if x.get("move") and x.get("pid")]
        if mv:
            lines.append("Lineup: " + ", ".join(f"{x['name']} → {x['slot']} ({tip_pt(x['tip'])})" for x in mv if x.get("tip")))
        rel = [x for x in plan["lineup"] if x.get("relief")]
        if rel:
            lines.append("Relief: " + ", ".join(f"if {x['name']} < {x['keepBar']}, swap {x['relief']['name']}" for x in rel))
        if moves.get("adds"):
            a = moves["adds"][0]
            lines.append(f"Waiver: add {a['name']}, drop {a['dropName']} (${a['bid']})")
        once(f"brief|{local.date().isoformat()}", f"Lock Desk — week {plan.get('week')}",
             "\n".join(lines) or "Nothing to do today.", tags="basketball")

    _save(sent)
    print("alerts sent:", n)
    return n


if __name__ == "__main__":
    main()
