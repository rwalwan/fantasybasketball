// Today's-starter study (Nov 28): should near-ties go to the game with more upside instead of whoever is already in
// the slot? Fri Nov 27: Queta (34.9 expected) lost the UTIL start to Derrick White (34.4 + 0.5 for already sitting
// there), then scored 70.5. In Lock-In a start costs nothing, but a slot keeps only one game, so a game's value is
// its chance to beat the slot's keep-line (option value), not only its average.
// Plays the same simulated weeks (tools/week_sim.mjs world) under several start rules and reports the paired
// difference in points per week vs the current rule (keepBonus 0.5, upsideW 0.001), 95% interval.
// Usage: node tools/today_study.mjs [weeks=200] [seed=7] [plan_debug.json for the roster]
import fs from "node:fs";
import { runEngine, makeWeek, loadQ, defaultLeague, rng32 } from "./week_sim.mjs";

const weeks = Number(process.argv[2] || 200), seed = Number(process.argv[3] || 7);
const league = process.argv[4] ? (() => {
  const p = JSON.parse(fs.readFileSync(process.argv[4]));
  return { slots: p.slots.map(s => s.slot), roster: p.grid.map((g, i) => ({ pid: "P" + i, name: g.name, pos: g.pos.split("/"), mu: p.values?.[g.name] })).filter(x => x.mu > 0) };
})() : defaultLeague();
const RULES = { current: { keepBonus: 0.5, upsideW: 1e-3 }, no_keep: { keepBonus: 0, upsideW: 1e-3 },
  keep_up_0_25: { keepBonus: 0.1, upsideW: 0.25 }, keep_up_0_5: { keepBonus: 0.1, upsideW: 0.5 }, up_1: { keepBonus: 0.1, upsideW: 1 } };
const QS = loadQ(), rnd = rng32(seed), d = Object.fromEntries(Object.keys(RULES).map(k => [k, []])), t0 = Date.now();
for (let k = 0; k < weeks; k++) {
  const wk = makeWeek(rnd, league.roster, QS);
  const tot = Object.fromEntries(Object.entries(RULES).map(([n, o]) => [n, runEngine(wk, QS, league.slots, { opts: { rotate: true, ...o } }).total]));
  for (const n of Object.keys(RULES)) d[n].push(tot[n] - tot.current);
}
const out = { weeks, seed, roster: league.roster.length, secs: Math.round((Date.now() - t0) / 1000), vs_current: {} };
for (const [n, xs] of Object.entries(d)) {
  if (n === "current") continue;
  const m = xs.reduce((a, b) => a + b, 0) / xs.length, sd = Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1)), se = sd / Math.sqrt(xs.length);
  out.vs_current[n] = { rule: RULES[n], gain_per_week: +m.toFixed(2), ci95: [+(m - 1.96 * se).toFixed(2), +(m + 1.96 * se).toFixed(2)], weeks_changed: xs.filter(x => Math.abs(x) > 1e-9).length };
}
console.log(JSON.stringify(out, null, 1));
