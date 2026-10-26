// Lock Desk engine (browser + Node). Same math as app/*.py: Lock-In optimal stopping, play
// probabilities, slot assignment, waivers. Pure functions over plain data — no fetching here.

export const ELIGIBLE = {
  PG: ["PG"], SG: ["SG"], G: ["PG", "SG"], SF: ["SF"], PF: ["PF"], F: ["SF", "PF"],
  C: ["C"], UTIL: ["PG", "SG", "SF", "PF", "C"],
};
export const fits = (slot, pos) => (ELIGIBLE[slot] || []).some(p => (pos || []).includes(p));

// ---------- scoring (Sleeper stores NBA scoring x10; verified 170/170 vs players_points) ----------
const BASE = ["pts", "tpm", "reb", "ast", "stl", "blk", "tf", "ff"];
export function fantasyPoints(st, sc) {
  const v = k => Number(st[k] || 0);
  let t = BASE.reduce((a, k) => a + v(k) * (sc[k] || 0), 0) - v("to") * Math.abs(sc.to || 0);
  const tens = ["pts", "reb", "ast", "stl", "blk"].filter(k => v(k) >= 10).length;
  if (tens >= 2) t += sc.dd || 0;
  if (tens >= 3) t += sc.td || 0;
  if (v("pts") >= 40) t += sc.bonus_pt_40p || 0;
  if (v("pts") >= 50) t += sc.bonus_pt_50p || 0;
  if (v("reb") >= 20) t += sc.bonus_reb_20p || 0;
  if (v("ast") >= 15) t += sc.bonus_ast_15p || 0;
  return Math.round(t * 10) / 100;   // /10, 2 decimals
}

// ---------- lock-in math ----------
// Q = quantiles of (single-game FP / season average), top-150 players 2021-24 (research/lockin.py)
export function expectedMax(Q, mu, floor) {
  if (mu <= 0) return floor;
  let s = 0;
  for (const q of Q) s += Math.max(mu * q, floor);
  return s / Q.length;
}
// W[j] = value of arriving at game j unlocked; lock after game j iff score >= W[j+1].
// Each game may carry its own spread curve (g.Q: the player's volatility tier); Q is the fallback.
export function contValues(Q, games) { return contStats(Q, games).W; }
// Same recursion plus the second moment of the score you end up with, so the spread of a slot's outcome
// comes from the actual stopping rule rather than a flat guess:
//   M2[j] = q * (E[X^2; X >= W[j+1]] + P(X < W[j+1]) * M2[j+1]) + (1-q) * M2[j+1];  sd = sqrt(M2 - W^2)
export function contStats(Q, games) {
  const n = games.length, W = new Array(n + 1).fill(0), M2 = new Array(n + 1).fill(0);
  for (let j = n - 1; j >= 0; j--) {
    const g = games[j], qs = g.Q || Q, last = j === n - 1, floor = last ? -Infinity : W[j + 1];
    let e = 0, e2 = 0;
    for (const r of qs) { const x = g.mu * r; if (x >= floor) { e += x; e2 += x * x; } else { e += W[j + 1]; e2 += M2[j + 1]; } }
    e /= qs.length; e2 /= qs.length;
    W[j] = g.q * e + (1 - g.q) * W[j + 1];
    M2[j] = g.q * e2 + (1 - g.q) * M2[j + 1];
  }
  return { W, sd: W.map((w, j) => Math.sqrt(Math.max(0, M2[j] - w * w))) };
}
// volatility tier for a player whose typical game is `base` FP: bench guys swing far more than stars
export function tierQ(tiers, base, fallback) {
  if (!tiers?.length) return fallback;
  return (tiers.find(t => t.max == null || base <= t.max) || tiers.at(-1)).quantiles;
}
export const lockBar = (Q, after) => (after.length ? contValues(Q, after)[0] : 0);
export const range80 = (Q, mu) => [Math.round(mu * Q[10] * 10) / 10, Math.round(mu * Q[89] * 10) / 10];

// ---------- player book ----------
const STATUS_Q = { Probable: 0.9, "Day-To-Day": 0.75, GTD: 0.6, Questionable: 0.55, Doubtful: 0.2,
  Out: 0, IR: 0, Suspended: 0, NA: 0, DNR: 0, COV: 0 };
const OUT = new Set(["Out", "IR", "Suspended", "NA", "DNR", "COV"]);
const SHAKY = new Set(["Questionable", "Doubtful", "GTD", "Day-To-Day"]);
export const B2B_FACTOR = 0.86, PRIOR_GAMES = 8;

