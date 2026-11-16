// Nov 15, Sunday night: the opponent's projected final (354.5) came out below his current score (514.5).
//  1) Anthony Davis was locked at 79.5 (Nov 9) and playing again: counted at his live game, not the 79.5
//  2) slots with no games left (score counts automatically) were discounted by the human lock-rate model
//  3) Caruso showed 40.5 but his latest game was from the bench: counted as 0
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const [mon, wed, fri, sun] = ["2026-11-09", "2026-11-11", "2026-11-13", "2026-11-15"];
const g = (date, st, t) => ({ week: 4, date, home: { team: t }, away: { team: "XXX" }, status: st });
const sched = [g(mon, "complete", "LAL"), g(wed, "complete", "LAL"), g(sun, "in_progress", "LAL"),
               g(mon, "complete", "UTA"), g(sun, "complete", "UTA"),
               g(wed, "complete", "OKC"), g(fri, "complete", "OKC")];
const players = { D: ["Davis", "LAL", ["C"], null], K: ["George", "UTA", ["PG"], null], C: ["Caruso", "OKC", ["SG"], null] };
const gamelog = { D: [[mon, 79.5, 36, "d1"], [wed, 53.5, 34, "d2"], [sun, 27, 20, "d3"]], K: [[mon, 30, 30, "k1"], [sun, 38, 33, "k2"]],
                  C: [[wed, 40.5, 30, "c1"], [fri, 19, 22, "c2"]] };
const book = new Book({ scoring: {}, players, priors: { D: 55, K: 40, C: 25 }, gamelog, weights: { rotowire: 1, model: 0, ctx: 0 } });
const snaps = { [`${mon}|D`]: { slot: "C", frozen: true }, [`${wed}|D`]: { slot: "C", frozen: true }, [`${sun}|D`]: { slot: "C", frozen: true },
  [`${mon}|K`]: { slot: "PG", frozen: true }, [`${sun}|K`]: { slot: "PG", frozen: true },
  [`${wed}|C`]: { slot: "SG", frozen: true }, [`${fri}|C`]: { slot: null, frozen: true } };
import { eligFromSnaps } from "../site/engine.js";
const wp = new WeekPlan({ Q: QS, schedule: sched, week: 4, today: sun, now: new Date("2026-11-16T01:30:00Z"), book,
  rosterPositions: ["PG", "SG", "C", "BN"], roster: { players: ["K", "C", "D"] },
  matchup: { starters: ["K", "C", "D"], starters_points: [380, 405, 795], players_points: { K: 380, C: 405, D: 795 } },
  rosters: [], tips: { [`${sun}|LAL`]: "2026-11-16T00:30:00Z", [`${sun}|UTA`]: "2026-11-15T20:00:00Z" }, elig: eligFromSnaps(snaps), locks: {} });
const sD = wp.lockState("D"), sC = wp.lockState("C");
assert.equal(sD.st, "locked"); assert.equal(sD.g.fp, 79.5);
assert.equal(sC.st, "open"); assert.equal(sC.g.fp, 40.5); assert.ok(sC.kept);
const human = [{ lo: 0, hi: 99, lock_rate: 0.7 }];     // any lock-rate table: must not matter with no games left
const plan = wp.build({ humanLocks: human });
console.log("opponent final:", plan.outlook.mean.toFixed(1), "(score now 158.0)");
assert.ok(Math.abs(plan.outlook.mean - (38 + 40.5 + 79.5)) < 0.01, plan.outlook.mean);
console.log("ok: nov 15 opponent final");
