// Lock Desk backend — Cloudflare Worker + KV (free plan).
//
// 1) Four times a minute: record who is in each starting slot of Ryan's team AND his opponent's for every game that
//    hasn't tipped, freeze that record at tip-off, and note any trip to the bench after tip (worker/src/lineup.js).
//    This is what makes a game lock-eligible in Lock-In mode.
// 2) Stores the answers and lock marks made on the site so phone and laptop agree.
//
// Kept deliberately light (free-plan CPU budget): one small Sleeper call per sample; ESPN tip times
// and the player->team map are fetched once a day and cached in KV.

import { sampleLineups } from "./lineup.js";

const LEAGUE = "1400915575915491328", USER = "1388708038000533504";
const S1 = "https://api.sleeper.app/v1";
const SITE = "https://rwalwan.github.io/fantasybasketball";
const ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=";
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
  if (info) return info;
  const [state, players, sb] = await Promise.all([getJSON(`${S1}/state/nba`), getJSON(`${SITE}/static/players.json`),
                                                  getJSON(ESPN + date.replace(/-/g, ""))]);
  const tips = {};
  for (const e of sb.events || []) for (const c of e.competitions?.[0]?.competitors || []) {
    const a = c.team?.abbreviation; tips[ESPN_TEAM[a] || a] = e.date;
  }
  const team = Object.fromEntries(Object.entries(players).map(([pid, v]) => [pid, v[1]]));
  info = { week: state.week, season: state.season, tips, team };
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
  if (!Object.keys(info.tips).length) return { date, games: 0 };
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
// Sleeper's state week can lag the matchup week the site and job use (Nov 16: the site asked for week 5 while the
// record was filed under Sleeper's week), so the weeks either side are read too; each is stored under its own week.
async function sleeperLocks(env) {
  const info = await dayInfo(env, etDate());
  const w0 = Number(info.week), out = {};
  let status = "ok";
  if (!env.SLEEPER_TOKEN) status = "no SLEEPER_TOKEN secret on the worker";
  else for (const w of [w0 - 1, w0, w0 + 1].filter(w => w >= 1)) {
    try {
      const legs = await legsFor(env, w);
      if (!legs.length) continue;                                    // no matchups that week
      const teams = Object.fromEntries(legs.map(l => [String(l.roster_id), l.starters_games || {}]));
      const key = `sleeper_locks_${info.season}_w${w}`, prev = await kvGet(env, key, null);
      if (JSON.stringify(teams) !== JSON.stringify(prev?.teams))
        await env.KV.put(key, JSON.stringify({ teams, changed: new Date().toISOString(), status: "ok" }), { expirationTtl: 60 * 86400 });
      out[w] = Object.keys(teams).length;
    } catch (e) { status = String(e.message || e).slice(0, 120); break; }
  }
  const st = await kvGet(env, "sleeper_locks_status", null);
  if (!st || st.status !== status) await env.KV.put("sleeper_locks_status", JSON.stringify({ status, since: new Date().toISOString() }));
  return { status, weeks: out };
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
    if (new Date(event.scheduledTime).getUTCMinutes() % 15 === 0) ctx.waitUntil(kickWorkflow(env).catch(() => {}));
  },

  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return json({});
    if (url.pathname === "/state") {
      const season = url.searchParams.get("season"), week = url.searchParams.get("week");
      const [elig, locks, lineups, oppLineups] = await Promise.all([kvGet(env, "elig", {}), kvGet(env, `locks_w${week}`, {}),
        kvGet(env, `lineups_${season}_w${week}`, {}), kvGet(env, `opp_lineups_${season}_w${week}`, {})]);
      const kick = await kvGet(env, "kick", null);
      // Sleeper's lock record: usable only while the token works (status ok); the site and job fall back otherwise
      const [sl, slStatus] = await Promise.all([kvGet(env, `sleeper_locks_${season}_w${week}`, null), kvGet(env, "sleeper_locks_status", null)]);
      const sleeperLocks = sl ? { ...sl, status: slStatus?.status || sl.status, since: slStatus?.since || null } : (slStatus ? { teams: null, ...slStatus } : null);
      return json({ ok: true, elig, locks, lineups, oppLineups, kick, sleeperLocks, now: new Date().toISOString() });
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
      return json({ snapshot: await snapshot(env), sleeperLocks: await sleeperLocks(env) });
    }
    if (url.pathname === "/kick" && req.headers.get("x-key") === env.WRITE_KEY) return json(await kickWorkflow(env));
    return json({ service: "lock-desk", ok: true });
  },
};
