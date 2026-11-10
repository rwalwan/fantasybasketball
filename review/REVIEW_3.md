# Lock Desk: independent review 3

Reviewed 2026-11-10 at commit `6c87d2b` (main) and the `state` branch as of 08:46 UTC.
Everything below was recomputed from the repo's data or code. The scripts are in `review3_analysis.tar.gz`; the fixes and their tests are in `lockdesk_review3_fixes.patch`.

## Bottom line

1. **The x0.90 bar calibration (C7) is an artifact.** The study picks every player's volatility tier with a projection in the wrong units, so all 6,788 starter-weeks were replayed with the bench tier's spread. With the right tiers the best scale is 1.00.
2. **The 99.9% healthy play rate (C6) and the 74% GTD rate (C5) measure the status at tip, not at decision time.** The log rewrites each prediction on every run, so anyone ruled out that afternoon leaves the healthy and GTD groups. The next-game rate this season is 95.8%.
3. **These two errors currently offset.** 0.999 raises bars about 4.6% on last-game decisions and x0.90 lowers them 10%. Fix both together; fixing either alone makes the replay result worse.
4. **Two of this week's calls change.** Ty Jerome's 48 and Onyeka Okongwu's 43.5 are "lock" only because of the x0.90. Unscaled, the engine's own math says pass, by 4.4 and 3.0 points.
5. **The core math is right.** `contStats` matches simulation to 0.004 FP, the Nov 10 bar fix is correct, the blend beats RotoWire held out, and the engine's calls beat always-lock and always-pass on your own graded decisions.

One limit on all of this: Sleeper's API is blocked from where I ran, so I could not refetch box scores. I re-ran the league study from `leagues.sqlite` and `memory.sqlite` in "we back" scoring rather than each league's own. Sample sizes match yours (6,840 starter-weeks, 260 player-weeks against your 6,788 and 258), but the numbers are not identical to a rerun of `league_run.py`.

## 1. Claims C1 to C14

