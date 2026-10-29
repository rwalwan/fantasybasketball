// Suggested moves with short AI reasoning -> site/static/moves.json
// Runs in the scheduled job after `python -m app.run` (needs site/static/*.json). Uses the same engine as
// the site, so the numbers match what you see there. Reasons are cached so each suggestion is only
// written once (OpenRouter key stays server-side; never shipped to the browser).
import { stageOf, calibration } from "./winprob.mjs";
import fs from "node:fs";
import { Book, WeekPlan, Valuer, eligFromSnaps, selectAdds, weekDays, tradeIdeas, waiverMoves, playerValue } from "../site/engine.js";

const LEAGUE = "1400915575915491328", USER = "1388708038000533504";
const S1 = "https://api.sleeper.app/v1", S2 = "https://api.sleeper.com";
const MODEL = process.env.OPENROUTER_MODEL || "anthropic/claude-haiku-5.5";
const get = async u => { const r = await fetch(u, { headers: { "user-agent": "we-back-lock-desk" } }); if (!r.ok) throw new Error(`${r.status} ${u}`); return r.json(); };
const st = n => JSON.parse(fs.readFileSync(`site/static/${n}.json`, "utf8"));
const stateFile = n => `data/state/${n}`;
const readState = (n, d) => { try { return JSON.parse(fs.readFileSync(stateFile(n), "utf8")); } catch { return d; } };

const league = await get(`${S1}/league/${LEAGUE}`), season = league.season;
const schedule = await get(`${S2}/schedule/nba/regular/${season}`);
const today = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const week = schedule.filter(g => g.week && g.date <= today).map(g => g.week).sort((a, b) => a - b).at(-1) || 1;
const [rosters, matchups, users, stats, proj, trending] = await Promise.all([
  get(`${S1}/league/${LEAGUE}/rosters`), get(`${S1}/league/${LEAGUE}/matchups/${week}`), get(`${S1}/league/${LEAGUE}/users`),
  get(`${S2}/stats/nba/${season}/${week}?season_type=regular`), get(`${S2}/projections/nba/${season}/${week}?season_type=regular`),
  get(`${S1}/players/nba/trending/add?lookback_hours=24&limit=50`).catch(() => [])]);
const userName = Object.fromEntries(users.map(u => [u.user_id, u.display_name]));

const backend = process.env.WORKER_URL ? await get(`${process.env.WORKER_URL}/state?season=${season}&week=${week}`).catch(() => ({})) : {};
const locks = { ...readState(`locks_w${week}.json`, {}), ...(backend.locks || {}) };
const ov = { ...readState("eligibility_overrides.json", {}), ...(backend.elig || {}) };
const snaps = { ...readState(`lineups_${season}_w${week}.json`, {}), ...(backend.lineups || {}) };
const tipsRaw = st("tips");

const ctxMap = (() => { try { return st("context"); } catch { return {}; } })();
const book = new Book({ scoring: league.scoring_settings, players: st("players"), priors: st("priors"), gamelog: st("gamelog").games,
  weights: st("experts").weights, ctx: ctxMap, usage: (() => { try { return st("usage"); } catch { return {}; } })(), avail: (() => { try { return st("availability"); } catch (e) { console.log("availability not loaded:", e.message); return null; } })() });
book.addStats(stats); book.addProjections(proj);
const mine = rosters.find(r => r.owner_id === USER), my = matchups.find(m => m.roster_id === mine.roster_id);
const slots = league.roster_positions.filter(s => s !== "BN" && s !== "IR");
const wp = new WeekPlan({ Q: st("quantiles"), book, schedule, week, today, rosterPositions: league.roster_positions,
  roster: mine, matchup: my, rosters, tips: tipsRaw, locks,
  elig: (p, d) => { const k = `${d}|${p}`; if (k in ov) return !!ov[k]; const s = snaps[k]; return s && s.frozen ? s.slot != null : null; } });
const opp = matchups.find(m => m.matchup_id === my.matchup_id && m.roster_id !== mine.roster_id);
const oppRoster = opp && rosters.find(r => r.roster_id === opp.roster_id);
const oppPlan = oppRoster ? new WeekPlan({ Q: st("quantiles"), book, schedule, week, today, rosterPositions: league.roster_positions,
  roster: oppRoster, matchup: opp, rosters, tips: tipsRaw, locks: {}, elig: eligFromSnaps(readState(`opp_lineups_${season}_w${week}.json`, {})) })
  .build({ humanLocks: (s => s.opponent_model_ready ? s.lock_rate_eligible : null)(readState("league_study.json", {})) }) : null;
