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
// W[j] = value of arriving at game j unlocked; lock after game j iff score >= W[j+1]
export function contValues(Q, games) {
  const n = games.length, W = new Array(n + 1).fill(0);
  for (let j = n - 1; j >= 0; j--) {
    const g = games[j];
    W[j] = j === n - 1 ? g.q * g.mu : g.q * expectedMax(Q, g.mu, W[j + 1]) + (1 - g.q) * W[j + 1];
  }
  return W;
}
export const lockBar = (Q, after) => (after.length ? contValues(Q, after)[0] : 0);
export const range80 = (Q, mu) => [Math.round(mu * Q[10] * 10) / 10, Math.round(mu * Q[90] * 10) / 10];

// ---------- player book ----------
const STATUS_Q = { Probable: 0.9, "Day-To-Day": 0.75, GTD: 0.6, Questionable: 0.55, Doubtful: 0.2,
  Out: 0, IR: 0, Suspended: 0, NA: 0, DNR: 0, COV: 0 };
const OUT = new Set(["Out", "IR", "Suspended", "NA", "DNR", "COV"]);
const SHAKY = new Set(["Questionable", "Doubtful", "GTD", "Day-To-Day"]);
export const B2B_FACTOR = 0.86, PRIOR_GAMES = 8;

export class Book {
  constructor({ scoring, players, priors, gamelog, weights }) {
    this.sc = scoring;
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
      if (!r.date || !(Number(st.min) > 0)) continue;
      const list = this.games[r.player_id] || (this.games[r.player_id] = []);
      const i = list.findIndex(g => g.gid === r.game_id);
      const g = { date: r.date, fp: fantasyPoints(st, this.sc), min: Number(st.min), gid: r.game_id };
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
  avg(p) { const g = this.games[p] || []; return g.length ? g.reduce((a, x) => a + x.fp, 0) / g.length : null; }
  baseline(p) {
    const g = this.games[p] || [], cur = this.avg(p);
    let prior = this.prior[p];
    if (prior == null) {
      const f = Object.entries(this.proj).filter(([k]) => k.startsWith(p + "|")).map(([, v]) => v);
      prior = f.length ? f.reduce((a, b) => a + b, 0) / f.length : (cur ?? 0);
    }
    if (cur == null) return prior;
    return (g.length * cur + PRIOR_GAMES * prior) / (g.length + PRIOR_GAMES);
  }
  gameMu(p, date) {
    const base = this.baseline(p), pr = this.proj[`${p}|${date}`];
    if (!(pr > 0)) return Math.round(base * 10) / 10;
    const wr = this.w.rotowire ?? 0.5, wm = this.w.model ?? 0.5;
    return Math.round(((wr * pr + wm * base) / (wr + wm)) * 10) / 10;
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

// ---------- the week plan ----------
export class WeekPlan {
  constructor({ Q, book, schedule, week, today, now, rosterPositions, roster, matchup, rosters, tips, elig, locks }) {
    Object.assign(this, { Q, b: book, week, today, now: now || new Date(), roster, matchup, tips: tips || {} });
    this.days = weekDays(schedule, week);
    this.tg = teamGames(schedule);
    this.slots = rosterPositions.filter(s => s !== "BN" && s !== "IR");
    this.rostered = new Set(rosters.flatMap(r => r.players || []));
    this.elig = elig || (() => null);
    this.locks = locks || {};
  }
  teamDays(t) { return Object.keys(this.tg[t] || {}).filter(d => this.days.includes(d)).sort(); }
  played(p) { return (this.b.games[p] || []).filter(g => this.days.includes(g.date)); }
  tip(p, d) { return this.tips[`${d}|${this.b.team(p)}`]; }
  tipped(p, d) { const t = this.tip(p, d); return t ? new Date(t) <= this.now : d < this.today; }
  upcoming(p) {
    const t = this.b.team(p), done = new Set(this.played(p).map(g => g.date)), all = Object.keys(this.tg[t] || {});
    return this.teamDays(t).filter(d => !done.has(d) && !this.tipped(p, d)).map(d => {
      const b2b = all.includes(addDays(d, -1));
      return { date: d, mu: this.b.gameMu(p, d), q: this.b.playProb(p, dayDiff(d, this.today), b2b),
               opp: this.tg[t][d].opp, b2b, tip: this.tip(p, d) };
    });
  }
  lockState(p) {
    const pl = this.played(p);
    if (this.locks[p]) return { st: "locked", g: pl.at(-1) || null };
    const raw = this.matchup.players_points?.[p];
    if (!pl.length || raw == null) return { st: "none", g: null };
    const pts = Math.round(raw) / 10, latest = pl.at(-1);
    for (const g of pl.slice(0, -1)) if (Math.abs(g.fp - pts) < 0.01 && Math.abs(latest.fp - pts) >= 0.01) return { st: "locked", g };
    const e = this.elig(p, latest.date);
    return { st: e === true ? "open" : e === null ? "confirm" : "bench", g: latest };
  }
  build() {
    const Q = this.Q, starters = this.matchup.starters || [];
    const reserve = new Set(this.roster.reserve || []);
    const players = (this.roster.players || []).filter(p => !reserve.has(p));
    const ls = {}; for (const p of players) ls[p] = this.lockState(p);
    const locked = new Set(starters.filter(p => ls[p]?.st === "locked"));
    const cont = {};
    for (const p of players) if (!locked.has(p)) { const u = this.upcoming(p); cont[p] = { W: u.length ? contValues(Q, u)[0] : 0, u }; }

    const open = this.slots.map((s, i) => ({ s, i, p: starters[i] })).filter(x => !locked.has(x.p));
    const pending = {}; for (const x of open) if (ls[x.p]?.st === "open") pending[x.p] = ls[x.p].g;
    const willLock = new Set(Object.keys(pending).filter(p => pending[p].fp >= lockBar(Q, cont[p]?.u || [])));
    let best = {};
    for (let pass = 0; pass < 2; pass++) {
      const pool = Object.keys(cont).filter(p => !willLock.has(p));
      const left = open.filter(x => !willLock.has(x.p)).sort((a, b) => pool.filter(p => fits(a.s, this.b.pos(p))).length - pool.filter(p => fits(b.s, this.b.pos(p))).length);
      const taken = new Set(); best = {};
      for (const x of left) {
        const c = pool.filter(p => !taken.has(p) && fits(x.s, this.b.pos(p))).sort((a, b) => cont[b].W - cont[a].W)[0];
        if (c) { best[x.i] = { W: cont[c].W, p: c }; taken.add(c); }
      }
      for (const x of open) if (willLock.has(x.p)) {
        const alt = Math.max(0, ...pool.filter(p => !taken.has(p) && fits(x.s, this.b.pos(p))).map(p => cont[p].W));
        best[x.i] = { W: alt, p: null };
        if (pending[x.p].fp < alt) willLock.delete(x.p);
      }
    }

    const r1 = v => Math.round(v * 10) / 10;
    const slots = this.slots.map((slot, i) => {
      const p = starters[i], name = p && p !== "0" ? this.b.name(p) : "(empty)", s = ls[p] || { st: "none" };
      const base = { slot, pid: p, name, status: this.b.status(p) };
      if (s.st === "locked") return { ...base, action: "locked", score: s.g?.fp ?? null, detail: s.g ? `Locked ${s.g.fp.toFixed(1)} (${s.g.date}).` : "Locked." };
      const u = cont[p]?.u || [], own = lockBar(Q, u), alt = best[i] || { W: 0, p: null }, bar = Math.max(own, alt.W);
      const nxt = u[0], deadline = nxt ? { date: nxt.date, tip: nxt.tip } : null;
      if (s.st === "confirm" && s.g.fp < own) return { ...base, action: "pass", score: s.g.fp, bar: r1(own), deadline,
        detail: `Pass either way: ${s.g.fp.toFixed(1)} is under his bar of ${own.toFixed(1)}, so it doesn't matter whether that game was from your lineup.` };
      if (s.st === "confirm") return { ...base, action: "confirm", score: s.g.fp, bar: r1(own), gameDate: s.g.date, deadline,
        detail: `Was he in your starting lineup when his ${s.g.date} game (${s.g.fp.toFixed(1)}) tipped? If yes, ${s.g.fp >= own ? "lock it" : "pass"} (bar ${own.toFixed(1)}).` };
      if (s.st === "open") {
        const sc = s.g.fp;
        if (!u.length) return { ...base, action: "lock", score: sc, bar: 0, deadline, detail: "No games left this week; this game counts either way." };
        if (sc >= bar) return { ...base, action: "lock", score: sc, bar: r1(bar), deadline, detail: `${sc.toFixed(1)} beats the bar of ${bar.toFixed(1)}.` };
        const bench = alt.p && alt.p !== p && !starters.includes(alt.p) ? ` Bench option: ${this.b.name(alt.p)}.` : "";
        return { ...base, action: "pass", score: sc, bar: r1(bar), deadline, detail: `${sc.toFixed(1)} is under the bar of ${bar.toFixed(1)}; waiting is worth more.${bench}` };
      }
      if (!nxt) return { ...base, action: "fallback-risk", detail: "No games left and nothing locked: this slot scores his last game of the week." };
      const [lo, hi] = range80(Q, nxt.mu);
      const note = s.st === "bench" ? " His last game was played from your bench, so it can't count." : "";
      return { ...base, action: "start", bar: r1(own), deadline,
        detail: `Next: ${nxt.date} vs ${nxt.opp} · ${nxt.mu.toFixed(1)} projected (${lo}–${hi}) · plays ${Math.round(nxt.q * 100)}%.${note}` };
    });

    // who should sit in each still-open slot for TODAY's games (only a starter's game can be locked)
    const fixed = new Set([...locked, ...willLock]);
    const openToday = this.slots.map((s, i) => ({ s, p: starters[i] })).filter(x => !fixed.has(x.p));
    const todayPl = Object.keys(cont).filter(p => !willLock.has(p) && cont[p].u.some(g => g.date === this.today));
    const gain = {};
    for (const p of todayPl) {
      const u = cont[p].u, after = u.length > 1 ? contValues(Q, u.slice(1))[0] : 0;
      // value of sampling him today: the option gain over waiting, or his full value if it's his last game
      gain[p] = u.length === 1 ? u[0].q * u[0].mu : u[0].q * (expectedMax(Q, u[0].mu, after) - after);
    }
    // Primary assignment: scarcest slots first, best option value first.
    const tipMs = p => { const t = cont[p]?.u[0]?.tip; return t ? Date.parse(t) : null; };
    const used = new Set();
    const lineup = openToday.map((x, k) => ({ ...x, k })).sort((a, b) => todayPl.filter(p => fits(a.s, this.b.pos(p))).length - todayPl.filter(p => fits(b.s, this.b.pos(p))).length)
      .map(x => {
        const c = todayPl.filter(p => !used.has(p) && fits(x.s, this.b.pos(p))).sort((a, b) => gain[b] - gain[a])[0];
        if (!c) return { slot: x.s, k: x.k, pid: null, name: "nobody eligible plays today", current: x.p, currentName: x.p ? this.b.name(x.p) : null, gain: 0 };
        used.add(c);
        const g = cont[c].u[0];
        return { slot: x.s, k: x.k, pid: c, name: this.b.name(c), current: x.p, currentName: x.p ? this.b.name(x.p) : null,
                 move: c !== x.p, gain: r1(gain[c]), tip: g.tip, opp: g.opp, mu: g.mu };
      }).sort((a, b) => a.k - b.k);

    // Same-day relief: a player whose game tips at least 2.5 h after the primary's can take the slot if the
    // primary's game misses its bar. Primaries most likely to miss (lowest projection) get relief first.
    const GAME_MS = 150 * 60000;
    const relievers = todayPl.filter(p => !used.has(p)).sort((a, b) => (cont[b].u[0]?.mu || 0) - (cont[a].u[0]?.mu || 0));
    for (const rp of relievers) {
      const rt = tipMs(rp); if (!rt) continue;
      const cands = lineup.filter(x => x.pid && !x.relief && fits(x.slot, this.b.pos(rp)) && tipMs(x.pid) && rt >= tipMs(x.pid) + GAME_MS)
        .sort((a, b) => a.mu - b.mu);
      const x = cands[0]; if (!x) continue;
      const rg = cont[rp].u[0], rW = contValues(Q, cont[rp].u)[0];
      const ownAfter = cont[x.pid].u.length > 1 ? contValues(Q, cont[x.pid].u.slice(1))[0] : 0;
      x.relief = { pid: rp, name: this.b.name(rp), tip: rg.tip, opp: rg.opp, mu: rg.mu,
                   swapAfter: new Date(tipMs(x.pid) + 135 * 60000).toISOString() };
      x.keepBar = r1(Math.max(ownAfter, rW));           // keep the primary's game only if it beats this
      used.add(rp);
    }
    // Timing: change as late as possible (final injury reports land ~30-60 min before tip), but before tip.
    for (const x of lineup) if (x.move && x.tip) {
      x.changeBy = x.tip;
      x.bestTime = new Date(Date.parse(x.tip) - 40 * 60000).toISOString();
    }

    const grid = players.map(p => {
      const t = this.b.team(p), pl = Object.fromEntries(this.played(p).map(g => [g.date, g.fp]));
      const cells = this.days.map(d => {
        const info = this.tg[t]?.[d]; if (!info) return null;
        if (d in pl) return { kind: "played", fp: r1(pl[d]), opp: info.opp, started: this.elig(p, d) };
        if (this.tipped(p, d)) return { kind: "live", opp: info.opp };
        return { kind: "upcoming", mu: this.b.gameMu(p, d), opp: info.opp, tip: this.tips[`${d}|${t}`] };
      });
      return { pid: p, name: this.b.name(p), team: t, pos: this.b.pos(p).join("/"), status: this.b.status(p),
               locked: locked.has(p), starter: starters.includes(p), cells, left: cells.filter(c => c?.kind === "upcoming").length };
    }).sort((a, b) => this.b.baseline(b.pid) - this.b.baseline(a.pid));

    const before = this.slots.map((slot, i) => ({ slot, pid: starters[i], name: starters[i] && starters[i] !== "0" ? this.b.name(starters[i]) : "(empty)",
      fixed: fixed.has(starters[i]), plays: !!cont[starters[i]]?.u.some(g => g.date === this.today) }));
    return { slots, lineup, before, idle: todayPl.filter(p => !used.has(p)).map(p => ({ pid: p, name: this.b.name(p) })), grid,
             days: this.days, unlocked: open.length - willLock.size };
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
export function playerValue(book, pid) {
  const g = book.games[pid] || [], base = book.baseline(pid);
  let cv = 0.3;
  if (g.length >= 5) {
    const m = g.reduce((a, x) => a + x.fp, 0) / g.length;
    const sd = Math.sqrt(g.reduce((a, x) => a + (x.fp - m) ** 2, 0) / g.length);
    cv = Math.min(0.5, Math.max(0.15, sd / Math.max(m, 1)));
  }
  const out = ["Out", "IR", "Suspended"].includes(book.status(pid)) ? 0.6 : 1;
  return base * (1 + 0.7 * cv) * 0.86 * out;
}
export function teamValue(book, players, slots) {
  const vals = players.map(p => ({ p, v: playerValue(book, p) })).sort((a, b) => b.v - a.v);
  const used = new Set(); let total = 0;
  const order = [...slots].sort((a, b) => vals.filter(x => fits(a, book.pos(x.p))).length - vals.filter(x => fits(b, book.pos(x.p))).length);
  for (const s of order) { const x = vals.find(x => !used.has(x.p) && fits(s, book.pos(x.p))); if (x) { used.add(x.p); total += x.v; } }
  const bench = vals.filter(x => !used.has(x.p)).slice(0, 3).reduce((a, x) => a + x.v, 0);
  return total + 0.12 * bench;
}
const swapIn = (roster, out, inn) => roster.filter(p => !out.includes(p)).concat(inn);

export function tradeIdeas(book, mine, others, slots, limit = 15) {
  const myB = teamValue(book, mine.players, slots), ideas = [];
  for (const r of others) {
    const tb = teamValue(book, r.players, slots), mp = mine.players, tp = r.players;
    const tryDeal = (give, get) => {
      const dm = teamValue(book, swapIn(mp, give, get), slots) - myB;
      if (dm <= 0.5) return;
      const dt = teamValue(book, swapIn(tp, get, give), slots) - tb;
      if (dt >= 0) ideas.push({ give, get, dm, dt, roster_id: r.roster_id, owner_id: r.owner_id });
    };
    for (const a of mp) for (const b of tp) tryDeal([a], [b]);
    for (let i = 0; i < mp.length; i++) for (let j = i + 1; j < mp.length; j++) for (const b of tp) tryDeal([mp[i], mp[j]], [b]);
  }
  ideas.sort((x, y) => (y.dm + 0.5 * y.dt) - (x.dm + 0.5 * x.dt));
  // keep variety: at most 2 ideas per target player
  const per = {}, out = [];
  for (const x of ideas) { const k = x.get.join(); if ((per[k] = (per[k] || 0) + 1) <= 2) out.push(x); if (out.length >= limit) break; }
  return out;
}

export function waiverMoves(book, mine, candidates, slots, protect, limit = 8) {
  // for each free agent, the drop that improves the team most; protected = locked/IR players
  const base = teamValue(book, mine.players, slots), out = [];
  for (const fa of candidates) {
    let best = null;
    for (const d of mine.players) {
      if (protect.has(d)) continue;
      const dv = teamValue(book, swapIn(mine.players, [d], [fa.pid]), slots) - base;
      if (!best || dv > best.dv) best = { drop: d, dv };
    }
    if (best && best.dv > 0.3) out.push({ ...fa, drop: best.drop, dropName: book.name(best.drop), gain: Math.round(best.dv * 10) / 10,
      bid: Math.min(40, Math.max(1, Math.round(best.dv * 2 + Math.min(fa.trend || 0, 20000) / 5000))) });
  }
  return out.sort((a, b) => b.gain - a.gain).slice(0, limit);
}
