// Review 2, finding 7e: the home-screen app had no sign when it showed old data offline. The service worker now
// stamps saved copies and marks a copy served offline (x-lockdesk-cached), and the page shows a banner.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const store = new Map(), handlers = {};
const caches = { open: async () => ({ put: async (req, res) => store.set(req.url, res), addAll: async () => {} }),
  match: async req => store.get(req.url)?.clone(), keys: async () => [], delete: async () => true };
let online = true;
const ctx = { self: { addEventListener: (t, f) => (handlers[t] = f), location: { origin: "https://rwalwan.github.io" }, skipWaiting() {}, clients: { claim() {} } },
  caches, Headers, Response, URL, Promise, Object, String, Date,
  fetch: async req => { if (!online) throw new TypeError("Failed to fetch"); return new Response(JSON.stringify({ pts: 41 }), { status: 200, headers: { "content-type": "application/json" } }); } };
vm.runInNewContext(fs.readFileSync(new URL("../site/sw.js", import.meta.url), "utf8"), ctx);
const fetchVia = async url => { let p; handlers.fetch({ request: { method: "GET", url }, respondWith: x => (p = x) }); return p; };

const url = "https://api.sleeper.com/stats/nba/2026/2?season_type=regular";
const a = await fetchVia(url);
assert.equal(a.headers.get("x-lockdesk-cached"), null, "online: the live response, unmarked");
await new Promise(r => setTimeout(r, 20));
online = false;
const b = await fetchVia(url);
assert.equal(b.headers.get("x-lockdesk-cached"), "1", "offline: the saved copy, marked");
assert.ok(+b.headers.get("x-lockdesk-saved") > 0, "with the time it was saved");
assert.deepEqual(await b.json(), { pts: 41 });
const app = fs.readFileSync(new URL("../site/app.js", import.meta.url), "utf8");
assert.ok(app.includes('r.headers.get("x-lockdesk-cached")') && app.includes("Offline: showing saved data"), "page shows the banner");
console.log("ok: review 2 finding 7e");
