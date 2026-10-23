import { Book, WeekPlan, weekDays, teamGames, fits } from "./engine.js";

// ---- config -----------------------------------------------------------------------------------
const LEAGUE = "1400915575915491328", USER = "1388708038000533504";
const STATE = "https://raw.githubusercontent.com/rwalwan/fantasybasketball/state/";
const S1 = "https://api.sleeper.app/v1", S2 = "https://api.sleeper.com";
const ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=";
const ESPN_TEAM = { NY: "NYK", GS: "GSW", SA: "SAS", NO: "NOP", UTAH: "UTA", WSH: "WAS" };
const API = localStorage.getItem("lockdesk_api") || "";   // optional backend for saving locks/answers

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const r1 = v => (Math.round(v * 10) / 10).toFixed(1);
const day = d => new Date(d + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", day: "numeric" });
const tipTime = t => t ? new Date(t).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit" }) : "";
const until = t => { const m = Math.round((new Date(t) - Date.now()) / 60000); return m <= 0 ? "now" : m < 60 ? `${m} min` : `${Math.floor(m / 60)}h ${m % 60}m`; };
const etToday = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const get = async (url, opt = {}) => { const r = await fetch(url, { cache: "no-store", ...opt }); if (!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); };
const soft = url => get(url).catch(() => ({}));

// ---- local answers (until a backend is connected these live in this browser) --------------------
const local = { get: k => { try { return JSON.parse(localStorage.getItem(k) || "{}"); } catch { return {}; } },
                set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };
async function saveAnswer(kind, key, value) {
  const store = local.get(kind); store[key] = value; local.set(kind, store);
  if (API) fetch(`${API}/${kind}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key, value }) }).catch(() => {});
}

// ---- data ---------------------------------------------------------------------------------------
let base = null, live = null, tab = "locks";
async function loadBase() {
  const [Q, league, players, priors, gamelog, schedule, lg] = await Promise.all([
    get("static/quantiles.json"), get(`${S1}/league/${LEAGUE}`), get("static/players.json"), get("static/priors.json"),
    get("static/gamelog.json"), get(`${S2}/schedule/nba/regular/${new Date().getFullYear() - (new Date().getMonth() < 7 ? 1 : 0)}`),
    get(`${S1}/league/${LEAGUE}/users`)]);
  const today = etToday();
  const weeks = schedule.filter(g => g.week).map(g => [g.date, g.week]).sort();
  const week = (weeks.filter(([d]) => d <= today).at(-1) || weeks[0])[1];
  base = { Q: Q.quantiles, league, players, priors, gamelog, schedule, users: Object.fromEntries(lg.map(u => [u.user_id, u.display_name])), week };
}
async function loadLive() {
  const { week, league } = base, season = league.season;
  const days = weekDays(base.schedule, week), today = etToday();
  const tipDays = days.filter(d => d >= today || d === days.find(x => x >= today));
  const [rosters, matchups, stats, proj, trending, snaps, overrides, locks, ...espn] = await Promise.all([
    get(`${S1}/league/${LEAGUE}/rosters`), get(`${S1}/league/${LEAGUE}/matchups/${week}`),
    get(`${S2}/stats/nba/${season}/${week}?season_type=regular`), get(`${S2}/projections/nba/${season}/${week}?season_type=regular`),
    get(`${S1}/players/nba/trending/add?lookback_hours=24&limit=50`).catch(() => []),
    soft(`${STATE}lineups_${season}_w${week}.json`), soft(`${STATE}eligibility_overrides.json`), soft(`${STATE}locks_w${week}.json`),
    ...days.map(d => soft(ESPN + d.replace(/-/g, "")))]);
  const tips = {};
  espn.forEach((sb, i) => (sb.events || []).forEach(e => (e.competitions?.[0]?.competitors || []).forEach(c => {
    const a = c.team?.abbreviation; tips[`${days[i]}|${ESPN_TEAM[a] || a}`] = e.date; })));
  live = { rosters, matchups, stats, proj, trending, snaps, overrides, locks, tips, at: new Date() };
  void tipDays;
}

// ---- eligibility: was the player in a starting slot when that game tipped? ----------------------
function eligFn(starters) {
  const ov = { ...live.overrides, ...local.get("elig") };
  return (pid, date) => {
    const k = `${date}|${pid}`;
    if (k in ov) return !!ov[k];
    const s = live.snaps[k];
    if (s && (s.frozen || isTipped(pid, date))) return s.slot != null;
    return null;
  };
}
let bookRef = null;
const isTipped = (pid, date) => { const t = live.tips[`${date}|${bookRef?.team(pid)}`]; return t ? new Date(t) <= new Date() : date < etToday(); };

// ---- compute + render ---------------------------------------------------------------------------
function compute() {
  const book = new Book({ scoring: base.league.scoring_settings, players: base.players, priors: base.priors, gamelog: base.gamelog.games });
  bookRef = book;
  book.addStats(live.stats); book.addProjections(live.proj);
  const mine = live.rosters.find(r => r.owner_id === USER);
  const my = live.matchups.find(m => m.roster_id === mine.roster_id);
  const opp = live.matchups.find(m => m.matchup_id === my.matchup_id && m.roster_id !== mine.roster_id);
  const locks = { ...live.locks, ...local.get(`locks_w${base.week}`) };
  const wp = new WeekPlan({ Q: base.Q, book, schedule: base.schedule, week: base.week, today: etToday(), now: new Date(),
    rosterPositions: base.league.roster_positions, roster: mine, matchup: my, rosters: live.rosters, tips: live.tips,
    elig: eligFn(my.starters), locks });
  return { book, wp, plan: wp.build(), waivers: wp.waivers(live.trending), mine, my, opp };
}

const LABEL = { lock: "Lock", pass: "Pass", start: "Start", locked: "Locked", confirm: "Confirm", "fallback-risk": "Fallback" };
function render() {
  const c = compute(), { plan, my, opp, mine } = c;
  const oppOwner = live.rosters.find(r => r.roster_id === opp?.roster_id)?.owner_id;
  $("score").innerHTML = `<b>${r1((my.points || 0) / 10)}</b> – ${r1((opp?.points || 0) / 10)}<span>vs ${esc(base.users[oppOwner] || "opponent")} · FAAB $${base.league.settings.waiver_budget - (mine.settings?.waiver_budget_used || 0)}</span>`;
  $("metatext").textContent = `${base.league.name} · week ${base.week} · live ${live.at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;

  // what to do next, by deadline
  const todo = plan.slots.filter(s => ["lock", "confirm", "fallback-risk"].includes(s.action) || (s.action === "pass" && s.deadline))
    .map(s => ({ s, t: s.deadline?.tip })).sort((a, b) => (a.t || "z").localeCompare(b.t || "z"));
  const moves = plan.lineup.filter(x => x.move && x.pid);
  const first = todo.find(x => x.t);
  $("now").innerHTML = (first ? `<b>Next deadline:</b> <span class="when">${until(first.t)}</span> (${esc(tipTime(first.t))})` : "<b>No lock deadlines pending.</b>") +
    `<ul>${todo.filter(x => x.s.action !== "pass").map(x => `<li><b>${LABEL[x.s.action]}</b> ${esc(x.s.name)} (${esc(x.s.slot)})${x.s.score != null ? ` — ${r1(x.s.score)}` : ""}${x.t ? ` · before ${esc(tipTime(x.t))}` : ""}</li>`).join("")}` +
    `${moves.length ? `<li><b>Lineup:</b> ${moves.map(m => `${esc(m.name)} → ${esc(m.slot)}`).join(", ")}</li>` : ""}</ul>`;

  $("slots").innerHTML = plan.slots.map(s => {
    const nums = s.score != null ? `<div class="nums">game <b>${r1(s.score)}</b>${s.bar ? ` · bar ${r1(s.bar)}` : ""}${s.deadline ? ` · by ${esc(tipTime(s.deadline.tip) || day(s.deadline.date))}` : ""}</div>` : (s.bar ? `<div class="nums">lock bar after his next game: ${r1(s.bar)}</div>` : "");
    let acts = "";
    if (s.action === "confirm") acts = `<button data-elig="${s.gameDate}|${s.pid}" data-v="1">He was starting</button><button data-elig="${s.gameDate}|${s.pid}" data-v="0">He was on my bench</button>`;
    if (["lock", "pass", "confirm"].includes(s.action)) acts += `<button data-lock="${s.pid}">I locked this</button>`;
    if (s.action === "locked") acts = `<button data-unlock="${s.pid}">Undo</button>`;
    return `<div class="slot ${s.action}"><div class="top"><span><span class="pos">${esc(s.slot)}</span> <span class="nm">${esc(s.name)}</span>${s.status ? `<span class="st">${esc(s.status)}</span>` : ""}</span><span class="tag">${LABEL[s.action] || s.action}</span></div><p>${esc(s.detail)}</p>${nums}${acts ? `<div class="acts">${acts}</div>` : ""}</div>`;
  }).join("");

  $("lineup").innerHTML = plan.lineup.length ? plan.lineup.map(x => `<div class="row"><span><span class="pos">${esc(x.slot)}</span> ${x.move ? `<span class="mv">${esc(x.name)}</span>` : esc(x.name)}${x.tip ? ` <span class="pos">vs ${esc(x.opp)} · ${esc(tipTime(x.tip))}</span>` : ""}</span><span class="pos">${x.pid ? `worth ${r1(x.gain)}` : ""}</span></div>`).join("") +
    (plan.idle.length ? `<div class="row"><span class="pos">Also playing today, no open slot: ${plan.idle.map(x => esc(x.name)).join(", ")}</span></div>` : "")
    : `<div class="row"><span class="pos">Every slot is locked or decided.</span></div>`;

  const today = etToday();
  $("grid").innerHTML = `<tr><th>Player</th><th>Pos</th>${plan.days.map(d => `<th class="${d === today ? "today" : ""}">${day(d)}</th>`).join("")}<th>Left</th></tr>` +
    plan.grid.map(r => `<tr><td>${r.starter ? "" : '<span class="pos">BN </span>'}${esc(r.name)}${r.status ? `<span class="st">${esc(r.status)}</span>` : ""}${r.locked ? ' <span class="pos">🔒</span>' : ""}</td><td class="pos">${esc(r.pos)}</td>` +
      r.cells.map((x, i) => { const td = plan.days[i] === today ? " today" : "";
        if (!x) return `<td class="c${td}"></td>`;
        if (x.kind === "played") return `<td class="c played${x.started === false ? " bench" : ""}${td}" title="vs ${esc(x.opp)} · ${x.started === false ? "from your bench: not lockable" : x.started ? "in your lineup" : "lineup at tip unknown"}">${r1(x.fp)}${x.started == null ? "?" : ""}</td>`;
        if (x.kind === "live") return `<td class="c livec${td}" title="in progress or awaiting stats">live</td>`;
        return `<td class="c up${td}" title="vs ${esc(x.opp)}${x.tip ? " · " + esc(tipTime(x.tip)) : ""}">${Math.round(x.mu)}</td>`; }).join("") + `<td class="n">${r.left}</td></tr>`).join("");

  const w = c.waivers;
  $("waivers").innerHTML = `<tr><th>Player</th><th>Team</th><th>Pos</th><th>FP/G</th><th>vs your worst (${r1(w.worst)})</th><th>Games left</th><th>Last 3</th><th>Adds 24h</th><th>Bid</th></tr>` +
    w.list.map(x => `<tr><td>${esc(x.name)}${x.status ? `<span class="st">${esc(x.status)}</span>` : ""}</td><td>${esc(x.team)}</td><td class="pos">${esc(x.pos)}</td><td class="n">${r1(x.fpg)}</td><td class="n">${x.over > 0 ? "+" : ""}${r1(x.over)}</td><td class="n">${x.left}</td><td class="n">${x.recent.map(r1).join(" / ") || "–"}</td><td class="n">${x.trend.toLocaleString()}</td><td class="n">$${x.bid}</td></tr>`).join("");

  renderTrades(c);
  $("foot").textContent = `Recomputed every minute from Sleeper and ESPN. A game is lockable only if he was starting when it tipped; lineups are recorded by the scheduled job (every 15 min) and by this page while it's open. Answers you give here are saved in this browser${API ? " and to your backend" : ""}.`;
  $("dot").classList.toggle("stale", Date.now() - live.at > 5 * 60000);
}

// ---- trade assistant ------------------------------------------------------------------------------
function playerValue(book, pid) {
  const g = book.games[pid] || [], base = book.baseline(pid);
  let cv = 0.3;
  if (g.length >= 5) { const m = g.reduce((a, x) => a + x.fp, 0) / g.length, sd = Math.sqrt(g.reduce((a, x) => a + (x.fp - m) ** 2, 0) / g.length); cv = Math.min(0.5, Math.max(0.15, sd / Math.max(m, 1))); }
  const out = ["Out", "IR", "Suspended"].includes(book.status(pid)) ? 0.6 : 1;
  return base * (1 + 0.7 * cv) * 0.86 * out;     // locked points per week: best-of-~3.5 games, ~14% miss rate
}
function teamValue(book, players, slots) {
  const vals = players.map(p => ({ p, v: playerValue(book, p) })).sort((a, b) => b.v - a.v);
  const used = new Set(); let total = 0;
  const order = [...slots].sort((a, b) => vals.filter(x => fits(a, book.pos(x.p))).length - vals.filter(x => fits(b, book.pos(x.p))).length);
  for (const s of order) { const x = vals.find(x => !used.has(x.p) && fits(s, book.pos(x.p))); if (x) { used.add(x.p); total += x.v; } }
  const bench = vals.filter(x => !used.has(x.p)).slice(0, 3).reduce((a, x) => a + x.v, 0);
  return total + 0.12 * bench;   // bench depth = extra lock options
}
let tradeSel = { give: new Set(), get: new Set(), partner: null };
function renderTrades(c) {
  const { book, mine } = c, slots = base.league.roster_positions.filter(s => s !== "BN" && s !== "IR");
  const others = live.rosters.filter(r => r.roster_id !== mine.roster_id);
  const sel = $("partner");
  if (!sel.options.length) {
    sel.innerHTML = others.map(r => `<option value="${r.roster_id}">${esc(base.users[r.owner_id] || "Team " + r.roster_id)}</option>`).join("");
    sel.onchange = () => { tradeSel = { give: new Set(), get: new Set(), partner: +sel.value }; render(); };
  }
  tradeSel.partner ||= +sel.value;
  const them = others.find(r => r.roster_id === tradeSel.partner);
  const list = (r, side) => `<h3>${side === "give" ? "You give" : "You get"}</h3>` + [...(r.players || [])].sort((a, b) => playerValue(book, b) - playerValue(book, a))
    .map(p => `<label><input type="checkbox" data-side="${side}" value="${p}" ${tradeSel[side].has(p) ? "checked" : ""}>${esc(book.name(p))} <span class="pos">${esc(book.pos(p).join("/"))}</span><span class="v">${r1(playerValue(book, p))}</span></label>`).join("");
  $("give").innerHTML = list(mine, "give"); $("get").innerHTML = list(them, "get");
  document.querySelectorAll("input[data-side]").forEach(el => el.onchange = () => { tradeSel[el.dataset.side][el.checked ? "add" : "delete"](el.value); render(); });
  const swap = (roster, out, inn) => roster.filter(p => !out.has(p)).concat([...inn]);
  const myB = teamValue(book, mine.players, slots), thB = teamValue(book, them.players, slots);
  if (tradeSel.give.size || tradeSel.get.size) {
    const myA = teamValue(book, swap(mine.players, tradeSel.give, tradeSel.get), slots), thA = teamValue(book, swap(them.players, tradeSel.get, tradeSel.give), slots);
    const dm = myA - myB, dt = thA - thB;
    $("verdict").innerHTML = `Your team: <b class="${dm >= 0 ? "good" : "bad"}">${dm >= 0 ? "+" : ""}${r1(dm)}</b> locked pts/week · theirs: <b class="${dt >= 0 ? "good" : "bad"}">${dt >= 0 ? "+" : ""}${r1(dt)}</b>. ` +
      (dm > 0 && dt >= 0 ? "Helps both of you — a realistic offer." : dm > 0 ? "Good for you, but they lose value, so expect pushback." : "This makes your team worse.");
  } else $("verdict").textContent = "";
  // ideas: 1-for-1 and 2-for-1 across the league that help you and don't hurt them
  if (!renderTrades.cache || renderTrades.cache.at !== live.at) {
    const ideas = [];
    for (const r of others) {
      const tb = teamValue(book, r.players, slots);
      const mp = mine.players, tp = r.players;
      for (const a of mp) for (const b of tp) {
        const dm = teamValue(book, swap(mp, new Set([a]), new Set([b])), slots) - myB;
        if (dm <= 0.5) continue;
        const dt = teamValue(book, swap(tp, new Set([b]), new Set([a])), slots) - tb;
        if (dt >= 0) ideas.push({ give: [a], get: [b], dm, dt, r });
      }
      for (let i = 0; i < mp.length; i++) for (let j = i + 1; j < mp.length; j++) for (const b of tp) {
        const give = new Set([mp[i], mp[j]]);
        const dm = teamValue(book, swap(mp, give, new Set([b])), slots) - myB;
        if (dm <= 0.5) continue;
        const dt = teamValue(book, swap(tp, new Set([b]), give), slots) - tb;
        if (dt >= 0) ideas.push({ give: [...give], get: [b], dm, dt, r });
      }
    }
    ideas.sort((x, y) => (y.dm + 0.5 * y.dt) - (x.dm + 0.5 * x.dt));
    renderTrades.cache = { at: live.at, ideas: ideas.slice(0, 15) };
  }
  $("ideas").innerHTML = `<tr><th>With</th><th>You give</th><th>You get</th><th>You</th><th>Them</th></tr>` +
    renderTrades.cache.ideas.map(x => `<tr><td>${esc(base.users[x.r.owner_id] || "Team " + x.r.roster_id)}</td><td>${x.give.map(p => esc(book.name(p))).join(" + ")}</td><td>${x.get.map(p => esc(book.name(p))).join(" + ")}</td><td class="n good">+${r1(x.dm)}</td><td class="n">+${r1(x.dt)}</td></tr>`).join("") ||
    `<tr><td colspan="5" class="pos">No trades found that help both sides right now.</td></tr>`;
}

// ---- events + loop --------------------------------------------------------------------------------
document.addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.t) { tab = b.dataset.t; document.querySelectorAll("#tabs button").forEach(x => x.classList.toggle("on", x === b)); document.querySelectorAll("section[data-p]").forEach(s => s.classList.toggle("hide", s.dataset.p !== tab)); return; }
  if (b.dataset.elig) { saveAnswer("elig", b.dataset.elig, b.dataset.v === "1"); render(); }
  if (b.dataset.lock) { saveAnswer(`locks_w${base.week}`, b.dataset.lock, true); render(); }
  if (b.dataset.unlock) { saveAnswer(`locks_w${base.week}`, b.dataset.unlock, false); render(); }
});

async function tick(full) {
  try { if (full || !base) await loadBase(); await loadLive(); render(); }
  catch (err) { $("now").textContent = "Couldn't load live data: " + err.message; $("dot").classList.add("stale"); }
}
tick(true);
setInterval(() => tick(false), 60000);           // live data every minute
setInterval(() => tick(true), 30 * 60000);       // game logs / priors every 30 minutes
setInterval(() => { if (live) render(); }, 30000); // countdowns
