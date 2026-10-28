// Review 2, finding 1: every open slot's rotation stream used the same idle bench players, so their games were
// counted once per slot. Two PG-eligible slots: P1 plays Wed, P2 plays Sun; idle PG P3 plays Thu and Sat. Everyone
// projects 40 and plays with probability 0.92. Only one slot can use P3: the slot evs must sum to at most the best
// feasible split (review: 99.2 shown vs ~93.8 feasible). Here: 90.3 shown before the fix, 86.6 feasible
// (P3 in one slot; P1 Wed then P2 Sun rotating through the other).
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, contStats, tierQ } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const [wed, thu, sat, sun] = ["2026-11-04", "2026-11-05", "2026-11-07", "2026-11-08"];
const g = (date, t) => ({ week: 3, date, home: { team: t }, away: { team: "XXX" }, status: "pre_game" });
const sched = [g(wed, "AAA"), g(thu, "CCC"), g(sat, "CCC"), g(sun, "BBB")];
const days = [wed, thu, sat, sun], q92 = Object.fromEntries(days.map(d => [d, 0.92]));
const book = new Book({ scoring: {}, players: { P1: ["P1", "AAA", ["PG"], null], P2: ["P2", "BBB", ["PG"], null], P3: ["P3", "CCC", ["PG"], null] },
  priors: { P1: 40, P2: 40, P3: 40 }, gamelog: {}, weights: { rotowire: 1, model: 0, ctx: 0 },
  avail: { model: null, players: Object.fromEntries(["P1", "P2", "P3"].map(p => [p, { status: null, q: q92 }])) } });
book.proj = { [`P1|${wed}`]: 40, [`P2|${sun}`]: 40, [`P3|${thu}`]: 40, [`P3|${sat}`]: 40 };
const wp = new WeekPlan({ Q: QS, book, schedule: sched, week: 3, today: "2026-11-03", now: new Date("2026-11-03T20:00:00Z"),
  rosterPositions: ["PG", "G", "BN"], roster: { players: ["P1", "P2", "P3"] }, matchup: { starters: ["P1", "P2"], players_points: {} },
  rosters: [], tips: {}, elig: () => true, locks: {} });
const plan = wp.build();
const evs = plan.slots.filter(s => s.slot === "PG" || s.slot === "G").map(s => s.ev);

// feasible maximum: each player's games go to one slot (or none); best over every split
const Qp = tierQ(QS.tiers, 40, QS.quantiles), W = n => n ? contStats(QS.quantiles, Array.from({ length: n }, () => ({ mu: 40, q: 0.92, Q: Qp }))).W[0] : 0;
const nGames = [1, 1, 2];                                    // P1, P2, P3 (no two share a day)
let feasible = 0;
for (let k = 0; k < 27; k++) {
  const to = [k % 3, Math.floor(k / 3) % 3, Math.floor(k / 9)], n = [0, 0];
  to.forEach((s, j) => { if (s < 2) n[s] += nGames[j]; });
  feasible = Math.max(feasible, W(n[0]) + W(n[1]));
}
const total = evs.reduce((a, b) => a + b, 0);
console.log("slot evs", evs, "total", total.toFixed(1), "| feasible max", feasible.toFixed(1), "| outlook mean", plan.outlook.mean.toFixed(1));
assert.ok(total <= feasible + 0.15, `slot evs ${total.toFixed(1)} exceed the feasible maximum ${feasible.toFixed(1)}`);
assert.ok(total >= feasible - 0.15, "the idle player's games should still be used by one slot");
console.log("ok: review 2 finding 1");
