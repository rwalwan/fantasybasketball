// Nov 28: the last-minute injury watch (worker/src/injuries.js).
// Case: Lock Desk re-ran every 15 minutes and Sleeper's labels can lag a team's report by hours (Nov 16: Queta ruled
// out 5:16 pm ET, Sleeper GTD 2+ hours). Rule: in the 2 hours before a tip, read ESPN's injury report every minute for
// the teams about to play; on a status change save it and start the update job (at most every 4 minutes); the first
// read of a team's report is recorded without a run; a player taken off the report = Available; outside the window
// nothing is fetched. A report only ever makes a player LESS likely to play than Sleeper says (escalate).
import assert from "node:assert/strict";
import { parseInjuries, watchInjuries, windowTeams } from "../worker/src/injuries.js";
import { escalateStatus as escalate, Book, reportCurrent } from "../site/engine.js";

const feed = (st, extra = []) => ({ injuries: [
  { displayName: "Boston Celtics", injuries: [{ status: st, shortComment: "Robinson (illness) is out Friday", date: "2026-11-27T20:01Z",
    athlete: { displayName: "Mitchell Robinson" } }, ...extra] },
  { displayName: "Atlanta Hawks", injuries: [{ status: "Questionable", athlete: { displayName: "Onyeka Okongwu" } }] },
  { displayName: "Utah Jazz", injuries: [{ status: "Out", athlete: { displayName: "Far Away" } }] }] });
const items = parseInjuries(feed("Out"));
assert.deepEqual(items.map(x => [x.team, x.name, x.status]), [["BOS", "Mitchell Robinson", "Out"], ["ATL", "Onyeka Okongwu", "Questionable"], ["UTA", "Far Away", "Out"]]);
assert.deepEqual(parseInjuries({ injuries: [{ team: { abbreviation: "GS" }, injuries: [{ status: "Out", athlete: { displayName: "X" } }] }] }).map(x => x.team), ["GSW"]);
assert.deepEqual(parseInjuries(null), []);

const tips = { BOS: "2026-11-28T01:00:00Z", ATL: "2026-11-28T01:00:00Z", UTA: "2026-11-28T03:00:00Z" };
assert.deepEqual(windowTeams(tips, new Date("2026-11-27T22:00:00Z")), [], "3 hours out: no watch");
assert.deepEqual(windowTeams(tips, new Date("2026-11-27T23:30:00Z")).sort(), ["ATL", "BOS"]);

const players = { 1887: ["Mitchell Robinson", "BOS"], 2302: ["Neemias Queta", "BOS"], 9: ["Far Away", "UTA"] };
let saved = null, kicks = 0, fetches = 0;
const run = (now, st, prev, extra) => watchInjuries({ fetchInjuries: async () => { fetches++; return feed(st, extra); }, tips, now: new Date(now), players, prev,
  save: async v => { saved = v; }, kick: async () => { kicks++; return { ok: true }; } });

// outside the window: nothing fetched, nothing written
let r = await run("2026-11-27T21:00:00Z", "Out", {});
assert.equal(r.active, false); assert.equal(fetches, 0); assert.equal(saved, null);
// first read of the day: recorded, no run started
r = await run("2026-11-27T23:01:00Z", "Questionable", {});
assert.equal(r.active, true); assert.equal(kicks, 0); assert.ok(saved.items["BOS|mitchell robinson"]);
assert.equal(saved.items["BOS|mitchell robinson"].pid, "1887"); assert.equal(saved.items["UTA|far away"], undefined, "Utah tips later");
// nothing new: no write
let prev = saved; saved = null;
r = await run("2026-11-27T23:02:00Z", "Questionable", prev);
assert.equal(saved, null); assert.equal(kicks, 0);
// Robinson ruled out: saved, update job started
r = await run("2026-11-27T23:10:00Z", "Out", prev);
assert.equal(kicks, 1); assert.deepEqual(r.changed.map(c => [c.name, c.from, c.to]), [["Mitchell Robinson", "Questionable", "Out"]]);
assert.equal(saved.items["BOS|mitchell robinson"].status, "Out"); assert.ok(saved.kickedAt);
// another change 2 minutes later: saved, but no second run inside 4 minutes
prev = saved;
r = await run("2026-11-27T23:12:00Z", "Out", prev, [{ status: "Doubtful", athlete: { displayName: "Derrick White" } }]);
assert.equal(kicks, 1); assert.equal(saved.items["BOS|derrick white"].status, "Doubtful");
// taken off the report = cleared
prev = saved;
r = await run("2026-11-27T23:20:00Z", "Out", prev);
assert.equal(saved.items["BOS|derrick white"].status, "Available"); assert.equal(kicks, 2);

