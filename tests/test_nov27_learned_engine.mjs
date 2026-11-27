// Nov 27: the nightly trainer (app/train_models.py) can now promote the season-start baseline (R, M, c), a win-chance
// temperature and the wins-per-point of weekly score. The job writes them to site/static/learned.json; the page and
// tools/moves.mjs pass them to the engine. This pins the engine side: nothing learned = exactly the factory numbers;
// learned numbers change the baseline blend, the win chance and the trade values the way they should.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, Valuer, tradeIdeas, BASELINE } from "../site/engine.js";

// --- baseline: 3 games at 20 FP in 20 min; last season 40 FP in 32 min over 60 games ---------------------------------
const gl = { P: [["2026-11-01", 20, 20, "x"], ["2026-11-03", 20, 20, "x"], ["2026-11-05", 20, 20, "x"]] };
const mk = (o = {}) => new Book({ scoring: {}, players: { P: ["P", "AAA", ["SF"], null] }, priors: { P: 40 }, gamelog: gl,
                                  priorMin: { P: [32, 60] }, ...o });
const f0 = mk().baseline("P"), fSame = mk({ baseline: { R: BASELINE.R, M: BASELINE.M, c: BASELINE.c } }).baseline("P");
assert.equal(f0, fSame, "learned numbers equal to the factory change nothing");
const trustLast = mk({ baseline: { R: 400, M: 8, c: 0 } }).baseline("P");
const trustNow = mk({ baseline: { R: 100, M: 1, c: 30 } }).baseline("P");
assert.ok(trustNow < f0 && f0 < trustLast && trustLast < 40, `${trustNow.toFixed(2)} < ${f0.toFixed(2)} < ${trustLast.toFixed(2)}`);
assert.deepEqual(mk({ baseline: { R: 400 } }).bl.part, BASELINE.part, "a partial learned set keeps the other factory numbers");
console.log(`ok: learned baseline blends last season ${trustNow.toFixed(1)} / ${f0.toFixed(1)} / ${trustLast.toFixed(1)} FP/G`);

// --- trades: win chance temperature and wins per point ---------------------------------------------------------------
const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const today = "2026-11-12", sched = [];
const add = (week, date, team, status = "pre_game") => sched.push({ week, date, home: { team }, away: { team: "ZZZ" }, status });
add(4, "2026-11-09", "AAA", "complete"); add(4, "2026-11-13", "BBB"); add(4, "2026-11-14", "BBB");
for (let w = 5; w <= 20; w++) for (const t of ["AAA", "BBB", "CCC"]) for (const k of [0, 2, 4])
  add(w, new Date(Date.UTC(2026, 10, 16 + (w - 5) * 7 + k)).toISOString().slice(0, 10), t);
const players = { X: ["X", "AAA", ["SF"], null], Y: ["Y", "BBB", ["SF"], null], M: ["M", "CCC", ["SF"], null], N: ["N", "CCC", ["SF"], null] };
const RP = ["SF", "UTIL", "BN"], tips = { "2026-11-13|BBB": "2026-11-14T00:00:00Z", "2026-11-14|BBB": "2026-11-15T00:00:00Z" };
const me = { roster_id: 1, owner_id: "me", players: ["X", "M"], reserve: [] }, them = { roster_id: 3, owner_id: "t", players: ["Y", "N"], reserve: [] };
function deal(winTemp, wps) {
  const book = new Book({ scoring: {}, players, priors: { X: 35, Y: 35, M: 30, N: 30 }, gamelog: { X: [["2026-11-09", 44, 34, "x"]] },
                          weights: { rotowire: 1, model: 0, ctx: 0 }, winTemp });
  const plan = (roster, starters, locks = {}) => new WeekPlan({ Q: QS, schedule: sched, week: 4, today, now: new Date("2026-11-12T20:00:00Z"), book,
    rosterPositions: RP, roster, matchup: { starters, players_points: {}, starters_points: [] }, rosters: [me, them], tips, elig: () => true, locks });
  const myWp = plan(me, ["X", "M"], { X: true, "X|2026-11-09": true }), thWp = plan(them, ["Y", "N"]);
  const valuer = new Valuer({ book, schedule: sched, Q: QS, rosterPositions: RP, week: 4, today, settings: {}, freeAgents: [] });
  const ctx = { S: 500, from: null, wps, weekOf: { 1: { wp: myWp, mean: 300, var: 900, opp: 2 }, 2: { wp: null, mean: 300, var: 900, opp: 1 },
                                                   3: { wp: thWp, mean: 200, var: 900, opp: 4 }, 4: { wp: null, mean: 400, var: 900, opp: 3 } } };
  return tradeIdeas(valuer, book, me, [them], 10, ctx).find(x => x.give.join() === "X" && x.get.join() === "Y");
}
const d0 = deal(undefined, undefined), dT = deal(1.5, undefined), dW = deal(undefined, 4.4);
assert.ok(d0 && dT && dW, "the X-for-Y deal is offered in each case");
assert.ok(dT.winsWeekMe > d0.winsWeekMe, `a tighter win chance (t 1.5) makes the close week's swing bigger: ${d0.winsWeekMe} -> ${dT.winsWeekMe}`);
assert.ok(Math.abs(dW.winsRosMe - 2 * d0.winsRosMe) < 1e-9, `double the wins per point, double the season value: ${d0.winsRosMe} -> ${dW.winsRosMe}`);
assert.equal(dW.winsWeekMe, d0.winsWeekMe, "wins per point doesn't touch this week's win chance");
assert.ok(Math.abs(d0.winsRosMe) > 1e-4, "the season value isn't zero, so the doubling means something: " + d0.winsRosMe);
console.log("ok: learned win temperature and wins per point reach the trade check", d0.winsRosMe, dW.winsRosMe);
