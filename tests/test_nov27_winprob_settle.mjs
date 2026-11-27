// Nov 27: win-chance predictions were graded with the public feed's matchup points as soon as the week flipped. Right
// after the flip the feed can still sum each starter's latest game instead of the game locked in his slot (week 5's
// decision grades read three of Ryan's locks that way; week 6 mid-week the feed said 387.5 for a team Sleeper's app had
// at 169.0), so a winner can be read wrong. Rule: grade a week only 2 days after its last day, and regrade weeks
// graded before this rule once, on the settled scores.
import assert from "node:assert/strict";
import { gradeWeeks } from "../tools/winprob.mjs";

const last = { 5: "2026-11-22", 6: "2026-11-29" };
const feed = { 5: [{ roster_id: 1, points: 4000 }, { roster_id: 2, points: 3900 }] };
const finals = async w => feed[w];
const log = { open: { "5|end (1-2 days left)|1": { week: 5, mid: "1", stage: "end (1-2 days left)", a: 1, b: 2, p_a: 0.3 } },
              graded: [{ week: 4, mid: "1", stage: "end (1-2 days left)", a: 1, b: 2, p_a: 0.6, a_won: false }] };
feed[4] = [{ roster_id: 1, points: 5000 }, { roster_id: 2, points: 4000 }];    // week 4 settled: team 1 won after all
last[4] = "2026-11-15";
// Monday Nov 23: week 5 not settled yet; week 4 (graded before the rule) is regraded on its settled score
await gradeWeeks(log, 6, "2026-11-23", w => last[w], finals);
assert.equal(log.graded.length, 1); assert.equal(log.graded[0].week, 4); assert.equal(log.graded[0].a_won, true);
assert.ok(log.open["5|end (1-2 days left)|1"], "week 5 waits for the settle");
// Tuesday Nov 24: settled -> graded
feed[5] = [{ roster_id: 1, points: 3000 }, { roster_id: 2, points: 3900 }];
await gradeWeeks(log, 6, "2026-11-24", w => last[w], finals);
assert.equal(log.graded.length, 2); assert.equal(log.graded[1].a_won, false);
assert.equal(Object.keys(log.open).length, 0);
// the one-time regrade doesn't repeat
await gradeWeeks(log, 6, "2026-11-25", w => last[w], finals);
assert.equal(log.graded.length, 2);
console.log("ok: nov 27 win-chance grading waits for settled scores");
