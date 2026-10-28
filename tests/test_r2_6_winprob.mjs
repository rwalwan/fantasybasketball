// Review 2, finding 6: the win-chance log kept a prediction per matchup per DAY (up to 7 correlated predictions,
// one outcome) and reported them as the sample size. Now: one prediction per matchup per stage of the week, graded
// per stage, sample size = matchups.
import assert from "node:assert/strict";
import { stageOf, calibration } from "../tools/winprob.mjs";

assert.equal(stageOf(7), stageOf(6)); assert.equal(stageOf(5), stageOf(3)); assert.equal(stageOf(2), stageOf(1));
assert.notEqual(stageOf(7), stageOf(4)); assert.equal(stageOf(0), null);
// one matchup-week logged on 7 days used to count as 7 predictions; it is 3 stage predictions and 1 matchup
const g = [7, 4, 1].map(d => ({ week: 2, mid: "1", stage: stageOf(d), p_a: 0.7, a_won: true }));
const c = calibration(g);
console.log(JSON.stringify(c));
assert.equal(c.matchups, 1);
assert.deepEqual(Object.values(c.by_stage).map(v => v.matchups), [1, 1, 1]);
assert.equal(c.by_stage[stageOf(7)].favorite_by_bin["70-80%"].won, 100);
console.log("ok: review 2 finding 6");
