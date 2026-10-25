// Lock Desk backend — Cloudflare Worker + KV (free plan).
//
// 1) Every minute: record who is in each of Ryan's starting slots for every game that hasn't tipped,
//    and freeze that record at tip-off. This is what makes a game lock-eligible in Lock-In mode.
// 2) Stores the answers and lock marks made on the site so phone and laptop agree.
//
// Kept deliberately light (free-plan CPU budget): one small Sleeper call per minute; ESPN tip times
// and the player->team map are fetched once a day and cached in KV.

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

async function snapshot(env) {
  const now = new Date(), date = etDate(now);
  const info = await dayInfo(env, date);
  if (!Object.keys(info.tips).length) return { date, games: 0 };
  const [rosters, matchups] = await Promise.all([getJSON(`${S1}/league/${LEAGUE}/rosters`),
                                                 getJSON(`${S1}/league/${LEAGUE}/matchups/${info.week}`)]);
  const mine = rosters.find(r => r.owner_id === USER);
  const my = matchups.find(m => m.roster_id === mine.roster_id);
  const league = await kvGet(env, "league", null) || await (async () => {
    const lg = await getJSON(`${S1}/league/${LEAGUE}`);
    const v = { slots: lg.roster_positions.filter(s => s !== "BN" && s !== "IR") };
    await env.KV.put("league", JSON.stringify(v), { expirationTtl: 86400 }); return v; })();
  const slotOf = {}; (my.starters || []).forEach((p, i) => { if (p && p !== "0") slotOf[p] = league.slots[i]; });

  const key = `lineups_${info.season}_w${info.week}`;
  const snaps = await kvGet(env, key, {});
  let changed = false;
  const stamp = now.toISOString().slice(0, 16) + "Z";
  for (const pid of mine.players || []) {
    const tip = info.tips[info.team[pid]];
    if (!tip) continue;                                   // no game today
    const k = `${date}|${pid}`, cur = snaps[k];
    if (cur?.frozen) continue;
    if (new Date(tip) <= now) {                           // tipped: freeze last pre-tip record
      if (cur) { cur.frozen = true; changed = true; }
      continue;
    }
    const slot = slotOf[pid] ?? null;
    if (!cur || cur.slot !== slot) { snaps[k] = { slot, seen: stamp, frozen: false }; changed = true; }
  }
  // KV free plan = 1,000 writes/day. Only write when a lineup actually changes (~10-40 writes on a game day).
  if (changed) await env.KV.put(key, JSON.stringify(snaps));
  return { date, changed };
}

// GitHub throttles scheduled workflows on free repos (runs can be hours apart), so the Worker's reliable
// minute cron kicks the workflow every 15 minutes instead. Needs the GH_TOKEN secret (fine-grained PAT,
// this repo only, Actions: read & write).
async function kickWorkflow(env) {
  if (!env.GH_TOKEN) return;
  await fetch("https://api.github.com/repos/rwalwan/fantasybasketball/actions/workflows/update.yml/dispatches", {
    method: "POST", body: JSON.stringify({ ref: "main" }),
    headers: { authorization: `Bearer ${env.GH_TOKEN}`, accept: "application/vnd.github+json", "user-agent": "lock-desk-worker" } });
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(snapshot(env).catch(e => console.log("snapshot failed", e.message)));
    if (new Date(event.scheduledTime).getUTCMinutes() % 15 === 0) ctx.waitUntil(kickWorkflow(env).catch(() => {}));
  },

  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return json({});
    if (url.pathname === "/state") {
      const season = url.searchParams.get("season"), week = url.searchParams.get("week");
      const [elig, locks, lineups] = await Promise.all([kvGet(env, "elig", {}), kvGet(env, `locks_w${week}`, {}),
        kvGet(env, `lineups_${season}_w${week}`, {})]);
      return json({ ok: true, elig, locks, lineups, now: new Date().toISOString() });
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
    if (url.pathname === "/run") return json(await snapshot(env));   // manual trigger / health check
    return json({ service: "lock-desk", ok: true });
  },
};
