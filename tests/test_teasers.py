"""Cut-off injury teasers (review finding 12 leftover): read the full article when the feed text is truncated
and the title promises a timeline that the teaser didn't give."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import news
no_tl = {"kind": "injury", "out_min_days": None, "out_max_days": None}
assert news.needs_full_text("Anthony Edwards Sidelined Until December",
                            "Minnesota Timberwolves guard Anthony Edwards (knee) will undergo an arthroscopic procedure on his right knee and miss up to two […]", no_tl)
assert news.needs_full_text("Jalen Suggs to be Re-Evaluated in Two Weeks", "Orlando Magic guard Jalen Suggs (knee) will be re-evaluated in two weeks after an MRI revealed a mild right knee […]", no_tl)
assert not news.needs_full_text("Rui Hachimura: Ruled out for Wednesday", "Hachimura (quadriceps) has been ruled out for Wednesday's game.", no_tl)
assert not news.needs_full_text("Kawhi Leonard Out Multiple Weeks", "… multiple weeks […]", dict(no_tl, out_min_days=14))
assert not news.needs_full_text("Edwards Sidelined Until December", "… […]", dict(no_tl, kind="other"))
print("ok: teasers")
