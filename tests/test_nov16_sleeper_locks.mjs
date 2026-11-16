// Nov 16: Sleeper's own lock record (the app's GraphQL get_matchup_legs, starters_games = player -> locked game id),
// read by the backend with Ryan's login. Week 4 capture (Nov 15, 9 pm): the public API showed the opponent's Keyonte
// George at 38 (his Sunday game) though he was locked on Nov 13's 54.5, and one host showed Grayson Allen at 35 though
// he was locked on Nov 9's 56. The record must win over the slot score, and a starter missing from it is not locked.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, sleeperLocksFor } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const g = (date, t) => ({ week: 4, date, home: { team: t }, away: { team: "XXX" }, status: "complete" });
const sched = [g("2026-11-09", "CHA"), g("2026-11-12", "CHA"), g("2026-11-15", "CHA"),
               g("2026-11-11", "UTA"), g("2026-11-13", "UTA"), g("2026-11-15", "UTA")];
const players = { allen: ["Allen", "CHA", ["SG"], null], george: ["George", "UTA", ["PG"], null], kess: ["Kessler", "UTA", ["C"], null] };
const gamelog = {
  allen: [["2026-11-09", 56, 30, "1393723842827911168"], ["2026-11-12", 39.5, 30, "1393723865997246464"], ["2026-11-15", 35, 30, "1393723875283435520"]],
  george: [["2026-11-11", 43, 30, "1393723860750172160"], ["2026-11-13", 54.5, 34, "1393301036038381568"], ["2026-11-15", 38, 32, "1393723875237298176"]],
  kess: [["2026-11-11", 54, 30, "k1"], ["2026-11-13", 43, 30, "k2"], ["2026-11-15", 50.5, 30, "k3"]] };
const book = new Book({ scoring: {}, players, priors: { allen: 30, george: 40, kess: 40 }, gamelog, weights: { rotowire: 1, model: 0, ctx: 0 } });
const mk = (starters, pts, sleeperLocks) => new WeekPlan({ Q: QS, schedule: sched, week: 4, today: "2026-11-15", now: new Date("2026-11-16T05:00:00Z"), book,
  rosterPositions: ["PG", "SG", "C", "BN"], roster: { players: starters }, matchup: { starters, starters_points: pts, players_points: {} },
  rosters: [], tips: {}, elig: () => true, locks: {}, sleeperLocks });

// the backend's record as it would arrive (status ok), team 2 = opponent, team 3 = us
const SL = { status: "ok", teams: { "2": { george: "1393301036038381568" }, "3": { allen: "1393723842827911168" } } };
const opp = mk(["george", "x", "kess"], [380, 0, 430], sleeperLocksFor(SL, 2));
assert.equal(opp.lockState("george").st, "locked"); assert.equal(opp.lockState("george").g.fp, 54.5);
// Kessler isn't in the record: not locked, even though his slot shows an earlier game (43) than his latest (50.5),
// which the slot-score guess would have called a lock
assert.notEqual(opp.lockState("kess").st, "locked");
const me = mk(["x", "allen", "y"], [0, 350, 0], sleeperLocksFor(SL, 3));
assert.equal(me.lockState("allen").st, "locked"); assert.equal(me.lockState("allen").g.fp, 56);
// the opponent's final: George's 54.5 counts, not the 38 the public slot score shows
const total = opp.build().outlook.mean;
assert.ok(Math.abs(total - (54.5 + 50.5)) < 0.01, total);
// feed down (bad token) -> null -> the old behaviour (slot-score guess) takes over
assert.equal(sleeperLocksFor({ status: "Unauthorized", teams: null }, 2), null);
assert.equal(mk(["george", "x", "kess"], [380, 0, 430], null).lockState("kess").st, "locked");   // the guess
console.log("ok: nov 16 sleeper locks");
