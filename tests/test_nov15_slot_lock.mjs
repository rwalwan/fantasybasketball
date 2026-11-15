// Nov 15: a game moved into a slot was offered as a lock when Sleeper doesn't allow it.
//  - Neemias Queta (UTIL): "lock 52", but the 52 (Wed) came before he was on the roster (no lineup record that day)
//  - Onyeka Okongwu (C): 39 treated as lockable in C, but he played it from UTIL
// Cause: "Sleeper's slot shows his latest game's points -> that game counted" (Oct 31). Sleeper shows a player's latest
// game in whatever slot he sits in now. Rule now: the lineup record decides, and only for the slot he played it in.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, eligFromSnaps } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const [wed, sun] = ["2026-11-11", "2026-11-15"];
const g = (date, st, t) => ({ week: 4, date, home: { team: t }, away: { team: "XXX" }, status: st });
const sched = [g(wed, "complete", "AAA"), g(sun, "pre_game", "AAA"), g(wed, "complete", "BBB"), g(sun, "pre_game", "BBB")];
const mk = (starters, gamelog, pts, snaps, ov = {}) => new WeekPlan({ Q: QS, schedule: sched, week: 4, today: "2026-11-15", now: new Date("2026-11-15T08:00:00Z"),
  book: new Book({ scoring: {}, players: { Q: ["Q", "AAA", ["C"], null], O: ["O", "BBB", ["C"], null], X: ["X", "BBB", ["C"], null] },
    priors: { Q: 40, O: 40, X: 30 }, gamelog, weights: { rotowire: 1, model: 0, ctx: 0 } }),
  rosterPositions: ["C", "UTIL", "UTIL", "BN"], roster: { players: ["Q", "O", "X"] }, matchup: { starters, players_points: pts },
  rosters: [], tips: { [`${sun}|AAA`]: "2026-11-16T00:00:00Z", [`${sun}|BBB`]: "2026-11-16T01:00:00Z" }, elig: eligFromSnaps(snaps, ov), locks: {} });
const log = { Q: [[wed, 52, 30, "q"]], O: [[wed, 39, 30, "o"]], X: [[wed, 20, 30, "x"]] };
const pts = { Q: 520, O: 390, X: 200 };

// Queta: picked up after Wednesday (others have Wednesday records, he has none) -> not lockable, even though Sleeper
// shows his 52 in the UTIL slot
const snapsQ = { [`${wed}|O`]: { slot: "C", i: 0, frozen: true }, [`${wed}|X`]: { slot: null, i: null, frozen: true } };
const wq = mk(["O", "Q", "X"], log, pts, snapsQ);
assert.equal(wq.elig("Q", wed), false);
assert.equal(wq.lockState("Q").st, "bench");
const sq = wq.build().slots.find(s => s.pid === "Q");
assert.notEqual(sq.action, "lock"); assert.notEqual(sq.action, "pass");
console.log("Queta:", sq.action, "-", sq.detail);

// Okongwu: played Wednesday in UTIL (index 1), now in C (index 0) -> not lockable there
const snapsO = { [`${wed}|O`]: { slot: "UTIL", i: 1, frozen: true }, [`${wed}|Q`]: { slot: "C", i: 0, frozen: true }, [`${wed}|X`]: { slot: null, frozen: true } };
const wo = mk(["O", "Q", "X"], log, pts, snapsO);
assert.equal(wo.lockState("O").st, "moved");
const so = wo.build().slots.find(s => s.pid === "O");
assert.ok(!["lock", "pass"].includes(so.action), so.action);
assert.match(so.detail, /played in UTIL/);
console.log("Okongwu:", so.action, "-", so.detail);
// ...back in UTIL index 1, the same game is lockable
assert.equal(mk(["Q", "O", "X"], log, pts, snapsO).lockState("O").st, "open");
// the other UTIL (index 2) is a different slot even though the name matches
assert.equal(mk(["Q", "X", "O"], log, pts, snapsO).lockState("O").st, "moved");
// records from before slot indexes were saved fall back to the slot name
const old = { [`${wed}|O`]: { slot: "UTIL", frozen: true } };
assert.equal(mk(["Q", "X", "O"], log, pts, old).lockState("O").st, "open");
assert.equal(mk(["O", "Q", "X"], log, pts, old).lockState("O").st, "moved");

// a bench record stays a bench game even when Sleeper's slot shows its points (replaces the Oct 31 rule)
assert.equal(mk(["O", "Q", "X"], log, pts, { [`${wed}|O`]: { slot: null, frozen: true } }).lockState("O").st, "bench");
// a manual "he was starting" answer still makes it lockable (no slot to check against)
assert.equal(mk(["O", "Q", "X"], log, pts, snapsQ, { [`${wed}|Q`]: true }).lockState("Q").st, "open");
// a date the tracker never covered is unknown, not "off the roster"
assert.equal(eligFromSnaps({})("O", wed), null);
console.log("ok: nov 15 slot locks");

// Moving him out of the slot after the game loses it for good, even if he's moved back (Sleeper doesn't allow it)
import { mergeSnaps } from "../site/engine.js";
const leftSnaps = { [`${wed}|O`]: { slot: "UTIL", i: 1, frozen: true, left: true }, [`${wed}|Q`]: { slot: "C", i: 0, frozen: true } };
assert.equal(mk(["Q", "O", "X"], log, pts, leftSnaps).lockState("O").st, "moved");     // back in UTIL index 1: still gone
// the Worker's record (no "left") doesn't erase the job's "left"
const m = mergeSnaps(leftSnaps, { [`${wed}|O`]: { slot: "UTIL", i: 1, frozen: true } });
assert.equal(m[`${wed}|O`].left, true);
console.log("ok: nov 15 moved-and-back");
