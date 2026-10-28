"""Finding 13 (review 2026-10-28): the model eval didn't score injury timelines - the only AI output that changes
a decision - and its consensus panel let same-family models vote for each other (Haiku twice)."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENROUTER_API_KEY", "")
from tools import llm_eval as E
from app import news

m = E.timeline_match
assert m((42, 56), (42, 56)) and m((40, 58), (42, 56)) and m((None, None), (None, None))
assert not m((0, 0), (None, None)), "an in-game exit read as '0 days out' is wrong"
assert not m((None, 60), (60, 60)) and not m((14, None), (14, 28))
# panel: a model never votes for its own family, and only one model per family votes
labels = ["Claude Haiku 5.5", "Claude Haiku 5.5 + reasoning (low)", "GPT-6 Luna", "DeepSeek V4.1 Flash", "Claude Sonnet 5.5"]
assert E.panel("Claude Haiku 5.5", labels) == ["GPT-6 Luna", "DeepSeek V4.1 Flash"]
assert E.panel("GPT-6 Luna", labels) == ["Claude Haiku 5.5", "DeepSeek V4.1 Flash"]
# the labeled set exists and scores the production extractions (raw and after news._window validation)
fx = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "timeline_labels.json")))["items"]
assert len(fx) == 50
raw, eff = E.score_timelines([(x["production_extraction"]["out_min_days"], x["production_extraction"]["out_max_days"]) for x in fx], fx)
print(f"production extractions vs labels: raw {raw:.0%}, after validation {eff:.0%}")
assert 0 < raw <= 1 and 0 < eff <= 1
print("ok: finding 13")
