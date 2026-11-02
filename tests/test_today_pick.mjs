// Today's starter per slot is chosen on its own (Nov 2): Wendell Carter Jr. (40 proj today) sat while Day'Ron Sharpe
// (35) started at C, and Grayson Allen (32) sat while Mikal Bridges (29) started at PF with Alex Sarr at F, because
// today's lineup just followed each slot's week-long player.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08"];
const games = { WCJ: [0, 3, 5], SHA: [0, 2, 5, 6], BRI: [0, 2, 5], SAR: [0, 2, 4, 5], ALL: [0, 2, 4] };
const teams = { WCJ: "ORL", SHA: "BKN", BRI: "NYK", SAR: "WAS", ALL: "PHX" };
const sched = [];
for (const [p, ix] of Object.entries(games)) for (const i of ix) sched.push({ week: 3, date: days[i], home: { team: teams[p] }, away: { team: "X" + p }, status: "pre_game" });
const proj = { WCJ: [40.3, 35, 35.9], SHA: [34.8, 35.3, 38.4, 39.6], BRI: [28.7, 30.2, 28.8], SAR: [33.8, 34.5, 35.5, 34], ALL: [31.8, 33.1, 30.7] };
const book = new Book({ scoring: {}, weights: { rotowire: 1, model: 0, ctx: 0 }, gamelog: {},
  players: { WCJ: ["Carter", "ORL", ["C"], null], SHA: ["Sharpe", "BKN", ["C"], null], BRI: ["Bridges", "NYK", ["PF", "SF", "SG"], null],
             SAR: ["Sarr", "WAS", ["C", "PF"], null], ALL: ["Allen", "PHX", ["SF", "SG"], null] },
  priors: { WCJ: 37, SHA: 36, BRI: 29, SAR: 34, ALL: 32 } });
book.proj = {}; for (const [p, ix] of Object.entries(games)) ix.forEach((i, k) => { book.proj[`${p}|${days[i]}`] = proj[p][k]; });
const tips = {}; for (const [p, ix] of Object.entries(games)) for (const i of ix) tips[`${days[i]}|${teams[p]}`] = `${days[i]}T23:30:00Z`;
const wp = new WeekPlan({ Q: QS, book, schedule: sched, week: 3, today: days[0], now: new Date("2026-11-02T15:00:00Z"),
  rosterPositions: ["PF", "F", "C", "BN", "BN"], roster: { players: Object.keys(games) }, matchup: { starters: ["BRI", "SAR", "SHA"], players_points: {} },
  rosters: [], tips, elig: () => true, locks: {} });
const plan = wp.build();
const today = Object.fromEntries(plan.slots.map(s => [s.slot, s.today?.name]));
console.log("today:", today);
assert.equal(today.C, "Carter", "the better C today starts, Sharpe's weekend games stay the fallback");
assert.ok(today.PF === "Sarr" && today.F === "Allen", "Sarr to PF, Allen at F (Bridges sits)");

// Nov 2 (2): interchangeable players trade slots so the best ones start today. C, C, UTIL, UTIL with Gobert, Sharpe,
// Okongwu (all C) and Derrick White (guard) + Carter (C) on the bench: start Gobert, Carter, Okongwu, White; Sharpe sits.
{
  const d2 = days, g2 = { GOB: [0, 2, 4, 6], SHA: [0, 2, 5, 6], OKO: [0, 2, 4, 5], WHI: [0, 2, 4, 6], WCJ: [0, 3, 5] };
  const t2 = { GOB: "MIN", SHA: "BKN", OKO: "ATL", WHI: "BOS", WCJ: "ORL" };
  const p2 = { GOB: [37.5, 36.9, 37.2, 37.9], SHA: [34.8, 35.3, 38.4, 39.6], OKO: [39.1, 40, 39.1, 36.5], WHI: [37.5, 38.9, 37.1, 39], WCJ: [40.3, 35, 35.9] };
  const sc2 = []; for (const [p, ix] of Object.entries(g2)) for (const i of ix) sc2.push({ week: 3, date: d2[i], home: { team: t2[p] }, away: { team: "X" + p }, status: "pre_game" });
  const bk = new Book({ scoring: {}, weights: { rotowire: 1, model: 0, ctx: 0 }, gamelog: {},
    players: { GOB: ["Gobert", "MIN", ["C"], null], SHA: ["Sharpe", "BKN", ["C"], null], OKO: ["Okongwu", "ATL", ["C"], null],
               WHI: ["White", "BOS", ["PG", "SG"], null], WCJ: ["Carter", "ORL", ["C"], null] },
    priors: { GOB: 37, SHA: 36, OKO: 39, WHI: 38, WCJ: 37 } });
  bk.proj = {}; for (const [p, ix] of Object.entries(g2)) ix.forEach((i, k) => { bk.proj[`${p}|${d2[i]}`] = p2[p][k]; });
  const tp = {}; for (const [p, ix] of Object.entries(g2)) for (const i of ix) tp[`${d2[i]}|${t2[p]}`] = `${d2[i]}T23:30:00Z`;
  const w2 = new WeekPlan({ Q: QS, book: bk, schedule: sc2, week: 3, today: d2[0], now: new Date("2026-11-02T15:00:00Z"),
    rosterPositions: ["C", "C", "UTIL", "UTIL", "BN"], roster: { players: Object.keys(g2) }, matchup: { starters: ["GOB", "SHA", "OKO", "WHI"], players_points: {} },
    rosters: [], tips: tp, elig: () => true, locks: {} });
  const started = w2.build().slots.map(s => s.today?.name).filter(Boolean).sort();
  console.log("today (C, C, UTIL, UTIL):", started);
  assert.deepEqual(started, ["Carter", "Gobert", "Okongwu", "White"]);
}
console.log("ok: today's pick");
