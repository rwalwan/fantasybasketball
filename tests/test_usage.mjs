// Engine side of the usage model: a graded 'usage' source in the blend, and usage in near-week season values.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, Valuer } from "../site/engine.js";
const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const usage = { P: { "2026-11-03": [1.2, ["S likely out"]] } };
const book = new Book({ scoring: {}, players: { P: ["P", "AAA", ["PG"], null] }, priors: { P: 40 }, gamelog: {}, usage,
  weights: { rotowire: 0, model: 0, ctx: 0, usage: 1 } });
assert.equal(book.gameMu("P", "2026-11-03"), 48);       // 40 x 1.2
assert.equal(book.gameMu("P", "2026-11-05"), 40);       // no adjustment that day
const sched = [{ week: 3, date: "2026-11-03", home: { team: "AAA" }, away: { team: "BBB" }, status: "pre_game" }];
const b2 = new Book({ scoring: {}, players: { P: ["P", "AAA", ["PG"], null] }, priors: { P: 40 }, gamelog: {}, usage });
const b3 = new Book({ scoring: {}, players: { P: ["P", "AAA", ["PG"], null] }, priors: { P: 40 }, gamelog: {} });
const v = b => new Valuer({ book: b, schedule: sched, Q: QS, rosterPositions: ["PG"], week: 2, today: "2026-11-01" }).weekly("P")[0];
assert.ok(Math.abs(v(b2) / v(b3) - 1.2) < 0.01, "season value uses the usage factor for that week");
console.log("ok: usage (engine)");
