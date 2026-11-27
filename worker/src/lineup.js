// Lineup records for lock eligibility (Worker side). Pure functions, so tests/test_nov26_bench_trip.mjs can run them.
//
// Sleeper (its own message, Nov 15): a game can't be locked if the player "was not in the starting lineup at the
// scheduled game time OR was moved to bench since the game began". Sleeper doesn't publish that answer anywhere we can
// read (checked Nov 26: every MatchupLeg field logged in and out, all 241 GraphQL queries, league_event_logs = only
// commissioner edits), so we rebuild it from lineup samples. A bench trip between two samples is invisible, which is
// how Cam Spencer's Wed game (and the opponent's Zach Edey's) was still shown as lockable on Nov 26.

// One sample: record who is in each starting slot for every game that hasn't tipped, freeze the record at tip, and
// mark a frozen starting-slot record "benched" the first time a sample sees him on the bench (or IR) after the game
// began. Returns true if anything changed. snaps = {"<date>|<pid>": {slot, i, seen, frozen, benched?}}.
export function recordLineup(snaps, { starters = [], players = [], slots, tips, team, date, now }) {
  const slotOf = {}, idxOf = {};
  (starters || []).forEach((p, i) => { if (p && p !== "0") { slotOf[p] = slots[i]; idxOf[p] = i; } });
  let changed = false;
  const stamp = now.toISOString().slice(0, 16) + "Z";
  for (const pid of players || []) {
    const tip = tips[team[pid]];
    if (!tip) continue;                                   // no game today
    const k = `${date}|${pid}`, cur = snaps[k];
    if (cur?.frozen) continue;
    if (new Date(tip) <= now) {                           // tipped: freeze the last pre-tip record
      if (cur) { cur.frozen = true; changed = true; }
      continue;
    }
    const slot = slotOf[pid] ?? null, i = idxOf[pid] ?? null;   // i: which slot index (names repeat, e.g. two UTIL)
    if (!cur || cur.slot !== slot || (cur.i ?? null) !== i) { snaps[k] = { slot, i, seen: stamp, frozen: false }; changed = true; }
  }
  const roster = new Set(players || []);
  for (const [k, rec] of Object.entries(snaps)) {
    if (!rec.frozen || rec.slot == null || rec.benched) continue;
    const pid = k.split("|")[1];
    if (roster.has(pid) && slotOf[pid] == null) { rec.benched = true; changed = true; }
  }
  return changed;
}

// Several samples a minute (Nov 26): the cron fires once a minute, so the Worker samples `samples` times, `gapMs`
// apart, and records both teams of the matchup each time. fetchLegs() -> [{roster_id, matchup_id, starters, players}]
// (Sleeper's own scoring lineup, matchup_legs_raw). save({mine, opp}) is called right after any sample that changed a
// record set (so a run cut short keeps what it saw); returns which sets changed over the whole run.
export async function sampleLineups({ fetchLegs, rosterId, slots, tips, team, date, mine, opp, samples = 4, gapMs = 15000,
                                      sleep = ms => new Promise(r => setTimeout(r, ms)), clock = () => new Date(), save = async () => {} }) {
  let changedMine = false, changedOpp = false, oppId = null, ok = 0;
  for (let k = 0; k < samples; k++) {
    if (k) await sleep(gapMs);
    let legs;
    try { legs = await fetchLegs(); } catch { continue; }
    const me = (legs || []).find(l => l.roster_id === rosterId);
    if (!me) continue;
    const them = legs.find(l => l.matchup_id === me.matchup_id && l.roster_id !== rosterId);
    const now = clock();
    const m = recordLineup(mine, { starters: me.starters, players: me.players, slots, tips, team, date, now });
    const o = !!them && recordLineup(opp, { starters: them.starters, players: them.players, slots, tips, team, date, now });
    if (them) oppId = them.roster_id;
    if (m || o) await save({ mine: m, opp: o });
    changedMine ||= m; changedOpp ||= o;
    ok++;
  }
  return { changedMine, changedOpp, oppId, ok };
}
