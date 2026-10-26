import { Book, WeekPlan, Valuer, waiverMoves, weekDays, teamGames, fits, range80 } from "./engine.js";

// ---- config -----------------------------------------------------------------------------------
const LEAGUE = "1400915575915491328", USER = "1388708038000533504";
const STATE = "https://raw.githubusercontent.com/rwalwan/fantasybasketball/state/";
const S1 = "https://api.sleeper.app/v1", S2 = "https://api.sleeper.com";
const ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=";
const ESPN_TEAM = { NY: "NYK", GS: "GSW", SA: "SAS", NO: "NOP", UTAH: "UTA", WSH: "WAS" };
// Backend (Cloudflare Worker). One-time setup per device: open the site with #api=<url>&key=<write key>.
(() => { const h = new URLSearchParams(location.hash.slice(1));
  if (h.get("api")) { try { localStorage.setItem("lockdesk_api", h.get("api")); localStorage.setItem("lockdesk_key", h.get("key") || ""); } catch {}
    history.replaceState(null, "", location.pathname); } })();
const API = (() => { try { return localStorage.getItem("lockdesk_api") || ""; } catch { return ""; } })();
const KEY = (() => { try { return localStorage.getItem("lockdesk_key") || ""; } catch { return ""; } })();

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const r1 = v => (Math.round(v * 10) / 10).toFixed(1);
const day = d => new Date(d + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", day: "numeric" });
const tipTime = t => t ? new Date(t).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit" }) : "";
const until = t => { const m = Math.round((new Date(t) - Date.now()) / 60000); return m <= 0 ? "now" : m < 60 ? `${m} min` : `${Math.floor(m / 60)}h ${m % 60}m`; };
const etToday = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const get = async (url, opt = {}) => { const r = await fetch(url, { cache: "no-store", ...opt }); if (!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); };
const soft = url => get(url).catch(() => ({}));
// ESPN rejects CORS preflights, and cache:"no-store" makes Chrome add headers that trigger one.
// So scoreboard requests use a plain GET with a cache-busting query param instead.
const espnGet = d => fetch(`${ESPN}${d.replace(/-/g, "")}&_=${Math.floor(Date.now() / 60000)}`).then(r => r.ok ? r.json() : {}).catch(() => ({}));

// ---- local answers (until a backend is connected these live in this browser) --------------------
const local = { get: k => { try { return JSON.parse(localStorage.getItem(k) || "{}"); } catch { return {}; } },
                set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };
async function saveAnswer(kind, key, value) {
  const store = local.get(kind); store[key] = value; local.set(kind, store);
  if (API) {
    const [k, w] = kind.startsWith("locks_w") ? ["locks", kind.slice(7)] : [kind, base.week];
    fetch(`${API}/answer`, { method: "POST", headers: { "content-type": "application/json", "x-key": KEY },
      body: JSON.stringify({ kind: k, week: w, key, value }) }).catch(() => {});
  }
}

// ---- data ---------------------------------------------------------------------------------------
let base = null, live = null, tab = "locks";
async function loadBase() {
  const [experts, Q, league, players, priors, gamelog, schedule, lg] = await Promise.all([
    get("static/experts.json").catch(() => ({ weights: null, sources: [] })), get("static/quantiles.json"), get(`${S1}/league/${LEAGUE}`), get("static/players.json"), get("static/priors.json"),
    get("static/gamelog.json"), get(`${S2}/schedule/nba/regular/${new Date().getFullYear() - (new Date().getMonth() < 7 ? 1 : 0)}`),
    get(`${S1}/league/${LEAGUE}/users`)]);
  const today = etToday();
  const weeks = schedule.filter(g => g.week).map(g => [g.date, g.week]).sort();
  const week = (weeks.filter(([d]) => d <= today).at(-1) || weeks[0])[1];
  base = { experts, Q: Q.quantiles, QS: Q, league, players, priors, gamelog, schedule, users: Object.fromEntries(lg.map(u => [u.user_id, u.display_name])), week };
}
async function loadLive() {
  const { week, league } = base, season = league.season;
  const days = weekDays(base.schedule, week), today = etToday();
  const tipDays = days.filter(d => d >= today || d === days.find(x => x >= today));
  const [schedule, rosters, matchups, stats, proj, trending, snapsGh, overridesGh, locksGh, backend, tips, news, claims, moves, context, insights, learning, avail] = await Promise.all([
    get(`${S2}/schedule/nba/regular/${season}`).catch(() => base.schedule),
    get(`${S1}/league/${LEAGUE}/rosters`), get(`${S1}/league/${LEAGUE}/matchups/${week}`),
    get(`${S2}/stats/nba/${season}/${week}?season_type=regular`), get(`${S2}/projections/nba/${season}/${week}?season_type=regular`),
    get(`${S1}/players/nba/trending/add?lookback_hours=24&limit=50`).catch(() => []),
    soft(`${STATE}lineups_${season}_w${week}.json`), soft(`${STATE}eligibility_overrides.json`), soft(`${STATE}locks_w${week}.json`),
    API ? soft(`${API}/state?season=${season}&week=${week}`) : Promise.resolve({}),
    get(`static/tips.json?_=${Math.floor(Date.now() / 60000)}`).catch(() => ({})),
    get(`static/news.json?_=${Math.floor(Date.now() / 60000)}`).catch(() => ({ items: [], mine: [] })),
    get(`static/claims.json?_=${Math.floor(Date.now() / 60000)}`).catch(() => ({ experts: [], consensus: {}, recent: [] })),
    get(`static/moves.json?_=${Math.floor(Date.now() / 60000)}`).catch(() => ({ adds: [], trades: [] })),
    get(`static/context.json?_=${Math.floor(Date.now() / 60000)}`).catch(() => ({})),
    get(`static/insights.json?_=${Math.floor(Date.now() / 60000)}`).catch(() => ({ notes: [], trends: [], openings: [] })),
    get(`static/learning.json?_=${Math.floor(Date.now() / 60000)}`).catch(() => ({})),
    get(`static/availability.json?_=${Math.floor(Date.now() / 60000)}`).catch(() => null)]);
  // backend (minute-level lineup records, shared answers) wins over the 15-minute GitHub state branch
  const snaps = { ...snapsGh, ...(backend.lineups || {}) };
  const overrides = { ...overridesGh, ...(backend.elig || {}) };
  const locks = { ...locksGh, ...(backend.locks || {}) };
  base.schedule = schedule;
  live = { rosters, matchups, stats, proj, trending, snaps, overrides, locks, tips, news, claims, moves, context, insights, learning, avail, backend: !!backend.ok, at: new Date() };
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
  const book = new Book({ scoring: base.league.scoring_settings, players: base.players, priors: base.priors,
                          gamelog: base.gamelog.games, weights: base.experts.weights, ctx: live.context || {}, avail: live.avail });
  bookRef = book;
  book.addStats(live.stats); book.addProjections(live.proj);
  const mine = live.rosters.find(r => r.owner_id === USER);
  const my = live.matchups.find(m => m.roster_id === mine.roster_id);
  const opp = live.matchups.find(m => m.matchup_id === my.matchup_id && m.roster_id !== mine.roster_id);
  const locks = { ...live.locks, ...local.get(`locks_w${base.week}`) };
  const wp = new WeekPlan({ Q: base.QS, book, schedule: base.schedule, week: base.week, today: etToday(), now: new Date(),
    rosterPositions: base.league.roster_positions, roster: mine, matchup: my, rosters: live.rosters, tips: live.tips,
    elig: eligFn(my.starters), locks });
  // opponent's outlook from the same engine (their recent games assumed countable), then my matchup-aware plan
  let oppOut = null, oppPlan = null;
  const oppRoster = opp && live.rosters.find(r => r.roster_id === opp.roster_id);
  if (oppRoster) {
    oppPlan = new WeekPlan({ Q: base.QS, book, schedule: base.schedule, week: base.week, today: etToday(), now: new Date(),
      rosterPositions: base.league.roster_positions, roster: oppRoster, matchup: opp, rosters: live.rosters, tips: live.tips,
      elig: () => true, locks: {} }).build();
    oppOut = { mean: oppPlan.outlook.mean, var: oppPlan.outlook.var };
  }
  const waivers = wp.waivers(live.trending);
  const valuer = new Valuer({ book, schedule: base.schedule, Q: base.QS, rosterPositions: base.league.roster_positions, week: base.week, today: etToday(),
                              freeAgents: waivers.list.map(x => x.pid) });
  const plan = wp.build({ opp: oppOut });
  // every free agent scored the same way Moves does: best drop, this week's locked-points change + rest of season
  const protect = new Set([...(mine.reserve || []),
    ...plan.slots.filter(s => ["locked", "lock", "keep", "live", "confirm"].includes(s.action)).map(s => s.pid),
    ...plan.slots.flatMap(s => [s.today?.pid, s.today?.relief?.pid, s.later?.pid]).filter(Boolean)]);
  const best = Object.fromEntries(waiverMoves(wp, valuer, mine, waivers.list, protect, 999).map(m => [m.pid, m]));
  for (const x of waivers.list) Object.assign(x, best[x.pid] ? { drop: best[x.pid].dropName, gain: best[x.pid].gain, weekGain: best[x.pid].weekGain,
    rosGain: best[x.pid].rosGain, bid: best[x.pid].bid } : { drop: null, gain: 0, bid: 0 });
  waivers.list.sort((a, b) => b.gain - a.gain);
  return { book, wp, valuer, plan, oppPlan, waivers, mine, my, opp };
}

const LABEL = { lock: "Lock", keep: "Counts", pass: "Pass", start: "Start", locked: "Locked", confirm: "Confirm", live: "Live", "fallback-risk": "Fallback" };
function render() {
  const c = compute(), { plan, my, opp, mine } = c;
  const oppOwner = live.rosters.find(r => r.roster_id === opp?.roster_id)?.owner_id;
  $("score").innerHTML = `<b>${r1((my.points || 0) / 10)}</b> – ${r1((opp?.points || 0) / 10)}<span>score now vs ${esc(base.users[oppOwner] || "opponent")} · FAAB $${base.league.settings.waiver_budget - (mine.settings?.waiver_budget_used || 0)}</span>`;
  $("metatext").textContent = `${base.league.name} · week ${base.week} · live ${live.at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;

  // ONE source: plan.actions (top summary), plan.slots (cards + table). Phone alerts read the same lists.
  const acts = plan.actions.filter(a => !a.by || new Date(a.by) > new Date());
  const topAdd = live.moves?.adds?.[0];
  const nextBy = acts.filter(a => a.kind !== "pass" && a.by).map(a => a.by).sort()[0];
  const when = a => a.kind === "relief" ? `between ${tipTime(a.from)} and ${tipTime(a.by)}`
    : a.kind === "move" ? `best ~${tipTime(a.best)}, by ${tipTime(a.by)}` : a.by ? `by ${tipTime(a.by)}` : "";
  const passes = acts.filter(a => a.kind === "pass");
  const ol = plan.outlook;
  // projected FINAL totals; range = 80% band (±1.28 sd); win chance = P(your final > theirs), normal approximation
  const band = (m, sd) => `${Math.round(m - 1.28 * sd)}–${Math.round(m + 1.28 * sd)}`, pct = p => p < 0.01 ? "<1%" : p > 0.99 ? ">99%" : Math.round(p * 100) + "%";
  const mline = ol?.opp ? `<div class="pos" style="margin-bottom:6px" title="Projected final: locked games + live games' remaining projection + the expected value of every open slot. Range = 80% likely band. Win chance = probability your final beats theirs.">Projected final: you <b>${r1(ol.mean)}</b> <span class="pos">(${band(ol.mean, ol.sd)})</span> vs ${esc(base.users[oppOwner] || "opponent")} <b>${r1(ol.opp.mean)}</b> <span class="pos">(${band(ol.opp.mean, Math.sqrt(ol.opp.var))})</span> · win chance <b>${pct(ol.winProb)}</b></div>` : "";
  $("now").innerHTML = mline + (nextBy ? `<b>Next deadline:</b> <span class="when">${until(nextBy)}</span> (${esc(tipTime(nextBy))})` : "<b>No deadlines pending.</b>") +
    `<ul>${acts.filter(a => a.kind !== "pass").map(a => { const [w, ...rest] = a.text.split(" "); return `<li><b>${esc(w)}</b> ${esc(rest.join(" "))} <span class="pos">· ${esc(when(a))}</span></li>`; }).join("")}` +
    (passes.length ? `<li><b>Pass</b> ${passes.map(a => esc(a.text.replace(/^Don't lock /, ""))).join(", ")} <span class="pos">· waiting is worth more</span></li>` : "") +
    (topAdd ? `<li><b>Waiver</b> add ${esc(topAdd.name)}, drop ${esc(topAdd.dropName)} — bid $${topAdd.bid} <span class="pos">· Moves tab</span></li>` : "") + `</ul>`;

  $("slots").innerHTML = plan.slots.map(s => {
    const nums = s.score != null && s.action !== "locked" && s.action !== "live" ? `<div class="nums">game <b>${r1(s.score)}</b>${s.bar != null ? ` · bar ${r1(s.bar)}` : ""}${s.deadline ? ` · decide by ${esc(tipTime(s.deadline.tip) || day(s.deadline.date))}` : ""}</div>` : "";
    const td = s.today ? `<div class="nums">today: <b>${esc(s.today.name)}</b> ${esc(tipTime(s.today.tip))}${s.today.keepBar > 0.05 ? ` · keep if ≥ ${r1(s.today.keepBar)}` : ""}${s.today.relief ? ` · else ${esc(s.today.relief.name)}` : ""}</div>` : "";
    let acts2 = "";
    if (s.action === "confirm") acts2 = `<button data-elig="${s.gameDate}|${s.pid}" data-v="1">He was starting</button><button data-elig="${s.gameDate}|${s.pid}" data-v="0">He was on my bench</button>`;
    if (["lock", "pass", "confirm", "keep"].includes(s.action)) acts2 += `<button data-lock="${s.pid}">I locked this</button>`;
    if (s.action === "locked") acts2 = `<button data-unlock="${s.pid}">Not locked</button>`;
    return `<div class="slot ${s.action}"><div class="top"><span><span class="pos">${esc(s.slot)}</span> <span class="nm">${esc(s.name)}</span>${s.status ? `<span class="st">${esc(s.status)}</span>` : ""}</span><span class="tag">${LABEL[s.action] || s.action}</span></div><p>${esc(s.detail)}</p>${nums}${td}${acts2 ? `<div class="acts">${acts2}</div>` : ""}</div>`;
  }).join("");

  const STATE_TXT = { locked: "locked", live: "game in progress", lock: "lock this game", keep: "counts as is", confirm: "check, then lock" };
  $("lineup").innerHTML = `<div class="wrap" style="border:0"><table><tr><th>Slot</th><th>Now</th><th>Plan for today</th><th>Tip</th><th>Keep his game if ≥</th><th>If he misses it</th></tr>` +
    plan.slots.map(x => {
      const t = x.today;
      const planCell = STATE_TXT[x.action] && !t ? `<span class="pos">${STATE_TXT[x.action]}</span>`
        : t ? (t.move ? `<span class="mv">${esc(t.name)}</span>` : esc(t.name))
        : x.later ? `<span class="pos">no game today · ${esc(x.later.name)} ${esc(day(x.later.date))}</span>` : `<span class="pos">nobody eligible plays</span>`;
      return `<tr><td class="pos">${esc(x.slot)}</td><td>${esc(x.name)}</td><td>${planCell}</td><td class="pos">${t ? esc(tipTime(t.tip)) : ""}</td>` +
        `<td class="n">${t ? (t.keepBar > 0.05 ? r1(t.keepBar) : "any score") : ""}</td><td>${t?.relief ? `${esc(t.relief.name)} <span class="pos">(tips ${esc(tipTime(t.relief.tip))})</span>` : ""}</td></tr>`;
    }).join("") + `</table></div>` +
    (plan.idle.length ? `<div class="row"><span class="pos">Also playing today without a slot: ${plan.idle.map(x => esc(x.name)).join(", ")}</span></div>` : "");

  const today = etToday();
  $("grid").innerHTML = `<tr><th>Player</th><th>Pos</th>${plan.days.map(d => `<th class="${d === today ? "today" : ""}">${day(d)}</th>`).join("")}<th>Left</th></tr>` +
    plan.grid.map(r => `<tr><td>${r.starter ? "" : '<span class="pos">BN </span>'}${esc(r.name)}${r.status ? `<span class="st">${esc(r.status)}</span>` : ""}${r.locked ? ' <span class="pos">🔒</span>' : ""}</td><td class="pos">${esc(r.pos)}</td>` +
      r.cells.map((x, i) => { const td = plan.days[i] === today ? " today" : "";
        if (!x) return `<td class="c${td}"></td>`;
        if (x.kind === "played") return `<td class="c played${x.started === false ? " bench" : ""}${td}" title="vs ${esc(x.opp)} · ${x.started === false ? "from your bench: not lockable" : x.started ? "in your lineup" : "lineup at tip unknown"}">${r1(x.fp)}${x.started == null ? "?" : ""}</td>`;
        if (x.kind === "live") return `<td class="c livec${td}" title="in progress: not final yet">${x.fp != null ? r1(x.fp) + "…" : "live"}</td>`;
        return `<td class="c up${td}" title="vs ${esc(x.opp)}${x.tip ? " · " + esc(tipTime(x.tip)) : ""}">${Math.round(x.mu)}</td>`; }).join("") + `<td class="n">${r.left}</td></tr>`).join("");

  const w = c.waivers;
  $("waivers").innerHTML = `<tr><th>Player</th><th>Team</th><th>Pos</th><th>FP/G</th><th>Games left</th><th title="Expected locked points gained this week with the best drop">This week</th><th title="Lock-in points per week after this one">Per week after</th><th>Drop</th><th>Last 3</th><th>Adds 24h</th><th>Experts</th><th>Bid</th></tr>` +
    w.list.map(x => `<tr><td>${esc(x.name)}${x.status ? `<span class="st">${esc(x.status)}</span>` : ""}</td><td>${esc(x.team)}</td><td class="pos">${esc(x.pos)}</td><td class="n">${r1(x.fpg)}</td><td class="n">${x.left}</td><td class="n">${x.drop ? (x.weekGain >= 0 ? "+" : "") + r1(x.weekGain) : "–"}</td><td class="n">${x.drop ? (x.rosGain >= 0 ? "+" : "") + r1(x.rosGain) : "–"}</td><td class="pos">${x.drop ? esc(x.drop) : "no gain"}</td><td class="n">${x.recent.map(r1).join(" / ") || "–"}</td><td class="n">${x.trend.toLocaleString()}</td><td class="n">${consCell(x.pid)}</td><td class="n">${x.bid ? "$" + x.bid : "–"}</td></tr>`).join("");

  renderTrades(c);
  renderExperts();
  renderNews();
  renderMoves();
  renderResearch(c);
  renderInsights(c);
  $("foot").textContent = `Plan's expected total from open slots: ${r1(plan.expectedTotal || 0)}. Recomputed every minute from Sleeper (scores, schedule, injuries). A game is lockable only if he was starting when it tipped; lineups are recorded by the scheduled job (every 15 min) and by this page while it's open. ${live.backend ? "Answers sync to your backend, and lineups are recorded every minute." : "Answers are saved in this browser only (backend not connected)."}`;
  $("dot").classList.toggle("stale", Date.now() - live.at > 5 * 60000);
}

// ---- trade assistant ------------------------------------------------------------------------------
let tradeSel = { give: new Set(), get: new Set(), partner: null };
function renderTrades(c) {
  const { book, mine, valuer } = c;
  const others = live.rosters.filter(r => r.roster_id !== mine.roster_id);
  const sel = $("partner");
  if (!sel.options.length) {
    sel.innerHTML = others.map(r => `<option value="${r.roster_id}">${esc(base.users[r.owner_id] || "Team " + r.roster_id)}</option>`).join("");
    sel.onchange = () => { tradeSel = { give: new Set(), get: new Set(), partner: +sel.value }; render(); };
  }
  tradeSel.partner ||= +sel.value;
  const them = others.find(r => r.roster_id === tradeSel.partner);
  const list = (r, side) => `<h3>${side === "give" ? "You give" : "You get"}</h3>` + [...(r.players || [])].sort((a, b) => valuer.perWeek(b) - valuer.perWeek(a))
    .map(p => `<label><input type="checkbox" data-side="${side}" value="${p}" ${tradeSel[side].has(p) ? "checked" : ""}>${esc(book.name(p))} <span class="pos">${esc(book.pos(p).join("/"))}</span><span class="v" title="Lock-in value per remaining week (his schedule, volatility and health)">${r1(valuer.perWeek(p))}</span></label>`).join("");
  $("give").innerHTML = list(mine, "give"); $("get").innerHTML = list(them, "get");
  document.querySelectorAll("input[data-side]").forEach(el => el.onchange = () => { tradeSel[el.dataset.side][el.checked ? "add" : "delete"](el.value); render(); });
  const swap = (roster, out, inn) => roster.filter(p => !out.has(p)).concat([...inn]);
  const myB = valuer.team(mine.players, true), thB = valuer.team(them.players, true);
  if (tradeSel.give.size || tradeSel.get.size) {
    const myA = valuer.team(swap(mine.players, tradeSel.give, tradeSel.get), true), thA = valuer.team(swap(them.players, tradeSel.get, tradeSel.give), true);
    const dm = myA - myB, dt = thA - thB;
    const T = set => [...set].reduce((a, p) => a + valuer.tradeValue(p), 0), mg = T(tradeSel.give), mt = T(tradeSel.get);
    const fair = mt === 0 ? 1 : mg / mt;
    $("verdict").innerHTML = `Your team: <b class="${dm >= 0 ? "good" : "bad"}">${dm >= 0 ? "+" : ""}${r1(dm)}</b> locked pts per week, rest of season · theirs: <b class="${dt >= 0 ? "good" : "bad"}">${dt >= 0 ? "+" : ""}${r1(dt)}</b>. ` +
      (dm > 0 && dt >= 0 ? "Helps both of you." : dm > 0 ? "Good for you, but it makes their lineup worse." : "This makes your team worse.") +
      ` Market value (above waiver level, stars weighted up): you give ${r1(mg)}, you get ${r1(mt)}` +
      (fair < 0.9 ? " — <b class=\"bad\">lopsided, they'll likely decline</b>." : fair > 1.3 ? " — you're overpaying." : " — fair.");
  } else $("verdict").textContent = "";
  const sug = live.moves?.trades || [];
  $("ideas").innerHTML = `<tr><th>With</th><th>You give</th><th>You get</th><th>You</th><th>Them</th><th></th></tr>` +
    sug.map((x, i) => `<tr><td>${esc(x.partner)}</td><td>${x.giveNames.map(esc).join(" + ")}</td><td>${x.getNames.map(esc).join(" + ")}</td><td class="n good">+${r1(x.dm)}</td><td class="n">+${r1(x.dt)}</td><td><button data-loadtrade="${i}">Load</button></td></tr>`).join("") ||
    `<tr><td colspan="6" class="pos">No trades found that help both sides right now.</td></tr>`;
}

function renderMoves() {
  const m = live.moves || { adds: [], trades: [] };
  $("movesmeta").textContent = m.generated ? `Suggestions updated ${new Date(m.generated).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}; refreshed every 15 minutes.` : "";
  $("adds").innerHTML = (m.adds || []).length ? m.adds.map(x => `<div class="slot lock"><div class="top"><span><span class="nm">Add ${esc(x.name)}</span> <span class="pos">${esc(x.team)} ${esc(x.pos)}</span></span><span class="tag">bid $${x.bid}</span></div>` +
      `<p>Drop <b>${esc(x.dropName)}</b>. ${x.weekGain != null ? `+${r1(x.weekGain)} locked pts this week, ${x.rosGain >= 0 ? "+" : ""}${r1(x.rosGain)}/week after` : `Team +${r1(x.gain)}`} · ${r1(x.fpg)} FP/G · ${x.left} games left this week${x.experts ? ` · ${Math.round(x.experts.bull_share * 100)}% of experts say add` : ""}${x.trend ? ` · ${x.trend.toLocaleString()} adds in 24h` : ""}</p>` +
      (x.reason ? `<p><i>${esc(x.reason)}</i></p>` : "") + `</div>`).join("")
    : `<div class="box"><div class="row"><span class="pos">No add/drop improves your team right now.</span></div></div>`;
  $("trades2").innerHTML = (m.trades || []).length ? m.trades.map((x, i) => `<div class="slot start"><div class="top"><span class="nm">${esc(x.partner)}</span><span class="tag">+${r1(x.dm)} you / +${r1(x.dt)} them</span></div>` +
      `<p>Give <b>${x.giveNames.map(esc).join(" + ")}</b>, get <b>${x.getNames.map(esc).join(" + ")}</b></p>` +
      ((x.theirFit || []).length ? `<p class="pos">For them: ${x.theirFit.map(f => `${esc(f.inName)} takes their ${esc(f.slot)} spot from ${esc(f.outName)} (${f.gain >= 0 ? "+" : ""}${r1(f.gain)}/wk)`).join("; ")}</p>` : "") +
      ((x.myFit || []).length ? `<p class="pos">For you: ${x.myFit.map(f => `${esc(f.inName)} replaces ${esc(f.outName)} at ${esc(f.slot)} (${f.gain >= 0 ? "+" : ""}${r1(f.gain)}/wk)`).join("; ")}</p>` : "") + (x.reason ? `<p><i>${esc(x.reason)}</i></p>` : "") +
      `<div class="acts"><button data-loadtrade="${i}">Open in trade builder</button></div></div>`).join("")
    : `<div class="box"><div class="row"><span class="pos">No trades found that help both sides right now.</span></div></div>`;
}

// ---- research: every player, every game left this week -------------------------------------------
const riskOf = (book, p) => { const g = book.done(p); if (g.length < 4) return ["–", ""];
  const m = g.reduce((a, x) => a + x.fp, 0) / g.length, cv = Math.sqrt(g.reduce((a, x) => a + (x.fp - m) ** 2, 0) / g.length) / Math.max(m, 1);
  return cv < 0.22 ? ["steady", "safe floor"] : cv < 0.32 ? ["balanced", ""] : ["boom/bust", "big ceiling, low floor"]; };
function researchRows(c, roster, who) {
  const { book, wp } = c, trends = Object.fromEntries((live.insights?.trends || []).map(t => [t.pid, t]));
  const takes = live.claims?.takes || {};
  const takeCell = p => (takes[p] || []).slice(0, 2).map(t => `<div class="take"><span class="chip ${t.lean === "up" ? "up" : t.lean === "down" ? "down" : ""}">${t.lean === "up" ? "▲" : t.lean === "down" ? "▼" : "•"}</span> ${esc(t.take)} <a class="pos" href="${esc(t.link)}" target="_blank" rel="noopener">${esc(t.expert)}</a></div>`).join("") || '<span class="pos">–</span>';
  const rows = [];
  for (const p of roster.players || []) {
    const ups = wp.upcoming(p);
    const [risk, riskWhy] = riskOf(book, p), tr = trends[p];
    if (!ups.length) { rows.push(`<tr><td>${esc(book.name(p))}${book.status(p) ? `<span class="st">${esc(book.status(p))}</span>` : ""}</td><td class="pos">${esc(book.pos(p).join("/"))}</td><td colspan="6" class="pos">no games left this week</td><td style="white-space:normal;min-width:220px">${takeCell(p)}</td></tr>`); continue; }
    ups.forEach((g, k) => {
      const cx = book.ctx?.[`${p}|${g.date}`], rw = book.proj[`${p}|${g.date}`], mdl = book.baseline(p);
      const [lo, hi] = range80(g.Q || base.Q, g.mu);
      const chips = (cx?.parts || []).map(x => `<span class="chip ${x.f >= 1 ? "up" : "down"}" title="${esc(x.why)}">${esc(x.k)} ${x.f >= 1 ? "+" : ""}${Math.round((x.f - 1) * 100)}%</span>`).join(" ");
      rows.push(`<tr><td>${k ? "" : esc(book.name(p))}${!k && book.status(p) ? `<span class="st">${esc(book.status(p))}</span>` : ""}${!k && tr ? ` <span class="chip ${tr.dir === "up" ? "up" : "down"}" title="${esc(tr.why)}">${tr.dir === "up" ? "▲" : "▼"} role</span>` : ""}</td>` +
        `<td class="pos">${k ? "" : esc(book.pos(p).join("/"))}</td><td>${esc(day(g.date))} ${g.b2b ? '<span class="pos">b2b</span>' : ""} <span class="pos">vs ${esc(g.opp)}${g.tip ? " · " + esc(tipTime(g.tip)) : ""}</span></td>` +
        `<td class="n"><b>${r1(g.mu)}</b></td><td class="n pos">${rw ? r1(rw) : "–"} / ${r1(mdl)} / ${cx ? r1(mdl * cx.f) : "–"}</td><td class="n">${lo}–${hi}</td>` +
        `<td style="white-space:normal">${chips || '<span class="pos">neutral</span>'}</td><td class="pos" title="${esc((live.avail?.players?.[p]?.basis ? "Play chance: " + live.avail.players[p].basis + ". " : "") + riskWhy)}">${k ? "" : risk} · ${Math.round(g.q * 100)}%${!k && live.avail?.players?.[p]?.timeline ? " ⏱" : ""}</td>` +
        `<td style="white-space:normal;min-width:220px">${k ? "" : takeCell(p)}</td></tr>`);
    });
  }
  return `<tr><th>${esc(who)}</th><th>Pos</th><th>Game</th><th>Proj</th><th>RotoWire / model / matchup</th><th>Range (10–90%)</th><th>Matchup factors (hover for why)</th><th>Profile · plays</th><th>What experts say</th></tr>` + rows.join("");
}
function renderResearch(c) {
  $("research").innerHTML = researchRows(c, c.mine, "Your players");
  const oppRoster = c.opp && live.rosters.find(r => r.roster_id === c.opp.roster_id);
  $("research_opp").innerHTML = oppRoster ? researchRows(c, oppRoster, "Opponent's players") : "";
}

// ---- insights ----------------------------------------------------------------------------------------
function renderInsights(c) {
  const ins = live.insights || {}, lr = live.learning || {}, mine = new Set(c.mine.players || []);
  const ol = c.plan.outlook;
  $("outlook").innerHTML = ol?.opp ? `<div class="row"><span>Projected final — you: <b>${r1(ol.mean)}</b> (80% range ${Math.round(ol.mean - 1.28 * ol.sd)}–${Math.round(ol.mean + 1.28 * ol.sd)}) · opponent: <b>${r1(ol.opp.mean)}</b> (${Math.round(ol.opp.mean - 1.28 * Math.sqrt(ol.opp.var))}–${Math.round(ol.opp.mean + 1.28 * Math.sqrt(ol.opp.var))})</span><span><b>${ol.winProb < 0.01 ? "<1%" : ol.winProb > 0.99 ? ">99%" : Math.round(ol.winProb * 100) + "%"}</b> win chance</span></div>` +
    `<div class="row"><span class="pos">Projected final = locked games + the rest of live games' projections + the expected value of each open slot (from the lock plan). Win chance = how often your final beats theirs given both ranges.</span></div>` +
    `<div class="row"><span class="pos">Lock calls compare your win chance if you lock vs wait. When they differ by 2+ points, the matchup decides: protect a lead with safe locks, chase upside when behind.</span></div>` : `<div class="row"><span class="pos">No matchup found.</span></div>`;
  $("why").innerHTML = (ins.notes || []).map(n => `<div class="row"><span><b>${esc(n.player)}</b> <span class="pos">${esc(n.date)}</span> — ${esc(n.text)}</span><span class="chip ${n.tag === "signal" ? "up" : ""}">${esc(n.tag)}</span></div>`).join("") ||
    `<div class="row"><span class="pos">Notes appear after games finish, for any game that lands well above or below its projection.</span></div>`;
  $("trends").innerHTML = (ins.trends || []).slice(0, 25).map(t => `<div class="row"><span>${t.dir === "up" ? "▲" : "▼"} <b>${esc(t.player)}</b> <span class="pos">${esc(t.team)}</span> — ${esc(t.why)} · ${r1(t.fp4)} FP/G lately</span><span class="pos">${t.mine ? "your player" : t.rostered ? "rostered" : "free agent"}</span></div>`).join("") ||
    `<div class="row"><span class="pos">No clear minutes trends yet (needs 5+ games).</span></div>`;
  $("openings").innerHTML = (ins.openings || []).map(o => `<div class="row"><span><b>${esc(o.player)}</b> (${esc(o.team)}, ${esc(o.status)}, ${r1(o.min)} min) → ${o.gainers.map(g => `${esc(g.player)} +${r1(g.dfp)} FP${g.rostered ? "" : ' <span class="chip up">FA</span>'}${mine.has(g.pid) ? ' <span class="chip">yours</span>' : ""}`).join(", ")}</span><span class="pos">${esc(o.gainers[0]?.basis || "")}</span></div>`).join("") ||
    `<div class="row"><span class="pos">No major rotation players out right now.</span></div>`;
  $("scorecard").innerHTML = `<tr><th>Week</th><th>Calls graded</th><th>You followed</th><th>Right calls</th><th>Points saved</th><th>Points lost</th></tr>` +
    ((lr.weeks || []).map(w => `<tr><td>${w.week}</td><td class="n">${w.graded}/${w.calls}</td><td class="n">${w.followed}</td><td class="n">${w.good}</td><td class="n good">+${r1(w.points_saved)}</td><td class="n bad">−${r1(w.points_lost)}</td></tr>`).join("") ||
     `<tr><td colspan="6" class="pos">Calls are logged from now on and graded when each week is final.</td></tr>`);
  $("graded").innerHTML = (lr.graded || []).slice(0, 30).map(g => `<tr><td>${g.week}</td><td>${esc(g.slot)}</td><td>${g.kind === "move" ? `start ${esc(g.name)} over ${esc(g.replaces)}` : `${esc(g.call)} ${esc(g.name)} ${r1(g.score)}`}</td><td class="n">${g.final != null ? r1(g.final) : "–"}</td><td class="n">${g.cf != null ? r1(g.cf) : "–"}</td><td class="n ${g.regret <= 0 ? "good" : "bad"}">${g.regret <= 0 ? "+" + r1(-g.regret) : "−" + r1(g.regret)}</td><td class="pos">${g.followed ? "followed" : "overrode"}</td></tr>`).join("");
}

const consCell = pid => { const c = live.claims?.consensus?.[pid]; return c && c.bull_share != null ? `<span title="${c.n} call(s) in the last 7 days, weighted by each expert's record">${Math.round(c.bull_share * 100)}% add</span>` : "–"; };

// ---- news -------------------------------------------------------------------------------------------
function renderNews() {
  const n = live.news || { items: [], mine: [] };
  const ago = t => { const m = Math.round((Date.now() - new Date(t)) / 60000); return m < 60 ? `${m}m ago` : m < 1440 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`; };
  $("mynews").innerHTML = n.mine.length ? n.mine.map(x => `<div class="row"><span><b>${esc(x.player || x.title)}</b> — ${esc(x.summary || x.title)}<br><span class="pos">${esc(x.means)}</span></span><span class="pos"><a href="${esc(x.link)}" target="_blank" rel="noopener">${esc(x.source)}</a> · ${ago(x.at)}</span></div>`).join("")
    : `<div class="row"><span class="pos">Nothing in the latest news changes your roster.</span></div>`;
  $("allnews").innerHTML = n.items.slice(0, 50).map(x => `<div class="row"><span>${x.player ? `<b>${esc(x.player)}</b> — ` : ""}${esc(x.summary || x.title)}${x.status && x.status !== "unknown" ? ` <span class="st">${esc(x.status)}</span>` : ""}</span><span class="pos"><a href="${esc(x.link)}" target="_blank" rel="noopener">${esc(x.source)}</a> · ${ago(x.at)}</span></div>`).join("")
    || `<div class="row"><span class="pos">No news collected yet.</span></div>`;
}

// ---- experts ----------------------------------------------------------------------------------------
const SRC_NAME = { rotowire: "RotoWire per-game projections (via Sleeper)", model: "Lock Desk model (season avg shrunk to last season)", ctx: "Lock Desk matchup model (model × opponent, pace, minutes, injuries, rest)", blend: "Blend the engine uses (weighted mix of the above)" };
function renderExperts() {
  const ex = base.experts, rows = ex.sources || [];
  const weeks = [...new Set(rows.flatMap(r => Object.keys(r.weekly || {})))].sort((a, b) => a - b);
  $("experts").innerHTML = `<tr><th>Source</th><th>Graded games</th><th>Avg miss (FP)</th><th>RMSE</th><th>Bias</th><th>Weight now</th>${weeks.map(w => `<th>Wk ${w}</th>`).join("")}</tr>` +
    (rows.map(r => `<tr><td>${esc(SRC_NAME[r.source] || r.source)}</td><td class="n">${r.games}</td><td class="n">${r1(r.mae)}</td><td class="n">${r1(r.rmse)}</td><td class="n">${r.bias > 0 ? "+" : ""}${r1(r.bias)}</td><td class="n">${r.weight != null ? Math.round(r.weight * 100) + "%" : "–"}</td>${weeks.map(w => `<td class="n">${r.weekly?.[w] != null ? r1(r.weekly[w]) : ""}</td>`).join("")}</tr>`).join("") ||
     `<tr><td colspan="6" class="pos">Grading starts with tonight's games: each source's projection is logged before tip and scored once the box score is in.</td></tr>`);
  const cl = live.claims || { experts: [], recent: [] };
  const sr = cl.sources || { rows: [] };
  $("sources").innerHTML = `<tr><th>Source</th><th>Type</th><th>Status</th><th>Newest item</th><th>Takes (7d)</th><th>Calls (7d)</th></tr>` +
    (sr.rows || []).sort((a, b) => (b.ok - a.ok) || (b.takes7 + b.calls7) - (a.takes7 + a.calls7)).map(r => `<tr><td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.name)}</a></td><td class="pos">${esc(r.role)}</td>` +
      `<td>${r.ok ? '<span class="good">active</span>' : `<span class="pos">${esc(r.why || "off")}</span>`}</td><td class="pos">${r.newest ? esc(new Date(r.newest).toLocaleDateString()) : "–"}</td><td class="n">${r.takes7 || 0}</td><td class="n">${r.calls7 || 0}</td></tr>`).join("");
  $("sourcesmeta").textContent = sr.checked ? `Sources re-checked ${new Date(sr.checked).toLocaleString()} (every 3 days): reachable, allowed by the site's robots.txt, recent, and NBA-focused.` : "";
  $("pundits").innerHTML = `<tr><th>Expert</th><th>Calls</th><th>Graded</th><th>Hit rate</th><th title="Hit rate minus what an average expert hits on the same kinds of calls">vs. average</th><th>Weight</th></tr>` +
    (cl.experts.map(e => `<tr><td>${esc(e.expert)}</td><td class="n">${e.calls}</td><td class="n">${e.graded}</td><td class="n">${e.hit_rate != null ? Math.round(e.hit_rate * 100) + "%" : "–"}</td><td class="n">${e.hit_rate != null && e.base_rate != null ? (e.hit_rate >= e.base_rate ? "+" : "") + Math.round((e.hit_rate - e.base_rate) * 100) + " pts" : "–"}</td><td class="n">${Math.round(e.weight * 100)}%</td></tr>`).join("") ||
     `<tr><td colspan="6" class="pos">No expert calls collected yet. They appear as advice articles are published and read.</td></tr>`);
  $("calls").innerHTML = `<tr><th>Date</th><th>Expert</th><th>Call</th><th>Player</th><th>Why</th><th>Result</th></tr>` +
    cl.recent.slice(0, 40).map(c => `<tr><td class="pos">${esc(c.date)}</td><td>${esc(c.expert)}</td><td>${esc(c.action)}</td><td>${esc(c.player)}</td><td class="pos" style="white-space:normal">${esc(c.reason)}</td><td class="n">${c.correct === true ? '<span class="good">right</span>' : c.correct === false ? '<span class="bad">wrong</span>' : "pending"}</td></tr>`).join("");
}

// ---- events + loop --------------------------------------------------------------------------------
document.addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.t) { tab = b.dataset.t; document.querySelectorAll("#tabs button").forEach(x => x.classList.toggle("on", x === b)); document.querySelectorAll("section[data-p]").forEach(s => s.classList.toggle("hide", s.dataset.p !== tab)); return; }
  if (b.dataset.loadtrade != null) {
    const x = live.moves.trades[+b.dataset.loadtrade];
    tradeSel = { give: new Set(x.give), get: new Set(x.get), partner: x.roster_id };
    $("partner").value = String(x.roster_id);
    document.querySelector('#tabs button[data-t="trades"]').click(); render(); return;
  }
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
