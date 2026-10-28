// Finding 9 (review 2026-10-28): when a player's status changed between the 15-minute job and the browser, the
// browser fell back to a status-only chain that assumed 0 games missed. A long-absent player re-listed Out got a
// fresh-injury curve (~50% for the game after next) until the next job run (seen: Haliburton built GTD, live Out).
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book } from "../site/engine.js";
const M = JSON.parse(fs.readFileSync(new URL("../app/data/availability_model.json", import.meta.url)));
const avail = { model: M, players: { H: { status: "GTD", missed: 6, q: { "2026-11-02": 0.483, "2026-11-04": 0.6 } } } };
const book = new Book({ scoring: {}, players: { H: ["H", "IND", ["PG"], "Out"] }, priors: { H: 45 }, gamelog: {}, avail });
const q1 = book.playProb("H", 2, false, "2026-11-04", 1);
console.log("status now Out, job built GTD with 6 missed -> game after next:", q1);
// the job's own model for 6 missed: next game 0 (Out), then the 7-missed return rate
assert.ok(q1 < 0.2, `kept the missed count (expected ~${(M.by_k[6] * 0.923).toFixed(2)}), got ${q1}`);
assert.equal(book.playProb("H", 1, false, "2026-11-02", 0), 0);
console.log("ok: finding 9");
