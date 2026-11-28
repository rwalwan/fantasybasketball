// Lock Desk backend — Cloudflare Worker + KV (free plan).
//
// 1) Four times a minute: record who is in each starting slot of Ryan's team AND his opponent's for every game that
//    hasn't tipped, freeze that record at tip-off, and note any trip to the bench after tip (worker/src/lineup.js).
//    This is what makes a game lock-eligible in Lock-In mode.
// 2) Stores the answers and lock marks made on the site so phone and laptop agree.
// 3) Sleeper's own lock record; 4) the last-minute injury watch (both below).
//
// Kept deliberately light (free-plan CPU budget): one small Sleeper call per sample; ESPN tip times
// and the player->team map are fetched once a day and cached in KV.

import { sampleLineups } from "./lineup.js";
import { watchInjuries } from "./injuries.js";

const LEAGUE = "1400915575915491328", USER = "1388708038000533504";
const S1 = "https://api.sleeper.app/v1";
const SITE = "https://rwalwan.github.io/fantasybasketball";
const ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=";
const ESPN_INJ = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries";
const ESPN_TEAM = { NY: "NYK", GS: "GSW", SA: "SAS", NO: "NOP", UTAH: "UTA", WSH: "WAS" };

const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: { "content-type": "application/json", "access-control-allow-origin": "*",
                     "access-control-allow-headers": "content-type,x-key", "access-control-allow-methods": "GET,POST,OPTIONS",
                     "cache-control": "no-store" } });
const etDate = (d = new Date()) => d.toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const getJSON = async url => { const r = await fetch(url, { headers: { "user-agent": "we-back-lock-desk" } }); if (!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); };
const kvGet = async (env, k, dflt) => (await env.KV.get(k, "json")) ?? dflt;

async function dayInfo(env, date) {
  const key = `day_${date}`;
  let info = await kvGet(env, key, null);
  if (info?.names) return info;                     // (a day cached before Nov 28 has no names: build it again once)
  const [state, players, sb] = await Promise.all([getJSON(`${S1}/state/nba`), getJSON(`${SITE}/static/players.json`),
                                                  getJSON(ESPN + date.replace(/-/g, ""))]);
  const tips = {};
  for (const e of sb.events || []) for (const c of e.competitions?.[0]?.competitors || []) {
    const a = c.team?.abbreviation; tips[ESPN_TEAM[a] || a] = e.date;
  }
  const team = Object.fromEntries(Object.entries(players).map(([pid, v]) => [pid, v[1]]));
  const names = Object.fromEntries(Object.entries(players).map(([pid, v]) => [pid, v[0]]));   // injury watch: name -> pid
  info = { week: state.week, season: state.season, tips, team, names };
  await env.KV.put(key, JSON.stringify(info), { expirationTtl: 3 * 86400 });
  return info;
}

// Nov 26: lineups come from Sleeper's own scoring lineup (matchup_legs_raw: public, a POST, so never a stale CDN copy),
// sampled four times a minute for both teams. The once-a-minute REST read missed Cam Spencer's bench trip (and the
// opponent's lineup was only seen by the 15-minute job). REST, cache-busted, is the fallback if the GraphQL call fails.
async function fetchLegs(week) {
  try {
    const r = await fetch("https://api.sleeper.app/graphql", { method: "POST",
      headers: { "content-type": "application/json", accept: "application/json", "user-agent": "we-back-lock-desk" },
      body: JSON.stringify({ query: `query { matchup_legs_raw(league_id: "${LEAGUE}", round: ${Number(week)}) { roster_id matchup_id starters players } }` }) });
    const legs = (await r.json().catch(() => null))?.data?.matchup_legs_raw;
    if (r.ok && Array.isArray(legs) && legs.length) return legs;
  } catch {}
  return getJSON(`${S1}/league/${LEAGUE}/matchups/${week}?_=${Date.now()}`);
}

async function snapshot(env) {
  const date = etDate();
  const info = await dayInfo(env, date);
  // no early return on days without games (Thanksgiving, Nov 26): a bench trip on an off day still voids that week's
  // earlier games, and only a sample can see it
  const league = await kvGet(env, "league", null) || await (async () => {
    const lg = await getJSON(`${S1}/league/${LEAGUE}`);
    const v = { slots: lg.roster_positions.filter(s => s !== "BN" && s !== "IR") };
    await env.KV.put("league", JSON.stringify(v), { expirationTtl: 86400 }); return v; })();
  let me = await kvGet(env, "my_roster", null);
  if (!me) {
    const rosters = await getJSON(`${S1}/league/${LEAGUE}/rosters`);
    me = { roster_id: rosters.find(r => r.owner_id === USER).roster_id };
    await env.KV.put("my_roster", JSON.stringify(me), { expirationTtl: 7 * 86400 });
  }
  const keyMine = `lineups_${info.season}_w${info.week}`, keyOpp = `opp_lineups_${info.season}_w${info.week}`;
  const [mine, opp] = await Promise.all([kvGet(env, keyMine, {}), kvGet(env, keyOpp, {})]);
  // KV free plan = 1,000 writes/day: a record set is written only after a sample that changed it (lineup moves, tips).
  const res = await sampleLineups({ fetchLegs: () => fetchLegs(info.week), rosterId: me.roster_id, slots: league.slots,
                                    tips: info.tips, team: info.team, date, mine, opp,
                                    save: async c => { if (c.mine) await env.KV.put(keyMine, JSON.stringify(mine));
                                                       if (c.opp) await env.KV.put(keyOpp, JSON.stringify(opp)); } });
  return { date, ...res };
}

