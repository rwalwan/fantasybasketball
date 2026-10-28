// Finding 10 (review 2026-10-28): season value covered the wrong weeks. League settings: playoffs start week 22
// with 8 teams (three one-week rounds: 22-24), trade deadline week 18. The Valuer counted every remaining NBA
// week (incl. week 25, after the championship) and weighted playoff weeks 0.97^19-21 = 0.53-0.56 of next week.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, Valuer, tradeIdeas } from "../site/engine.js";
const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const sched = [];
for (let w = 2; w <= 25; w++) { const d = new Date(Date.UTC(2026, 9, 26 + (w - 2) * 7)).toISOString().slice(0, 10);
  sched.push({ week: w, date: d, home: { team: "AAA" }, away: { team: "BBB" }, status: "pre_game" }); }
const settings = { playoff_week_start: 22, playoff_teams: 8, trade_deadline: 18 };
const book = new Book({ scoring: {}, players: { P: ["P", "AAA", ["SF"], null] }, priors: { P: 40 }, gamelog: {} });
const v = new Valuer({ book, schedule: sched, Q: QS, rosterPositions: ["SF", "BN"], week: 1, today: "2026-10-20", settings });
const ws = v.weeks.map(x => x.w);
console.log("weeks", ws[0], "..", ws.at(-1), "| playoff weights", v.weeks.filter(x => x.w >= 22).map(x => x.disc));
assert.equal(ws.at(-1), 24, "stop at the championship week");
assert.ok(v.weeks.filter(x => x.w >= 22).every(x => x.disc === 1), "playoff weeks count fully");
// no trade ideas after the deadline
const late = new Valuer({ book, schedule: sched, Q: QS, rosterPositions: ["SF", "BN"], week: 19, today: "2027-03-01", settings });
assert.deepEqual(tradeIdeas(late, book, { players: ["P"] }, [{ roster_id: 2, players: ["P"] }]), []);
console.log("ok: finding 10");
