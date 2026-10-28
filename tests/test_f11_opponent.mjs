// Finding 11 (review 2026-10-28): the opponent was modeled with elig: () => true, so every recent opponent game
// counted as lockable - including games their player played from the BENCH, which Sleeper never counts.
// The job now records the opponent's lineup each run (opp_lineups_<season>_w<week>.json); a game frozen with
// the player on their bench is not lockable. Unknown games keep the old assumption.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, eligFromSnaps } from "../site/engine.js";
const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const sched = [{ week: 2, date: "2026-10-27", home: { team: "AAA" }, away: { team: "BBB" }, status: "complete" },
               { week: 2, date: "2026-10-30", home: { team: "AAA" }, away: { team: "BBB" }, status: "pre_game" }];
const book = new Book({ scoring: {}, players: { O: ["O", "AAA", ["SF"], null] }, priors: { O: 40 }, gamelog: { O: [["2026-10-27", 60, 30, "g"]] } });
const mk = elig => new WeekPlan({ Q: QS, book, schedule: sched, week: 2, today: "2026-10-28", now: new Date("2026-10-28T20:00:00Z"),
  rosterPositions: ["SF", "BN"], roster: { players: ["O"] }, matchup: { starters: ["O"], players_points: { O: 600 } },
  rosters: [], tips: {}, elig, locks: {} });
const snaps = { "2026-10-27|O": { slot: null, frozen: true } };           // he was on their bench at tip
assert.equal(mk(() => true).lockState("O").st, "open");                  // old: his 60 counted as lockable
assert.equal(mk(eligFromSnaps(snaps)).lockState("O").st, "bench");        // now: bench game, not lockable
assert.equal(eligFromSnaps({})("O", "2026-10-27"), null);                 // no record: unknown
console.log("ok: finding 11");
