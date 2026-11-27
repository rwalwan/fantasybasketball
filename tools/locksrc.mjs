// Sleeper's lock record without a login (Nov 27). The app's own query (get_matchup_legs) needs Ryan's token, but the
// public matchup_legs_raw query (the one the Worker already reads lineups from) also returns starters_games: each
// starter's locked game id, for every team. compareLocks checks the two sources against each other, so we can see
// whether the public one can stand in when the token expires.
export const RAW_Q = (league, round) => `query { matchup_legs_raw(league_id: "${league}", round: ${Number(round)}) { roster_id starters starters_games } }`;
export async function publicLocks(fetchFn, league, round) {
  const r = await fetchFn("https://api.sleeper.app/graphql", { method: "POST",
    headers: { "content-type": "application/json", accept: "application/json", "user-agent": "we-back-lock-desk" },
    body: JSON.stringify({ query: RAW_Q(league, round) }) });
  const legs = (await r.json().catch(() => null))?.data?.matchup_legs_raw;
  if (!r.ok || !Array.isArray(legs)) throw new Error(`matchup_legs_raw HTTP ${r.status}`);
  return Object.fromEntries(legs.map(l => [String(l.roster_id), l.starters_games || {}]));
}
// a, b: {roster_id: {player: game id}} -> {teams, locks, same, diffs: [{team, pid, a, b}]}
export function compareLocks(a = {}, b = {}) {
  const out = { teams: 0, locks: 0, same: 0, diffs: [] };
  for (const t of new Set([...Object.keys(a || {}), ...Object.keys(b || {})])) {
    out.teams++;
    const x = a?.[t] || {}, y = b?.[t] || {};
    for (const p of new Set([...Object.keys(x), ...Object.keys(y)])) {
      out.locks++;
      if (String(x[p] ?? "") === String(y[p] ?? "")) out.same++;
      else out.diffs.push({ team: t, pid: p, a: x[p] ?? null, b: y[p] ?? null });
    }
  }
  return out;
}
