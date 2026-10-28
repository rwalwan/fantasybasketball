// Finding 3, engine side: the fitted weights are used as given, the bias scale applies, and a game with no
// RotoWire line under RotoWire-only weights falls back to the model instead of dividing by zero.
import assert from "node:assert/strict";
import { Book } from "../site/engine.js";
const w = { rotowire: 1, model: 0, ctx: 0, scale: 0.98 };
const book = new Book({ scoring: {}, players: { P: ["P", "AAA", ["SF"], null] }, priors: { P: 40 }, gamelog: {}, weights: w });
book.proj = { "P|2026-11-02": 50 };
assert.equal(book.gameMu("P", "2026-11-02"), 49);                 // 50 x 0.98: RotoWire only
assert.equal(book.gameMu("P", "2026-11-04"), Math.round(40 * 0.98 * 10) / 10);   // no RotoWire line: model
console.log("ok: finding 3 (engine)");
