// Review 3, finding 4: a starter who sits a game while in the lineup can have his slot reset to 0 (in the other
// Lock-In leagues: 423 of 1,200 mid-week cases, uniform across leagues for a given player-game; the earlier score
// is gone). lockState treated every 0 as a Sleeper glitch and kept offering the earlier game: "Lock A - 35.0" for a
// score Sleeper no longer holds, and the week plan counted it.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const d = ["2026-11-09", "2026-11-11", "2026-11-13"];
const G = (date, st) => ({ week: 4, date, home: { team: "AAA" }, away: { team: "XXX" }, status: st });
const mk = ({ wed = "complete", slotPts = 0, inLineupWed = true }) => {
  const book = new Book({ scoring: {}, weights: { rotowire: 1, model: 0, ctx: 0 }, players: { A: ["A", "AAA", ["C"], null] }, priors: { A: 34 },
    gamelog: { A: [[d[0], 35, 33, "g0"]] } });                      // played Monday (35), no stat line Wednesday
  book.proj = { [`A|${d[2]}`]: 34 };
  const sched = [G(d[0], "complete"), ...(wed ? [G(d[1], wed)] : []), G(d[2], "pre_game")];
  return new WeekPlan({ Q: QS, book, schedule: sched, week: 4, today: "2026-11-12", now: new Date("2026-11-12T18:00:00Z"), rosterPositions: ["C"],
    roster: { players: ["A"] }, matchup: { starters: ["A"], players_points: { A: slotPts }, starters_points: [slotPts] }, rosters: [],
    tips: { [`${d[2]}|AAA`]: "2026-11-14T00:00:00Z" }, elig: (p, date) => (date === d[1] ? inLineupWed : true), locks: {} }).build().slots[0];
};
const wiped = mk({});
console.log("sat Wednesday in the lineup, Sleeper shows 0:", wiped.action, "| score", wiped.score ?? null, "|", wiped.detail);
assert.notEqual(wiped.action, "lock", "there is no 35 left to lock");
assert.ok(wiped.score == null, "the earlier score must not be offered");
assert.match(wiped.detail, /35/, "say what happened to the 35");
// controls: the 35 is still his slot's score when (a) Sleeper still shows it, (b) there was no game he sat (a 0 is a
// glitch, as before), (c) he sat it on the bench
assert.equal(mk({ slotPts: 350 }).action, "lock");
assert.equal(mk({ wed: null }).action, "lock");
assert.equal(mk({ inLineupWed: false }).action, "lock");
console.log("ok: review 3 finding 4 (wiped score)");
