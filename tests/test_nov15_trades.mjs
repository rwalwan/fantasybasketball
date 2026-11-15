// Nov 15 trade rework. Sleeper (help page, Lock-In): "You can only earn points for games after the trade. Previous points
// stay with the original team" (a locked score stays with the team that locked it). The old search valued trades from
// next week on only, so a deal that swaps a player whose week is done for one with games left was invisible.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, Valuer, tradeIdeas, WINS_PER_SCORE } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const today = "2026-11-12";                                        // Thursday of week 4 (Mon Nov 9 - Sun Nov 15)
const sched = [];
const add = (week, date, team, status = "pre_game") => sched.push({ week, date, home: { team }, away: { team: "ZZZ" }, status });
add(4, "2026-11-09", "AAA", "complete");                           // X (AAA): played Monday, nothing left this week
add(4, "2026-11-13", "BBB"); add(4, "2026-11-14", "BBB");          // Y (BBB): Fri + Sat left
for (let w = 5; w <= 20; w++) for (const t of ["AAA", "BBB", "CCC"]) for (const k of [0, 2, 4])
  add(w, new Date(Date.UTC(2026, 10, 16 + (w - 5) * 7 + k)).toISOString().slice(0, 10), t);
const players = { X: ["X", "AAA", ["SF"], null], Y: ["Y", "BBB", ["SF"], null], M: ["M", "CCC", ["SF"], null], N: ["N", "CCC", ["SF"], null] };
const gamelog = { X: [["2026-11-09", 44, 34, "x"]] };
const book = new Book({ scoring: {}, players, priors: { X: 35, Y: 35, M: 30, N: 30 }, gamelog, weights: { rotowire: 1, model: 0, ctx: 0 } });
const RP = ["SF", "UTIL", "BN"];
const me = { roster_id: 1, owner_id: "me", players: ["X", "M"], reserve: [] }, them = { roster_id: 3, owner_id: "t", players: ["Y", "N"], reserve: [] };
const tips = { "2026-11-13|BBB": "2026-11-14T00:00:00Z", "2026-11-14|BBB": "2026-11-15T00:00:00Z" };
const plan = (roster, starters, locks = {}) => new WeekPlan({ Q: QS, schedule: sched, week: 4, today, now: new Date("2026-11-12T20:00:00Z"), book,
  rosterPositions: RP, roster, matchup: { starters, players_points: {}, starters_points: [] }, rosters: [me, them], tips, elig: () => true, locks });
const myWp = plan(me, ["X", "M"], { X: true, "X|2026-11-09": true }), thWp = plan(them, ["Y", "N"]);
const valuer = new Valuer({ book, schedule: sched, Q: QS, rosterPositions: RP, week: 4, today, settings: {}, freeAgents: [] });

// 1) a locked starter traded away keeps his slot (the old weekTotal reopened it and refilled it)
assert.equal(myWp.lockState("X").st, "locked");
const before = myWp.weekTotal(["X", "M"]), after = myWp.weekTotal(["Y", "M"], { outgoing: ["X"] });
assert.ok(after - before > 20, `Y's two games now fill the SF/UTIL slot M doesn't use: ${before.toFixed(1)} -> ${after.toFixed(1)}`);
const naive = myWp.weekTotal(["M"]);
assert.ok(naive <= before + 1e-9, "trading X for nothing changes nothing this week: his slot stays locked");
// 2) review period: a deal that goes through Saturday only gets Y's Saturday game
const sat = myWp.weekTotal(["Y", "M"], { from: "2026-11-14", outgoing: ["X"] });
assert.ok(sat > before && sat < after, `${before.toFixed(1)} < ${sat.toFixed(1)} < ${after.toFixed(1)}`);
assert.equal(myWp.weekTotal(["Y", "M"], { from: "2026-11-16", outgoing: ["X"] }), before);
// a player on IR who is part of the deal doesn't start playing this week because he's leaving (Nov 15 live run:
// their side showed +23.5 pts this week for a deal that only goes through next week)
const irWp = plan({ ...me, players: ["X", "M", "Y"], reserve: ["Y"] }, ["X", "M"], { X: true, "X|2026-11-09": true });
assert.equal(irWp.weekTotal(["X", "M"], { from: "2026-11-16", outgoing: ["Y"] }), irWp.weekTotal(["X", "M", "Y"]));

// 3) the search: equal rest-of-season value, so only this week separates them
const ctx = (theirMean, theirOpp) => ({ S: 500, from: null, weekOf: {
  1: { wp: myWp, mean: 300, var: 900, opp: 2 }, 2: { wp: null, mean: 300, var: 900, opp: 1 },
  3: { wp: thWp, mean: theirMean, var: 900, opp: 4 }, 4: { wp: null, mean: theirOpp, var: 900, opp: 3 } } });
// their week is lost (way behind): giving up Y's two games costs them ~nothing, and our close week gains a lot
const lost = tradeIdeas(valuer, book, me, [them], 10, ctx(200, 400));
const d = lost.find(x => x.give.join() === "X" && x.get.join() === "Y");
assert.ok(d, "X (week done) for Y (2 games left) is offered when their week is lost: " + JSON.stringify(lost.map(x => [x.give, x.get])));
assert.ok(d.winsWeekMe > 0.1 && Math.abs(d.winsRosMe) < 0.1 && d.winsThem >= 0, JSON.stringify(d));
console.log(`X for Y: this week +${d.myWeek.toFixed(1)} pts, win chance +${(d.winsWeekMe * 100).toFixed(1)}%, season ${d.winsRosMe.toFixed(3)} wins; them ${d.winsThem.toFixed(3)}`);
// their week is a coin flip: Y's games matter to them, so they lose wins -> not offered
const close = tradeIdeas(valuer, book, me, [them], 10, ctx(300, 300));
assert.ok(!close.some(x => x.give.join() === "X" && x.get.join() === "Y"), "not offered when it costs them their week");
// without the week context (the old behaviour) the deal is invisible
assert.ok(!tradeIdeas(valuer, book, me, [them], 10).some(x => x.give.join() === "X" && x.get.join() === "Y"));
assert.ok(WINS_PER_SCORE > 1.5 && WINS_PER_SCORE < 3);
console.log("ok: nov 15 trades");
