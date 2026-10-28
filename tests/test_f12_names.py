"""Finding 12 (review 2026-10-28): news-to-player matching was an exact normalized full name, so common short
forms never reached the player ("Cam Johnson", "Steph Curry"), and duplicate names silently kept the first match."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import news

meta = {"1": {"first_name": "Cameron", "last_name": "Johnson", "team": "DEN"},
        "2": {"first_name": "Stephen", "last_name": "Curry", "team": "GSW"},
        "3": {"first_name": "Kevin", "last_name": "Porter Jr.", "team": "MIL"},
        "4": {"first_name": "Jalen", "last_name": "Williams", "team": "OKC"},
        "5": {"first_name": "Jalen", "last_name": "Williams", "team": "DEN"},
        "6": {"first_name": "Jaylin", "last_name": "Williams", "team": "OKC"}}
n = news.Names(meta)
assert n.pid("Cam Johnson") == "1", n.pid("Cam Johnson")
assert n.pid("Steph Curry") == "2"
assert n.pid("Kevin Porter Jr.") == "3" and n.pid("Kevin Porter") == "3"
assert n.pid("Jalen Williams") is None, "ambiguous without a team"
assert n.pid("Jalen Williams", "DEN") == "5" and n.pid("Jalen Williams", "OKC") == "4"
assert n.pid("Johnson", "DEN") == "1"            # unique last name on the reported team
assert n.pid("Williams", "OKC") is None          # not unique on that team
print("ok: finding 12")
