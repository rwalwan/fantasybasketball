// Finding 15 (review 2026-10-28), smaller defects - engine side.
//  a) relief swaps were offered at tip + 135 min while sequencing assumed 150-min games, so the keep line could be
//     judged before the first game ended.
//  b) tools/moves.mjs: `.slice(0, 8).map(...)` sat after a // comment, so adds weren't capped and expert consensus
//     never attached. Now a tested function, selectAdds().
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, GAME_MINUTES, selectAdds } from "../site/engine.js";
const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const d = "2026-11-02", tips = { [`${d}|AAA`]: "2026-11-02T23:00:00Z", [`${d}|BBB`]: "2026-11-03T03:00:00Z" };
const sched = [{ week: 3, date: d, home: { team: "AAA" }, away: { team: "XXX" }, status: "pre_game" },
               { week: 3, date: d, home: { team: "BBB" }, away: { team: "YYY" }, status: "pre_game" }];
const book = new Book({ scoring: {}, players: { A: ["A", "AAA", ["SF"], null], B: ["B", "BBB", ["SF"], null] }, priors: { A: 40, B: 40 }, gamelog: {} });
const wp = new WeekPlan({ Q: QS, book, schedule: sched, week: 3, today: d, now: new Date("2026-11-02T18:00:00Z"),
  rosterPositions: ["UTIL", "BN"], roster: { players: ["A", "B"] }, matchup: { starters: ["A"], players_points: {} }, rosters: [], tips, elig: () => true, locks: {} });
const r = wp.build().slots[0].today?.relief;
assert.ok(r, "B (4 h later) should be offered as relief");
assert.equal(GAME_MINUTES, 150);
assert.equal(Date.parse(r.swapAfter) - Date.parse(tips[`${d}|AAA`]), GAME_MINUTES * 60000, "swap only after the first game is over");
// adds: capped at 8, real edges only, consensus attached
const list = Array.from({ length: 12 }, (_, i) => ({ pid: `p${i}`, weekGain: i % 3 === 0 ? 0.5 : 3, rosGain: 0.2 }));
const out = selectAdds(list, { p1: { bull_share: 0.8, n: 3 } });
assert.equal(out.length, 8);
assert.ok(out.every(m => m.weekGain >= 2 || m.rosGain >= 1));
assert.deepEqual(out.find(m => m.pid === "p1").experts, { bull_share: 0.8, n: 3 });
console.log("ok: finding 15 (engine)");

//  c) RETURN_RAMP was defined but unused. Research (2021-24, n=278 returns from 5+ game absences): first game
//     back 0.86x normal FP, second 0.96x.
import { usesFaab, RETURN_RAMP } from "../site/engine.js";
{
  const days = ["2026-10-20", "2026-10-22", "2026-10-24", "2026-10-26", "2026-10-28", "2026-10-30", "2026-11-01", "2026-11-03", "2026-11-05", "2026-11-07"];
  const sch = days.map(x => ({ week: x < "2026-11-02" ? 2 : 3, date: x, home: { team: "AAA" }, away: { team: "ZZZ" }, status: x < "2026-11-02" ? "complete" : "pre_game" }));
  const mk = played => new WeekPlan({ Q: QS, book: new Book({ scoring: {}, players: { R: ["R", "AAA", ["SF"], null] }, priors: { R: 40 },
    gamelog: { R: played.map((x, i) => [x, 40, 30, "g" + i]) }, weights: { rotowire: 0, model: 1, ctx: 0 } }), schedule: sch, week: 3, today: "2026-11-02",
    now: new Date("2026-11-02T12:00:00Z"), rosterPositions: ["SF"], roster: { players: ["R"] }, matchup: { starters: ["R"], players_points: {} }, rosters: [], tips: {}, elig: () => true, locks: {} });
  const back = mk(["2026-10-20"]).upcoming("R"), healthy = mk(days.slice(0, 7)).upcoming("R");
  assert.deepEqual(RETURN_RAMP, [0.86, 0.96]);
  assert.equal(back[0].mu, Math.round(healthy[0].mu * 0.86 * 10) / 10, "first game back after 6 missed");
  assert.equal(back[1].mu, Math.round(healthy[1].mu * 0.96 * 10) / 10);
  assert.equal(back[2].mu, healthy[2].mu);
}
//  d) the league's waiver_type is 0; Sleeper's FAAB is 2 and it sends a default budget either way
assert.equal(usesFaab({ waiver_type: 0, waiver_budget: 100 }), false);
assert.equal(usesFaab({ waiver_type: 2, waiver_budget: 100 }), true);
// review 2: the code 2 isn't in Sleeper's docs, so real spending also marks a FAAB league
assert.equal(usesFaab({ waiver_type: 0, waiver_budget: 100 }, [{ settings: { waiver_budget_used: 0 } }]), false);
assert.equal(usesFaab({ waiver_type: 0, waiver_budget: 100 }, [{ settings: { waiver_budget_used: 7 } }]), true);
console.log("ok: finding 15 (ramp, FAAB)");
