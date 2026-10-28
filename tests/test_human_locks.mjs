// Opponent model from other Lock-In leagues: an opponent's open lockable game is valued at what real managers
// do (P(lock | score vs bar)), not at the engine's perfect call.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, humanLockRate } from "../site/engine.js";
const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const rows = [{ lo: 0, hi: 1, lock_rate: 0.1 }, { lo: 1, hi: 1.5, lock_rate: 0.4 }, { lo: 1.5, hi: 99, lock_rate: 0.35 }];
assert.equal(humanLockRate(rows, 1.2), 0.4);
assert.equal(humanLockRate([], 1.2), 1);            // no data: engine behavior
const sched = [{ week: 2, date: "2026-10-27", home: { team: "AAA" }, away: { team: "BBB" }, status: "complete" },
               { week: 2, date: "2026-10-30", home: { team: "AAA" }, away: { team: "BBB" }, status: "pre_game" }];
const book = new Book({ scoring: {}, players: { O: ["O", "AAA", ["SF"], null] }, priors: { O: 40 }, gamelog: { O: [["2026-10-27", 70, 30, "g"]] } });
const wp = new WeekPlan({ Q: QS, book, schedule: sched, week: 2, today: "2026-10-28", now: new Date("2026-10-28T20:00:00Z"),
  rosterPositions: ["SF", "BN"], roster: { players: ["O"] }, matchup: { starters: ["O"], players_points: { O: 700 } }, rosters: [], tips: {}, elig: () => true, locks: {} });
const perfect = wp.build().outlook.mean, human = wp.build({ humanLocks: rows }).outlook.mean;
console.log("opponent expected: engine-perfect", perfect.toFixed(1), "| like real managers", human.toFixed(1));
assert.ok(Math.abs(perfect - 70) < 0.5 && human < perfect - 5, "70 vs a ~37 bar: real managers lock it only 35% of the time");
console.log("ok: human locks");