export class Book {
  constructor({ scoring, players, priors, gamelog, weights, ctx }) {
    this.sc = scoring;
    this.ctx = ctx || {};                                 // "pid|date" -> {f, parts} matchup context (app/memory.py)
    this.w = weights || { rotowire: 0.5, model: 0.5 };   // learned from graded accuracy (app/experts.py)
    this.meta = {};                    // pid -> {name, team, pos, status}
    for (const [pid, [name, team, pos, status]] of Object.entries(players || {}))
      this.meta[pid] = { name, team, pos, status };
    this.prior = priors || {};
    this.games = {};                   // pid -> [{date, fp, min, gid}]
    for (const [pid, gs] of Object.entries(gamelog || {}))
      this.games[pid] = gs.map(([date, fp, min, gid]) => ({ date, fp, min, gid }));
    this.proj = {};                    // `${pid}|${date}` -> fp
  }
  _meta(row) {                         // freshest metadata rides on live stat/projection rows
    const p = row.player || {};
    const m = this.meta[row.player_id] || (this.meta[row.player_id] = {});
    if (p.first_name || p.last_name) m.name = `${p.first_name || ""} ${p.last_name || ""}`.trim();
    if (p.team) m.team = p.team;
    if (p.fantasy_positions) m.pos = p.fantasy_positions;
    if ("injury_status" in p) m.status = p.injury_status;
  }
  addStats(rows) {
    for (const r of rows || []) {
      this._meta(r);
      const st = r.stats || {};
      const mins = Number(st.min) || Number(st.sp || 0) / 60;   // some feeds only report seconds played
      if (!r.date || !(mins > 0)) continue;
      const list = this.games[r.player_id] || (this.games[r.player_id] = []);
      const i = list.findIndex(g => g.gid === r.game_id);
      const g = { date: r.date, fp: fantasyPoints(st, this.sc), min: mins, gid: r.game_id };
      if (i >= 0) list[i] = g; else list.push(g);
    }
    for (const l of Object.values(this.games)) l.sort((a, b) => a.date.localeCompare(b.date));
  }
  addProjections(rows) {
    for (const r of rows || []) {
      this._meta(r);
      if (r.date && r.stats) this.proj[`${r.player_id}|${r.date}`] = fantasyPoints(r.stats, this.sc);
    }
  }
  name(p) { return this.meta[p]?.name || p; }
  team(p) { return this.meta[p]?.team; }
  pos(p) { return this.meta[p]?.pos || []; }
  status(p) { return this.meta[p]?.status || null; }
  // only FINAL games feed averages: a half-finished game would drag every projection down while it's live
  done(p) { const g = this.games[p] || []; return this.isFinal ? g.filter(x => this.isFinal(p, x.date)) : g; }
  avg(p) { const g = this.done(p); return g.length ? g.reduce((a, x) => a + x.fp, 0) / g.length : null; }
  baseline(p) {
    const g = this.done(p), cur = this.avg(p);
    let prior = this.prior[p];
    if (prior == null) {
      const f = Object.entries(this.proj).filter(([k]) => k.startsWith(p + "|")).map(([, v]) => v);
      prior = f.length ? f.reduce((a, b) => a + b, 0) / f.length : (cur ?? 0);
    }
    if (cur == null) return prior;
    return (g.length * cur + PRIOR_GAMES * prior) / (g.length + PRIOR_GAMES);
  }
  gameMu(p, date) {
    // sources blended by graded accuracy: plain model, model x matchup context, RotoWire
    const base = this.baseline(p), pr = this.proj[`${p}|${date}`], c = this.ctx?.[`${p}|${date}`];
    const srcs = [[this.w.model ?? 1 / 3, base]];
    if (c?.f) srcs.push([this.w.ctx ?? 1 / 3, base * c.f]);
    if (pr > 0) srcs.push([this.w.rotowire ?? 1 / 3, pr]);
    const tw = srcs.reduce((a, [w]) => a + w, 0);
    return Math.round((srcs.reduce((a, [w, v]) => a + w * v, 0) / tw) * 10) / 10;
  }
  playProb(p, daysAhead, b2b) {
    const st = this.status(p);
    let q = st == null || st === "" ? 0.92 : (STATUS_Q[st] ?? 0.85);
    if (OUT.has(st) && daysAhead >= 3) q = 0.25;
    else if (SHAKY.has(st) && daysAhead >= 2) q = Math.max(q, 0.75);
    if (b2b) q *= B2B_FACTOR;
    return Math.round(q * 100) / 100;
  }
}

// ---------- schedule ----------
export function weekDays(schedule, week) {
  const d = schedule.filter(g => g.week === week).map(g => g.date).sort();
  if (!d.length) return [];
  const s = new Date(d[0] + "T12:00:00Z"); s.setUTCDate(s.getUTCDate() - ((s.getUTCDay() + 6) % 7));
  return [...Array(7)].map((_, i) => { const x = new Date(s); x.setUTCDate(s.getUTCDate() + i); return x.toISOString().slice(0, 10); });
}
export function teamGames(schedule) {
  const out = {};
  for (const g of schedule) for (const [side, other] of [["home", "away"], ["away", "home"]]) {
    const t = g[side]?.team; if (!t) continue;
    (out[t] ||= {})[g.date] = { opp: g[other]?.team || "", home: side === "home", status: g.status };
  }
  return out;
}
const addDays = (d, n) => { const x = new Date(d + "T12:00:00Z"); x.setUTCDate(x.getUTCDate() + n); return x.toISOString().slice(0, 10); };
const dayDiff = (a, b) => Math.round((new Date(a + "T12:00:00Z") - new Date(b + "T12:00:00Z")) / 864e5);

