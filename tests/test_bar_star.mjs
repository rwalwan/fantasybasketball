// Nov 10 review: a lock bar is what the slot + the player are worth for the rest of the week. The 'lock' side let
// the locked player's own later games fill other slots, so Luka's bar read 46 while his two games alone were worth 75.
// Bar must be at least the player's own continuation when he's the slot's best option.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, WeekPlan, contStats, tierQ } from "../site/engine.js";

const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const d = ["2026-11-09", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-15"];
const G = (date, t, st = "pre_game") => ({ week: 4, date, home: { team: t }, away: { team: "X" + t }, status: st });
const sched = [G(d[0], "LAL", "complete"), G(d[1], "LAL"), G(d[4], "LAL"), G(d[2], "BOS"), G(d[3], "BOS"), G(d[1], "ATL"), G(d[3], "ATL")];
const book = new Book({ scoring: {}, weights: { rotowire: 1, model: 0, ctx: 0 },
  players: { L: ["Luka", "LAL", ["PG", "SG"], null], W: ["White", "BOS", ["PG", "SG"], null], O: ["Okongwu", "ATL", ["C", "PF"], null] },
  priors: { L: 70, W: 38, O: 40 }, gamelog: { L: [[d[0], 83.5, 36, "g"]] } });
book.proj = { [`L|${d[1]}`]: 70.1, [`L|${d[4]}`]: 70.8, [`W|${d[2]}`]: 38, [`W|${d[3]}`]: 38, [`O|${d[1]}`]: 40, [`O|${d[3]}`]: 40 };
const tips = {}; for (const g of sched) tips[`${g.date}|${g.home.team}`] = `${g.date}T23:30:00Z`;
const wp = new WeekPlan({ Q: QS, book, schedule: sched, week: 4, today: "2026-11-10", now: new Date("2026-11-10T18:00:00Z"),
  rosterPositions: ["PG", "UTIL", "BN"], roster: { players: ["L", "W", "O"] }, matchup: { starters: ["L", "O"], players_points: { L: 835 }, starters_points: [835, 0] },
  rosters: [], tips, elig: () => true, locks: {} });
const s = wp.build().slots.find(x => x.slot === "PG");
const own = contStats(QS.quantiles, [{ mu: 70.1, q: 0.94, Q: tierQ(QS.tiers, 70, QS.quantiles) }, { mu: 70.8, q: 0.92, Q: tierQ(QS.tiers, 70, QS.quantiles) }]).W[0];
console.log("Luka: score", s.score, "bar", s.bar, "| his own two games", own.toFixed(1), "| call", s.action);
assert.ok(s.bar >= own - 3, `bar ${s.bar} should be about his own rest-of-week value ${own.toFixed(1)} or more`);
assert.equal(s.action, "lock");
console.log("ok: star bar");
