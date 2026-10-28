// Win-chance calibration (review 2, finding 6). A matchup-week has one outcome, so daily predictions are not
// independent samples: keep ONE prediction per matchup per stage of the week and grade each stage separately,
// counting matchups, not predictions.
export const STAGES = [["start (6-7 days left)", 6, 7], ["middle (3-5 days left)", 3, 5], ["end (1-2 days left)", 1, 2]];
export const stageOf = daysLeft => (STAGES.find(([, lo, hi]) => daysLeft >= lo && daysLeft <= hi) || [null])[0];

export function calibration(graded) {
  const out = { matchups: new Set(graded.map(x => `${x.week}|${x.mid}`)).size, by_stage: {} };
  for (const [name] of STAGES) {
    const g = graded.filter(x => x.stage === name);
    if (!g.length) continue;
    const bins = {};
    for (const x of g) {
      const pf = Math.max(x.p_a, 1 - x.p_a), b = Math.min(4, Math.floor(pf * 10) - 5), fav = x.p_a >= 0.5 ? x.a_won : !x.a_won;
      const k = `${50 + b * 10}-${60 + b * 10}%`;
      (bins[k] ||= { n: 0, pred: 0, won: 0 }); bins[k].n++; bins[k].pred += pf; bins[k].won += fav;
    }
    out.by_stage[name] = { matchups: g.length,
      brier: Math.round(1000 * g.reduce((a, x) => a + (x.p_a - (x.a_won ? 1 : 0)) ** 2, 0) / g.length) / 1000,
      favorite_by_bin: Object.fromEntries(Object.entries(bins).sort().map(([k, v]) => [k, { n: v.n, predicted: Math.round(100 * v.pred / v.n), won: Math.round(100 * v.won / v.n) }])) };
  }
  return out;
}
