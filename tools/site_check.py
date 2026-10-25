"""Headless-Chrome health check of the built site: console errors + whether each section rendered."""
import json
import re
import sys
from html.parser import HTMLParser

dom = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
console = open(sys.argv[2], encoding="utf-8", errors="ignore").read()


class Count(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.counts, self.text = [], {}, {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for s in self.stack:
            self.counts[s] = self.counts.get(s, 0) + 1
        self.stack.append(a.get("id")) if a.get("id") else self.stack.append(None)

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        for s in self.stack:
            if s:
                self.text[s] = (self.text.get(s, "") + data)[:300]


c = Count()
c.feed(dom)
ids = ["now", "slots", "lineup", "grid", "waivers", "adds", "ideas", "research", "research_opp", "outlook", "why", "trends",
       "openings", "scorecard", "experts", "mynews", "sources"]
errors = [l.strip()[:300] for l in console.splitlines() if "CONSOLE" in l and re.search(r"Uncaught|Error|TypeError|ReferenceError", l)]
out = {"errors": errors[:10], "sections": {i: c.counts.get(i, 0) for i in ids},
       "now_text": re.sub(r"\s+", " ", c.text.get("now", ""))[:300]}
print(json.dumps(out, indent=1))
