// Finding 2 (review 2026-10-28): healthy players' play probabilities were too low.
//  * B2B_FACTOR was 0.86: that's the BASE play rate from the research (miss 14% -> 20%), not the back-to-back
//    ratio. The ratio is 0.802 / 0.861 = 0.93, and refitting on 2021-24 (top-100) gives 0.93-0.94 at every horizon.
//  * Healthy was a flat 0.92 with no source. History (2021-24, top-100, games after a game he played):
//    P(plays the next non-b2b game) = 0.944 (n=16,500), decaying to ~0.85 twenty games out as injuries arrive.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, B2B_FACTOR, contStats, tierQ } from "../site/engine.js";

assert.ok(Math.abs(B2B_FACTOR - 0.93) < 0.005, `b2b factor ${B2B_FACTOR} should be the ratio 0.93`);

const book = new Book({ scoring: {}, players: { P: ["P", "AAA", ["SF"], null] }, priors: { P: 40 }, gamelog: {} });
const next = book.playProb("P", 1, false, "2026-11-02", 0), nextB2b = book.playProb("P", 1, true, "2026-11-02", 0);
const far = book.playProb("P", 60, false, "2026-12-30", 29);
console.log("healthy next", next, "| next on b2b", nextB2b, "| 30 games out", far);
assert.equal(next, 0.94, "next game, undesignated, not a b2b");
assert.equal(nextB2b, 0.88, "next game on a b2b = 0.944 x 0.93");
assert.ok(far >= 0.84 && far <= 0.86, "30 games out decays to the long-run rate");

// review's worked example: 40 FP/G, two games left -> bar 43.3 with the old flat 0.92 (0.79 on a b2b: 41.3)
const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const Qp = tierQ(QS.tiers, 40, QS.quantiles), W = qs => Math.round(contStats(QS.quantiles, qs.map(q => ({ mu: 40, q, Q: Qp }))).W[0] * 10) / 10;
assert.equal(W([0.92, 0.92]), 43.3);
assert.equal(W([0.974, 0.974]), 44.7);           // the review's 0.974 case (reproduces); its b2b 42.6 does not (0.974 x 0.93 gives 43.5)
console.log("bar now", W([next, book.playProb("P", 2, false, "2026-11-04", 1)]), "(was 43.3)");
console.log("ok: finding 2");
