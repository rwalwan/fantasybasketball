"""Finding 14 (review 2026-10-28): if robots.txt errored or returned non-200, allowed() permitted everything.
RFC 9309: 4xx (no robots.txt) = may crawl; 5xx or unreachable = assume complete disallow."""
import os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import sources

def fake(status=None, exc=None, text=""):
    def get(url, **kw):
        if exc:
            raise exc
        return types.SimpleNamespace(status_code=status, text=text)
    return get

cases = [("a", fake(200, text="User-agent: *\nDisallow: /private"), "/news", True),
         ("b", fake(200, text="User-agent: *\nDisallow: /private"), "/private/x", False),
         ("c", fake(404), "/x", True),
         ("d", fake(503), "/x", False),
         ("e", fake(exc=ConnectionError("down")), "/x", False)]
for host, get, path, want in cases:
    sources.requests.get = get
    got = sources.allowed(f"https://{host}.example.com{path}")
    assert got == want, (host, path, got)
print("ok: finding 14")