| # | Verdict | My numbers |
|---|---|---|
| C1 | Confirmed | 6 cases (flat, healthy curve, GTD, mixed tiers, one game, volatile bench), 2M simulations each. Largest gap 0.004 FP; Monte Carlo se 0.009 to 0.016. |
| C2 | Confirmed | `test_bar_star.mjs` gives 46.2 at `be21bc5^` and 74.7 at HEAD (unscaled). |
| C3 | Partly | Aggregate holds out of sample: with the 2021-24 tiers and x0.969, shares below the 10/25/50/75/90th pct are .103/.248/.506/.771/.898 (n=1,995, se .007 to .011). By tier it does not: bench tier .073/.175/.427/.710/.848 (n=480), 26-34 tier median share .572 (n=390). The spread is fine; the mean is off by band (G2) and the bands cancel. |
| C4 | Confirmed | Leave-one-day-out MAE 9.044 vs 9.218, n=1,995 over 12 days. Difference 0.174, day-block CI [0.084, 0.242]. Fitting on earlier days only (n=1,281): 0.264 [0.168, 0.329] with the scale. Most of the gain is de-biasing: RotoWire times its own flat scale gets 9.025. |
| C5 | Number confirmed, meaning refuted | GTD 124/158 = 78.5% [71.4, 84.2], DTD 32/35 = 91.4% [77.6, 97.0], blend 0.741. But the 158 are players still GTD at the last run before the game. 97 other records are "Out, missed 0 games so far"; if all began as GTD the first-sight rate is 48.6%. The log cannot say where in 49% to 78% it is. |
| C6 | Number confirmed, use refuted | 1,004/1,005 = 99.9% [99.4, 100]. Same selection. From the game store, rotation players (20+ min) played their team's next game 1,385/1,445 = 95.8% [94.7, 96.8] when not a back-to-back, 297/334 = 88.9% [85.1, 91.9] on one, and 92.3% (n=1,590) two games ahead. Those match your historical curve (0.955, x0.93, 0.923). |
| C7 | Refuted | See finding 1. Correct tiers: best scale 1.00; x0.90 vs x1.00 is -0.98% of projection [-2.32, +0.31]; in 1,000 player-week resamples 1.00 is best in 66% and 0.90 or lower in 6%. With the bug reproduced, x0.90 is +0.11% [-1.18, +1.52]; I could not reproduce your +2.19 [0.37, 4.09] in our scoring. |
| C8 | Confirmed, but it says less than it seems | Engine minus manager +10.2% of projection [6.2, 14.2], n=6,006 starter-weeks, 255 player-weeks. 3.0 points of that come from the 4.8% of starter-weeks where the manager ended on 0. On the same weeks: managers 105.0%, engine 115.2%, never lock 89.9%, "lock the first game at or above its projection" 113.6%. Engine minus that one-line rule: +1.6% [-0.3, +3.6]. |
| C9 | Partly | In-sample 4.630 to 4.541 reproduced. Leave-one-season-out (752 player-seasons): gain 0.065 [0.001, 0.130] over the k=8 blend, but 0.005 [-0.037, +0.048] over the same blend with k=4. After 10 games it is -0.045 [-0.121, +0.029]. Short last seasons (n=153): +0.15 [-0.35, +0.66]. The gain is mostly "8 pseudo-games was too many". |
| C10 | Partly | The quoted rates pool all players. For the under-20-minute players it is applied to: 13.2/33.2/43.8/56.2/69.0/89.4% for 0 to 5 of the last 5 (n = 6,889 to 13,337 each). Production uses the ratio to the 5-of-5 rate, so the error is 1 to 3 points, plus a base of 0.894 rather than 0.944. |
| C11 | Confirmed | Pinball loss -0.26% [-0.32, -0.21] overall, -0.35% [-0.43, -0.28] on the top 30% of quantiles; bootstrap over 605 player-seasons. Small and consistent. |
| C12 | Fit confirmed; live check mixed | `hazard_refit.py` reproduces exactly. This season, Out players with no reported timeline played the following game: after 1 missed 35/68 = 51% (model 48%), 2 missed 7/26 = 27% (29%), 3 missed 9/23 = 39% (24%), 4-8 missed 3/37 = 8% (21%), 9+ missed 7/159 = 4.4% (11.1%). Long absences are returning less than half as often as modeled. |
| C13 | Partly | Research leave-one-season-out reproduces (+0.08 to +0.28 FP). Live it is worse at every horizon: next day +0.18 MAE [-0.10, +0.33] (n=3,873), 2-7 days +0.47 [+0.32, +0.65] (n=1,413), 8-28 days +0.36 [+0.19, +0.58] (n=714). The ordering has signal at 2+ days (slope of actual on predicted lift 0.84 and 0.78) but the level is off (predicted +9%, actual +3%). The gate has it off everywhere, so no production effect today. |
| C14 | Confirmed, limited | Pass -10.4 [-15.6, -5.0] (n=50; 36 player-games), lock -12.4 [-23.4, -2.7] (n=21). Any threshold rule gets negative regret on this metric, so the useful comparison is with trivial rules: per player-game (n=57, 17 players) engine 44.7, always pass 40.1 (-4.6 [-8.8, -0.8]), always lock 38.2 (-6.4 [-10.6, -2.3]). It cannot tell bars 20% apart: 24 calls were near the bar, se 4.1 FP. No graded call was flipped by the matchup override, so that feature has no evidence either way. |

## 2. Findings, ranked by expected points per week

"1% of projection" is about 4.5 FP a week for your ten slots. Findings 1 to 4 have patches and tests; 5 onward are observations.

### 1. Bars are multiplied by 0.90 on the strength of a units bug (C7, G4)

`league_study.tier_q(mu)` compares `mu` with thresholds of 18/26/34/42 "we back" FP per game. In the study `mu` is `leagues.fantasy_points()`, the other league's own scoring divided by 10. The median final starter score in those leagues is 29.5 before the division, so every `mu` is below 10 and every player gets the bench tier (sd 0.80; a star's is 0.27). Only 14 of 793 unique sequences belong there.

- Effect on the study's bars: identical with one game left (n=618), 14.7% too high with two or more left (n=499). Lower scales then look better.
- The same table feeds the opponent model: `humanLockRate` reads `score / own continuation` with correct tiers against bins built with bench-tier continuations, so it reads about one bin high (a 42% lock rate where the data say 25%).
- G4 stands on principle too: the factor is measured on a single player's continuation and applied to a difference of week totals. For Naji Marshall's slot the bar is 41.6 while his own continuation is 29.3.

Failure case, live today: Jerome scored 48 with games of 44.4, 48.0 and 45.9 left. Unscaled bar 52.5, so pass. Published bar 47.2, so "lock". Okongwu: 43.5 against 46.8 unscaled, published 42.1, "lock".

