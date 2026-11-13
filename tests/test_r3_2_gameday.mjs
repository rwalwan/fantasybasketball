// Review 3, finding 2 (engine side): "no designation -> plays 99.9%" is the rate at the last check before tip. It was
// used as the next-game probability whenever the game was (0.999 for a game three days away, then 0.92 for the one
// after). Now the curve's first point is the next-game rate (95.5% at this stage of the season; this season 95.8%,
// n=1,445) and the game-day rate applies only to a game that tips today.
import assert from "node:assert/strict";
import { Book } from "../site/engine.js";
const model = { by_k: [0.5, 0.3, 0.25, 0.25, 0.23, 0.18, 0.16, 0.22], k9_12: 0.12, k13_20: 0.12, healthy: 0.944, healthy_gameday: 0.999,
  designation: { Probable: 0.866, Questionable: 0.483, Doubtful: 0.042, Out: 0 },
  healthy_curve: { ahead: [1, 2, 3], q: [0.955, 0.923, 0.907] } };
const b = new Book({ scoring: {}, players: { P: ["P", "AAA", ["SF"], null] }, priors: { P: 40 }, gamelog: {}, avail: { model, players: {} } });
assert.equal(b.playProb("P", 0, false, "2026-11-10", 0), 1, "tips today, no designation: the game-day rate (0.999, shown as 1)");
assert.equal(b.playProb("P", 2, false, "2026-11-12", 0), 0.96, "next game two days away: the next-game rate, not 0.999");
assert.equal(b.playProb("P", 1, true, "2026-11-11", 0), 0.89, "second night of a back-to-back tomorrow: 0.955 x 0.93 (this season: 0.889, n=334)");
assert.equal(b.playProb("P", null, false, "2026-11-20", 1), 0.92, "valuations (no day count) use the curve");
delete model.healthy_gameday;
assert.equal(b.playProb("P", 0, false, "2026-11-10", 0), 0.96, "no game-day rate published yet: the curve");
console.log("ok: review 3 finding 2 (game-day vs next-game play rate)");
