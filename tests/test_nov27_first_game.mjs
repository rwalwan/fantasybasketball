// Nov 27: players Sleeper listed "Out" when the game first became their next game played 42% of the time after 0
// missed games (31 of 73, graded Nov 2-25) and 35% after 1 missed (19 of 55), but the engine gave them 0%. The nightly
// trainer (app/train_models.py PlayFirst) now learns a next-game rate by status and games missed; the job ships it in
// the availability model as M.first_game. The browser's own status-only chain (used when the status changed since the
// job ran) must use those learned rates too, and fall back to the old rule when none are learned.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, firstGame } from "../site/engine.js";
const M0 = JSON.parse(fs.readFileSync(new URL("../app/data/availability_model.json", import.meta.url)));
const cells = (o) => Object.fromEntries(["0", "1", "2-3", "4+"].map(b => [b, o[b]]));
const first_game = {
  ahead: { Out: cells({ "0": 0.3, "1": 0.25, "2-3": 0.2, "4+": 0.05 }), Questionable: cells({ "0": 0.65, "1": 0.55, "2-3": 0.5, "4+": 0.35 }),
           Probable: cells({ "0": 0.9, "1": 0.9, "2-3": 0.9, "4+": 0.9 }), Doubtful: cells({ "0": 0.05, "1": 0.05, "2-3": 0.05, "4+": 0.05 }) },
  gameday: { Out: cells({ "0": 0.04, "1": 0.01, "2-3": 0.01, "4+": 0.01 }), Questionable: cells({ "0": 0.8, "1": 0.7, "2-3": 0.7, "4+": 0.55 }),
             Probable: cells({ "0": 0.9, "1": 0.9, "2-3": 0.9, "4+": 0.9 }), Doubtful: cells({ "0": 0.05, "1": 0.05, "2-3": 0.05, "4+": 0.05 }) } };

assert.equal(firstGame({ ...M0, first_game }, "Out", 0), 0.3);
assert.equal(firstGame({ ...M0, first_game }, "DTD", 5), 0.35);
assert.equal(firstGame({ ...M0, first_game }, "IR", 0), null);            // IR / Suspended keep the old rule
assert.equal(firstGame(M0, "Out", 0), null);                               // nothing learned: old rule
console.log("ok: learned next-game rate by status and games missed");

// job built him healthy (no curve), now listed Out: the status-only chain
const mk = (M) => new Book({ scoring: {}, players: { A: ["A", "BOS", ["PG"], "Out"] }, priors: { A: 40 }, gamelog: {},
                             avail: { model: M, players: {} } });
assert.equal(mk(M0).playProb("A", 2, false, "2026-11-30", 0), 0);
assert.equal(mk({ ...M0, first_game }).playProb("A", 2, false, "2026-11-30", 0), 0.3);
const later = mk({ ...M0, first_game }).playProb("A", 4, false, "2026-12-02", 1);
assert.ok(later > 0.3 && later < 0.8, `game after next: back with the learned first-game chance plus the return rate (${later})`);
console.log("ok: status-only chain uses the learned rate, old rule without it");