// a new note with the same status (Out from Friday, now ruled out for Saturday) is news too
prev = saved;
const feedAt = (at) => ({ injuries: [{ displayName: "Boston Celtics", injuries: [{ status: "Out", shortComment: "Robinson is out Saturday", date: at, athlete: { displayName: "Mitchell Robinson" } }] }] });
r = await watchInjuries({ fetchInjuries: async () => feedAt("2026-11-27T23:25Z"), tips, now: new Date("2026-11-27T23:30:00Z"), players, prev,
  save: async v => { saved = v; }, kick: async () => { kicks++; return { ok: true }; } });
assert.equal(kicks, 3); assert.equal(saved.items["BOS|mitchell robinson"].at, "2026-11-27T23:25Z");

// escalate only toward sitting
assert.equal(escalate(null, "Out"), "Out");
assert.equal(escalate("GTD", "Out"), "Out");
assert.equal(escalate("Questionable", "Doubtful"), "Doubtful");
assert.equal(escalate("Out", "Questionable"), null, "never un-rule a player out");
assert.equal(escalate("GTD", "Available"), null);
assert.equal(escalate(null, "Questionable"), null, "a questionable tag isn't enough to override");
assert.equal(escalate("IR", "Out"), null);
// the page applies the saved report to the book: Robinson GTD on Sleeper, Out on the report -> Out; Queta untouched
const book = new Book({ scoring: {}, players: { 1887: ["Mitchell Robinson", "BOS", ["C"], "GTD"], 2302: ["Neemias Queta", "BOS", ["C"], null] }, priors: {}, gamelog: {} });
const FRI = new Date("2026-11-27T22:00:00Z"), SAT = new Date("2026-11-28T18:41:00Z");
const rob = { pid: "1887", team: "BOS", status: "Out", comment: "Robinson (illness) is out Friday", at: "2026-11-27T20:01Z" };
const ch = book.applyReports({ "BOS|mitchell robinson": rob, "BOS|neemias queta": { pid: "2302", team: "BOS", status: "Questionable", comment: "Queta is questionable", at: "2026-11-27T20:01Z" } }, FRI);
assert.deepEqual(ch, [{ pid: "1887", from: "GTD", to: "Out" }]);
assert.equal(book.status("1887"), "Out"); assert.equal(book.status("2302"), null);
assert.deepEqual(book.applyReports(null), []);
// first live run (Nov 28): ESPN's "Out" lags its own note and outlives the game it was about
const allen = { status: "Out", comment: "Allen (concussion) has been upgraded to probable for Saturday's game against the Nets.", at: "2026-11-28T18:08Z" };
const landale = { status: "Out", comment: "Landale (hip) is out for Friday's game against the Celtics.", at: "2026-11-26T22:44Z" };
assert.equal(reportCurrent(allen, SAT), false, "a note that says probable wins over the Out label");
assert.equal(reportCurrent(landale, SAT), false, "Friday's game is over by Saturday");
assert.equal(reportCurrent(landale, new Date("2026-11-27T20:00:00Z")), true);
assert.equal(reportCurrent(rob, SAT), false);
assert.equal(reportCurrent({ comment: "Smith has been ruled out.", at: "2026-11-28T15:00Z" }, SAT), true);
assert.equal(reportCurrent({ comment: "Smith has been ruled out.", at: "2026-11-27T15:00Z" }, SAT), false, "no day named: 24 hours");
const b2 = new Book({ scoring: {}, players: { 1959: ["Grayson Allen", "CHA", ["SG"], "GTD"] }, priors: {}, gamelog: {} });
assert.deepEqual(b2.applyReports({ "CHA|grayson allen": { pid: "1959", team: "CHA", ...allen } }, SAT), []);
assert.equal(b2.status("1959"), "GTD");
console.log("ok: Nov 28 injury watch");
