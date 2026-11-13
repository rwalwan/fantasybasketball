// Week simulator (review 3): how many points does the engine's slot plan leave on the table?
//
// Simulates whole Lock-In weeks and plays each one several ways on the SAME game outcomes:
//   engine   the real engine (site/engine.js WeekPlan.build), followed to the letter: its lineup every morning,
//            its lock calls every morning and after every night's games
//   hold     a looser policy that uses "a passed score stays with the player": nobody is locked until the week
//            ends, every player runs his own stopping rule (start his next game only while his score in hand is
//            below what his remaining games are worth), and the ten best scores that fit the slots count.
//            Only possible if a score also survives a game the player plays FROM THE BENCH (rule "keep").
//   defer    a looser policy under the stricter rule (a score in hand dies at the player's next team game, started
//            or not: rule "expire"): any player can fill any open slot each day, and a lock is decided at the
//            player's next tip instead of right after his game
//   ceiling  perfect hindsight: every player's best game of the week, best ten that fit. No policy can reach it.
//
// World: game = projection x a draw from the player's volatility tier (app/data/game_ratio_quantiles.json), every
// player plays every scheduled game, no back-to-backs, one tip time per day (so no same-day relief). Those are
// simplifications that apply to every policy alike; the point is the difference between policies.
//
// Usage: node tools/week_sim.mjs [weeks=300] [seed=1]
import fs from "node:fs";
import { Book, WeekPlan, contStats, tierQ, maxAssign, fits, ELIGIBLE } from "../site/engine.js";

export const DAYS = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"];
const next = d => { const x = new Date(d + "T12:00:00Z"); x.setUTCDate(x.getUTCDate() + 1); return x.toISOString().slice(0, 10); };
export const rng32 = seed => { let s = seed >>> 0; return () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; };
// every set of 2-4 game days with no two on consecutive days
const PATTERNS = { 2: [], 3: [], 4: [] };
for (let m = 0; m < 128; m++) {
  const ds = [...Array(7).keys()].filter(i => m >> i & 1);
  if (PATTERNS[ds.length] && ds.every((d, i) => !i || d - ds[i - 1] > 1)) PATTERNS[ds.length].push(ds);
}
// everyone healthy: the play-rate curve is 1 at every horizon, for the engine and for the world
const AVAIL = { model: { by_k: [0.5, 0.3, 0.25, 0.25, 0.23, 0.18, 0.16, 0.22], k9_12: 0.12, k13_20: 0.12, healthy: 1,
  designation: { Probable: 0.866, Questionable: 0.483, Doubtful: 0.042, Out: 0 }, healthy_curve: { ahead: [1, 30], q: [1, 1] } }, players: {} };

export function loadQ() { return JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url))); }
// the roster and slots of the published plan (review/data/plan_debug.json): 15 players, 10 starting slots
export function defaultLeague() {
  const p = JSON.parse(fs.readFileSync(new URL("../review/data/plan_debug.json", import.meta.url)));
  return { slots: p.slots.map(s => s.slot),
           roster: p.grid.map((g, i) => ({ pid: "P" + i, name: g.name, pos: g.pos.split("/"), mu: p.values[g.name] })).filter(x => x.mu > 0) };
}
export function makeWeek(rnd, roster, QS, nGames = null) {
  return roster.map((r, i) => {
    const n = nGames ?? (rnd() < 0.05 ? 2 : rnd() < 0.53 ? 3 : 4), pat = PATTERNS[n][Math.floor(rnd() * PATTERNS[n].length)];
    const Q = tierQ(QS.tiers, r.mu, QS.quantiles);
    return { ...r, team: "T" + i, Q, games: pat.map(d => ({ d, x: Math.round(r.mu * Q[Math.floor(rnd() * Q.length)] * 10) / 10 })) };
  });
}
const W = (QS, p, fromDay) => { const g = p.games.filter(x => x.d >= fromDay).map(() => ({ mu: p.mu, q: 1, Q: p.Q })); return g.length ? contStats(QS.quantiles, g).W : [0]; };
const emax = (p, T) => p.Q.reduce((a, r) => a + Math.max(p.mu * r, T), 0) / p.Q.length;
// best total of `scores` ({pid: score}) over the open slots, each player once
function bestFit(players, slots, scores) {
  const ps = players.filter(p => scores[p.pid] > 0);
  if (!ps.length || !slots.length) return 0;
  const m = slots.map(s => ps.map(p => (fits(s, p.pos) ? scores[p.pid] : null)));
  let t = 0; maxAssign(m).forEach((c, r) => { if (c >= 0 && m[r][c] != null) t += m[r][c]; });
  return t;
}

