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


def send_alerts(plan, waivers, book, tips, today):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return 0
    now = dt.datetime.now(dt.timezone.utc)
    sent, n = _load(), 0

    def once(key, *args, **kw):
        nonlocal n
        if key in sent:
            return
        push(topic, *args, **kw)
        sent[key] = now.isoformat()
        n += 1

    # 1) lock decisions due within the hour
    for s in plan["slots"]:
        tip = s.get("deadline_tip")
        relevant = s["action"] == "lock" or (s["action"] == "confirm" and s.get("score", 0) >= s.get("bar", 0))
        if relevant and tip:
            mins = (dt.datetime.fromisoformat(tip.replace("Z", "+00:00")) - now).total_seconds() / 60
            if 0 < mins <= 70:
                verb = "Lock" if s["action"] == "lock" else "Check"
                once(f"lock|{s['pid']}|{s.get('last_date')}", f"{verb} {s['name']} before {tip_pt(tip)}",
                     f"{s['slot']}: {s['detail']}", priority="high", tags="lock")

    # 2) a starter ruled out before tonight's game
    for s in plan["slots"]:
        st = book.status(s["pid"]) if s.get("pid") else None
        team = book.team(s["pid"]) if s.get("pid") else None
        tip = tips.get((today, team))
        if st in ("Out", "Doubtful") and tip and dt.datetime.fromisoformat(tip.replace("Z", "+00:00")) > now \
                and s["action"] not in ("locked",):
            once(f"out|{s['pid']}|{today}", f"{s['name']} is {st} tonight",
                 f"He's in your {s['slot']} slot and tips at {tip_pt(tip)}. Swap in a bench player who plays today.",
                 priority="high", tags="warning")

    # 3) morning brief
    local = now.astimezone(PT)
    if local.hour >= 8 and f"brief|{today}" not in sent:
        decide = [s for s in plan["slots"] if s["action"] == "lock" or (s["action"] == "confirm" and s.get("score", 0) >= s.get("bar", 0))]
        moves = [x for x in plan["today_lineup"]["slots"] if x.get("pid")]
        lines = []
        if decide:
            lines.append("Decide today: " + "; ".join(f"{s['action'].title()} {s['name']} ({s['score']:.1f})" for s in decide))
        if moves:
            lines.append("Open slots today: " + ", ".join(f"{x['name']} {x['slot']}" for x in moves))
        good = [w for w in waivers if w["over_worst"] > 0][:3]
        if good:
            lines.append("Waivers: " + ", ".join(f"{w['name']} {w['fpg']:.0f} FP/G (${w['faab']})" for w in good))
        once(f"brief|{today}", f"Lock Desk — week {plan['week']}", "\n".join(lines) or "Nothing to do today.", tags="basketball")

    _save(sent)
    return n