const day3 = d => new Date(d + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" });

// Max-weight assignment of rows to columns (null = forbidden). Hungarian algorithm (O(n^3)) on
// cost = -value, with one zero-value dummy column per row so any row may stay empty.
export function maxAssign(value) {
  const n = value.length; if (!n) return [];
  const C = value[0].length, m = C + n, BIG = 1e7;
  const cost = (i, j) => (j < C ? (value[i][j] == null ? BIG : -value[i][j]) : 0);
  const u = new Float64Array(n + 1), v = new Float64Array(m + 1), p = new Int32Array(m + 1), way = new Int32Array(m + 1);
  for (let i = 1; i <= n; i++) {
    p[0] = i; let j0 = 0;
    const minv = new Float64Array(m + 1).fill(Infinity), used = new Uint8Array(m + 1);
    do {
      used[j0] = 1; const i0 = p[j0]; let delta = Infinity, j1 = 0;
      for (let j = 1; j <= m; j++) if (!used[j]) {
        const cur = cost(i0 - 1, j - 1) - u[i0] - v[j];
        if (cur < minv[j]) { minv[j] = cur; way[j] = j0; }
        if (minv[j] < delta) { delta = minv[j]; j1 = j; }
      }
      for (let j = 0; j <= m; j++) { if (used[j]) { u[p[j]] += delta; v[j] -= delta; } else minv[j] -= delta; }
      j0 = j1;
    } while (p[j0] !== 0);
    do { const j1 = way[j0]; p[j0] = p[j1]; j0 = j1; } while (j0);
  }
  const ans = new Array(n).fill(-1);
  for (let j = 1; j <= m; j++) if (p[j] && j - 1 < C && value[p[j] - 1][j - 1] != null) ans[p[j] - 1] = j - 1;
  return ans;
}

// ---------- the week plan ----------
export class WeekPlan {
  constructor({ Q, book, schedule, week, today, now, rosterPositions, roster, matchup, rosters, tips, elig, locks }) {
    Object.assign(this, { Q: Array.isArray(Q) ? Q : Q.quantiles, QT: Array.isArray(Q) ? null : Q.tiers,
                          b: book, week, today, now: now || new Date(), roster, matchup, tips: tips || {} });
    this.gstatus = {};
    for (const g of schedule) for (const side of ["home", "away"]) if (g[side]?.team) this.gstatus[`${g.date}|${g[side].team}`] = g.status;
    this.days = weekDays(schedule, week);
    this.tg = teamGames(schedule);
    this.slots = rosterPositions.filter(s => s !== "BN" && s !== "IR");
    this.rostered = new Set(rosters.flatMap(r => r.players || []));
    this.elig = elig || (() => null);
    this.locks = locks || {};
    if (!book.isFinal) book.isFinal = (p, d) => this.final(p, d);
  }
  teamDays(t) { return Object.keys(this.tg[t] || {}).filter(d => this.days.includes(d)).sort(); }
  // a game counts as played only once it's final (schedule says complete, or 4 h past tip if the schedule lags)
  final(p, d) {
    if (this.gstatus[`${d}|${this.b.team(p)}`] === "complete") return true;
    const t = this.tip(p, d);
    return t ? this.now - new Date(t) > 4 * 3600e3 : d < this.today;
  }
  played(p) { return (this.b.games[p] || []).filter(g => this.days.includes(g.date) && this.final(p, g.date)); }
  livePlayed(p) { return (this.b.games[p] || []).filter(g => this.days.includes(g.date) && !this.final(p, g.date)); }
  tip(p, d) { return this.tips[`${d}|${this.b.team(p)}`]; }
  qOf(p) { return tierQ(this.QT, this.b.baseline(p), this.Q); }
  tipped(p, d) { const t = this.tip(p, d); return t ? new Date(t) <= this.now : d < this.today; }
  upcoming(p) {
    const t = this.b.team(p), done = new Set(this.played(p).map(g => g.date)), all = Object.keys(this.tg[t] || {});
    return this.teamDays(t).filter(d => !done.has(d) && !this.tipped(p, d)).map(d => {
      const b2b = all.includes(addDays(d, -1));
      return { date: d, mu: this.b.gameMu(p, d), q: this.b.playProb(p, dayDiff(d, this.today), b2b), Q: this.qOf(p),
               opp: this.tg[t][d].opp, b2b, tip: this.tip(p, d) };
    });
  }
  lockState(p) {
    const pl = this.played(p);
    if (this.locks[p] === true) return { st: "locked", g: pl.at(-1) || null };
    const lv = this.livePlayed(p);
    if (lv.length) return { st: "live", g: lv.at(-1) };
    // tipped but no stat line yet (Sleeper's first box score row lags the tip by a few minutes): still live, 0 so far.
    // Without this, a game in its first minutes vanished and the slot looked like it had nothing left.
    const t = this.b.team(p), done = new Set((this.b.games[p] || []).map(g => g.date));
    const fresh = this.teamDays(t).find(d => this.tipped(p, d) && !this.final(p, d) && !done.has(d));
    if (fresh && !OUT.has(this.b.status(p)) && this.elig(p, fresh) !== false) return { st: "live", g: { date: fresh, fp: 0, min: 0, gid: null } };
    const raw = this.matchup.players_points?.[p];
    if (!pl.length || raw == null) return { st: "none", g: null };
    const pts = Math.round(raw) / 10;
    // Sleeper's points for a starter = his locked game, or else his latest COUNTABLE game. So an earlier game
    // matching means "locked" only if his latest game was countable (played from a starting slot).
    // locks[p] === false is the manager saying "not locked" (overrides the inference).
    const countable = pl.filter(g => this.elig(p, g.date) !== false), latest = countable.at(-1) || pl.at(-1);
    if (this.locks[p] !== false && countable.length && this.elig(p, pl.at(-1).date) !== false)
      for (const g of countable.slice(0, -1)) if (Math.abs(g.fp - pts) < 0.01 && Math.abs(latest.fp - pts) >= 0.01) return { st: "locked", g, inferred: true };
    const last = pl.at(-1), e = this.elig(p, last.date);
    if (e === false) return { st: "bench", g: last };
    return { st: e === true ? "open" : "confirm", g: last };
  }
  // opts.opp = the opponent's outlook ({mean, var}) -> matchup-aware lock calls
  build(opts = {}) {
    const Q = this.Q, starters = this.matchup.starters || [], r1 = v => Math.round(v * 10) / 10;
    const reserve = new Set(this.roster.reserve || []);
    const players = (this.roster.players || []).filter(p => !reserve.has(p));
    const ls = {}; for (const p of players) ls[p] = this.lockState(p);
    const locked = new Set(starters.filter(p => ls[p]?.st === "locked"));
    const liveNow = new Set(starters.filter(p => ls[p]?.st === "live"));   // game in progress: slot committed today
    const cont = {};
    for (const p of players) if (!locked.has(p)) {
      const u = this.upcoming(p), cs = contStats(Q, u);
      cont[p] = { W: u.length ? cs.W[0] : 0, sd: u.length ? cs.sd[0] : 0, u };
    }

    // ---- 1) rest-of-week assignment, solved jointly ---------------------------------------------
    // Every open slot gets one player for the rest of the week (or its own pending game, locked in place).
    // value(slot, p) = p's continuation value W_p; for the slot's own starter with a lockable game,
    // max(score, W_p). Max-weight assignment picks the best combination across ALL slots at once, and a
    // lock's bar is its true opportunity cost: (best total if this slot can't lock) - (best total of
    // everything else without this slot and player).
    const open = this.slots.map((s, i) => ({ s, i, p: starters[i] })).filter(x => !locked.has(x.p) && !liveNow.has(x.p));
    const pool = Object.keys(cont).filter(p => !liveNow.has(p));
    const lockable = {};
    for (const x of open) { const st = ls[x.p]?.st; if (st === "open" || st === "confirm") lockable[x.i] = ls[x.p].g; }
    const val = (x, p, allowLock = true) => {
      if (!fits(x.s, this.b.pos(p))) return null;
      const W = cont[p].W, stay = p === x.p ? 0.01 : 0;   // tie-break: don't shuffle players between equivalent slots
      return (allowLock && p === x.p && lockable[x.i] ? Math.max(lockable[x.i].fp, W) : W) + stay;
    };
    const solve = (rows, cols, noLock = null) => {
      if (!rows.length) return { total: 0, pick: [] };
      const m = rows.map(x => cols.map(p => val(x, p, x.i !== noLock)));
      const pick = maxAssign(m);
      let total = 0;
      pick.forEach((c, r) => { if (c >= 0 && c < cols.length && m[r][c] != null) total += m[r][c]; });
      return { total, pick: pick.map(c => (c >= 0 && c < cols.length ? cols[c] : null)) };
    };
    const main = solve(open, pool);
    const assignedTo = {}; open.forEach((x, r) => { assignedTo[x.i] = main.pick[r]; });
    const willLock = new Set(), bars = {}, altFor = {};
    for (const x of open) {
      const g = lockable[x.i]; if (!g) continue;
      const noLock = solve(open, pool, x.i);
      const rest = solve(open.filter(y => y.i !== x.i), pool.filter(p => p !== x.p));
      bars[x.i] = Math.max(0, noLock.total - rest.total);
      altFor[x.i] = noLock.pick[open.indexOf(x)];
      if (g.fp >= bars[x.i] && (ls[x.p].st === "open" || ls[x.p].st === "confirm")) willLock.add(x.p);
    }

    // ---- 1b) matchup outlook + matchup-aware lock calls ------------------------------------------
    // Each slot: expected points (ev) and spread (sd). Locked = known. Waiting/open = the spread of the score the
    // stopping rule actually ends on (contStats), from the player's own volatility tier. Live games: points so
    // far + the rest of his projection, with the single-game spread of his tier shrinking as the game runs.
    const qsd = qs => { const m = qs.reduce((a, b) => a + b, 0) / qs.length; return Math.sqrt(qs.reduce((a, b) => a + (b - m) ** 2, 0) / qs.length); };
    const evOf = {}, sdOf = {};
    let M = 0, V = 0;
    this.slots.forEach((slot, i) => {
      const p = starters[i], st = ls[p]?.st;
      let ev = 0, sd = 0;
      if (st === "locked") ev = ls[p].g?.fp || 0;
      else if (st === "live") {
        const g = ls[p].g, t = this.tip(p, g.date), frac = t ? Math.min(1, Math.max(0, (this.now - new Date(t)) / (150 * 60000))) : 0.5;
        const mu = this.b.gameMu(p, g.date);
        ev = g.fp + (1 - frac) * mu * 0.95; sd = qsd(this.qOf(p)) * mu * Math.sqrt(1 - frac);
      } else {
        const x = open.find(y => y.i === i);
        if (x && willLock.has(p)) ev = lockable[i].fp;
        else if (x) { const a = assignedTo[i]; ev = a ? Math.max(0, (val(x, a, false) ?? 0)) : 0; sd = a ? cont[a].sd : 0; }
      }
      evOf[i] = ev; sdOf[i] = sd; M += ev; V += sd * sd;
    });
    const Phi = z => 0.5 * (1 + Math.tanh(0.7978845608 * (z + 0.044715 * z ** 3)));
    const pWin = (m, v) => opts.opp ? Phi((m - opts.opp.mean) / Math.sqrt(v + opts.opp.var + 1)) : null;
    const mx = {};
    if (opts.opp) for (const x of open) {
      const g = lockable[x.i]; if (!g || !cont[x.p]?.u.length) continue;
      const base = M - evOf[x.i], baseV = V - sdOf[x.i] ** 2, bar = bars[x.i];
      const alt = altFor[x.i], passSd = alt && cont[alt] ? cont[alt].sd : cont[x.p].sd;
      const pL = pWin(base + g.fp, baseV), pP = pWin(base + bar, baseV + passSd ** 2);
      const evCall = willLock.has(x.p) ? "lock" : "pass", call = pL >= pP ? "lock" : "pass";
      mx[x.i] = { pLock: pL, pPass: pP, evCall, call, flipped: false };
      if (call !== evCall && Math.abs(pL - pP) >= 0.02) {
        mx[x.i].flipped = true;
        if (call === "lock") willLock.add(x.p); else willLock.delete(x.p);
      }
    }
    const outlook = { mean: M, var: V, sd: Math.sqrt(V), winProb: pWin(M, V), opp: opts.opp || null };

    // ---- 2) today's sequence per slot -------------------------------------------------------------
    // A slot can try several games in one day: if the first misses its keep-line, pass and slide in a
    // player whose game tips >= 2.5 h later. Each open slot starts with its assigned player's games;
    // unassigned players who play today are inserted where they add the most expected value.
    //   value(draws..., tail) folds from the end: V = q*E[max(X, V)] + (1-q)*V
    const fixed = new Set([...locked, ...willLock, ...liveNow]);
    const GAME_MS = 150 * 60000;
    const todayGame = p => { const g = cont[p]?.u[0]; return g && g.date === this.today && g.tip ? g : null; };
    const afterToday = p => { const u = (cont[p]?.u || []).filter(g => g.date > this.today); return u.length ? contValues(Q, u)[0] : 0; };
    const fold = (draws, tail) => {
      let V = tail; const keep = [];
      for (let k = draws.length - 1; k >= 0; k--) { keep[k] = V; const g = draws[k].g; V = g.q * expectedMax(g.Q || Q, g.mu, V) + (1 - g.q) * V; }
      return { V, keep };
    };
    const openToday = this.slots.map((s, i) => ({ s, i, p: starters[i] })).filter(x => !fixed.has(x.p)).map((x, k) => ({ ...x, k }));
    const plans = openToday.map(x => {
      const a = assignedTo[x.i] && !willLock.has(assignedTo[x.i]) ? assignedTo[x.i] : null;
      const ga = a ? todayGame(a) : null;
      return { x, a, draws: ga ? [{ p: a, g: ga }] : [], tail: a ? (ga ? afterToday(a) : cont[a].W) : 0 };
    });
    const used = new Set([...Object.values(assignedTo).filter(Boolean), ...willLock]);
    const insertBest = (pl, b, gb) => {
      let best = null;
      for (let pos = 0; pos <= pl.draws.length; pos++) {
        const d = [...pl.draws.slice(0, pos), { p: b, g: gb }, ...pl.draws.slice(pos)];
        let ok = true;
        for (let k = 1; k < d.length; k++) if (Date.parse(d[k].g.tip) < Date.parse(d[k - 1].g.tip) + GAME_MS) ok = false;
        if (!ok) continue;
        const v = fold(d, pl.tail).V;
        if (!best || v > best.v) best = { v, d };
      }
      return best;
    };
    for (;;) {
      let best = null;
      for (const b of pool) {
        if (used.has(b)) continue;
        const gb = todayGame(b); if (!gb) continue;
        for (const pl of plans) {
          if (!fits(pl.x.s, this.b.pos(b))) continue;
          const now = fold(pl.draws, pl.tail).V, ins = insertBest(pl, b, gb);
          if (ins && ins.v - now > 0.05 && (!best || ins.v - now > best.gain)) best = { pl, b, d: ins.d, gain: ins.v - now };
        }
      }
      if (!best) break;
      best.pl.draws = best.d; used.add(best.b);
    }
    const planByIdx = Object.fromEntries(plans.map(pl => [pl.x.i, pl]));
    const tipOf = g => g?.tip || null;
    const swapAfterOf = g => new Date(Date.parse(g.tip) + 135 * 60000).toISOString();
    const nm = p => (p && p !== "0" ? this.b.name(p) : "(empty)");

    // ---- 3) one plan per slot: the lock call + today's sequence, rendered everywhere from this ------
    const slots = this.slots.map((slot, i) => {
      const p = starters[i], s = ls[p] || { st: "none" }, name = nm(p);
      const out = { slot, pid: p, name, status: this.b.status(p), today: null, later: null };
      if (s.st === "locked") return { ...out, action: "locked", score: s.g?.fp ?? null, inferred: !!s.inferred,
        detail: s.g ? `Locked ${s.g.fp.toFixed(1)} (${s.g.date})${s.inferred ? " — read from Sleeper's score; tap Not locked if that's wrong" : ""}.` : "Locked." };
      if (s.st === "live") return { ...out, action: "live", score: s.g.fp, detail: `Game in progress: ${s.g.fp.toFixed(1)} so far. The lock call comes after the final buzzer.` };

      // today's sequence for this slot (empty if the slot is being locked)
      const pl = planByIdx[i];
      if (pl && pl.draws.length) {
        const { V, keep } = fold(pl.draws, pl.tail), f = pl.draws[0];
        out.today = { pid: f.p, name: nm(f.p), tip: f.g.tip, opp: f.g.opp, mu: f.g.mu, keepBar: r1(keep[0]), move: f.p !== p,
                      gain: r1(V - pl.tail), bestTime: f.p !== p ? new Date(Date.parse(f.g.tip) - 40 * 60000).toISOString() : null };
        if (pl.draws[1]) { const r = pl.draws[1]; out.today.relief = { pid: r.p, name: nm(r.p), tip: r.g.tip, opp: r.g.opp, mu: r.g.mu, swapAfter: swapAfterOf(f.g), keepBar: r1(keep[1]) }; }
      } else if (pl?.a && cont[pl.a]?.u[0]) {
        const g = cont[pl.a].u[0];
        out.later = { pid: pl.a, name: nm(pl.a), date: g.date, tip: g.tip, opp: g.opp, mu: g.mu, move: pl.a !== p };
      }
      const next = cont[p]?.u[0] || null;
      const deadline = next ? { date: next.date, tip: next.tip } : null;
      const planTxt = out.today ? (out.today.move ? ` Today: start ${out.today.name} here (${out.today.opp}, ${out.today.mu.toFixed(1)} proj).` : "")
                    : out.later?.move ? ` Next: ${out.later.name} covers this slot (${day3(out.later.date)}).` : "";

      if (lockable[i]) {
        const sc = lockable[i].fp, bar = bars[i], m = mx[i];
        const range = cont[p]?.u[0] ? ` Waiting: ~${bar.toFixed(1)} expected (his next game ${range80(cont[p].u[0].Q || Q, cont[p].u[0].mu).join("–")}).` : "";
        const decided = m && Math.max(m.pLock, m.pPass) < 0.02 || m && Math.min(m.pLock, m.pPass) > 0.98;
        const wp = !m ? "" : decided ? " (Matchup looks decided, so this call maximizes points.)" : ` Win chance: lock ${Math.round(m.pLock * 100)}% · wait ${Math.round(m.pPass * 100)}%.`;
        const base = { ...out, score: sc, bar: r1(bar), gameDate: lockable[i].date, deadline, matchup: m || null };
        const lockIt = willLock.has(p);
        if (s.st === "confirm" && lockIt)
          return { ...base, action: "confirm", detail: `Was he in your starting lineup when his ${lockable[i].date} game (${sc.toFixed(1)}) tipped? If yes, lock it.${wp}` };
        if (lockIt) {
          if (!deadline) return { ...base, action: "keep", detail: `${sc.toFixed(1)} counts automatically: he has no games left and nothing else beats it.` };
          if (m?.flipped) return { ...base, action: "lock", detail: `Matchup call — lock the safe ${sc.toFixed(1)}: you're projected ahead, so protecting the floor raises your win chance (${Math.round(m.pPass * 100)}% → ${Math.round(m.pLock * 100)}%), even though waiting averages ${bar.toFixed(1)}.` };
          return { ...base, action: "lock", detail: `${sc.toFixed(1)} beats the best alternative for this slot (${bar.toFixed(1)} expected). Lock before ${day3(deadline.date)}'s tip.${wp}` };
        }
        if (m?.flipped) return { ...base, action: "pass", detail: `Matchup call — wait for upside: you're projected behind, so passing on ${sc.toFixed(1)} raises your win chance (${Math.round(m.pLock * 100)}% → ${Math.round(m.pPass * 100)}%).${planTxt}` };
        return { ...base, action: "pass", detail: `Don't lock: ${sc.toFixed(1)} is under ${bar.toFixed(1)}, what this slot is expected to get by waiting.${planTxt}${wp}` };
      }
      if (!out.today && !out.later) return { ...out, action: "fallback-risk", detail: "Nobody eligible has a game left and nothing is locked: this slot scores its player's last game of the week." };
      const g = out.today || out.later;
      const note = s.st === "bench" ? " His last game was played from your bench, so it can't count." : "";
      return { ...out, action: "start", deadline,
        detail: out.today ? (out.today.move ? `Start ${out.today.name} here today (${out.today.opp}, ${out.today.mu.toFixed(1)} proj).${note}`
                                            : `Plays today vs ${g.opp}: ${g.mu.toFixed(1)} projected (${range80(g.Q || Q, g.mu).join("–")}).${note}`)
                          : `${out.later.move ? `Put ${out.later.name} here` : `${name} plays next`} ${day3(out.later.date)} vs ${out.later.opp}.${note}` };
    });

    // ---- 4) the time-ordered action list (top summary + phone alerts read this) ----------------------
    const actions = [];
    for (const x of slots) {
      if (x.action === "lock") actions.push({ kind: "lock", slot: x.slot, pid: x.pid, by: x.deadline.tip, t: x.deadline.tip,
        text: `Lock ${x.name} (${x.slot}) — ${x.score.toFixed(1)}` });
      if (x.action === "confirm") actions.push({ kind: "confirm", slot: x.slot, pid: x.pid, by: x.deadline?.tip, t: x.deadline?.tip || "",
        text: `Check ${x.name} (${x.slot}): was he starting on ${x.gameDate}? If yes, lock ${x.score.toFixed(1)}` });
      if (x.action === "fallback-risk") actions.push({ kind: "fallback", slot: x.slot, pid: x.pid, t: "", text: `${x.slot}: ${x.detail}` });
      if (x.action === "pass") actions.push({ kind: "pass", slot: x.slot, pid: x.pid, by: x.deadline?.tip, t: x.deadline?.tip || x.today?.tip || "",
        text: `Don't lock ${x.name}'s ${x.score.toFixed(1)} (${x.slot})` });
      const td = x.today;
      if (td?.move) actions.push({ kind: "move", slot: x.slot, pid: td.pid, by: td.tip, t: td.bestTime, best: td.bestTime,
        text: `Start ${td.name} at ${x.slot}${x.pid && x.pid !== "0" ? ` (bench ${x.name})` : ""}` });
      if (td?.relief) actions.push({ kind: "relief", slot: x.slot, pid: td.relief.pid, from: td.relief.swapAfter, by: td.relief.tip, t: td.relief.swapAfter,
        text: `If ${td.name} scores under ${td.keepBar.toFixed(1)}, swap ${td.relief.name} into ${x.slot}` });
      if (!td && x.later?.move && x.later.tip) actions.push({ kind: "later", slot: x.slot, pid: x.later.pid, by: x.later.tip, t: x.later.tip,
        text: `Put ${x.later.name} at ${x.slot} before ${day3(x.later.date)}'s game` });
    }
    // order by hard deadline (the tip that closes the decision); relief swaps sort by when they open
    const key = a => (a.kind === "relief" ? a.from : a.by) || a.t || "9";
    actions.sort((a, b) => String(key(a)).localeCompare(String(key(b))));

    // compatibility views
    const lineup = slots.filter(x => x.today).map(x => ({ slot: x.slot, pid: x.today.pid, name: x.today.name, current: x.pid, currentName: x.name,
      move: x.today.move, tip: x.today.tip, opp: x.today.opp, mu: x.today.mu, keepBar: x.today.keepBar, relief: x.today.relief || null,
      bestTime: x.today.bestTime, changeBy: x.today.move ? x.today.tip : null, gain: x.today.gain }));
    void tipOf;

    const grid = players.map(p => {
      const t = this.b.team(p), pl = Object.fromEntries(this.played(p).map(g => [g.date, g.fp]));
      const lv = Object.fromEntries(this.livePlayed(p).map(g => [g.date, g.fp]));
      const cells = this.days.map(d => {
        const info = this.tg[t]?.[d]; if (!info) return null;
        if (d in pl) return { kind: "played", fp: r1(pl[d]), opp: info.opp, started: this.elig(p, d) };
        if (d in lv || this.tipped(p, d)) return { kind: "live", opp: info.opp, fp: d in lv ? r1(lv[d]) : null };
        return { kind: "upcoming", mu: this.b.gameMu(p, d), opp: info.opp, tip: this.tips[`${d}|${t}`] };
      });
      return { pid: p, name: this.b.name(p), team: t, pos: this.b.pos(p).join("/"), status: this.b.status(p),
               locked: locked.has(p), starter: starters.includes(p), cells, left: cells.filter(c => c?.kind === "upcoming").length };
    }).sort((a, b) => this.b.baseline(b.pid) - this.b.baseline(a.pid));

    const idle = pool.filter(p => !used.has(p) && todayGame(p)).map(p => ({ pid: p, name: this.b.name(p) }));
    for (const x of slots) { const i = this.slots.indexOf(x.slot) >= 0 ? slots.indexOf(x) : -1; x.ev = r1(evOf[i] || 0); x.sd = r1(sdOf[i] || 0); }
    return { slots, actions, lineup, idle, grid, days: this.days, unlocked: open.length - willLock.size, expectedTotal: r1(main.total), outlook };
  }

  // expected locked points from the open slots for the rest of THIS week if the roster were `players`
  // (same joint assignment as build(), without the lock-bar detail). Locked/live slots stay as they are.
  weekTotal(players) {
    const starters = this.matchup.starters || [], have = new Set(players);
    this._ls ||= {}; this._W ||= {};
    const ls = p => (this._ls[p] ||= this.lockState(p));
    const fixed = new Set(starters.filter(p => have.has(p) && ["locked", "live"].includes(ls(p).st)));
    const open = this.slots.map((s, i) => ({ s, i, p: starters[i] })).filter(x => !fixed.has(x.p));
    const pool = players.filter(p => !fixed.has(p) && !(this.roster.reserve || []).includes(p));
    const W = p => (this._W[p] ??= contValues(this.Q, this.upcoming(p))[0] || 0);
    const m = open.map(x => pool.map(p => {
      if (!fits(x.s, this.b.pos(p))) return null;
      const st = p === x.p ? ls(p).st : null;
      return (st === "open" || st === "confirm") && ls(p).g ? Math.max(ls(p).g.fp, W(p)) : W(p);
    }));
    let total = 0;
    maxAssign(m).forEach((c, r) => { if (c >= 0 && c < pool.length && m[r][c] != null) total += m[r][c]; });
    return total;
  }

  waivers(trending, limit = 30) {
    const Q = this.Q, trend = Object.fromEntries((trending || []).map(t => [t.player_id, t.count]));
    const mine = this.roster.players || [];
    const worst = Math.min(...mine.map(p => this.b.baseline(p)));
    const out = [];
    for (const [pid, m] of Object.entries(this.b.meta)) {
      if (this.rostered.has(pid) || !m.team || OUT.has(m.status)) continue;
      const u = this.upcoming(pid);
      const hasProj = u.some(g => this.b.proj[`${pid}|${g.date}`]);
      if (!(this.b.games[pid] || []).length && !hasProj) continue;
      const base = this.b.baseline(pid); if (base < 15) continue;
      const recent = (this.b.games[pid] || []).slice(-3).map(g => g.fp);
      const r = { pid, name: m.name, team: m.team, pos: (m.pos || []).join("/"), status: m.status || null,
                  fpg: Math.round(base * 10) / 10, over: Math.round((base - worst) * 10) / 10, left: u.length,
                  week: Math.round((u.length ? contValues(Q, u)[0] : 0) * 10) / 10, recent, trend: trend[pid] || 0 };
      r.bid = r.over <= 0 ? 0 : Math.min(40, Math.round(1 + r.over * 0.8 + Math.min(r.trend, 20000) / 4000));
      out.push(r);
    }
    out.sort((a, b) => (b.over > 0) - (a.over > 0) || (b.fpg + 0.15 * b.week) - (a.fpg + 0.15 * a.week));
    return { list: out.slice(0, limit), worst: Math.round(worst * 10) / 10 };
  }
}

// ---------- roster value: trades and waiver pickups ----------
// A player's value = locked points per week: baseline x (best-of-~3.5-games gain, larger for streaky
// players) x ~86% availability. A team's value = best positional fill of the 10 slots + a little for
// bench depth (more lock options). Used for both trade grading and add/drop suggestions.
// ---------- player & team value (waivers, trades) ------------------------------------------------
// "Market" value: roughly how other managers see a player (per-game production, a bit extra for upside).
// Used only for the realism check on trade offers, never to decide what helps YOUR team.
export function playerValue(book, pid) {
  const g = book.done ? book.done(pid) : (book.games[pid] || []), base = book.baseline(pid);
  let cv = 0.3;
  if (g.length >= 5) {
    const m = g.reduce((a, x) => a + x.fp, 0) / g.length;
    const sd = Math.sqrt(g.reduce((a, x) => a + (x.fp - m) ** 2, 0) / g.length);
    cv = Math.min(0.5, Math.max(0.15, sd / Math.max(m, 1)));
  }
  const out = ["Out", "IR", "Suspended"].includes(book.status(pid)) ? 0.6 : 1;
  return base * (1 + 0.7 * cv) * 0.86 * out;
}

// What a roster is actually worth in Lock-In: for every remaining week, each player's lock-in value of THAT
// week's games (more games = more chances to lock a big one; his own volatility tier), then the best way to
// fill the starting slots. Future weeks are discounted 3%/week (rosters, roles and health change).
// Missing roster spots are filled with the best free agent, so a 2-for-1 gets credit for the open spot.
const NEAR = 4;   // weeks solved one by one in team valuation
export class Valuer {
  constructor({ book, schedule, Q, rosterPositions, week, freeAgents = [] }) {
    Object.assign(this, { b: book, week, Q: Array.isArray(Q) ? Q : Q.quantiles, QT: Array.isArray(Q) ? null : Q.tiers });
    this.slots = rosterPositions.filter(s => s !== "BN" && s !== "IR");
    this.size = rosterPositions.filter(s => s !== "IR").length;
    this.tg = teamGames(schedule);
    const weeks = [...new Set(schedule.filter(g => g.week > week).map(g => g.week))].sort((a, b) => a - b);
    this.weeks = weeks.map((w, i) => ({ w, days: weekDays(schedule, w), disc: 0.97 ** i }));
    this.discSum = this.weeks.reduce((a, x) => a + x.disc, 0) || 1;
    this.fa = freeAgents; this.memo = new Map();
  }
  // discounted sum over remaining weeks of the player's lock-in value; .perWeek for display
  // per-week lock-in value (undiscounted) for each remaining week: [w0, w1, ...]
  weekly(p) {
    if (this.memo.has(p)) return this.memo.get(p);
    const t = this.b.team(p), st = this.b.status(p), base = this.b.baseline(p), Qp = tierQ(this.QT, base, this.Q);
    const all = Object.keys(this.tg[t] || {});
    const out = this.weeks.map(({ days }, i) => {
      const games = all.filter(d => days.includes(d)).sort().map(d => {
        let q = 0.92;
        if (OUT.has(st)) q = i === 0 ? 0.3 : 0.85;           // unknown return date
        else if (SHAKY.has(st)) q = i === 0 ? 0.8 : 0.92;
        const prev = new Date(d + "T12:00:00Z"); prev.setUTCDate(prev.getUTCDate() - 1);
        if (all.includes(prev.toISOString().slice(0, 10))) q *= B2B_FACTOR;
        return { mu: base, q, Q: Qp };
      });
      return games.length ? contValues(this.Q, games)[0] : 0;
    });
    this.memo.set(p, out);
    return out;
  }
  ros(p) { return this.weekly(p).reduce((a, v, i) => a + this.weeks[i].disc * v, 0); }
  // value of the far weeks only (aggregated), used after the near weeks are solved one by one
  far(p) { return this.weekly(p).reduce((a, v, i) => a + (i >= NEAR ? this.weeks[i].disc * v : 0), 0); }
  perWeek(p) { return this.ros(p) / this.discSum; }
  topFA() { return (this._fa ||= [...this.fa].sort((a, b) => this.ros(b) - this.ros(a))); }
  // replacement level: what any manager can pick up today (5th-best free agent's per-week value)
  repl() { const f = this.topFA(); return this._repl ??= (f.length ? this.perWeek(f[Math.min(4, f.length - 1)]) : 0); }
  // trade value as managers see it: only value ABOVE replacement counts, and stars are worth more than the sum of
  // parts (convex), because a roster spot and a starting slot can only hold one player
  tradeValue(p) { return Math.max(0, this.perWeek(p) - this.repl()) ** 1.5; }
  // best lineup over the rest of the season, in points per week
  // withFA: the team may also use the best free agents (anyone below waiver level is replaceable for free).
  // Trades MUST be judged this way: otherwise receiving two replacement-level bodies looks like a gain for a team
  // with weak starters, when it could fill those holes from waivers without giving anything up.
  team(players, withFA = false) { return this.lineup(players, withFA).value; }
  // Best lineups: each of the next NEAR weeks is solved on its own (so short injuries, light schedules and depth
  // show up as real needs: a team missing a starter for two weeks values a replacement more), the rest of the
  // season as one block. Returns value per week plus the season-long slot assignment (for "fit" notes).
  lineup(players, withFA = false) {
    let ps = [...new Set(players)];
    const have = new Set(ps), fas = this.topFA().filter(p => !have.has(p));
    if (withFA) ps = ps.concat(fas.slice(0, 8));
    else if (ps.length < this.size) ps = ps.concat(fas.slice(0, this.size - ps.length));
    const solve = val => {
      const m = this.slots.map(s => ps.map(p => (fits(s, this.b.pos(p)) ? val(p) : null)));
      const pick = maxAssign(m); let total = 0; const by = {};
      pick.forEach((c, r) => { if (c >= 0 && m[r][c] != null) { total += m[r][c]; by[r] = ps[c]; } });
      return { total, by };
    };
    let total = 0;
    for (let i = 0; i < Math.min(NEAR, this.weeks.length); i++) total += this.weeks[i].disc * solve(p => this.weekly(p)[i]).total;
    const farSol = solve(p => this.far(p));
    total += farSol.total;
    const used = new Set(Object.values(farSol.by));
    // bench: injury cover and same-day relief are worth something, a little
    const bench = ps.filter(p => !used.has(p)).map(p => this.ros(p)).sort((a, b) => b - a).slice(0, 3).reduce((a, b) => a + b, 0);
    return { value: (total + 0.1 * bench) / this.discSum, slots: this.slots.map((s, r) => ({ slot: s, pid: farSol.by[r] || null })) };
  }
  // what a trade changes in a team's regular lineup: [{slot, out, in}], for "why it helps them" notes
  fit(before, after) {
    const a = this.lineup(before, true).slots, b = this.lineup(after, true).slots, inA = new Set(a.map(x => x.pid));
    const added = b.filter(x => x.pid && !inA.has(x.pid));
    const gone = new Set(b.map(x => x.pid)), dropped = a.filter(x => x.pid && !gone.has(x.pid));
    return added.map((x, i) => ({ slot: x.slot, in: x.pid, out: dropped[i]?.pid || null,
      gain: Math.round((this.perWeek(x.pid) - (dropped[i] ? this.perWeek(dropped[i].pid) : this.repl())) * 10) / 10 }));
  }
}

const swapIn = (roster, out, inn) => roster.filter(p => !out.includes(p)).concat(inn);
export const teamValue = (valuer, players) => valuer.team(players);

export function tradeIdeas(valuer, book, mine, others, limit = 15) {
  const T = ps => ps.reduce((a, p) => a + valuer.tradeValue(p), 0);
  const myB = valuer.team(mine.players, true), ideas = [];
  for (const r of others) {
    const tb = valuer.team(r.players, true), mp = mine.players, tp = r.players;
    const tryDeal = (give, get) => {
      // realism: by market value (above replacement, stars convex) they must get back at least ~90% of what they give
      const tg = T(give), tt = T(get);
      if (tg < 0.9 * tt || tt === 0) return;
      const dm = valuer.team(swapIn(mp, give, get), true) - myB;
      if (dm <= 0.5) return;
      const dt = valuer.team(swapIn(tp, get, give), true) - tb;
      if (dt >= 0) ideas.push({ give, get, dm, dt, marketGive: tg, marketGet: tt, roster_id: r.roster_id, owner_id: r.owner_id, tp });
    };
    for (const a of mp) for (const b of tp) tryDeal([a], [b]);
    for (let i = 0; i < mp.length; i++) for (let j = i + 1; j < mp.length; j++) for (const b of tp) tryDeal([mp[i], mp[j]], [b]);
    for (const a of mp) for (let i = 0; i < tp.length; i++) for (let j = i + 1; j < tp.length; j++) tryDeal([a], [tp[i], tp[j]]);
  }
  // best for us, but only deals that are close to fair for them rank high (lopsided offers just get declined)
  ideas.sort((x, y) => (y.dm + 0.5 * y.dt) - (x.dm + 0.5 * x.dt));
  const per = {}, team = {}, out = [];
  for (const x of ideas) {
    const k = x.get.join();
    if ((per[k] || 0) >= 2 || (team[x.roster_id] || 0) >= 3) continue;      // variety: targets and partners
    per[k] = (per[k] || 0) + 1; team[x.roster_id] = (team[x.roster_id] || 0) + 1;
    // fit: which of THEIR lineup spots the players they receive take over (who they replace, per-week gain)
    x.theirFit = valuer.fit(x.tp, swapIn(x.tp, x.get, x.give)).map(f => ({ ...f, inName: book.name(f.in), outName: f.out ? book.name(f.out) : "a waiver pickup" }));
    x.myFit = valuer.fit(mine.players, swapIn(mine.players, x.give, x.get)).map(f => ({ ...f, inName: book.name(f.in), outName: f.out ? book.name(f.out) : "a waiver pickup" }));
    delete x.tp; out.push(x);
    if (out.length >= limit) break;
  }
  return out;
}

// For each free agent, the drop that gains the most: this week's expected locked total (the real plan: open
// slots, today's games, locks already made) plus rest-of-season value. Protected = players the plan uses.
export function waiverMoves(wp, valuer, mine, candidates, protect, limit = 8) {
  const baseWeek = wp.weekTotal(mine.players), baseRos = valuer.team(mine.players), out = [];
  for (const fa of candidates) {
    let best = null;
    for (const d of mine.players) {
      if (protect.has(d)) continue;
      const roster = swapIn(mine.players, [d], [fa.pid]);
      const week = wp.weekTotal(roster) - baseWeek, perWeek = valuer.team(roster) - baseRos;
      const gain = week + perWeek * valuer.discSum;
      if (!best || gain > best.gain) best = { drop: d, gain, week, perWeek };
    }
    if (best && best.gain > 0.3) out.push({ ...fa, drop: best.drop, dropName: wp.b.name(best.drop),
      gain: Math.round(best.gain * 10) / 10, weekGain: Math.round(best.week * 10) / 10, rosGain: Math.round(best.perWeek * 10) / 10,
      bid: Math.min(40, Math.max(1, Math.round(best.perWeek * 3 + Math.max(0, best.week) * 0.5 + Math.min(fa.trend || 0, 20000) / 5000))) });
  }
  return out.sort((a, b) => b.gain - a.gain).slice(0, limit);
}
