"""Nov 28: team injury reports raise Sleeper's labels in the job (app/injuries.py).

Case: Nov 16 Queta was ruled out at 5:16 pm ET and Sleeper still said GTD two hours later; Fri Nov 27 the start call
for Boston's centers hung on who was in. Rule (same as site/engine.js escalateStatus): a report only ever moves a
player toward sitting, only to Doubtful or Out; it never clears a player Sleeper has out, and IR/Suspended stay.
First live run (Nov 28): ESPN's status lags its own note and outlives the game (Grayson Allen "Out" with "upgraded to
probable for Saturday's game"; Landale "Out" from "out for Friday's game", read Saturday). A report counts only if its
note says he sits, nothing says he may play, and the game it names is today or later (else: under 24 hours old).
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import injuries, news

feed = {"injuries": [
    {"displayName": "Boston Celtics", "injuries": [
        {"status": "Out", "shortComment": "Robinson (illness) is out Friday", "date": "2026-11-27T20:01Z",
         "athlete": {"displayName": "Mitchell Robinson"}},
        {"status": "Questionable", "athlete": {"displayName": "Neemias Queta"}}]},
    {"team": {"abbreviation": "GS"}, "injuries": [{"status": "Out", "athlete": {"displayName": "Some Warrior"}}]},
    {"displayName": "Atlanta Hawks", "injuries": [{"athlete": {"displayName": "No Status"}}]}]}
items = injuries.parse(feed)
assert [(x["team"], x["name"], x["status"]) for x in items] == [
    ("BOS", "Mitchell Robinson", "Out"), ("BOS", "Neemias Queta", "Questionable"), ("GSW", "Some Warrior", "Out")], items
assert injuries.parse(None) == []

E = injuries.escalate
assert E(None, "Out") == "Out" and E("GTD", "Out") == "Out" and E("Questionable", "Doubtful") == "Doubtful"
assert E("Out", "Questionable") is None, "never un-rule a player out"
assert E("GTD", "Available") is None and E(None, "Questionable") is None and E("IR", "Out") is None

meta = {"1887": {"first_name": "Mitchell", "last_name": "Robinson", "team": "BOS", "injury_status": "GTD"},
        "2302": {"first_name": "Neemias", "last_name": "Queta", "team": "BOS", "injury_status": None},
        "77": {"first_name": "Some", "last_name": "Warrior", "team": "LAL", "injury_status": None}}
FRI = dt.datetime(2026, 11, 27, 22, 0, tzinfo=dt.timezone.utc)       # Friday 5 pm ET, before Boston's tip
SAT = dt.datetime(2026, 11, 28, 18, 41, tzinfo=dt.timezone.utc)
ch = injuries.apply(meta, items, news.Names(meta), FRI)
assert [(c["pid"], c["from"], c["to"]) for c in ch] == [("1887", "GTD", "Out")], ch
assert meta["1887"]["injury_status"] == "Out" and meta["2302"]["injury_status"] is None
assert meta["77"]["injury_status"] is None, "a report for another team's player doesn't match"
# the Worker's saved copy (keyed, with Sleeper ids) works the same way
meta["2302"]["injury_status"] = "GTD"
ch = injuries.apply(meta, {"BOS|neemias queta": {"pid": "2302", "name": "Neemias Queta", "team": "BOS", "status": "Doubtful",
                                                  "comment": "Queta (ankle) is doubtful for Friday", "at": "2026-11-27T19:00Z"}},
                    news.Names(meta), FRI)
assert meta["2302"]["injury_status"] == "Doubtful" and len(ch) == 1

# the live cases: stale or contradicted "Out" labels change nothing
C = injuries.current
allen = {"status": "Out", "comment": "Allen (concussion) has been upgraded to probable for Saturday's game against the Nets.", "at": "2026-11-28T18:08Z"}
landale = {"status": "Out", "comment": "Landale (hip) is out for Friday's game against the Celtics.", "at": "2026-11-26T22:44Z"}
mcc = {"status": "Out", "comment": "McConnell (hamstring) has been ruled out for Friday's game against the 76ers.", "at": "2026-11-27T23:02Z"}
assert not C(allen, SAT) and not C(landale, SAT) and not C(mcc, SAT)
assert C(landale, dt.datetime(2026, 11, 27, 20, 0, tzinfo=dt.timezone.utc)), "Thursday's report about Friday counts on Friday"
assert C({"comment": "Smith (knee) will not play Saturday.", "at": "2026-11-28T15:00Z"}, SAT)
assert C({"comment": "Smith (knee) has been ruled out.", "at": "2026-11-28T15:00Z"}, SAT)
assert not C({"comment": "Smith (knee) has been ruled out.", "at": "2026-11-27T15:00Z"}, SAT), "no day named: 24 hours"
assert not C({"comment": "", "at": "2026-11-28T15:00Z"}, SAT) and not C({"comment": "out Saturday"}, SAT)
m2 = {"1959": {"first_name": "Grayson", "last_name": "Allen", "team": "CHA", "injury_status": "GTD"}}
assert injuries.apply(m2, [dict(allen, name="Grayson Allen", team="CHA")], news.Names(m2), SAT) == [] and m2["1959"]["injury_status"] == "GTD"
print("ok: Nov 28 injury reports (job)")
