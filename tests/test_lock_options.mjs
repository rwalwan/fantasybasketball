// Lock style, lock certainty and what-ifs (Nov 9).
//  - lockBias moves the bar: -0.2 locks a score the engine would pass on; +0.2 passes one it would lock
//  - pWaitBeats: how often the slot's rest of the week (by the stopping rule) ends above the score in hand
//  - force {pid: "lock"|"pass"} re-plans with that call, so the lineup changes it implies show up
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, passOdds, tierQ } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
// passOdds: one 40-point game left vs a 40 in hand -> about half; vs 10 -> nearly always; no games -> 0
const Qp = tierQ(QS.tiers, 40, QS.quantiles), one = [{ mu: 40, q: 1, Q: Qp }];
const half = passOdds(QS.quantiles, one, 40).pBeat;
assert.ok(half > 0.35 && half < 0.6, half);
assert.ok(passOdds(QS.quantiles, one, 10).pBeat > 0.9 && passOdds(QS.quantiles, [], 40).pBeat === 0);
assert.equal(passOdds(QS.quantiles, one, 40, 3).pBeat, passOdds(QS.quantiles, one, 40, 3).pBeat, "seeded: stable between refreshes");

// a slot: A scored 38 on Monday (lockable), plays Wed and Fri (40 proj); bench B (C, 40 proj) plays Thu
const days = ["2026-11-09", "2026-11-11", "2026-11-12", "2026-11-13"];
const sched = [{ week: 4, date: days[0], home: { team: "AAA" }, away: { team: "X" }, status: "complete" },
  { week: 4, date: days[1], home: { team: "AAA" }, away: { team: "X" }, status: "pre_game" },
  { week: 4, date: days[3], home: { team: "AAA" }, away: { team: "X" }, status: "pre_game" },
  { week: 4, date: days[2], home: { team: "BBB" }, away: { team: "X" }, status: "pre_game" }];
const mk = () => {
  const book = new Book({ scoring: {}, weights: { rotowire: 1, model: 0, ctx: 0 }, players: { A: ["A", "AAA", ["C"], null], B: ["B", "BBB", ["C"], null] },
    priors: { A: 40, B: 40 }, gamelog: { A: [[days[0], 38, 30, "g"]] } });
  book.proj = { [`A|${days[1]}`]: 40, [`A|${days[3]}`]: 40, [`B|${days[2]}`]: 40 };
  return new WeekPlan({ Q: QS, book, schedule: sched, week: 4, today: "2026-11-10", now: new Date("2026-11-10T18:00:00Z"),
    rosterPositions: ["C", "BN"], roster: { players: ["A", "B"] }, matchup: { starters: ["A"], players_points: { A: 380 }, starters_points: [380] },
    rosters: [], tips: { [`${days[1]}|AAA`]: `${days[1]}T23:30:00Z`, [`${days[3]}|AAA`]: `${days[3]}T23:30:00Z`, [`${days[2]}|BBB`]: `${days[2]}T23:30:00Z` },
    elig: () => true, locks: {} });
};
const s0 = mk().build().slots[0];
console.log("engine:", s0.action, "score", s0.score, "bar", s0.bar, "| lock certainty", Math.round((1 - s0.pWaitBeats) * 100) + "%");
assert.ok(s0.pWaitBeats > 0.3 && s0.pWaitBeats < 0.95);
const lockMore = mk().build({ lockBias: -0.2 }).slots[0], waitMore = mk().build({ lockBias: 0.2 }).slots[0];
console.log("safer:", lockMore.action, lockMore.yourBar, "| gamble:", waitMore.action, waitMore.yourBar);
assert.ok(lockMore.yourBar < s0.bar && waitMore.yourBar > s0.bar);
if (s0.action === "pass") assert.equal(lockMore.action, "lock", "a safer style locks 38 against a ~40 bar");
// what-ifs
const forcedLock = mk().build({ force: { A: "lock" } }), forcedPass = mk().build({ force: { A: "pass" } });
assert.equal(forcedLock.slots[0].action, "lock"); assert.equal(forcedLock.slots[0].whatIf, "lock");
assert.equal(forcedPass.slots[0].action, "pass");
assert.ok(forcedPass.outlook.mean > forcedLock.outlook.mean - 40 && forcedLock.outlook.mean === 38, "locking makes the slot 38");
assert.ok(forcedPass.slots[0].later || forcedPass.slots[0].today, "passing shows who fills the slot next");
// consistency: a lock call (score above the bar) has certainty above 50%-ish, a pass call below
for (const pl of [mk().build({ force: {} })]) for (const sl of pl.slots) if (sl.pWaitBeats != null)
  assert.ok(sl.action === "lock" ? sl.pWaitBeats < 0.6 : sl.pWaitBeats > 0.4 || sl.score < sl.bar * 0.8, JSON.stringify(sl));
console.log("ok: lock options");

// bar calibration from the other-leagues study: used only when the gain's 95% interval excludes 0
{
  const { studyBarScale } = await import("../site/engine.js");
  assert.equal(studyBarScale({ tier_units: "we back FP/G", best_scale: { scale: 0.9, ci95_vs_current: [0.37, 4.09] } }), 0.9);
  assert.equal(studyBarScale({ tier_units: "we back FP/G", best_scale: { scale: 0.9, ci95_vs_current: [-0.5, 3] } }), 1);
  assert.equal(studyBarScale(null), 1);
  const raw = mk().build().slots[0].bar, cal = mk().build({ barScale: 0.9 }).slots[0].bar;
  assert.ok(Math.abs(cal - 0.9 * raw) < 0.15, `${cal} vs ${raw}`);
  for (const sc of [0.9, 1]) for (const sl of mk().build({ barScale: sc }).slots) if (sl.pWaitBeats != null)
    assert.ok(sl.action === "lock" ? sl.pWaitBeats <= 0.55 : sl.pWaitBeats >= 0.45 || sl.score < sl.bar * 0.85, `scale ${sc}: ${JSON.stringify(sl)}`);
  console.log("ok: study bar scale");
}