const plan = wp.build({ opp: oppPlan ? { mean: oppPlan.outlook.mean, var: oppPlan.outlook.var } : null });
// never suggest dropping someone the plan is counting on: locked/kept games, today's starters and relief, next-up players
const protect = new Set([...(mine.reserve || []),
  ...plan.slots.filter(s => ["locked", "lock", "keep", "live", "confirm"].includes(s.action)).map(s => s.pid),
  ...plan.slots.flatMap(s => [s.today?.pid, s.today?.relief?.pid, s.later?.pid]).filter(Boolean)]);

const claims = (() => { try { return st("claims"); } catch { return { consensus: {} }; } })();
const fa = wp.waivers(trending, 40).list;
const valuer = new Valuer({ book, schedule, Q: st("quantiles"), rosterPositions: league.roster_positions, week, today, settings: league.settings, freeAgents: fa.map(x => x.pid) });
const adds = selectAdds(waiverMoves(wp, valuer, mine, fa, protect, 12), claims.consensus || {});
const trades = tradeIdeas(valuer, book, mine, rosters.filter(r => r.roster_id !== mine.roster_id), 10)
  .map(t => ({ ...t, partner: userName[t.owner_id] || `Team ${t.roster_id}`,
               giveNames: t.give.map(p => book.name(p)), getNames: t.get.map(p => book.name(p)) }));