// ---------------- the engine, followed to the letter ----------------
export function runEngine(week, QS, slots, { rule = "keep", opts = {} } = {}) {
  const byId = Object.fromEntries(week.map(p => [p.pid, p]));
  // opening lineup: the best projections that fit (the engine re-sets it every morning anyway)
  const m0 = slots.map(s => week.map(p => (fits(s, p.pos) ? p.mu : null)));
  let starters = maxAssign(m0).map(c => (c >= 0 ? week[c].pid : "0"));
  const locks = {}, lockedPts = {}, started = {}, hand = {}, gamelog = {};
  let forecast = null;
  const alive = (p, d) => hand[p] && (rule === "keep" || !byId[p].games.some(g => g.d > hand[p].d && g.d <= d));
  const build = (d, evening) => {
    const sched = [];
    for (const p of week) for (const g of p.games) sched.push({ week: 4, date: DAYS[g.d], home: { team: p.team }, away: { team: "X" + p.team }, status: g.d < d || (g.d === d && evening) ? "complete" : "pre_game" });
    const tips = {}; for (const p of week) for (const g of p.games) tips[`${DAYS[g.d]}|${p.team}`] = `${DAYS[g.d]}T23:30:00Z`;
    const book = new Book({ scoring: {}, weights: { rotowire: 1, model: 0, ctx: 0 }, avail: AVAIL, gamelog,
      players: Object.fromEntries(week.map(p => [p.pid, [p.name, p.team, p.pos, null]])), priors: Object.fromEntries(week.map(p => [p.pid, p.mu])) });
    for (const p of week) for (const g of p.games) book.proj[`${p.pid}|${DAYS[g.d]}`] = p.mu;
    const pts = starters.map((p, i) => (lockedPts[i] != null ? lockedPts[i] * 10 : p !== "0" && alive(p, evening ? d : d - 1) ? hand[p].x * 10 : 0));
    return new WeekPlan({ Q: QS, book, schedule: sched, week: 4, today: DAYS[d], now: new Date(evening ? `${next(DAYS[d])}T06:00:00Z` : `${DAYS[d]}T15:00:00Z`),
      rosterPositions: [...slots, "BN"], roster: { players: week.map(p => p.pid) }, rosters: [], tips, locks,
      matchup: { starters, starters_points: pts, players_points: Object.fromEntries(starters.map((p, i) => [p, pts[i]])) },
      elig: (p, date) => started[`${p}|${date}`] ?? null }).build(opts);
  };
  const applyLocks = plan => plan.slots.forEach((s, i) => {
    if ((s.action === "lock" || s.action === "confirm") && lockedPts[i] == null && s.score != null) { locks[s.pid] = true; locks[`${s.pid}|${s.gameDate}`] = true; lockedPts[i] = s.score; }
  });
  for (let d = 0; d < 7; d++) {
    const plan = build(d, false);
    if (d === 0) forecast = plan.expectedTotal;
    applyLocks(plan);
    const want = plan.slots.map((s, i) => (lockedPts[i] == null && s.today ? s.today.pid : null)), moved = new Set(want.filter(Boolean));
    starters = starters.map((p, i) => (want[i] ? want[i] : lockedPts[i] == null && moved.has(p) ? "0" : p));
    for (const p of week) for (const g of p.games) if (g.d === d) {
      (gamelog[p.pid] ||= []).push([DAYS[d], g.x, 30, `${p.pid}-${d}`]);
      const i = starters.indexOf(p.pid), on = i >= 0;
      started[`${p.pid}|${DAYS[d]}`] = on;
      if (on && lockedPts[i] == null) hand[p.pid] = { x: g.x, d };
    }
    applyLocks(build(d, true));
  }
  let total = 0;
  starters.forEach((p, i) => { total += lockedPts[i] != null ? lockedPts[i] : p !== "0" && alive(p, 6) ? hand[p].x : 0; });
  return { total, forecast };
}

// ---------------- hold: nobody locks, every player runs his own stopping rule ----------------
export function runHold(week, QS, slots) {
  const hand = {};
  for (let d = 0; d < 7; d++) {
    const cands = week.filter(p => p.games.some(g => g.d === d)).map(p => {
      const w = W(QS, p, d), h = hand[p.pid] ?? 0;
      return { p, gain: w[0] - Math.max(h, w[1] ?? 0) };          // what today's game is worth to him
    }).filter(c => c.gain > 0);
    if (!cands.length) continue;
    const m = slots.map(s => cands.map(c => (fits(s, c.p.pos) ? c.gain : null)));
    maxAssign(m).forEach((c, r) => { if (c >= 0 && m[r][c] != null) hand[cands[c].p.pid] = cands[c].p.games.find(g => g.d === d).x; });
  }
  return bestFit(week, slots, hand);
}

