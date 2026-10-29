// A slot whose game is in progress kept no same-day option: the card said "lock call comes after the final buzzer"
// and the later-game swap vanished (Oct 28: every starter live at 6:15 PM PT, Derrick Jones Jr. and Sandro
// Mamukelashvili on the bench tipping at 7:30 PM PT). Now a live slot plans the swap: lock if his final reaches the
// keep-line, else slide in the later player.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const today = "2026-11-04", sat = "2026-11-07";
const sched = [
  { week: 3, date: today, home: { team: "AAA" }, away: { team: "XXX" }, status: "in_progress" },
  { week: 3, date: today, home: { team: "BBB" }, away: { team: "YYY" }, status: "pre_game" },
  { week: 3, date: sat, home: { team: "AAA" }, away: { team: "XXX" }, status: "pre_game" },
];
const q = { [today]: 0.94, [sat]: 0.94 };
const book = new Book({ scoring: {}, players: { A: ["A", "AAA", ["SF"], null], B: ["B", "BBB", ["SF"], null] },
  priors: { A: 35, B: 35 }, gamelog: { A: [[today, 12, 18, "g1"]] }, weights: { rotowire: 1, model: 0, ctx: 0 },
  avail: { model: null, players: { A: { status: null, q }, B: { status: null, q } } } });
book.proj = { [`A|${today}`]: 35, [`A|${sat}`]: 35, [`B|${today}`]: 35 };
const wp = new WeekPlan({ Q: QS, book, schedule: sched, week: 3, today, now: new Date("2026-11-05T00:45:00Z"),
  rosterPositions: ["UTIL", "BN"], roster: { players: ["A", "B"] }, matchup: { starters: ["A"], players_points: { A: 120 } },
  rosters: [], tips: { [`${today}|AAA`]: "2026-11-04T23:00:00Z", [`${today}|BBB`]: "2026-11-05T02:30:00Z", [`${sat}|AAA`]: "2026-11-08T00:00:00Z" },
  elig: () => true, locks: {} });
const plan = wp.build();
const s = plan.slots.find(x => x.slot === "UTIL");
console.log(s.action, "|", s.detail);
assert.equal(s.action, "live");
assert.equal(s.today?.relief?.pid, "B", "the later game is planned as a swap");
assert.ok(s.today.keepBar > 12 && s.today.keepBar < 60, s.today.keepBar);
assert.ok(plan.actions.some(a => a.kind === "relief" && a.pid === "B"), "and listed in the actions");
console.log("ok: live relief");
