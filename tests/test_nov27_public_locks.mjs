// Nov 27: Sleeper's lock record is also in the public matchup_legs_raw query (no login). The Nov 26 probe
// (legs_probe.json, no login) returned starters_games identical to the logged-in record for both teams in Ryan's
// matchup (7 and 3 locks). compareLocks is the cross-check the job runs every 15 minutes before anything relies on it.
import assert from "node:assert/strict";
import { compareLocks, publicLocks } from "../tools/locksrc.mjs";

const logged = { "1": { "1957": "1393723921454333952", "4871": "1393723922897174528" }, "3": { "1433": "1393723924411318272" } };
assert.deepEqual(compareLocks(logged, JSON.parse(JSON.stringify(logged))), { teams: 2, locks: 3, same: 3, diffs: [] });
const pub = { "1": { "1957": "1393723921454333952" }, "3": { "1433": "1393723924411318272", "1883": "g" } };
const c = compareLocks(logged, pub);
assert.equal(c.locks, 4); assert.equal(c.same, 2);
assert.deepEqual(c.diffs.map(d => d.pid).sort(), ["1883", "4871"]);
// the fetch sends no authorization header and reads starters_games per roster
let sent;
const fake = async (u, o) => { sent = o; return { ok: true, status: 200, json: async () => ({ data: { matchup_legs_raw: [{ roster_id: 3, starters_games: { a: "1" } }, { roster_id: 1, starters_games: null }] } }) }; };
assert.deepEqual(await publicLocks(fake, "L", 6), { "3": { a: "1" }, "1": {} });
assert.ok(!Object.keys(sent.headers).some(h => h.toLowerCase() === "authorization"));
await assert.rejects(publicLocks(async () => ({ ok: false, status: 500, json: async () => ({}) }), "L", 6));
console.log("ok: nov 27 public lock record");
