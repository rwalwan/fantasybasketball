// Nov 26 (Ryan): Lock Desk said Cam Spencer's Wednesday 26.0 (F) could be locked; the Sleeper app said it can't,
// "because I moved him to the bench at some point". Our minute-level record had his Monday game benched but Wednesday's
// frozen in F and never benched: the bench trip fell between two once-a-minute samples. The opponent's Zach Edey was the
// same, and the opponent's lineup was only sampled by the 15-minute job.
// Sleeper doesn't publish its eligibility answer (checked Nov 26: every MatchupLeg field logged in and out, all 241
// GraphQL queries, league_event_logs), so the fix is (1) sample Sleeper's own scoring lineup four times a minute, for
// both teams of the matchup, and (2) let Ryan mark a game Sleeper won't lock with one tap (an eligibility answer).
// The right answer in every case below: Spencer's Wednesday game is NOT lockable.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, eligFromSnaps } from "../site/engine.js";
import { recordLineup, sampleLineups } from "../worker/src/lineup.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const [mon, wed, fri] = ["2026-11-23", "2026-11-25", "2026-11-27"];
const SLOTS = ["G", "F", "C"];
const wedTip = "2026-11-26T01:00:00Z";                    // MEM vs LAC, 5 PM PT
const team = { S: "MEM", J: "MEM", E: "MEM", B: "NYK", Z: "POR" };

// Spencer (S) and Jerome (J) are Ryan's; Edey (E) is the opponent's. Records as the Worker had them on Nov 26.
const mineSnaps = () => ({ [`${mon}|S`]: { slot: "G", i: 0, frozen: true, benched: true }, [`${wed}|S`]: { slot: "F", i: 1, frozen: true },
                           [`${wed}|J`]: { slot: "G", i: 0, frozen: true } });
const oppSnaps = () => ({ [`${wed}|E`]: { slot: "C", i: 2, frozen: true } });

// Wednesday night after the game: Ryan sends Spencer to the bench at 6:30:20 PM PT and back to F at 6:30:40 PM PT; the
// opponent benches Edey for the same 20 seconds.
const t0 = Date.parse("2026-11-26T02:30:00Z");
const benchedAt = ms => ms >= t0 + 20000 && ms < t0 + 40000;
const legsAt = ms => [
  { roster_id: 3, matchup_id: 4, starters: ["J", benchedAt(ms) ? "0" : "S", "B"], players: ["J", "S", "B"] },
  { roster_id: 1, matchup_id: 4, starters: ["0", "0", benchedAt(ms) ? "0" : "E"], players: ["E", "Z"] },
  { roster_id: 7, matchup_id: 2, starters: ["0", "0", "0"], players: [] }];
const tips = { MEM: wedTip, NYK: "2026-11-26T00:30:00Z", POR: "2026-11-26T03:00:00Z" };

// Before: one sample a minute (at :00 and the next minute's :00) never sees the bench trip
{
  const snaps = mineSnaps();
  for (const ms of [t0, t0 + 60000]) {
    const l = legsAt(ms).find(x => x.roster_id === 3);
    recordLineup(snaps, { starters: l.starters, players: l.players, slots: SLOTS, tips, team, date: wed, now: new Date(ms) });
  }
  assert.ok(!snaps[`${wed}|S`].benched, "a once-a-minute sample misses a 20-second bench trip (the Nov 26 miss)");
}

// After: four samples a minute (0, 15, 30, 45 s) catch it, for Ryan and the opponent
let clockMs = t0;
const mine = mineSnaps(), opp = oppSnaps(), saved = [];
const res = await sampleLineups({ fetchLegs: async () => legsAt(clockMs), rosterId: 3, slots: SLOTS, tips, team, date: wed, mine, opp,
  sleep: async ms => { clockMs += ms; }, clock: () => new Date(clockMs), save: async c => saved.push([clockMs - t0, c]) });
assert.equal(res.ok, 4); assert.equal(res.oppId, 1);
// first sample: the opponent's bench player Z (game later tonight) gets his pre-tip record; 30 s: both bench trips
assert.deepEqual(saved, [[0, { mine: false, opp: true }], [30000, { mine: true, opp: true }]], "saved right after each sample that changed something");
assert.deepEqual(opp[`${wed}|Z`], { slot: null, i: null, seen: "2026-11-26T02:30Z", frozen: false });
assert.ok(res.changedMine && res.changedOpp);
assert.equal(mine[`${wed}|S`].benched, true, "Spencer's Wednesday game: benched after tip");
assert.ok(!mine[`${wed}|J`].benched, "Jerome never left the lineup");
assert.equal(opp[`${wed}|E`].benched, true, "the opponent's Edey too");

// A day without games (Thanksgiving): a bench trip still counts against the week's earlier games
{
  const snaps = mineSnaps();
  recordLineup(snaps, { starters: ["J", "0", "B"], players: ["J", "S", "B"], slots: SLOTS, tips: {}, team, date: "2026-11-26", now: new Date("2026-11-26T20:00:00Z") });
  assert.equal(snaps[`${wed}|S`].benched, true, "benched on an off day");
}

// The engine then says not lockable (Spencer has a game left Friday, so the slot isn't kept as is)
const g = (date, st, t) => ({ week: 6, date, home: { team: t }, away: { team: "X" + t }, status: st });
const sched = [g(mon, "complete", "MEM"), g(wed, "complete", "MEM"), g(fri, "pre_game", "MEM")];
const mk = (snaps, ov = {}) => new WeekPlan({ Q: QS, schedule: sched, week: 6, today: "2026-11-26", now: new Date("2026-11-27T00:00:00Z"),
  book: new Book({ scoring: {}, players: { S: ["Cam Spencer", "MEM", ["SG", "SF"], null], J: ["Ty Jerome", "MEM", ["PG", "SG"], null] },
    priors: { S: 27, J: 46 }, gamelog: { S: [[mon, 39, 24, "s1"], [wed, 26, 24, "s2"]], J: [[wed, 49.5, 25, "j2"]] }, weights: { rotowire: 1, model: 0, ctx: 0 } }),
  rosterPositions: ["G", "F", "BN"], roster: { players: ["J", "S"] }, matchup: { starters: ["J", "S"], starters_points: [495, 260], players_points: { J: 495, S: 260 } },
  rosters: [], tips: { [`${fri}|MEM`]: "2026-11-28T01:30:00Z" }, elig: eligFromSnaps(snaps, ov), locks: {} });

assert.equal(mk(mineSnaps()).lockState("S").st, "open", "the old record: offered as lockable (what Ryan saw)");
assert.equal(mk(mine).lockState("S").st, "moved", "with the bench trip recorded: not lockable");
assert.equal(mk(mine).lockState("J").st, "open", "Jerome's 49.5 stays lockable");
const plan = mk(mine).build({});
assert.ok(!plan.actions.some(a => a.pid === "S" && (a.kind === "lock" || a.kind === "pass")), plan.actions.map(a => a.text).join(" | "));

// Ryan's one tap ("Sleeper won't let me lock this") = an eligibility answer for that game: not lockable either
assert.notEqual(mk(mineSnaps(), { [`${wed}|S`]: false }).lockState("S").st, "open", "his answer overrides the record");
assert.equal(mk(mine, { [`${wed}|S`]: true }).lockState("S").st, "open", "undo (Sleeper does let me lock it) restores it");

console.log("ok: nov 26 bench trip between samples (Spencer, Edey)");
