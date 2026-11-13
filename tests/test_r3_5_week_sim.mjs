// Review 3: the week simulator (tools/week_sim.mjs) plays whole weeks with the real engine, so its harness must be right.
//  1) one slot, one player: following the engine's calls averages his continuation value (contStats)
//  2) full roster: nothing beats perfect hindsight, and the engine's Monday forecast matches what it then scores
import assert from "node:assert/strict";
import { runEngine, runHold, runDefer, runCeiling, makeWeek, rng32, loadQ, defaultLeague } from "../tools/week_sim.mjs";
import { contStats, tierQ } from "../site/engine.js";

const QS = loadQ();
for (const [mu, n] of [[40, 3], [70, 2]]) {
  const rnd = rng32(7), roster = [{ pid: "A", name: "A", pos: ["C"], mu }], N = 1500; let s = 0, s2 = 0;
  for (let k = 0; k < N; k++) { const e = runEngine(makeWeek(rnd, roster, QS, n), QS, ["C"]).total; s += e; s2 += e * e; }
  const w = contStats(QS.quantiles, Array(n).fill({ mu, q: 1, Q: tierQ(QS.tiers, mu, QS.quantiles) })).W[0], m = s / N, se = Math.sqrt((s2 / N - m * m) / N);
  console.log(`one player, ${n} games at ${mu}: contStats ${w.toFixed(2)}, engine followed ${m.toFixed(2)} (se ${se.toFixed(2)})`);
  assert.ok(Math.abs(m - w) < 4 * se, `engine ${m} vs contStats ${w}`);
}
const L = defaultLeague(), rnd = rng32(3); let e = 0, f = 0; const N = 25;
for (let k = 0; k < N; k++) {
  const wk = makeWeek(rnd, L.roster, QS), r = runEngine(wk, QS, L.slots), top = runCeiling(wk, L.slots);
  for (const v of [r.total, runHold(wk, QS, L.slots), runDefer(wk, QS, L.slots), runEngine(wk, QS, L.slots, { rule: "expire" }).total])
    assert.ok(v <= top + 1e-6, `a policy scored ${v}, above perfect hindsight ${top}`);
  e += r.total / N; f += r.forecast / N;
}
console.log(`full roster, ${N} weeks: engine ${e.toFixed(1)}, its Monday forecast ${f.toFixed(1)}`);
assert.ok(Math.abs(e - f) / f < 0.04, "the engine's forecast and its realized score agree within 4%");
console.log("ok: review 3 (week simulator)");
