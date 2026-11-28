// Nov 28: the upside model in the engine (app/upside.py via static/learned.json, absence factors via static/absence.json).
// Case: Fri Nov 27, Queta scored 70.5 from Ryan's bench with Boston's other center out. On this season's graded games,
// games the absence model put at 1.35x+ minutes went 1.5x their projection 41% of the time (13% otherwise). So a game
// in a big-absence bucket gets a higher projection (the bucket's mean) and a longer top end (its range), the
// lock-in values that read the range (contValues) rise with it, and a game in the normal bucket is untouched.
import assert from "node:assert/strict";
import fs from "node:fs";
import { Book, Valuer, contValues } from "../site/engine.js";

const raw = JSON.parse(fs.readFileSync(new URL("../app/data/upside_model.json", import.meta.url)));
const mean = Object.fromEntries(Object.keys(raw.g).map(b => [b, raw.g[b].reduce((a, v, i) => a + v * raw.base[i], 0) / raw.base.reduce((a, v) => a + v, 0)]));
const upside = { edges: raw.edges, taus: raw.taus, g: raw.g, mean };
const QS = JSON.parse(fs.readFileSync(new URL("../app/data/game_ratio_quantiles.json", import.meta.url)));
const absence = { Q: { "2026-11-27": [1.4, ["Mitchell Robinson out: +6 min"]], "2026-11-29": [1.03] } };
const mk = (extra = {}) => new Book({ scoring: {}, players: { Q: ["Neemias Queta", "BOS", ["C"], null] }, priors: { Q: 30 }, gamelog: {},
  weights: { rotowire: 0, model: 1, ctx: 0 }, ...extra });
const book = mk({ absence, upside }), plain = mk();

// the bucket: 1.4 is past the 1.35 edge (bucket 4); 1.03 is normal
assert.equal(book.situB("Q", "2026-11-27"), 4);
assert.equal(book.situB("Q", "2026-11-29"), 1);
assert.equal(plain.situB("Q", "2026-11-27"), null, "no model loaded: no change");
// the projection moves by the bucket's mean multiplier, only that night
assert.ok(mean[4] > 1.1, `big-absence games run hotter (x${mean[4]})`);
assert.equal(book.gameMu("Q", "2026-11-27"), Math.round(30 * mean[4] * 10) / 10);
assert.equal(book.gameMu("Q", "2026-11-29"), 30);
assert.equal(plain.gameMu("Q", "2026-11-27"), 30);
// the range: mean 1 (the mean moved the projection), sorted, and a longer top end than the normal range
const Q = QS.quantiles, Qb = book.situQ("Q", "2026-11-27", Q);
assert.equal(Qb.length, Q.length);
assert.ok(Math.abs(Qb.reduce((a, v) => a + v, 0) / Qb.length - 1) < 1e-9);
assert.ok(Qb.every((v, i) => !i || v >= Qb[i - 1]), "still sorted");
assert.strictEqual(book.situQ("Q", "2026-11-29", Q), Q, "normal bucket: the same range");
// the chance of a 1.5x-projection game (vs his usual projection) goes up
const p15 = (qs, mu) => qs.filter(r => mu * r >= 45).length / qs.length;
assert.ok(p15(Qb, book.gameMu("Q", "2026-11-27")) > p15(Q, 30) + 0.03, `${p15(Qb, 33.7)} vs ${p15(Q, 30)}`);
// lock-in value of that game (what a lock bar or a start reads) rises by more than the mean alone
const one = (qs, mu) => contValues(qs, [{ mu, q: 1, Q: qs }])[0];
assert.ok(one(Qb, book.gameMu("Q", "2026-11-27")) > one(Q, 30));
// season values (waivers, trades) use it too
const sched = [{ week: 6, date: "2026-11-27", home: { team: "BOS" }, away: { team: "ATL" }, status: "pre_game" }];
const v = b => new Valuer({ book: b, schedule: sched, Q: QS, rosterPositions: ["C"], week: 5, today: "2026-11-24" }).weekly("Q")[0];
assert.ok(v(book) > v(plain) * 1.1, `${v(book)} vs ${v(plain)}`);
console.log("ok: Nov 28 upside (engine)");
