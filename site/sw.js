// Home-screen app support. Network first for everything (live data must never be served stale while online);
// the cached copy is used only when the network fails, so the app still opens offline with the last data.
// Cached copies carry the time they were saved, and a copy served offline is marked (x-lockdesk-cached) so the
// page says it is showing old data (review 2, finding 7e).
const CACHE = "lockdesk-v2";
const SHELL = ["./", "index.html", "app.js", "engine.js", "manifest.webmanifest", "icons/icon-192.png", "icons/apple-touch-icon.png"];
const SLEEPER = /^https:\/\/api\.sleeper\.(app|com)\//;
const withHeaders = (res, extra) => res.blob().then(b => {
  const h = new Headers(res.headers); for (const [k, v] of Object.entries(extra)) h.set(k, v);
  return new Response(b, { status: res.status, statusText: res.statusText, headers: h });
});
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {})); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const sameOrigin = new URL(req.url).origin === self.location.origin, sleeper = SLEEPER.test(req.url);
  if (!sameOrigin && !sleeper) return;
  e.respondWith(fetch(req).then(res => {
    if (res.ok) { const copy = res.clone(); withHeaders(copy, { "x-lockdesk-saved": String(Date.now()) }).then(r => caches.open(CACHE).then(c => c.put(req, r))).catch(() => {}); }
    return res;
  }).catch(() => caches.match(req, { ignoreSearch: sameOrigin })
    .then(r => r ? withHeaders(r, { "x-lockdesk-cached": "1" }) : Response.error())));
});
