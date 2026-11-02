// IR: a healthy player still on IR blocks adds in Sleeper. The engine values every drop that brings him back
// (this week's locked points + rest of season) against releasing him; Out players go to an open IR spot.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, Valuer, irMoves } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const sched = [];
for (const [w, ds] of [[3, ["2026-11-03", "2026-11-05", "2026-11-07"]], [4, ["2026-11-10", "2026-11-12", "2026-11-14"]], [5, ["2026-11-17", "2026-11-19"]]])
  for (const d of ds) for (const t of ["AAA", "BBB", "CCC", "DDD", "EEE"]) sched.push({ week: w, date: d, home: { team: t }, away: { team: "X" }, status: "pre_game" });
const run = (priors, status = {}) => {
  const players = Object.fromEntries(Object.keys(priors).map((p, i) => [p, [p, "ABCDE"[i % 5].repeat(3), ["SF"], status[p] || null]]));
  const book = new Book({ scoring: {}, players, priors, gamelog: {}, weights: { rotowire: 1, model: 0, ctx: 0 } });
  const mine = { players: Object.keys(priors), reserve: ["R"] };
  const rp = ["SF", "SF", "BN", "BN", "IR", "IR"];
  const wp = new WeekPlan({ Q: QS, book, schedule: sched, week: 3, today: "2026-11-02", now: new Date("2026-11-02T18:00:00Z"),
    rosterPositions: rp, roster: mine, matchup: { starters: ["A", "B"], players_points: {} }, rosters: [mine], tips: {}, elig: () => true, locks: {} });
  const valuer = new Valuer({ book, schedule: sched, Q: QS, rosterPositions: rp, week: 3, today: "2026-11-02" });
  return irMoves(wp, valuer, mine, rp);
};
// R (healthy, 38/game) is better than C (bench, 15): bring him back, drop C
let ir = run({ A: 45, B: 30, C: 15, R: 38 });
console.log("healthy 38 on IR:", ir.activate[0].call, "drop", ir.activate[0].best.dropName, ir.activate[0].best.gain);
assert.equal(ir.activate[0].call, "activate"); assert.equal(ir.activate[0].best.dropName, "C");
assert.ok(ir.activate[0].options.length === 3, "every active player is a candidate");
// R is worse than everyone: release him
ir = run({ A: 45, B: 30, C: 25, R: 8 });
console.log("healthy 8 on IR:", ir.activate[0].call, ir.activate[0].best.gain);
assert.equal(ir.activate[0].call, "release");
// R still Out: nothing to do; an Out active player with an open IR spot goes to IR
ir = run({ A: 45, B: 30, C: 25, R: 38 }, { R: "Out", C: "Out" });
assert.equal(ir.activate.length, 0);
assert.deepEqual(ir.toIR.map(x => x.pid), ["C"]);
// tie (neither bench player starts either way): drop the one worth less on his own
ir = run({ A: 45, B: 30, C: 15, D: 12, R: 38 });
assert.equal(ir.activate[0].best.dropName, "D");
console.log("ok: ir");
