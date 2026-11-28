"""Nov 28: team injury reports raise Sleeper's labels in the job (app/injuries.py).

Case: Nov 16 Queta was ruled out at 5:16 pm ET and Sleeper still said GTD two hours later; Fri Nov 27 the start call
for Boston's centers hung on who was in. Rule (same as site/engine.js escalateStatus): a report only ever moves a
player toward sitting, only to Doubtful or Out; it never clears a player Sleeper has out, and IR/Suspended stay.
"""
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
ch = injuries.apply(meta, items, news.Names(meta))
assert [(c["pid"], c["from"], c["to"]) for c in ch] == [("1887", "GTD", "Out")], ch
assert meta["1887"]["injury_status"] == "Out" and meta["2302"]["injury_status"] is None
assert meta["77"]["injury_status"] is None, "a report for another team's player doesn't match"
# the Worker's saved copy (keyed, with Sleeper ids) works the same way
meta["2302"]["injury_status"] = "GTD"
ch = injuries.apply(meta, {"BOS|neemias queta": {"pid": "2302", "name": "Neemias Queta", "team": "BOS", "status": "Doubtful"}},
                    news.Names(meta))
assert meta["2302"]["injury_status"] == "Doubtful" and len(ch) == 1
print("ok: Nov 28 injury reports (job)")