// GitHub throttles scheduled workflows on free repos (runs can be hours apart), so the Worker's reliable
// minute cron kicks the workflow every 15 minutes instead. Needs the GH_TOKEN secret (fine-grained PAT,
// this repo only, Actions: read & write).
// 3) Every minute: Sleeper's own lock record for every team, from the app's GraphQL query get_matchup_legs
//    (starters_games = each starter's locked game id). It needs Ryan's Sleeper login, stored as the SLEEPER_TOKEN
//    secret (never in the repo). KV is written only when the locks or the status change.
const LEGS_Q = "query get_matchup_legs($leagueId: String!, $round: Int!) { matchup_legs(league_id: $leagueId, round: $round) { roster_id matchup_id starters starters_games } }";
async function legsFor(env, round) {
  const r = await fetch("https://api.sleeper.app/graphql", { method: "POST",
    headers: { "content-type": "application/json", accept: "application/json", authorization: env.SLEEPER_TOKEN, "user-agent": "we-back-lock-desk" },
    body: JSON.stringify({ operationName: "get_matchup_legs", query: LEGS_Q, variables: { leagueId: LEAGUE, round } }) });
  const j = await r.json().catch(() => null);
  const legs = j?.data?.matchup_legs;
  if (!r.ok || !Array.isArray(legs)) throw new Error(j?.errors?.[0]?.message || `HTTP ${r.status}`);
  return legs;
}
// Nov 27: the same record is in the public matchup_legs_raw query (no login). Checked against the logged-in record for
// all 12 teams, weeks 5 and 6: 112 of 112 locks identical (lock_source_check.json keeps checking every 15 minutes).
// So when the token is missing or rejected, the public record is used instead of falling back to guessing locks from
// slot points (which mid-week show the latest game, not the locked one).
async function publicLegsFor(round) {
  const r = await fetch("https://api.sleeper.app/graphql", { method: "POST",
    headers: { "content-type": "application/json", accept: "application/json", "user-agent": "we-back-lock-desk" },
    body: JSON.stringify({ query: `query { matchup_legs_raw(league_id: "${LEAGUE}", round: ${Number(round)}) { roster_id matchup_id starters starters_games } }` }) });
  const legs = (await r.json().catch(() => null))?.data?.matchup_legs_raw;
  if (!r.ok || !Array.isArray(legs)) throw new Error(`public record: HTTP ${r.status}`);
  return legs;
}
// Sleeper's state week can lag the matchup week the site and job use (Nov 16: the site asked for week 5 while the
// record was filed under Sleeper's week), so the weeks either side are read too; each is stored under its own week.
async function sleeperLocks(env) {
  const info = await dayInfo(env, etDate());
  const w0 = Number(info.week), out = {};
  let status = "ok", source = env.SLEEPER_TOKEN ? "login" : "public", loginErr = env.SLEEPER_TOKEN ? null : "no SLEEPER_TOKEN secret on the worker";
  for (const w of [w0 - 1, w0, w0 + 1].filter(w => w >= 1)) {
    try {
      let legs;
      if (source === "login") {
        try { legs = await legsFor(env, w); }
        catch (e) { loginErr = String(e.message || e).slice(0, 80); source = "public"; }
      }
      if (source === "public") legs = await publicLegsFor(w);
      if (!legs.length) continue;                                    // no matchups that week
      const teams = Object.fromEntries(legs.map(l => [String(l.roster_id), l.starters_games || {}]));
      const key = `sleeper_locks_${info.season}_w${w}`, prev = await kvGet(env, key, null);
      if (JSON.stringify(teams) !== JSON.stringify(prev?.teams))
        await env.KV.put(key, JSON.stringify({ teams, changed: new Date().toISOString(), status: "ok" }), { expirationTtl: 60 * 86400 });
      out[w] = Object.keys(teams).length;
    } catch (e) { status = String(e.message || e).slice(0, 120); break; }
  }
  // status stays "ok" (the engine's switch) while either source works; source and the login error are reported beside it
  const st = await kvGet(env, "sleeper_locks_status", null);
  if (!st || st.status !== status || st.source !== source || st.login_error !== loginErr)
    await env.KV.put("sleeper_locks_status", JSON.stringify({ status, source, login_error: loginErr, since: new Date().toISOString() }));
  return { status, source, login_error: loginErr, weeks: out };
}