Fix: `study(..., tier_scoring=our scoring)` picks the tier from the projection scored our way; the output carries `tier_units`; `studyBarScale` returns 1 for a study without it. Tests: `test_r3_1_study_tiers.py`, `test_r3_1_bar_scale_guard.mjs`.

Expected impact: x0.90 against x1.00 at correct play rates is -0.98% [-2.32, +0.31], about 4.4 FP a week [-1.4, +10.4]. See finding 2 for why the net today is smaller.

### 2. Play rates are graded on the last status before the game (C5, C6)

`log_and_grade` overwrites a game's open record on every 15-minute run until the game is final. A healthy or GTD player ruled out at 5 pm is graded as "Out". What remains in "healthy" and "GTD" is "still carrying that label at tip", and those rates (99.9%, 78.5%) then become the next-game probability for a game days away.

- Healthy: the engine uses 0.999 for the next game however far off, then 0.92 for the one after. The measured next-game rate is 0.958.
- Replay on the league sequences, next-game q of 0.999 against 0.944: -0.91% of projection [-1.72, -0.26]. A simple calculation gives about -0.3%, so treat the size as 0.3 to 0.9%.
- GTD: 0.741 is used a day or more ahead, where the true rate is somewhere in 49% to 78%.

Failure case: a score of 38.5 with one game left in two days, projection 40. Bar with 0.999 is 40.0, so pass; with 0.958 it is 38.3, so lock. Passing is worth 0.958 x 40 = 38.3.

Fix: the record made when a game becomes the player's next game is the one graded (`first: true`); later news is stored beside it (`last_status`). Day-ahead rates use first-sight records only (0.955 stage rate until 300 are graded; GTD prior 0.612, halfway between published and game-day, worth 50 games). Game-day rates (0.999 healthy, 0.741 GTD) apply only to a game that tips today, through the `daysAhead` argument `playProb` already received and ignored. Tests: `test_r3_2_first_sight.py`, `test_r3_2_gameday.mjs`; two older tests updated.

**Findings 1 and 2 together.** On the replay, relative to production now (0.999 and x0.90):

| Setting | Difference, % of projection |
|---|---|
| 0.955 and x1.00 (both fixed) | +0.32 [-0.52, +1.17] |
| 0.999 and x1.00 (scale fixed only) | -0.42 [-1.58, +0.64] |
| 0.955 and x0.90 (rate fixed only) | -0.17 [-0.47, +0.14] |

