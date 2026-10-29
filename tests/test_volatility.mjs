// Per-player spread (app/volatility.py): Lock-In keeps the best game, so at the same average a boom-or-bust player is
// worth more than a steady one. Before, both got their tier's spread and the same value.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, Valuer, volQ, tierQ } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const mean = a => a.reduce((x, y) => x + y, 0) / a.length, sd = a => Math.sqrt(mean(a.map(x => (x - mean(a)) ** 2)));
const Q = tierQ(QS.tiers, 35, QS.quantiles);
assert.ok(Math.abs(mean(volQ(Q, 1.4)) - 1) < 1e-9 && sd(volQ(Q, 1.4)) > sd(Q) && sd(volQ(Q, 0.7)) < sd(Q), "spread scales, mean stays 1");
assert.equal(volQ(Q, undefined), Q);

// two weeks, three games a week each, both 35 FP/G; one booms (r 1.4), one is steady (r 0.7)
const sched = [];
for (const [w, ds] of [[3, ["2026-11-02", "2026-11-04", "2026-11-06"]], [4, ["2026-11-09", "2026-11-11", "2026-11-13"]]])
  for (const d of ds) for (const t of ["AAA", "BBB"]) sched.push({ week: w, date: d, home: { team: t }, away: { team: "X" }, status: "pre_game" });
const book = new Book({ scoring: {}, players: { BOOM: ["Boom", "AAA", ["SF"], null], STEADY: ["Steady", "BBB", ["SF"], null] },
  priors: { BOOM: 35, STEADY: 35 }, gamelog: {}, weights: { rotowire: 1, model: 0, ctx: 0 }, vol: { BOOM: 1.4, STEADY: 0.7 } });
const v = new Valuer({ book, schedule: sched, Q: QS, rosterPositions: ["SF", "BN"], week: 2, today: "2026-11-01" });
const boom = v.perWeek("BOOM"), steady = v.perWeek("STEADY");
console.log("value per week at 35 FP/G: boom-or-bust", boom.toFixed(1), "| steady", steady.toFixed(1));
assert.ok(boom > steady + 1, "the boom-or-bust player is worth more in Lock-In");
console.log("ok: volatility (engine)");
