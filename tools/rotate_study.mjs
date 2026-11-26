// Rotation study (Nov 26): what is seating a lockable score in the tightest slot it fits worth?
// A lock can't move, but before locking, a finished game moves with its player to any starting slot he fits. Plays
// the same simulated weeks (tools/week_sim.mjs world) with the engine as-is and with opts.rotate, and reports the
// paired difference in points per week, plus how often a rotation was suggested.
// Nov 26 result (300 weeks each, paired): +1.57/week [0.43, 2.72] (seed 7), +1.75 [0.52, 2.97] (seed 11) on the
// review roster, +1.43 [0.28, 2.57] (seed 5) on the Nov 26 roster; a swap was suggested in ~2 of 3 weeks.
// Usage: node tools/rotate_study.mjs [weeks=200] [seed=7] [plan_debug.json for the roster]
import fs from "node:fs";
import { runEngine, makeWeek, loadQ, defaultLeague, rng32 } from "./week_sim.mjs";

const weeks = Number(process.argv[2] || 200), seed = Number(process.argv[3] || 7);
const league = process.argv[4] ? (() => {
  const p = JSON.parse(fs.readFileSync(process.argv[4]));
  return { slots: p.slots.map(s => s.slot), roster: p.grid.map((g, i) => ({ pid: "P" + i, name: g.name, pos: g.pos.split("/"), mu: p.values?.[g.name] })).filter(x => x.mu > 0) };
})() : defaultLeague();
const QS = loadQ(), rnd = rng32(seed), d = [], t0 = Date.now();
let withRot = 0, rots = 0;
for (let k = 0; k < weeks; k++) {
  const wk = makeWeek(rnd, league.roster, QS);
  const a = runEngine(wk, QS, league.slots, { opts: {} }), b = runEngine(wk, QS, league.slots, { opts: { rotate: true } });
  d.push(b.total - a.total); rots += b.rotations; if (b.rotations) withRot++;
}
const m = d.reduce((x, y) => x + y, 0) / d.length, sd = Math.sqrt(d.reduce((x, y) => x + (y - m) ** 2, 0) / (d.length - 1)), se = sd / Math.sqrt(d.length);
const nz = d.filter(x => Math.abs(x) > 1e-9);
console.log(JSON.stringify({ weeks, seed, slots: league.slots, roster: league.roster.length, secs: Math.round((Date.now() - t0) / 1000),
  gain_per_week: +m.toFixed(2), ci95: [+(m - 1.96 * se).toFixed(2), +(m + 1.96 * se).toFixed(2)],
  weeks_with_rotation: withRot, rotations: rots, weeks_changed: nz.length, better: d.filter(x => x > 1e-9).length, worse: d.filter(x => x < -1e-9).length,
  worst: +Math.min(...d).toFixed(1), best: +Math.max(...d).toFixed(1) }, null, 1));
