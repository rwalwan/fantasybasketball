// Review 3, finding 1: the x0.90 bar calibration came from a study whose bars used the bench volatility tier for
// every player (app/league_study.py picked the tier with a projection in the wrong units; tests/test_r3_1_study_tiers.py).
// A study that doesn't say which units its tiers used must not scale the bars; the published one doesn't.
import assert from "node:assert/strict";
import fs from "node:fs";
import { studyBarScale } from "../site/engine.js";

const old = { best_scale: { scale: 0.9, ci95_vs_current: [0.37, 4.09] } };
assert.equal(studyBarScale(old), 1, "a study without tier_units must not move the bars");
assert.equal(studyBarScale({ ...old, tier_units: "we back FP/G" }), 0.9, "a fixed study with a significant result still does");
assert.equal(studyBarScale({ tier_units: "we back FP/G", best_scale: { scale: 0.9, ci95_vs_current: [-0.5, 3] } }), 1);
const published = JSON.parse(fs.readFileSync(new URL("../review/data/league_study.json", import.meta.url)));
assert.equal(studyBarScale(published), 1, "the Nov 9 study (bench-tier bars) must not be applied");
console.log("ok: review 3 finding 1 (bar scale guard)");