// ---- short reasons from the AI model (cached per suggestion) ----
const cache = readState("reasons.json", {});
const fmtP = p => { const g = book.games[p] || [], avg = book.avg(p), pri = book.prior[p];
  return `${book.name(p)} (${book.team(p)}, ${book.pos(p).join("/")}, projection ${book.baseline(p).toFixed(1)} FP/G = ${g.length} games this season${avg != null ? ` at ${avg.toFixed(1)}` : ""} blended with ${pri != null ? `last season's ${pri.toFixed(1)}` : "preseason projections"}; last 3: ${g.slice(-3).map(x => x.fp).join("/") || "none"}${book.status(p) ? ", " + book.status(p) : ""})`; };
const items = [
  ...adds.map(m => ({ key: `add|${m.pid}|${m.drop}|${today}`, text: `WAIVER: add ${fmtP(m.pid)}; drop ${fmtP(m.drop)}. Gain: +${m.weekGain} locked pts this week, +${m.rosGain} per week after (${m.gain} total over the season). ${m.experts ? `Experts: ${Math.round(m.experts.bull_share * 100)}% bullish over ${m.experts.n} calls.` : ""} Sleeper adds last 24h: ${m.trend}.` })),
  ...trades.map(t => ({ key: `trade|${t.give.join("+")}|${t.get.join("+")}|${today}`, text: `TRADE with ${t.partner}: give ${t.give.map(fmtP).join(" + ")}; get ${t.get.map(fmtP).join(" + ")}. Our team +${t.dm.toFixed(1)}, theirs +${t.dt.toFixed(1)} locked pts per week for the rest of the season. Their lineup change: ${(t.theirFit || []).map(f => `${f.inName} takes their ${f.slot} spot from ${f.outName} (${f.gain >= 0 ? "+" : ""}${f.gain}/wk)`).join("; ") || "depth only"}. Ours: ${(t.myFit || []).map(f => `${f.inName} replaces ${f.outName} at ${f.slot} (${f.gain >= 0 ? "+" : ""}${f.gain}/wk)`).join("; ") || "depth only"}. Mention what it fixes for them.` })),
].filter(x => !cache[x.key]);

if (items.length && process.env.OPENROUTER_API_KEY) {
  const sys = "You write one-sentence reasons (max 25 words) for fantasy basketball moves in a 12-team head-to-head points league on Sleeper using Lock-In mode (each starter's weekly score is one game the manager locks; rebounds and assists are worth 2, steals/blocks 1.5, no turnover penalty, double-double +2, triple-double +3). Use only the numbers given. Early in the season the projection leans on last season, so a few hot or cold games matter less; say so when that's what drives the move. Reply as JSON: {\"reasons\": [{\"key\": \"...\", \"reason\": \"...\"}]}.";
  try {
    const r = await fetch("https://openrouter.ai/api/v1/chat/completions", { method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${process.env.OPENROUTER_API_KEY}`, "x-title": "Lock Desk" },
      body: JSON.stringify({ model: MODEL, temperature: 0.2, response_format: { type: "json_object" },
        messages: [{ role: "system", content: sys }, { role: "user", content: items.map(i => `key=${i.key}\n${i.text}`).join("\n\n") }] }) });
    const txt = (await r.json()).choices?.[0]?.message?.content || "{}";
    const parsed = JSON.parse(txt.match(/\{[\s\S]*\}/)?.[0] || "{}");
    for (const x of parsed.reasons || []) if (x.key && x.reason) cache[x.key] = x.reason.slice(0, 240);
  } catch (e) { console.error("reasoning failed:", e.message); }
}
const cutoff = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
for (const k of Object.keys(cache)) if (k.split("|").at(-1) < cutoff) delete cache[k];
fs.mkdirSync("data/state", { recursive: true });
fs.writeFileSync(stateFile("reasons.json"), JSON.stringify(cache));

const out = {
  generated: new Date().toISOString(), week,
  adds: adds.map(m => ({ pid: m.pid, name: m.name, team: m.team, pos: m.pos, fpg: m.fpg, left: m.left, trend: m.trend,
    drop: m.drop, dropName: m.dropName, gain: m.gain, weekGain: m.weekGain, rosGain: m.rosGain, bid: m.bid, experts: m.experts ? { bull_share: m.experts.bull_share, n: m.experts.n } : null,
    uncertain: [m.pid, m.drop].filter(p => book.avail?.players?.[p]?.uncertain).map(p => book.name(p)),
    reason: cache[`add|${m.pid}|${m.drop}|${today}`] || null })),
  trades: trades.map(t => ({ partner: t.partner, roster_id: t.roster_id, give: t.give, get: t.get, giveNames: t.giveNames, getNames: t.getNames,
    dm: Math.round(t.dm * 10) / 10, dt: Math.round(t.dt * 10) / 10, theirFit: t.theirFit, myFit: t.myFit,
    marketGive: Math.round(t.marketGive), marketGet: Math.round(t.marketGet),
    uncertain: [...t.give, ...t.get].filter(p => book.avail?.players?.[p]?.uncertain).map(p => book.name(p)),
    reason: cache[`trade|${t.give.join("+")}|${t.get.join("+")}|${today}`] || null })),
};
fs.writeFileSync("site/static/moves.json", JSON.stringify(out));
// the engine's plan, for phone alerts (app/alerts.py) — same numbers the site shows
fs.writeFileSync("site/static/plan.json", JSON.stringify({ week, generated: out.generated,
  slots: plan.slots, actions: plan.actions, lineup: plan.lineup, outlook: plan.outlook,
  oppName: oppRoster ? (userName[oppRoster.owner_id] || "Opponent") : null }));
// full plan snapshot on the state branch, for debugging what the engine saw
fs.writeFileSync(stateFile("plan_debug.json"), JSON.stringify({ at: new Date().toISOString(), today, week, expectedTotal: plan.expectedTotal,
  slots: plan.slots, actions: plan.actions, idle: plan.idle, outlook: plan.outlook, adds: out.adds, trades: out.trades,
  starters_debug: (my.starters || []).map(p => ({ pid: p, name: book.name(p), sleeper: my.players_points?.[p] ?? null, manualLock: locks[p] ?? null,
    state: wp.lockState(p), played: wp.played(p).map(g => [g.date, g.fp]) })),
  values: Object.fromEntries((mine.players || []).map(p => [book.name(p), Math.round(valuer.perWeek(p) * 10) / 10])),
  grid: plan.grid.map(r => ({ name: r.name, pos: r.pos, starter: r.starter, locked: r.locked, status: r.status, cells: r.cells })) }, null, 1));
console.log(`moves: ${out.adds.length} adds, ${out.trades.length} trades, ${items.length} new reasons requested`);
void playerValue;

// ---- valuation diagnostics (data/state/value_debug.json) ----
{
  const r1 = v => Math.round(v * 10) / 10;
  const row = p => ({ name: book.name(p), team: book.team(p), pos: book.pos(p).join("/"), status: book.status(p),
    perWeek: r1(valuer.perWeek(p)), market: r1(playerValue(book, p)), base: r1(book.baseline(p)), prior: book.prior[p] ?? null,
    avg: book.avg(p) != null ? r1(book.avg(p)) : null, games: book.done(p).length,
    avail: book.avail?.players?.[p] ? { basis: book.avail.players[p].basis, missed: book.avail.players[p].missed,
      next: Object.entries(book.avail.players[p].q).slice(0, 8).map(([d, q]) => `${d.slice(5)}:${q}`).join(" ") } : undefined });
  const rostered = rosters.flatMap(r => (r.players || []).map(p => ({ ...row(p), owner: userName[r.owner_id] || r.roster_id })));
  rostered.sort((a, b) => b.perWeek - a.perWeek);
  const faRows = fa.map(x => row(x.pid)).sort((a, b) => b.perWeek - a.perWeek);
  const teams = rosters.map(r => ({ owner: userName[r.owner_id] || r.roster_id, n: (r.players || []).length, value: r1(valuer.team(r.players || [])) }));
  fs.writeFileSync(stateFile("value_debug.json"), JSON.stringify({ at: new Date().toISOString(), discSum: valuer.discSum, weeks: valuer.weeks.length,
    size: valuer.size, teams, rostered, fa: faRows.slice(0, 40) }, null, 1));
}

// ---- win-chance calibration log (review validation plan 5; review 2, finding 6) ---------------------
// The win chance of EVERY matchup in the league, all from the same model (each team's plan, no matchup-aware calls,
// engine-perfect locks on both sides, ours included), logged once per matchup per stage of the week (tools/winprob.mjs)
// and graded when the week is final: does "70%" win 70% of the time? data/state/winprob_log.json
try {
  const log = readState("winprob_log.json", { open: {}, graded: [] });
  const Phi = z => 0.5 * (1 + Math.tanh(0.7978845608 * (z + 0.044715 * z ** 3)));
  const byMatch = {};
  for (const m of matchups) if (m.matchup_id != null) (byMatch[m.matchup_id] ||= []).push(m);
  const daysLeft = weekDays(schedule, week).filter(d => d >= today).length, stage = stageOf(daysLeft);
  for (const [mid, pair] of Object.entries(byMatch)) {
    const key = `${week}|${stage}|${mid}`;
    if (!stage || pair.length !== 2 || log.open[key]) continue;
    const out = pair.map(m => new WeekPlan({ Q: st("quantiles"), book, schedule, week, today, rosterPositions: league.roster_positions,
      roster: rosters.find(x => x.roster_id === m.roster_id), matchup: m, rosters, tips: tipsRaw, locks: {}, elig: () => true }).build().outlook);
    const p = Phi((out[0].mean - out[1].mean) / Math.sqrt(out[0].var + out[1].var + 1));
    log.open[key] = { week, mid, stage, day: today, days_left: daysLeft, a: pair[0].roster_id, b: pair[1].roster_id, p_a: Math.round(p * 1000) / 1000 };
  }
  // grade finished weeks (entries logged before stages existed are dropped: daily, two different models)
  for (const [k, x] of Object.entries(log.open)) if (!x.stage) delete log.open[k];
  log.graded = log.graded.filter(x => x.stage);
  for (const w of [...new Set(Object.values(log.open).map(x => x.week))].filter(w => w < week)) {
    const fin = await get(`${S1}/league/${LEAGUE}/matchups/${w}`);
    const pts = Object.fromEntries(fin.map(m => [m.roster_id, m.points]));
    for (const [k, x] of Object.entries(log.open)) if (x.week === w) {
      if (pts[x.a] != null && pts[x.b] != null && pts[x.a] !== pts[x.b]) log.graded.push({ ...x, a_won: pts[x.a] > pts[x.b] });
      delete log.open[k];
    }
  }
  log.calibration = calibration(log.graded);
  fs.writeFileSync(stateFile("winprob_log.json"), JSON.stringify(log));
  fs.writeFileSync("site/static/winprob.json", JSON.stringify(log.calibration));
} catch (e) { console.log("win-chance log failed:", e.message); }
