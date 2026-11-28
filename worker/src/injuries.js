// Last-minute injury watch (Worker side, Nov 28). Pure functions, so tests/test_nov28_injury_watch.mjs can run them.
//
// Why: Lock Desk re-ran every 15 minutes, and Sleeper's injury labels can lag the team's report by hours (Nov 16:
// Queta ruled out 5:16 pm ET, Sleeper GTD for 2+ hours). A late scratch decides who should start, and the start
// decision is due at tip. So in the two hours before each tip the Worker reads ESPN's public injury report every minute
// for the teams about to play; when a status changes it saves the report (KV, only on a change) and starts the
// update job at once (at most every 4 minutes), so projections, lineup moves and phone alerts follow in minutes.

export const WINDOW_MIN = 120;       // minutes before a tip when the watch is on
export const KICK_GAP_MIN = 4;       // at most one extra update run per 4 minutes

// ESPN team names -> Sleeper team codes (the injuries feed groups players by team display name)
export const TEAM_BY_NAME = {
  "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI",
  "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
  "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND", "LA Clippers": "LAC",
  "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM", "Miami Heat": "MIA",
  "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP", "New York Knicks": "NYK",
  "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
  "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
  "Utah Jazz": "UTA", "Washington Wizards": "WAS" };
const ABBR = { NY: "NYK", GS: "GSW", SA: "SAS", NO: "NOP", UTAH: "UTA", WSH: "WAS" };

export const norm = s => (s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
  .replace(/\b(jr|sr|ii|iii|iv)\b\.?/g, "").replace(/[^a-z ]/g, "").replace(/\s+/g, " ").trim();

// ESPN's injuries JSON -> [{name, team, status, comment, at}]. Read defensively: fields ESPN doesn't send are skipped.
export function parseInjuries(j) {
  const out = [];
  for (const blk of j?.injuries || []) {
    const bt = blk.team?.abbreviation;
    for (const it of blk.injuries || []) {
      const a = it.athlete || {}, t = bt || a.team?.abbreviation || TEAM_BY_NAME[blk.displayName] || TEAM_BY_NAME[a.team?.displayName];
      const status = it.status || it.type?.description || it.details?.fantasyStatus?.description;
      if (!a.displayName || !t || !status) continue;
      out.push({ name: a.displayName, team: ABBR[t] || t, status: String(status), comment: (it.shortComment || "").slice(0, 200), at: it.date || null });
    }
  }
  return out;
}

// Teams whose game tips within the next WINDOW_MIN minutes (and hasn't tipped)
export function windowTeams(tips, now) {
  return Object.entries(tips || {}).filter(([, t]) => { const m = (new Date(t) - now) / 60000; return m >= 0 && m <= WINDOW_MIN; }).map(([team]) => team);
}

// One minute's watch (a change = a new status or a new note). prev = {items: {"TEAM|name": {pid, name, team, status, comment, at}}, changes: [...], kickedAt}.
// Returns {active, changed: [...], kicked}. Writes (save) only when a status changed.
export async function watchInjuries({ fetchInjuries, tips, now, players = {}, prev = {}, save, kick }) {
  const teams = new Set(windowTeams(tips, now));
  if (!teams.size) return { active: false, changed: [], kicked: false };
  const list = parseInjuries(await fetchInjuries());
  if (!list.length) return { active: true, changed: [], kicked: false, empty: true };
  const pidOf = {};                                  // only the teams about to play (Worker free plan: ~10 ms CPU a run)
  for (const [pid, v] of Object.entries(players)) if (teams.has(v[1])) pidOf[`${v[1]}|${norm(v[0])}`] = pid;
  const old = prev.items || {}, items = { ...old }, changed = [];
  const stamp = now.toISOString().slice(0, 16) + "Z";
  const seen = new Set();
  for (const x of list) {
    if (!teams.has(x.team)) continue;
    const k = `${x.team}|${norm(x.name)}`;
    seen.add(k);
    const rec = { pid: pidOf[k] || null, name: x.name, team: x.team, status: x.status, comment: x.comment, at: x.at, seen: old[k]?.seen || stamp };
    // a new note counts too: ESPN's status can stay "Out" from an earlier game while the note becomes about tonight
    if (!old[k] || old[k].status !== x.status || (x.at && old[k].at !== x.at)) { rec.seen = stamp; changed.push({ k, name: x.name, team: x.team, from: old[k]?.status || null, to: x.status, at: stamp }); }
    items[k] = rec;
  }
  // taken off the report = cleared to play
  for (const [k, r] of Object.entries(old)) {
    if (teams.has(r.team) && !seen.has(k) && r.status !== "Available") {
      items[k] = { ...r, status: "Available", seen: stamp };
      changed.push({ k, name: r.name, team: r.team, from: r.status, to: "Available", at: stamp });
    }
  }
  if (!changed.length) return { active: true, changed, kicked: false };
  // the first read of a team's report isn't news: record it without starting a run
  const fresh = changed.filter(c => c.from !== null || Object.keys(old).some(k => k.startsWith(`${c.team}|`)));
  let kicked = false, kickedAt = prev.kickedAt || null;
  if (fresh.length && kick && (!kickedAt || now - new Date(kickedAt) >= KICK_GAP_MIN * 60000)) {
    kicked = !!(await kick())?.ok;
    if (kicked) kickedAt = now.toISOString();
  }
  await save({ items, changes: [...fresh, ...(prev.changes || [])].slice(0, 40), kickedAt, updated: stamp });
  return { active: true, changed: fresh, kicked };
}