So the honest expected gain from both fixes is about +1.4 FP a week, with an interval of -2.3 to +5.3. The case for making them is that both inputs are demonstrably wrong and each will move on its own (the scale switches off the moment the study's interval crosses zero).

### 3. Day-ahead GTD rate: size unknown

Covered by the fix in finding 2; listed separately because the data cannot size it. If the first-sight rate is near 55%, a GTD starter at 40 projected is worth 22 today, not 30, and should sit behind a healthy 27. With roughly two GTD player-games a week on a roster, I would guess 0 to 2 FP a week. About 150 first-sight GTD records will settle it; at the current pace that is two to three weeks.

### 4. A sat game can erase the score in hand, and the engine keeps offering it (G1)

When a starter sits a game while in the lineup, Sleeper sometimes resets the slot to 0 and sometimes keeps the earlier score. `lockState` treats every 0 as a glitch.

Failure case: A scores 35 Monday (passed), sits Wednesday in your lineup, Sleeper shows 0. Engine output: "Lock A, 35.0 beats the best alternative (32.0)". There is no 35 to lock, and the week plan counts it.

Fix: if every copy of the matchup shows 0 and his team has finished a game since his last one that he sat while in the lineup, the state is "none" and the card says the score is gone. A 0 with no such game is still read as a glitch. Test: `test_r3_4_wiped_score.mjs`.

Expected impact: small in points (perhaps 0.3 FP a week), larger in trust: it is an instruction that cannot be followed.

### 5. Keep-line and bar disagree whenever the scale is not 1

Before A's game the plan said "if A scores under 46.9, swap B in". A scored 43.5 and the plan said "lock 43.5" (bar 42.4). About 10% of games land in that band. With the scale at 1 the two agree (46.9 against 47.1). The patch makes the keep-line carry the same factor regardless. Test: `test_r3_3_keep_line.mjs`.

### 6. Today's starters and option value (G5)

The reason given for ranking by expected points is that option value benched Luka and Durant. That came from `val`, which uses `base.Ws[k] + M[ci]`: in the star's own slot this counts his later games twice (about 110 for Luka where the right tail is about 75), so his option value came out near zero. The keep-line was fixed for this (`planLater(t.p, k)`); `val` was not.

With the correct tail, stars and streamers come out close in the cases I worked by hand, so expected points is a reasonable rule and I am not proposing a change. Sizing the difference needs a full-week simulator. Cheapest check: log both rankings for a few weeks and count the slot-days they disagree.

### 7. Smaller items

- **Projection bias by band (G2).** After the blend and x0.969, actual over projected is 1.08 under 18, 0.935 for 18-26 (n=478), 0.972 for 26-34, 0.99 to 1.00 above 34. A flat scale cannot fix this; a scale per band would. Under 0.5 FP a week, mostly on streamers.
- **Long-absence returns (C12).** 4.4% a game against 11.1% modeled raises stash values: over 14 games the model implies an 83% chance of being back where this season's rate implies 47%.
- **`weekTotal` has no streams.** A free agent who would only fill off-days shows a this-week gain of 0. The live plan values streams at 9.0 of 430 FP; the Valuer's bench credit (0.1 x rest-of-season value of the top three) is about 11 a week, so the aggregate is about right but not schedule-aware.
- **Lock certainty.** A lock call can show 50% (GTD, one game left). The shift that makes it average the bar also makes it uninformative near the bar.
- **Move grades.** 48 of 67 graded moves replaced a player who did not play that day. Of the 19 others, 8 were slot reshuffles and 8 show the recommended player at 0.0. Some of those zeros are a date bug: `learn.record` stores `td["tip"][:10]`, the UTC date, so a game tipping after 7 pm ET is looked up a day late and graded as 0 (Jerome's Oct 29 game, 24.0, tipped at 02:00 UTC and is graded under Oct 30 as 0.0). The move grades say nothing about lineup choices yet.

## 3. Known gaps G1 to G6

**G1. Matters, and Sleeper does both.** From the league snapshots, for player-games where a starter with a score in hand sat a mid-week game (5+ leagues each): the slot went to 0 in every league for 17, kept the score in every league for 9, mixed for 5. It is uniform across leagues, so it is a property of the game record, not of the manager. My guess is active-but-did-not-play against inactive; your `week_stats` rows with `min` = 0 would show it, and the 31 player-dates are listed by `g1c.py`. At week's end: 246 zeros against 214 kept.
Two things follow. The engine's "0" is right about 60% of the time, so the +0.5 to 1.5 FP you estimated is about 40% of that. And a passed score survives a trip to the bench: of 246 cases where a player left the lineup and came back without playing, 161 still had the score (146 of them while someone else played from that slot), 72 had lost it and 13 showed a different one. So benching a player who is ruled out protects his score. For a manager who never reacts, that is worth 1.5% of projection [0.6, 2.6]; the engine already catches the last-game case by dropping the bar when he is ruled out.

**G2. Real, and not selection for the band that matters.** RotoWire runs 11% high at 18-26 [7, 14], 9% at 26-34 [6, 11], 6.5% at 34-42 [3, 10], 5% at 42-60 [2, 8]. Conditioning on games played raises actuals, so selection works against this finding. The low band is partly selection: a row exists only if he played, and the players projected under 10 who got real minutes pull that band to +67%.

**G3. Too thin.** 30 graded rows are 12 matchups. Favourites were given 77% and won 63%; Brier 0.175. With 12 matchups a calibrated model produces a gap that large about one time in eight. Telling 77% from 65% takes about 100 matchups, roughly 17 weeks. There is a structural reason to expect overconfidence: the variance has only game-to-game spread per slot, with no projection error shared across a team's slots.

**G4.** See finding 1. If a calibration is ever needed, apply it to the inputs (projection by band, play rates), which every component then shares, rather than to the bar.

**G5.** See finding 6.

**G6. Confirmed.** On 46 followed pass calls the slot ended 14.0 above the passed score [10.2, 18.2] while the same-player replay gives 9.9. Rotation added about 4 FP per passed slot that the grade does not see.

## 4. What is still too thin to call

| Question | Have | Need |
|---|---|---|
| Bar scale to within 1% of projection | 260 player-weeks, CI half-width 1.3 | about 1,000 player-weeks: 6 more weeks of snapshots |
| Bar scale to within 0.3% | same | about 2,000: the rest of the season |
| GTD play rate a day ahead | 0 first-sight records | 150: two to three weeks |
| Win-chance calibration | 12 matchups | about 100 |
| Matchup override | 0 flipped calls graded | 30 or more flips |
| Engine against a one-line threshold rule | +1.6% [-0.3, +3.6] | about 1,000 player-weeks |

## 5. The patch

`lockdesk_review3_fixes.patch` applies to `6c87d2b` with `git am` or `git apply`. Each new test fails on `6c87d2b` and passes after; the full suite (`tests/run_all.sh`) passes after.

| Test | Before | After |
|---|---|---|
| `test_r3_1_study_tiers.py` | star's lock graded in the 0.85-1.00 bin | 1.00-1.15 |
| `test_r3_1_bar_scale_guard.mjs` | published study scales bars by 0.90 | 1 |
| `test_r3_2_first_sight.py` | healthy player ruled out later is graded "Out"; 1,000 last-status records set the rate to 0.999 | graded healthy and sat; rate from first-sight records |
| `test_r3_2_gameday.mjs` | 0.999 for a game two days away | 0.96; 0.999 only for a game today |
| `test_r3_3_keep_line.mjs` | keep-line 46.9, bar after the game 42.4 | 42.2 and 42.4 |
| `test_r3_4_wiped_score.mjs` | "Lock 35.0" with the slot at 0 | no lockable score; card says why |

Three existing tests encoded the old behaviour and are updated in the patch: `test_lock_options.mjs`, `test_r2_f2_next_game.py`, `test_designation_calibration.py`.

After deploying: bars are unscaled at once (the published study has no `tier_units`); the next daily league run recomputes the study with correct tiers and the scale returns only if its interval excludes zero. The lock-rate bins for the opponent model are corrected by the same run. Old availability records keep feeding the game-day rates; day-ahead rates start from the priors above.

One judgment call in the patch: the day-ahead GTD prior of 0.612. The published first-report rate (0.483) and the game-day rate (0.741) bracket the plausible range, and I took the midpoint. Change `prior` in `calibrate_designations` if you would rather start from one end.

## 6. Week simulator: what the slot plan leaves on the table

Added after the review. `tools/week_sim.mjs` plays whole weeks with the real engine (`WeekPlan.build` every morning and after every night's games, its lineup and lock calls followed to the letter) and plays the same weeks with looser policies. Roster and slots are the published plan's (15 players, 10 slots). Every player plays every game, there are no back-to-backs and one tip time a day; those simplifications apply to every policy alike. Harness check: with one player and one slot the engine followed to the letter averages his `contStats` value (48.59 against 48.62 over 3,000 weeks).

400 weeks, points per week:

| Policy | Mean | Against the engine |
|---|---|---|
| Engine, followed to the letter | 608.0 | its own Monday forecast is 605.6; realized minus forecast +2.4 [-1.5, +6.3] |
| Defer: any player in any open slot each day, lock decided at the player's next tip | 608.6 | +0.6 [-1.4, +2.7]; +3.1 [0.1, 6.0] with its threshold tuned |
| Hold: nobody locked until the week ends, each player stops on his own, best ten that fit count | 622.8 | +14.8 [12.9, 16.7] |
| Perfect hindsight (not reachable) | 653.6 | +45.6 [43.1, 48.1] |

What this says:

- **The engine's plan value is honest.** What it forecasts on Monday is what it scores.
- **Under the rule the engine assumes (a score in hand is gone at the player's next team game), the slot system leaves 0 to 3 points a week.** Free daily assignment and deferring the lock to the deadline add almost nothing over the current plan.
- **If a score survives while the player sits on the bench through his own later games, holding instead of locking is worth about 15 points a week.** Then nobody needs a slot until Sunday, all 15 players get a full stopping problem, and the best ten count. The engine's `lockState` already reads Sleeper that way ("latest countable game"), but the league snapshots cannot confirm it: of 315 players benched with a score in hand who played while out of the morning lineup, 285 came back showing a different score and 26 the old one, and a morning snapshot cannot tell a bench game from a late lineup change. One deliberate test in your own league settles it: bench a player holding an unlocked score through his next game, put him back, and see which score the slot shows.
- **In this simulated world, bars at x0.90 cost 7.3 points a week [4.3, 10.3]** (250 weeks). The world is the engine's own model, so this is the cost if the model is right; the league replay in finding 1 put it at about 4.4.

Usage: `node tools/week_sim.mjs [weeks] [seed]`. Test: `tests/test_r3_5_week_sim.mjs`.
