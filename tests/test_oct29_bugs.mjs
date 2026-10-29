// Oct 29: the win chance fell from 99% to 17%; neither number was right.
//  1) a manually locked player's slot took his LATEST game (Gobert: locked 55 -> Wednesday's 12.5)
//  2) a live slot was worth its final alone, ignoring the option to pass a weak final for his remaining games
//  3) waiver moves at +1/week (inside projection noise) were suggested
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, selectAdds } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const [mon, wed, fri] = ["2026-11-02", "2026-11-04", "2026-11-06"];
const g = (date, st) => ({ week: 3, date, home: { team: "AAA" }, away: { team: "XXX" }, status: st });
const q = { [fri]: 0.94 };
const mk = (sched, gamelog, pts, locks, now, tips = {}) => new WeekPlan({ Q: QS, schedule: sched, week: 3, today: wed, now: new Date(now),
  book: new Book({ scoring: {}, players: { G: ["G", "AAA", ["C"], null] }, priors: { G: 40 }, gamelog, weights: { rotowire: 1, model: 0, ctx: 0 },
    avail: { model: null, players: { G: { status: null, q } } } }),
  rosterPositions: ["C", "BN"], roster: { players: ["G"] }, matchup: { starters: ["G"], players_points: { G: pts } },
  rosters: [], tips, elig: () => true, locks });

// 1) locked Monday's 55, then scored 12.5 on Wednesday: the slot is 55 (Sleeper shows 550)
const p1 = mk([g(mon, "complete"), g(wed, "complete"), g(fri, "pre_game")], { G: [[mon, 55, 30, "a"], [wed, 12.5, 30, "b"]] }, 550, { G: true }, "2026-11-05T05:00:00Z").build();
const s1 = p1.slots.find(x => x.slot === "C");
console.log("1) locked slot:", s1.score, "| outlook", p1.outlook.mean);
assert.equal(s1.score, 55); assert.equal(p1.outlook.mean, 55);
// a momentary 0 from Sleeper (recomputing) doesn't wipe the lock
const z = mk([g(mon, "complete"), g(wed, "complete"), g(fri, "pre_game")], { G: [[mon, 55, 30, "a"]] }, 0, { G: true }, "2026-11-05T05:00:00Z").build();
assert.equal(z.slots.find(x => x.slot === "C").score, 55);

// 2) live with 4 points, ~75% through, one more game Friday: the slot is worth about his Friday value, not ~11
const p2 = mk([g(wed, "in_progress"), g(fri, "pre_game")], { G: [[wed, 4, 25, "b"]] }, 40, {}, "2026-11-05T01:50:00Z",
  { [`${wed}|AAA`]: "2026-11-05T00:00:00Z", [`${fri}|AAA`]: "2026-11-07T00:00:00Z" });
p2.b.proj = { [`G|${wed}`]: 40, [`G|${fri}`]: 40 };
const ev2 = p2.build().outlook.mean;
console.log("2) live slot (4 pts so far, Friday left):", ev2.toFixed(1));
assert.ok(ev2 > 30, `a bad live game can be passed for Friday: ${ev2}`);

// 3) +1/week with 1.8 of noise is not suggested; +4/week is; +2.5 this week (not costing later) is
const moves = [{ pid: "a", weekGain: 0, rosGain: 1, noise: 1.8 }, { pid: "b", weekGain: 0, rosGain: 4, noise: 1.8 }, { pid: "c", weekGain: 2.5, rosGain: 0.2, noise: 1.8 }];
assert.deepEqual(selectAdds(moves).map(m => m.pid), ["b", "c"]);
console.log("ok: oct 29 bugs");