// 4) Every minute in the two hours before a tip: ESPN's injury report for the teams about to play (worker/src/injuries.js).
//    A status change is saved (KV injuries_<date>, only on a change) and starts the update job at once (Nov 28).
async function injuryWatch(env) {
  const date = etDate(), info = await dayInfo(env, date), key = `injuries_${date}`;
  const players = Object.fromEntries(Object.entries(info.team || {}).map(([pid, t]) => [pid, [info.names?.[pid] || "", t]]));
  return watchInjuries({ fetchInjuries: () => getJSON(ESPN_INJ), tips: info.tips, now: new Date(), players,
    prev: await kvGet(env, key, {}), save: v => env.KV.put(key, JSON.stringify(v), { expirationTtl: 3 * 86400 }),
    kick: () => kickWorkflow(env) });
}

async function kickWorkflow(env) {
  let result;
  if (!env.GH_TOKEN) result = { ok: false, status: "no GH_TOKEN secret on the worker" };
  else {
    try {
      const r = await fetch("https://api.github.com/repos/rwalwan/fantasybasketball/actions/workflows/update.yml/dispatches", {
        method: "POST", body: JSON.stringify({ ref: "main" }),
        headers: { authorization: `Bearer ${env.GH_TOKEN}`, accept: "application/vnd.github+json",
                   "x-github-api-version": "2022-11-28", "user-agent": "lock-desk-worker" } });
      result = { ok: r.status === 204, status: r.status, body: r.status === 204 ? "" : (await r.text()).slice(0, 200) };
    } catch (e) { result = { ok: false, status: "fetch error", body: e.message }; }
  }
  // record the outcome only when it changes (keeps KV writes tiny)
  const prev = await kvGet(env, "kick", null);
  if (!prev || prev.status !== result.status) await env.KV.put("kick", JSON.stringify({ ...result, at: new Date().toISOString() })).catch(() => {});
  return result;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(snapshot(env).catch(e => console.log("snapshot failed", e.message)));
    ctx.waitUntil(sleeperLocks(env).catch(e => console.log("sleeper locks failed", e.message)));
    ctx.waitUntil(injuryWatch(env).catch(e => console.log("injury watch failed", e.message)));
    if (new Date(event.scheduledTime).getUTCMinutes() % 15 === 0) ctx.waitUntil(kickWorkflow(env).catch(() => {}));
  },

  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return json({});
    if (url.pathname === "/state") {
      const season = url.searchParams.get("season"), week = url.searchParams.get("week");
      const [elig, locks, lineups, oppLineups] = await Promise.all([kvGet(env, "elig", {}), kvGet(env, `locks_w${week}`, {}),
        kvGet(env, `lineups_${season}_w${week}`, {}), kvGet(env, `opp_lineups_${season}_w${week}`, {})]);
      const [kick, injuries] = await Promise.all([kvGet(env, "kick", null), kvGet(env, `injuries_${etDate()}`, null)]);
      // Sleeper's lock record: usable only while the token works (status ok); the site and job fall back otherwise
      const [sl, slStatus] = await Promise.all([kvGet(env, `sleeper_locks_${season}_w${week}`, null), kvGet(env, "sleeper_locks_status", null)]);
      const sleeperLocks = sl ? { ...sl, status: slStatus?.status || sl.status, source: slStatus?.source || "login", since: slStatus?.since || null } : (slStatus ? { teams: null, ...slStatus } : null);
      return json({ ok: true, elig, locks, lineups, oppLineups, kick, sleeperLocks, injuries, now: new Date().toISOString() });
    }
    if (url.pathname === "/answer" && req.method === "POST") {
      if (req.headers.get("x-key") !== env.WRITE_KEY) return json({ error: "bad key" }, 401);
      const { kind, week, key, value } = await req.json();
      const name = kind === "elig" ? "elig" : kind === "locks" ? `locks_w${Number(week)}` : null;
      if (!name || typeof key !== "string" || key.length > 64) return json({ error: "bad request" }, 400);
      const cur = await kvGet(env, name, {});
      if (cur[key] === !!value) return json({ ok: true, unchanged: true });   // don't spend a write
      cur[key] = !!value;
      try { await env.KV.put(name, JSON.stringify(cur)); } catch (e) { return json({ error: "storage limit reached", detail: e.message }, 503); }
      return json({ ok: true });
    }
    if (url.pathname === "/run") {                                    // manual trigger / health check: key required
      if (req.headers.get("x-key") !== env.WRITE_KEY) return json({ error: "bad key" }, 401);
      return json({ snapshot: await snapshot(env), sleeperLocks: await sleeperLocks(env), injuries: await injuryWatch(env) });
    }
    if (url.pathname === "/kick" && req.headers.get("x-key") === env.WRITE_KEY) return json(await kickWorkflow(env));
    return json({ service: "lock-desk", ok: true });
  },
};
