"""Home-screen app: manifest + icons + iOS tags present, and the service worker is network-first."""
import json, os, struct


def png_size(path):
    """Width, height from the PNG header (no image library on the CI runner)."""
    b = open(path, "rb").read(24)
    assert b[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", b[16:24])

S = os.path.join(os.path.dirname(__file__), "..", "site")
m = json.load(open(os.path.join(S, "manifest.webmanifest")))
assert m["display"] == "standalone" and m["start_url"] == "./"
for ic in m["icons"]:
    w, h = png_size(os.path.join(S, ic["src"]))
    assert f"{w}x{h}" == ic["sizes"], ic
html = open(os.path.join(S, "index.html")).read()
for tag in ('rel="manifest"', 'apple-mobile-web-app-capable', 'rel="apple-touch-icon"', "viewport-fit=cover", 'id="setup"'):
    assert tag in html, tag
assert png_size(os.path.join(S, "icons", "apple-touch-icon.png")) == (180, 180)
sw = open(os.path.join(S, "sw.js")).read()
assert "fetch(req).then" in sw and ".catch(() => caches.match" in sw, "network first, cache only as fallback"
assert 'register("sw.js")' in open(os.path.join(S, "app.js")).read()
print("ok: pwa")
