// Review 3, finding 3: the pre-game keep-line and the post-game lock bar are the same quantity (what the slot is worth
// if you pass), but only the bar got the study's calibration factor. With x0.90: before A's game the plan said "if A
// scores under 46.9, swap B in"; A scored 43.5 and a minute later the same plan said "lock 43.5" (bar 42.4).
// Whatever factor the bars carry, the keep-line shown before the game must be the bar applied after it.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const d = ["2026-11-10", "2026-11-12", "2026-11-14", "2026-11-13"];
const G = (date, t, st = "pre_game") => ({ week: 4, date, home: { team: t }, away: { team: "X" + t }, status: st });
// C slot: A plays today 7pm ET, then Thu and Sat. Bench B plays today 10pm ET (same-day relief) and Fri.
const tips = { [`${d[0]}|AAA`]: "2026-11-11T00:00:00Z", [`${d[1]}|AAA`]: "2026-11-13T00:00:00Z", [`${d[2]}|AAA`]: "2026-11-15T00:00:00Z",
               [`${d[0]}|BBB`]: "2026-11-11T03:00:00Z", [`${d[3]}|BBB`]: "2026-11-14T00:00:00Z" };
const mk = (now, score) => {
  const sched = [G(d[0], "AAA", score == null ? "pre_game" : "complete"), G(d[1], "AAA"), G(d[2], "AAA"), G(d[0], "BBB"), G(d[3], "BBB")];
  const book = new Book({ scoring: {}, weights: { rotowire: 1, model: 0, ctx: 0 }, players: { A: ["A", "AAA", ["C"], null], B: ["B", "BBB", ["C"], null] },
    priors: { A: 40, B: 36 }, gamelog: score == null ? {} : { A: [[d[0], score, 34, "g1"]] } });
  book.proj = { [`A|${d[0]}`]: 40, [`A|${d[1]}`]: 40, [`A|${d[2]}`]: 40, [`B|${d[0]}`]: 36, [`B|${d[3]}`]: 36 };
  return new WeekPlan({ Q: QS, book, schedule: sched, week: 4, today: d[0], now: new Date(now), rosterPositions: ["C", "BN"], roster: { players: ["A", "B"] },
    matchup: { starters: ["A"], players_points: score == null ? {} : { A: score * 10 }, starters_points: [score == null ? 0 : score * 10] },
    rosters: [], tips, elig: () => true, locks: {} });
};
for (const barScale of [1, 0.9]) {
  const pre = mk("2026-11-10T18:00:00Z", null).build({ barScale }).slots[0];
  const keep = pre.today.keepBar;
  assert.ok(pre.today.relief, "B is the same-day relief");
  // a score just under the keep-line: the pre-game instruction is "swap B in", so the post-game call must not be "lock"
  const under = Math.floor((keep - 0.6) * 2) / 2, over = Math.ceil((keep + 0.6) * 2) / 2;
  const postU = mk("2026-11-11T02:40:00Z", under).build({ barScale }).slots[0], postO = mk("2026-11-11T02:40:00Z", over).build({ barScale }).slots[0];
  console.log(`barScale ${barScale}: keep-line ${keep} | A scores ${under} -> ${postU.action} (bar ${postU.bar}) | A scores ${over} -> ${postO.action} (bar ${postO.bar})`);
  assert.ok(Math.abs(keep - postU.bar) <= 1.5, `keep-line ${keep} and the bar after the game ${postU.bar} are the same quantity`);
  assert.equal(postU.action, "pass", `scored ${under}, under the keep-line ${keep}: the plan said to swap the relief in`);
  assert.equal(postO.action, "lock");
}
console.log("ok: review 3 finding 3 (keep-line = bar)");
