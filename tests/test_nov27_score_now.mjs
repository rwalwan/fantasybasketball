// Nov 27: the page's "score now" showed Sleeper's public matchup points (387.5 vs 439.5 in week 6), but Sleeper's app
// showed 169.0 vs 428.5. In Lock-In, Sleeper's matchup total counts only LOCKED slots, each at the game it was locked
// on, and mid-week the public feed's slot points show a starter's LATEST game even when an earlier one is locked
// (week 6: Durant locked on Mon's 63.5, the feed showing Wed's 48.5; the opponent's SGA locked 67.5 vs 52.0). So the
// score shown must be the sum of the plan's locked slots (each at its locked game), not the feed's points.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, sleeperLocksFor, lockedTotal } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const g = (date, t) => ({ week: 6, date, home: { team: t }, away: { team: "XXX" }, status: "complete" });
const sched = [g("2026-11-23", "HOU"), g("2026-11-25", "HOU"), g("2026-11-24", "ORL"), g("2026-11-23", "BKN"),
               g("2026-11-25", "BKN"), g("2026-11-24", "MIN"), { week: 6, date: "2026-11-28", home: { team: "MIN" }, away: { team: "XXX" }, status: "pre_game" }];
const players = { kd: ["Kevin Durant", "HOU", ["SF", "PF"], null], wcj: ["Wendell Carter Jr.", "ORL", ["C"], null],
                  sharpe: ["Day'Ron Sharpe", "BKN", ["C"], null], gob: ["Rudy Gobert", "MIN", ["C"], null] };
const gamelog = {
  kd: [["2026-11-23", 63.5, 36, "kd1"], ["2026-11-25", 48.5, 35, "kd2"]],
  wcj: [["2026-11-24", 44.5, 30, "wcj1"]],
  sharpe: [["2026-11-23", 31.5, 20, "sh1"], ["2026-11-25", 61, 28, "sh2"]],
  gob: [["2026-11-24", 24.5, 30, "gob1"]] };
const book = new Book({ scoring: {}, players, priors: { kd: 50, wcj: 35, sharpe: 30, gob: 38 }, gamelog, weights: { rotowire: 1, model: 0, ctx: 0 } });
const SL = { status: "ok", teams: { "3": { kd: "kd1", wcj: "wcj1", sharpe: "sh2" } } };
const starters = ["kd", "wcj", "sharpe", "gob"];
// the public feed: Durant's slot shows his latest game (48.5), not the locked 63.5; Gobert (not locked) shows 24.5
const matchup = { starters, starters_points: [485, 445, 610, 245], players_points: {}, points: 1785 };
const wp = new WeekPlan({ Q: QS, schedule: sched, week: 6, today: "2026-11-27", now: new Date("2026-11-27T05:00:00Z"), book,
  rosterPositions: ["SF", "C", "C", "UTIL", "BN"], roster: { players: starters }, matchup, rosters: [], tips: {},
  elig: () => true, locks: {}, sleeperLocks: sleeperLocksFor(SL, 3) });
const plan = wp.build();
assert.equal(lockedTotal(plan), 63.5 + 44.5 + 61);                 // 169.0, what Sleeper's app shows
assert.notEqual(lockedTotal(plan), matchup.points / 10);           // not the feed's 178.5
assert.equal(lockedTotal(null), 0);

// the page uses it for the header and the matchup tab, not the feed's points
const app = fs.readFileSync(new URL("../site/app.js", import.meta.url), "utf8");
const header = app.split("\n").find(l => l.includes('$("score").innerHTML'));
assert.ok(header && !/\.points\b/.test(header) && header.includes("lockedTotal"), "header must show the locked total");
const h2h = app.split("\n").filter(l => l.includes("· now</div>"));
assert.equal(h2h.length, 2); for (const l of h2h) assert.ok(!/\.points\b/.test(l) && l.includes("lockedTotal"), l);
console.log("ok: nov 27 score now = locked total");
