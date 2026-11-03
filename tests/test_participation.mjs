// A healthy player who has been sitting (Julian Reese: 1 of New Orleans' last 7) plays less: the job's participation
// factor (research: P(plays next) by games played of the team's last 5) scales his play chance, so his value drops.
import assert from "node:assert/strict";
import { Book, BASELINE } from "../site/engine.js";
const b = new Book({ scoring: {}, players: { R: ["Reese", "NOP", ["C"], null], S: ["Starter", "NOP", ["C"], null] }, priors: { R: 30, S: 30 }, gamelog: {},
  part: { R: Math.round(BASELINE.part[1] / BASELINE.part[5] * 1000) / 1000 } });
const qR = b.playProb("R", 1, false, "2026-11-04"), qS = b.playProb("S", 1, false, "2026-11-04");
console.log("plays next: benched bench player", qR, "| regular", qS);
assert.ok(qR < 0.4 && qS > 0.9);
console.log("ok: participation");