// ---------------- defer: free daily assignment, a lock is decided at the player's next tip ----------------
export function runDefer(week, QS, slots, scale = 1) {
  const hand = {}, lockedP = new Set(); let open = slots.map((s, i) => ({ s, i })), total = 0;
  const flex = s => ELIGIBLE[s].length;
  for (let d = 0; d < 7; d++) {
    const free = week.filter(p => !lockedP.has(p.pid));
    // what one more open slot is worth for the rest of the week: the continuation of the n-th best free player
    const ws = free.map(p => W(QS, p, d)[0]).sort((a, b) => b - a), S = ws[open.length - 1] ?? 0;
    // scores in hand that die at tonight's tip: lock them now if they beat what the slot and the player are worth
    const dying = free.filter(p => hand[p.pid] != null && p.games.some(g => g.d === d)).sort((a, b) => hand[b.pid] - hand[a.pid]);
    for (const p of dying) {
      const thr = scale * Math.max(W(QS, p, d)[0], S);
      const slot = open.filter(o => fits(o.s, p.pos)).sort((a, b) => flex(a.s) - flex(b.s))[0];
      if (slot && hand[p.pid] >= thr) { total += hand[p.pid]; lockedP.add(p.pid); open = open.filter(o => o !== slot); }
      delete hand[p.pid];
    }
    const cands = week.filter(p => !lockedP.has(p.pid) && p.games.some(g => g.d === d));
    if (!cands.length || !open.length) continue;
    const m = open.map(o => cands.map(p => { if (!fits(o.s, p.pos)) return null; const T = Math.max(W(QS, p, d)[1] ?? 0, S); return emax(p, T) - T + 1e-3 * p.mu; }));
    maxAssign(m).forEach((c, r) => { if (c >= 0 && m[r][c] != null) hand[cands[c].pid] = cands[c].games.find(g => g.d === d).x; });
  }
  return total + bestFit(week.filter(p => !lockedP.has(p.pid)), open.map(o => o.s), hand);
}

export function runCeiling(week, slots) {
  return bestFit(week, slots, Object.fromEntries(week.map(p => [p.pid, Math.max(...p.games.map(g => g.x))])));
}

const stat = xs => { const n = xs.length, m = xs.reduce((a, b) => a + b, 0) / n, sd = Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (n - 1)); return { mean: m, se: sd / Math.sqrt(n), n }; };
export function simulate({ weeks = 300, seed = 1, league = defaultLeague(), QS = loadQ(), engineOpts = {} } = {}) {
  const rnd = rng32(seed), rows = [];
  for (let k = 0; k < weeks; k++) {
    const wk = makeWeek(rnd, league.roster, QS);
    const e = runEngine(wk, QS, league.slots, { rule: "keep", opts: engineOpts }), eStrict = runEngine(wk, QS, league.slots, { rule: "expire", opts: engineOpts });
    rows.push({ engine: e.total, engineStrict: eStrict.total, forecast: e.forecast, hold: runHold(wk, QS, league.slots), defer: runDefer(wk, QS, league.slots),
                ceiling: runCeiling(wk, league.slots), proj: bestFit(wk, league.slots, Object.fromEntries(wk.map(p => [p.pid, p.mu]))) });
  }
  const col = k => stat(rows.map(r => r[k])), diff = (a, b) => stat(rows.map(r => r[a] - r[b]));
  return { weeks, rows, engine: col("engine"), engineStrict: col("engineStrict"), forecast: col("forecast"), hold: col("hold"), defer: col("defer"), ceiling: col("ceiling"), proj: col("proj"),
           holdMinusEngine: diff("hold", "engine"), deferMinusEngine: diff("defer", "engineStrict"), ceilingMinusEngine: diff("ceiling", "engine"), engineMinusForecast: diff("engine", "forecast") };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const weeks = Number(process.argv[2] || 300), seed = Number(process.argv[3] || 1), t0 = Date.now();
  const r = simulate({ weeks, seed }), f = s => `${s.mean.toFixed(1)} (se ${s.se.toFixed(1)})`, ci = s => `${s.mean >= 0 ? "+" : ""}${s.mean.toFixed(1)} [${(s.mean - 1.96 * s.se).toFixed(1)}, ${(s.mean + 1.96 * s.se).toFixed(1)}]`;
  console.log(`${weeks} simulated weeks, seed ${seed}, ${((Date.now() - t0) / 1000).toFixed(0)} s. Points per week, ten slots:`);
  console.log(`  best ten projections, one game each     ${f(r.proj)}`);
  console.log(`  engine, followed to the letter          ${f(r.engine)}   its own Monday forecast ${f(r.forecast)}, realized minus forecast ${ci(r.engineMinusForecast)}`);
  console.log(`  defer (score dies at next team game)    ${f(r.defer)}   vs engine under that rule ${ci(r.deferMinusEngine)}`);
  console.log(`  hold (score survives bench games)       ${f(r.hold)}   vs engine ${ci(r.holdMinusEngine)}`);
  console.log(`  ceiling (perfect hindsight)             ${f(r.ceiling)}   vs engine ${ci(r.ceilingMinusEngine)}`);
}
