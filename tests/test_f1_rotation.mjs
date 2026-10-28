// Finding 1 (review 2026-10-28): the lock bar ignored multi-day rotation through idle bench players.
// One UTIL slot. A played Monday (open, lockable) and plays again Sunday; bench B plays Wednesday and Friday.
// Everyone projects 40 FP/G and plays with probability 0.92. Waiting and rotating B (Wed), B (Fri), A (Sun)
// is worth 47.0; the old engine's bar was 43.3 (B's two games alone), so it locked a 44 or a 46.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, contStats, tierQ } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const days = ["2026-11-02", "2026-11-04", "2026-11-06", "2026-11-08"];          // Mon, Wed, Fri, Sun
const sched = [
  { week: 3, date: days[0], home: { team: "AAA" }, away: { team: "XXX" }, status: "complete" },
  { week: 3, date: days[1], home: { team: "BBB" }, away: { team: "YYY" }, status: "pre_game" },
  { week: 3, date: days[2], home: { team: "BBB" }, away: { team: "YYY" }, status: "pre_game" },
  { week: 3, date: days[3], home: { team: "AAA" }, away: { team: "XXX" }, status: "pre_game" },
];
const q92 = Object.fromEntries(days.map(d => [d, 0.92]));
function bar(score) {
  const book = new Book({ scoring: {}, players: { A: ["A", "AAA", ["SF"], null], B: ["B", "BBB", ["SF"], null] },
    priors: { A: 40, B: 40 }, gamelog: { A: [[days[0], score, 34, "g0"]] }, weights: { rotowire: 1, model: 0, ctx: 0 },
    avail: { model: null, players: { A: { status: null, q: q92 }, B: { status: null, q: q92 } } } });
  book.proj = { [`A|${days[3]}`]: 40, [`B|${days[1]}`]: 40, [`B|${days[2]}`]: 40 };
  const wp = new WeekPlan({ Q: QS, book, schedule: sched, week: 3, today: "2026-11-03", now: new Date("2026-11-03T20:00:00Z"),
    rosterPositions: ["UTIL", "BN"], roster: { players: ["A", "B"] }, matchup: { starters: ["A"], players_points: { A: score * 10 } },
    rosters: [], tips: {}, elig: () => true, locks: {} });
  const s = wp.build().slots.find(x => x.slot === "UTIL");
  return { bar: s.bar, action: s.action };
}

// the correct continuation: one stream of draws B, B, A
const Qp = tierQ(QS.tiers, 40, QS.quantiles);
const stream = contStats(QS.quantiles, [1, 2, 3].map(() => ({ mu: 40, q: 0.92, Q: Qp }))).W[0];
assert.equal(Math.round(stream * 10) / 10, 47.0, "rotation value");

const r44 = bar(44), r46 = bar(46), r50 = bar(50);
console.log("bar", r44.bar, "| 44 ->", r44.action, "| 46 ->", r46.action, "| 50 ->", r50.action);
assert.equal(r44.bar, 47.0, "bar should include rotating the idle bench player");
assert.notEqual(r44.action, "lock", "44 is below the rotation value: wait");
assert.notEqual(r46.action, "lock", "46 is below the rotation value: wait");
assert.equal(r50.action, "lock", "50 beats 47.0: lock");
console.log("ok: finding 1");
