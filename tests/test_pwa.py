"""Home-screen app: manifest + icons + iOS tags present, and the service worker is network-first."""
import json, os
from PIL import Image
S = os.path.join(os.path.dirname(__file__), "..", "site")
m = json.load(open(os.path.join(S, "manifest.webmanifest")))
assert m["display"] == "standalone" and m["start_url"] == "./"
for ic in m["icons"]:
    w, h = Image.open(os.path.join(S, ic["src"])).size
    assert f"{w}x{h}" == ic["sizes"], ic
html = open(os.path.join(S, "index.html")).read()
for tag in ('rel="manifest"', 'apple-mobile-web-app-capable', 'rel="apple-touch-icon"', "viewport-fit=cover", 'id="setup"'):
    assert tag in html, tag
assert Image.open(os.path.join(S, "icons", "apple-touch-icon.png")).size == (180, 180)
sw = open(os.path.join(S, "sw.js")).read()
assert "fetch(req).then" in sw and ".catch(() => caches.match" in sw, "network first, cache only as fallback"
assert 'register("sw.js")' in open(os.path.join(S, "app.js")).read()
print("ok: pwa")
