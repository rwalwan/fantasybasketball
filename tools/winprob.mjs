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

// Grade logged predictions of finished weeks. A week is graded only once it has SETTLED (SETTLE_DAYS after its last
// day): right after the week flips, the public feed's matchup points can still sum each starter's latest game rather
// than the game locked in his slot (Nov 27: week 5's decision grades read the feed that way). Graded weeks from before
// this rule are regraded once (log.settled_v). lastDay(w) = the week's last date; finals(w) = that week's matchups.
export const SETTLE_DAYS = 2;
const plusDays = (d, n) => { const x = new Date(d + "T12:00:00Z"); x.setUTCDate(x.getUTCDate() + n); return x.toISOString().slice(0, 10); };
export async function gradeWeeks(log, week, today, lastDay, finals) {
  const settled = w => { const d = lastDay(w); return !!d && plusDays(d, SETTLE_DAYS) <= today; };
  if (!log.settled_v) {                                  // one-time: put graded entries back to be graded on settled scores
    for (const x of log.graded || []) { const { a_won, ...o } = x; log.open[`${o.week}|${o.stage}|${o.mid}`] = o; }
    log.graded = []; log.settled_v = 1;
  }
  for (const w of [...new Set(Object.values(log.open).map(x => x.week))].filter(w => w < week && settled(w))) {
    const fin = await finals(w);
    const pts = Object.fromEntries(fin.map(m => [m.roster_id, m.points]));
    for (const [k, x] of Object.entries(log.open)) if (x.week === w) {
      if (pts[x.a] != null && pts[x.b] != null && pts[x.a] !== pts[x.b]) log.graded.push({ ...x, a_won: pts[x.a] > pts[x.b] });
      delete log.open[k];
    }
  }
  return log;
}
