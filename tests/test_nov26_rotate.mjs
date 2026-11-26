// Nov 26 (Ryan): "you can't reassign locked slots, but if a player does well we can move that good game to another
// slot and lock him there". Luka (PG) scored 70 sitting in UTIL and has no games left; Murray (PG) holds PG with a
// 10. A C-only bench player has three games left and only UTIL can take him. Locking Luka in UTIL blocks him;
// moving Luka to PG (Murray to UTIL) frees UTIL for the center. The plan must say so, and only with opts.rotate.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, eligFromSnaps } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const [mon, tue, wed, fri, sun] = ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-27", "2026-11-29"];
const g = (date, st, t) => ({ week: 6, date, home: { team: t }, away: { team: "X" + t }, status: st });
const sched = [g(mon, "complete", "DAL"), g(mon, "complete", "DEN"), g(wed, "pre_game", "BOS"), g(fri, "pre_game", "BOS"), g(sun, "pre_game", "BOS")];
const players = { L: ["Luka Doncic", "DAL", ["PG"], null], M: ["Jamal Murray", "DEN", ["PG"], null], C: ["Big Center", "BOS", ["C"], null] };
const gamelog = { L: [[mon, 70, 36, "l1"]], M: [[mon, 10, 30, "m1"]] };
const mk = () => new WeekPlan({ Q: QS, schedule: sched, week: 6, today: tue, now: new Date("2026-11-24T18:00:00Z"),
  book: new Book({ scoring: {}, players, priors: { L: 60, M: 40, C: 42 }, gamelog, weights: { rotowire: 1, model: 0, ctx: 0 } }),
  rosterPositions: ["PG", "UTIL", "BN"], roster: { players: ["M", "L", "C"] },
  matchup: { starters: ["M", "L"], starters_points: [100, 700], players_points: { M: 100, L: 700 } }, rosters: [],
  tips: { [`${wed}|BOS`]: "2026-11-26T00:30:00Z", [`${fri}|BOS`]: "2026-11-28T00:30:00Z", [`${sun}|BOS`]: "2026-11-30T00:30:00Z" },
  elig: eligFromSnaps({ [`${mon}|L`]: { slot: "UTIL", frozen: true }, [`${mon}|M`]: { slot: "PG", frozen: true } }), locks: {} });

const plain = mk().build({}), rot = mk().build({ rotate: true });
assert.equal(plain.rotation, undefined);
assert.equal(rot.rotation.length, 1, JSON.stringify(rot.rotation));
const m = rot.rotation[0];
assert.deepEqual([m.name, m.from, m.to, m.withName], ["Luka Doncic", "UTIL", "PG", "Jamal Murray"]);
assert.ok(rot.outlook.mean > plain.outlook.mean + 20, `${plain.outlook.mean} -> ${rot.outlook.mean}`);
assert.equal(rot.slots[0].pid, "L"); assert.equal(rot.slots[0].movedFrom, "UTIL");
assert.ok(rot.actions.some(a => /^Move Luka Doncic UTIL → PG \(Jamal Murray → UTIL\)/.test(a.text)), rot.actions.map(a => a.text).join(" | "));
console.log(`ok: rotate Luka UTIL -> PG frees UTIL for the center: ${plain.outlook.mean.toFixed(1)} -> ${rot.outlook.mean.toFixed(1)}`);
// nothing to gain: no suggestion (only swaps worth more than ROTATE_MIN)
const flat = new WeekPlan({ ...mk(), Q: QS, schedule: sched.slice(0, 2), week: 6, today: tue, now: new Date("2026-11-24T18:00:00Z"),
  book: new Book({ scoring: {}, players, priors: { L: 60, M: 40, C: 42 }, gamelog, weights: { rotowire: 1, model: 0, ctx: 0 } }),
  rosterPositions: ["PG", "UTIL", "BN"], roster: { players: ["M", "L", "C"] }, matchup: { starters: ["M", "L"], starters_points: [100, 700] }, rosters: [], tips: {},
  elig: eligFromSnaps({ [`${mon}|L`]: { slot: "UTIL", frozen: true }, [`${mon}|M`]: { slot: "PG", frozen: true } }), locks: {} }).build({ rotate: true });
assert.equal(flat.rotation.length, 0, JSON.stringify(flat.rotation));
console.log("ok: no swap suggested when it gains nothing");
