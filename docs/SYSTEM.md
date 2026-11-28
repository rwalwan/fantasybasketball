# Lock Desk: how the system works

How the system works **today**: the game rules it plays by, the pieces, how data moves, how each decision is
made, what each data file holds, and the decisions that shaped it, each with its evidence. Where a rule is enforced
by a test, the test is named; that test is the spec. How to work on the repo is in [`../CLAUDE.md`](../CLAUDE.md).

Numbers marked "as of" are measurements from that date. Re-measure before relying on one.

## 1. The game: Sleeper Lock-In rules

The league is **we back (TBK)**: Sleeper league `1400915575915491328`, 12 teams, head-to-head weekly matchups.
Ryan is `roster_id` 3. Starting slots: `PG, SG, G, SF, PF, F, C, C, UTIL, UTIL` (10), plus bench and IR. A player
fits a slot if one of his positions is in `ELIGIBLE[slot]` (`site/engine.js`).

What follows is what the engine assumes. Each rule is either Ryan's statement about how Sleeper behaves or
something measured in Sleeper's data, and the source is noted.

1. **One game per slot per week.** Each starting slot ends the week with the score of exactly one game.
2. **Lock or pass.** After a starter's game ends, the manager can lock that score into the slot; the slot is then
   done for the week. **A lock can't be moved or undone, and a locked slot can't be reassigned.** (Ryan)
3. **What's lockable:** a game is lockable only if the player was in a **starting slot when it tipped** and has
   **not been moved to the bench since the game began**. Moving him to the bench, even briefly and even if he's moved
   back, makes that game unlockable. Moving between starting slots is fine. (Ryan's Sleeper screenshot, Nov 15:
   Okongwu played from UTIL, was benched, then put at C, and Sleeper showed "ineligible".)
   Tests: `test_nov15_slot_lock.mjs`, `test_nov15_lineup_benched.py`, `test_nov26_bench_trip.mjs`.
   **Sleeper doesn't publish this answer** (checked Nov 26: every `MatchupLeg` field logged in and out, including
   `subs`, `bans`, `starters_by_date` and `players_by_date`, which come back null; all 241 GraphQL queries; and
   `league_event_logs`, which holds only commissioner edits). So Lock Desk rebuilds it from lineup samples, and a bench
   trip between two samples is invisible (Nov 26: Cam Spencer's Wed game, the opponent's Zach Edey).
4. **An unlocked score moves with its player.** A finished, unlocked, lockable game can be moved with the player to any
   other starting slot he fits and locked there. (Ryan, Nov 26.) This is what rotation (section 4.5) exploits.
   Test: `test_nov26_rotate.mjs`.
5. **If a slot is never locked,** Sleeper scores it with its player's **latest countable game** (a game played from a
   starting slot). If he then sits a game *while in the lineup*, that DNP can become the slot's game and the slot shows 0
   (measured in other Lock-In leagues: 423 of 1,200 mid-week cases, review 3 finding 4). Test: `test_r3_4_wiped_score.mjs`.
   *Open question:* exactly when Sleeper keeps the earlier score vs. the 0 isn't confirmed.
6. **Trades:** "You can only earn points for games after the trade. Previous points stay with the original team"
   (Sleeper). A slot locked before the trade stays locked for the team that locked it, so a starter with a score in hand
   can be locked first and then traded. Trades go through after the league's review period (2 days, from league
   settings). Test: `test_nov15_trades.mjs`.
7. **Sleeper's own lock record** (which game each starter is locked on) is in Sleeper's GraphQL API:
   `starters_games: {player_id: game_id}` on the app's `get_matchup_legs` (needs a logged-in token) and on the public
   `matchup_legs_raw` (no login). Nov 27: the two matched for all 12 teams in weeks 5 and 6 (112 of 112 locks); the
   job keeps comparing them (`lock_source_check.json`). The Worker reads the logged-in one and falls back to the public
   one when the token is missing or rejected. The public REST API only shows slot points. The website doesn't show matchup lock data; only the app does. (Ryan, Nov 16.)
   **Mid-week, the public feed's slot points show a starter's latest game even when an earlier one is locked**, and
   its matchup `points` count unlocked slots too. Sleeper's app shows only the locked slots, each at its locked game
   (week 6, Nov 26: feed 387.5 vs 439.5, app 169.0 vs 428.5; Durant locked on 63.5, feed showing 48.5). So the page's
   score is `lockedTotal(plan)` (engine), not the feed. Test: `test_nov27_score_now.mjs`.

## 2. The pieces

| Piece | Runs where / when | Does |
|---|---|---|
| `app/` (Python) | GitHub Actions, **Update Lock Desk** every 15 min (`python -m app.run`) | Pulls Sleeper/ESPN data, builds projections, play probabilities, matchup context, usage, volatility, news/expert grading; writes `site/static/*.json` and `data/state/*` |
| `tools/moves.mjs` | Same job, after `app.run` | Runs **the same engine as the site** (`site/engine.js`) to write the plan, waiver adds, trades, IR moves, AI reasons, win-chance log |
| `app/learn.py`, `app/alerts.py` | Same job | Logs and grades decisions; sends phone alerts (ntfy) from the engine's own action list |
| `site/` | GitHub Pages; recomputes **in the browser every minute** | The app Ryan uses (installable PWA). Loads `static/*.json` + live Sleeper + Worker + state branch |
| `worker/` | Cloudflare Worker, cron **every minute** | Lineup samples four times a minute for Ryan **and his opponent** (lock eligibility, `worker/src/lineup.js`), Sleeper's lock record, stores site answers, kicks the update workflow every 15 min. **Injury watch** (Nov 28, `worker/src/injuries.js`): in the 2 h before each tip, reads ESPN's injury report every minute for the teams about to play and kicks the update job on a status change |
| `app/league_run.py` | **Other Lock-In leagues** workflow, daily 15:07 UTC (7:07 AM PST, 8:07 PDT) | Finds other Lock-In leagues, snapshots them, studies real managers' locks (bar calibration, opponent lock model) |
| `research/` | By hand | Fits the constants in `app/data/*.json` from 2021-24 box scores (the factory numbers) |
| `app/train.py` | **Train models** workflow, nightly 10:37 UTC (2:37 AM PST) | Refits each learned model, promotes a new version only if it's clearly better on held-out days, watches it 7 days, reverts if worse (section 5) |
| `tests/` | **Tests** workflow on pushes to main and PRs | `tests/run_all.sh`; the update job runs the newest code that passed (`tools/tested_code.sh`; with no passing run at all it runs HEAD). The Worker deploy is **not** gated on Tests; `worker/src/lineup.js` is tested (`test_nov26_bench_trip.mjs`), the rest of `worker/src/index.js` is not |

**One engine.** All decision logic is in `site/engine.js`, which runs both in the browser and in Node (`tools/moves.mjs`).
Don't add Node-only APIs to it, and don't re-implement engine logic in Python (`test_r2_f9_one_engine.py`).
`app/lockin.py` and `app/league_study.py` keep a Python copy of the stopping math for the other-league study and for
grading decisions (`app/learn.py`). `engine.js` also holds hand copies of some fitted constants (`BASELINE`,
`DEFAULT_AVAIL`, `B2B_FACTOR`); a refit of `app/data/*.json` must update them too.

**Workflows** (`.github/workflows/`): `update.yml` (every 15 min + manual; also kicked by the Worker because GitHub
throttles schedules), `tests.yml` (push), `worker.yml` (push touching `worker/**`), `leagues.yml` (daily),
`llm-eval.yml` (manual AI model comparison), `train.yml` (nightly trainer). Update, leagues and llm-eval share the
`lock-desk` concurrency group; train has its own (`train`): it reads the state branch but writes only the `learning`
branch, so it can't overwrite or be overwritten by the 15-minute job.
A crash in `python -m app.run` stops the run before the Pages deploy (the site keeps its previous version); the later
steps (moves, learn, alerts) run through `tools/step.sh`, which records a failure in `step_health.json` and carries on.

## 3. Data flow

```
Sleeper API ─┬─> app/run.py ──> site/static/*.json ──┐
ESPN tips ───┤        │                               ├─> site (browser engine, every minute)
RSS / news ──┘        └──> data/state/* ──> state branch ─┤
                                                          └─> tools/moves.mjs ─> plan.json, moves.json ─> alerts.py (ntfy)
Worker (every minute): Sleeper lineup ─> KV lineups_<season>_w<week>   Sleeper GraphQL ─> KV sleeper_locks_*
                       site answers (lock marks, eligibility) ─> KV     /state endpoint ─> site + job
                       ESPN injury report (2 h before tips) ─> KV injuries_<date> ─> kick update job on a change
```

- The site reads `static/*.json` (from the last job), **live** Sleeper data (rosters, matchups, stats, projections), the
  `state` branch raw files (lineup records, locks, overrides), and the Worker's `/state` (minute-level lineup records,
  answers, Sleeper lock record). **Worker data wins** over the 15-minute state branch; `mergeSnaps` keeps "benched"
  if either source saw it.
- Sleeper's servers disagree sometimes (CDN copies hours old; `api.sleeper.app` vs `api.sleeper.com`). Live requests
  bust the cache, and matchups from both hosts are merged (`mergeMatchups`); `lockState` reads every copy's slot points.
- `tools/state.sh` restores and saves `data/state` from/to the `state` branch (refuses to run on empty state; repairs a
  corrupt file from the backup). **`state` is a single force-pushed commit with no history;** `state-backup` is a
  once-a-day snapshot of the previous state. So the state branch can't show you yesterday's files beyond that one copy.
- **Ryan's answers** ("I locked this", "was he starting?") are saved to Worker KV (`locks_w<week>`, `elig`) and to his
  browser's localStorage, which wins on that device. Nothing in the job writes `locks_w*.json` or
  `eligibility_overrides.json` on the state branch; they're read if present.
- **Lineup records:** both teams' come from the Worker four times a minute (at 0, 15, 30 and 45 s) and from the job
  every 15 min. The Worker reads Sleeper's own scoring lineup (`matchup_legs_raw`: public GraphQL, a POST, so never a
  stale CDN copy; cache-busted REST is the fallback) and writes a record set to KV only after a sample that changed it.
  The job merges the Worker's records into its own (`run.py`; "benched" sticks from either); `moves.mjs` and the site
  merge them with `mergeSnaps`. A bench trip shorter than 15 s can still be missed: Ryan's one-tap answer covers it
  (section 4.3).
- **Site vs job:** the site and `tools/moves.mjs` run the same engine, but not on identical inputs. The site passes
  `isTipped` to `eligFromSnaps` (a record not yet frozen after tip counts as final), uses localStorage answers and the
  current minute; `moves.mjs` does none of those. So `plan_debug.json` can briefly differ from Ryan's screen (e.g.
  "confirm" in the job where the site already shows "lock").
- The Worker's `/state` is unauthenticated (read-only); writes need `WRITE_KEY`. The Worker reads `players.json` from
  the Pages site for its player→team map, so a broken Pages deploy affects its tip/team data.

## 4. How the engine decides (`site/engine.js`)

### 4.1 Per game: projection, play chance, outcome distribution

- **Projection `mu`** (`Book.gameMu`): a blend of RotoWire (via Sleeper projections), the model (per-minute baseline,
  `app/model.py`), matchup context (`app/memory.py`: opponent vs position, pace, rest, teammates out) and usage
  (`app/usage.py`: rotation minutes missing on his team, opponent rim protection). Weights are fitted on graded games
  (`experts.stack_weights`) and scaled for bias.
- **Play probability `q`** (`Book.playProb`, from `static/availability.json` built by `app/availability.py`):
  - Healthy: historical curve by games ahead. The next-game point is a stage-of-season default (0.955 / 0.944 / 0.930)
    until 300 of this season's games are graded, then this season's rate. Games tipping today use separate game-day
    rates (`healthy_gameday`, `designation_gameday`), because by then the designation is final.
  - Healthy bench players (< 20 min/game) who sat recent team games get a participation factor on `q`.
  - Sleeper designation: calibrated rates for Probable / Questionable(GTD/DTD) / Doubtful, blending this season's
    graded results with a published table. "Out" was a fixed 0% (the doc said calibrated; the code never did that).
  - **Learned next-game rate** (Nov 27, `first_game` in the availability model): once the nightly trainer has promoted
    one, a listed player's next game uses a rate by status (Out, GTD/DTD/Questionable, Probable, Doubtful) and games
    missed so far (0, 1, 2-3, 4+), one set for a day or more ahead and one for game day. It replaces the designation
    rate and Out's 0% for that game; IR/Suspended keep 0%. Evidence: Out a day ahead played 42% after 0 missed (31 of 73)
    and 35% after 1 (19 of 55); DTD 65% after 0 missed vs 19% after 1+. Tests: `test_nov27_out_play.py`,
    `test_nov27_first_game.mjs` (the browser's status-only chain uses it too).
  - After k straight missed games: the return hazard (fitted 2021-24).
  - A news timeline ("out 2-4 weeks") with a minimum overrides these. Outlets vote; the latest report per outlet within 48 h counts.
  - **A single-game "ruled out" report** (the newest report for him says out for 1-3 games) sets those games to 0%
    even while Sleeper still shows GTD; a newer available/probable/questionable/doubtful report cancels it. The games
    are the ones it names by weekday (within 6 days), else his next ones from the report's date; with no weekday and a
    game he played on/after that date, it's ignored as ambiguous. No freshness window beyond the news store's 7 days;
    a report about a finished game simply has no upcoming game left to affect. Rest days return to the healthy rate
    after (Nov 16, Queta; `test_nov16_news_out.py`). Only rostered players and injured players with a team are modeled.
  - The engine uses the job's curve only while the live Sleeper status still matches the status it was built for.
  - **Team injury reports** (Nov 28): ESPN's public injury report, read by the Worker every minute in the 2 hours
    before each tip (only the teams about to play; saved to KV `injuries_<date>` only on a change; the first read of a
    team's report is recorded without a run; a player taken off the report = Available) and by the job once per run
    (`app/injuries.py`: the whole report plus the Worker's entries). On a new status or a new note the Worker starts the
    update job at once (at most every 4 minutes), so projections, lineup moves and alerts follow in minutes instead of
    up to 15. A report only ever makes a player **less** likely to play than Sleeper says, and only to Doubtful or Out
    (`escalateStatus` in `engine.js`, `injuries.escalate` in the job; the site applies the Worker's copy with
    `Book.applyReports`). It never clears a player Sleeper has out. **ESPN's status field is not trusted on its own**
    (first live run, Nov 28: 10 of 99 listed "Out" were stale or contradicted, e.g. Grayson Allen "Out" with the note
    "upgraded to probable for Saturday's game", Landale "Out" from Friday's game): a report counts only when its note
    says he sits, nothing in it says he may play, and the weekday it names is today or later in ET, or, naming none,
    it's under 24 hours old (`reportCurrent` / `injuries.current`). Tests: `test_nov28_injury_watch.mjs`,
    `test_nov28_injuries.py`.
- **Teammate absences → minutes** (Nov 28, `app/absence.py`; Fri Nov 27 Queta scored 70.5 from the bench with
  Mitchell Robinson, a 17.5-minute center, out sick; every older teammate path counted only 20+ minute rotation
  players, and the usage model was gated off). For each player and game in the next 4 weeks: every teammate who plays
  10+ min counts. His minutes move by his own on/off record with that teammate (the current streak without him weighs
  16x a game), shrunk (k = 70 games) toward a flat share of the teammate's minutes (10% for the same position group,
  6% otherwise), times the chance the teammate sits tonight. His usual minutes already include games the teammate
  missed, so a teammate coming back turns the boost into a cut; a traded teammate's minutes are gone for good.
  Factor = new minutes / usual minutes, kept in 0.7-1.5. Written to `static/absence.json` (this week's games carry the
  reasons, shown as a "minutes ±X%" chip on the Research tab) and `absence_debug.json`. Fitted by
  `research/absence_fit.py` (`app/data/absence_model.json`). The factor is **not multiplied into the projection**:
  this season the blend already prices absences on average (blend × factor: MAE +0.012, 95% interval -0.01 to 0.04).
  It sets the game's **upside bucket** below. Test: `test_nov28_absence.py`.
- **Upside by absence bucket** (Nov 28, `app/upside.py`, engine `Book.situB` / `situM` / `situQ`). On this season's
  graded games, games the absence factor put at 1.35x+ went 1.5x their projection 41% of the time (13% for normal
  games); 1.2-1.35x: 20%. So each game falls in a bucket by its factor (edges 0.9, 1.1, 1.2, 1.35). Each bucket has
  quantile multipliers on the normal outcome range (19 quantiles, shrunk 100 games toward no change, learned from
  graded games with the walk-forward factor of who actually sat). The bucket's mean multiplies `mu` that night only
  (factory: 0.89 teammate back, 1.05 / 1.09 / 1.16 for more minutes); its shape stretches the range `Q`
  (renormalized to mean 1, so the mean isn't counted twice). Lock values, starts, waivers and trades read both. The
  normal bucket is untouched. The page gets it through `static/learned.json` `upside` (factory numbers from
  `app/data/upside_model.json` until the nightly trainer promotes its own, section 5). A "▲ upside" chip marks
  buckets 3-4 on the Research tab. Tests: `test_nov28_upside.mjs`, `test_nov28_upside_train.py`.
- **Outcome** = `mu × R`, with `R` from 100 quantiles of the player's FP/G tier (`app/data/game_ratio_quantiles.json`,
  blended toward our own projection errors), widened or narrowed by the player's own spread (`app/volatility.py`).

### 4.2 Optimal stopping for one player (`contStats`)
For his remaining games, the value of arriving unlocked at game j is
`W_j = q_j·E[max(X_j, W_{j+1})] + (1−q_j)·W_{j+1}`. Lock a score `s` if it beats the value of continuing.

### 4.3 The week plan (`WeekPlan.buildOnce`)
1. **Lock state of every starter** (`lockState`), checked in this order:
   1. Sleeper's lock record (`sleeperLocks`) when the feed status is `ok`. It's authoritative: while it's on, Ryan's
      manual marks and both inferred-lock checks below are skipped (a player not in the record isn't locked).
   2. Ryan's manual lock marks (only when the feed is off).
   3. **Live**: if the game is in progress, but his slot shows an earlier game's score instead of the live points, that earlier game is locked.
   4. **Wiped**: the slot shows 0 after a DNP in the lineup.
   5. **Inferred lock** from slot points matching an earlier countable game.
   6. **Bench / moved** (not lockable). If he has no games left, the score shown still counts (`kept`). Ryan's
      eligibility answer for a game (`elig`, `"date|pid"`) beats the lineup record: each lock/pass slot card has a
      **"Sleeper won't let me lock this"** button (answer `false`), and an **Undo** button takes it back (`true`)
      (Nov 26, `test_nov26_bench_trip.mjs`).
   7. **Open** (lockable) or **confirm** (no lineup record: ask Ryan).
   Also possible: **live** (game in progress, after step 3) and **none** (no game played yet, or no slot points).
2. **Rest-of-week assignment**: max-weight assignment (`maxAssign`) of players to open slots, where
   value = continuation `W` (or `max(score, W)` for a lockable score). Idle bench players **stream** into slots on days
   that slot's player doesn't play (each idle player assigned to one slot).
3. **Lock bar** for each lockable score = (week value if this slot passes) − (week value with this slot closed and its
   player gone), × the **bar calibration** from other leagues (`studyBarScale`, used only when its 95% interval excludes 0),
   × Ryan's **lock style** slider (`lockBias`). Lock if score ≥ bar. A **matchup-aware** override applies when the
   call changes win chance by 2+ points. "Lock certainty" = share of 3,000 simulated weeks where passing ends lower.
4. **Today's lineup**: every day is its own assignment of who plays into which slot. The best expected game today in
   each slot starts; the **keep-line** for a starter = what the rest of the week loses if this slot is done and he's gone.
   **Same-day relief**: if the starter's game misses its keep-line, slide in a player whose game tips 2.5 h+ later.
5. **Outlook**: each slot's expected final and spread → projected final; **win chance** = normal approximation of
   my total vs the opponent's (its z-score times the learned `win_chance` temperature, 1 until one is promoted). The **opponent's plan** uses the same engine but locks the way real managers do
   (`humanLockRate` from the other-league study), not the engine's way.
6. **Actions**: one time-ordered list (`plan.actions`) that the site's top summary and the phone alerts both read.

### 4.4 Matchup tab
`site/app.js` `renderMatchup`: both lineups slot by slot. The score at the top (and in the page header) is each side's locked total, the number Sleeper's app shows. For each slot it shows the lock state, the game the score
came from and where the lock came from (Sleeper / your mark / estimated), plus games left, the next game, and the
projected edge per slot. Fields come from `plan.slots` (`st`, `game`, `lockSource`, `kept`, `left`).

### 4.5 Rotation (`build({rotate: true})`, Nov 26)
Before locking, try swapping each lockable starter with another open starter (or an empty slot) when both fit their
new slots, rebuild, and keep the swap that raises the expected final most (> `ROTATE_MIN` = 0.5), up to three.
Locked and live players never move. The lock call then reads "Move X UTIL → PG (Y → UTIL), then lock — 70.0", and
the slot card says to move him first. **It's on for Ryan's plan only** (site + `moves.mjs`), not for the opponent's
plan or trade checks, because it costs about 85 ms per plan versus 6 ms.

### 4.6 Waivers, trades, IR (`Valuer`, `waiverMoves`, `tradeIdeas`, `irMoves`)
- **Value of a roster** = for each remaining week, the best fill of the starting slots with each player's lock-in value
  for that week's games (more games = more chances at a big one), discounted 3%/week in the regular season (playoff
  weeks full), with missing roster spots filled by the best free agent.
- **Trades are valued in expected wins:** this week = change in win probability (each team's outlook, with the trade
  taking effect after the review period; locked slots stay); rest of season = Δ(lock-in value per week) ×
  `valuer.discSum` (the discounted count of remaining weeks) × `WINS_PER_SCORE` (2.2, or the learned `wins_per_point`, section 5) / S, where S is the median team
  value across the league's rosters (`tradeCtx` in `moves.mjs`, default 500). A deal is offered only if it adds wins for Ryan, doesn't cost the partner
  wins by the same model, and gives the partner back at least ~90% of the market value he gives up. Shapes from 1-for-1
  to 3-for-2, with caps so ideas don't repeat the same players.
- **Waiver adds**: best free agent adds with the best drop, bid suggestions when the league uses FAAB.
- **IR**: activate or release a returning player; move an Out player to IR to free a spot.

### 4.7 Phone alerts (`app/alerts.py`, ntfy)
Sent once each (deduplicated in `data/state/alerts.json`):
- a **lock** or **confirm** call whose deadline is within 75 min, and a lineup **move** within 60 min: text taken from
  `plan.actions`, so it matches the page. A rotation folded into a lock call ("Move X … then lock") rides on that alert;
  standalone `rotate`, `relief` and `later` actions get no alert of their own.
- a **fallback** alert, once a week per slot, when a slot has no games left (text from `plan.actions`);
- a starter ruled **Out/Doubtful** whose game is today and hasn't tipped (text written in `alerts.py`);
- a **morning brief**, once per Pacific day, 7-11 AM PT (written in `alerts.py`).

## 5. Learning loops

Two kinds. **Every run** (15 min): rates that are plain averages of graded results update themselves (below).
**Nightly trainer** (`app/train.py`, `app/train_models.py`, Train models workflow): fitted models that could make
things worse if refit blindly go through a gate.

**The nightly gate** (Nov 27; `test_nov27_learning.py` is the spec):
1. **Watch.** A model promoted in the last 7 days is graded against the version it replaced on every game graded since.
   Clearly worse (95% interval of the per-game loss difference above 0, 3+ days) = reverted at once; at the end of the
   watch, worse at all = reverted, then a 7-day cooldown. No new promotion while watching.
2. **Gate.** A candidate is fitted on rows before the exam window and moved from the current version by at most the
   model's step cap. Exam = the last 14 days (the newer half of the days while history is shorter than 28; rows of a
   kind that started later are split on their own, `s` key); for the season models the exam is the newest season with
   enough rows and the fit uses only older seasons. Promoted only if the paired loss difference's 95% interval
   (2,000 resamples of whole days, or of whole clusters where rows share one: a player-season, a league, a matchup) is
   entirely below 0, every number is inside the model's hard limits, and there are
   enough rows. What goes live is the same capped step toward a fit on all rows, checked against the limits again.
3. **Log.** Every outcome goes to `learned.json`'s log: the Insights tab shows it ("What the models learned"); the
   morning brief names promotions and rollbacks from the last 24 hours.

Learned numbers never change code, only fitted numbers. **Factory numbers** (`app/data/*.json` and the every-run
self-calibration) apply when there is no learned file, no entry for a model, or the repository variable `LEARNING` is
`off` (the trainer then skips and the job ignores learned numbers).

| Learned model | What | Data | Loss | Limits, step |
|---|---|---|---|---|
| `play_first` | next-game play rate by status x games missed, ahead and game day (section 4.1) | graded next-game predictions (`avail_graded.jsonl`); each rate shrunk 20 games toward its status's pooled rate, which is shrunk toward today's rates | log loss (clipped 1-99%) | rates in [0, 1], Out <= 90%; 0.25 per promotion |
| `return_rate` | chance to play after k missed games in a row (`by_k`, `k9_12`, `k13_20`, `k21p`; every game after the next one in an absence) | first-sight graded predictions with 1+ missed, no timeline, no news zero; each rate shrunk 30 games toward the current one | log loss | 2-80%; 0.10 per promotion |
| `baseline` | season-start blend R, M, c (`app/model.py` `BASE`, engine `Book.baseline`) | box scores of every season available (`app/seasons.py`: 2021-23 research parquet, the last two seasons from Sleeper kept as `seasons/*.json.gz`, this season from `memory.sqlite`); checkpoints after 1, 2, 3, 5, 10 games, target = mean of his later games; newer seasons weigh more (x0.7 per season back); grid fit | absolute error (FP/G) | R 50-1000, M 0.5-12, c 0-60; R ±100, M ±2, c ±10 |
| `spread` | per-player spread shrinkage a, k, m (`app/volatility.py`) | same seasons; players with 35+ games and mean 15+, checkpoints 0-40 games, target = spread of the rest of his season | squared error of r | a 0-1, k 5-400, m 0.8-1.1; a ±0.1, k ±40, m ±0.04 |
| `wins_per_point` | trade value of a weekly point (engine `WINS_PER_SCORE`, 2.2) | final weeks of verified leagues in `leagues.sqlite`: chance that a matchup ends within 4% of the league-week's median score = 2 x 0.04 x wps; shrunk 200 matchups toward the current value | log loss | 1.2-4.0; ±0.3 |
| `upside` | outcome range by teammate-absence bucket (section 4.1): 19 quantile multipliers per bucket vs the normal bucket | graded games of this season from `memory.sqlite`: target = FP / leave-one-day-out blend projection, bucket from the walk-forward absence factor (who actually sat); each multiplier shrunk 100 games toward 1, buckets under 20 games and the normal bucket stay 1 | pinball loss over the 19 quantiles | each multiplier 0.5-2.0; ±0.15 per promotion |
| `win_chance` | temperature t on the win-chance z-score (page outlook and trade check: Φ(t·z)) | graded win-chance log (`winprob_log.json`), raw predictions (the log is never tempered); grid 0.5-2.0 | log loss | 0.5-2.0; ±0.25 |

The job applies them at the start of each run (`app/run.py`: `play_first`, `return_rate` into the availability model;
`apply_learned` puts `baseline` and `spread` into `model.BASE` / `volatility.M`, and writes `site/static/learned.json` =
`{baseline, wins_per_score, win_temp, upside}` for the page and `tools/moves.mjs`; `upside` is always there, the factory copy when nothing is promoted or `LEARNING` is `off`). Known limits: `win_chance` learns from the
logged win chance, which is a simpler model than the page's (see "Win chance" below), so it corrects the width of the ranges both share,
not the page's extra logic. The usage model (`app/usage.py`) stays on its every-run gate below: its fit needs
teammate-absence context that isn't archived per game yet.

Every-run loops:
- **Projections**: every source's pre-tip projection is logged and graded once the game is final (`app/experts.py`,
  `projlog_*.json`, `expert_scores*.json`); blend weights refit each run.
- **Availability**: each next-game play chance is logged and graded (`availability_log.json`); designation rates and the
  healthy rate update from it.
- **Usage**: graded by horizon; a horizon that makes projections worse (100+ games) is switched off (`usage.gate`).
- **Decisions**: lock/pass calls and lineup moves logged in the `decisions` table of `memory.sqlite` and graded vs the
  counterfactual (`app/learn.py`); the site reads the summary from `site/static/learning.json`. A week is graded 2 days
  after its last game day (settled scores). Sleeper's lock record decides each slot's final and whether a lock call was
  followed; a followed pass is graded on what the slot really ended with (Nov 27: the feed's latest-game points had
  graded three of Ryan's week-5 locks "not followed"; `test_nov27_grading.py`).
- **Win chance**: one prediction per matchup per stage of the week, graded 2 days after the week's last day on the
  settled scores (`tools/winprob.mjs` `gradeWeeks`, `winprob_log.json`; `test_nov27_winprob_settle.mjs`).
  The logged win chance is a **simpler model than the one on the page** (no human-lock opponent, no matchup-aware calls,
  no rotation, every game treated as lockable), so its grades don't measure the displayed number exactly.
- **Experts/news**: RSS + polite crawler (`app/sources.py`: robots.txt, rate limits, public pages only); an AI model via
  OpenRouter extracts structured items; expert calls are graded and weighted (`app/news.py`).
- **Other leagues** (daily): bar calibration and real managers' lock rates (`league_study.json`).

## 6. Data files

**`state` branch** (`data/state/` in the job; read with `git show origin/state:<file>`):

| File | Holds |
|---|---|
| `plan_debug.json` | This week's plan from `moves.mjs`: `slots`, `actions`, `rotation`, `outlook`, `bar_debug`, `week_schedule`, `today_options`, **`starters_debug`** and **`opp_debug`** (per slot: lock state, every Sleeper copy of the slot score, manual mark, lineup record; start here for lock bugs), raw rosters/matchups, trade debug |
| `lineups_<season>_w<week>.json`, `opp_lineups_*` | Lineup record per `"date|pid"`: `{slot, i, seen, frozen, benched}` (Ryan's and the opponent's, the job's merged with the Worker's) |
| `lock_source_check.json` | Every run: the public `matchup_legs_raw` lock record compared with the logged-in one, this week and last, all teams (`tools/locksrc.mjs`; Nov 27) |
| `legs_probe.json` | Left over from the Nov 26 search for Sleeper's eligibility field; nothing reads it |
| `sleeper_locks_<season>_w<week>.json` | Sleeper's lock record per roster (copied from the Worker) |
| `eligibility_overrides.json`, `locks_w<week>.json` | Old copies of Ryan's answers, read if present; live answers are in Worker KV (section 3) |
| `availability_now.json`, `availability_log.json` | Current play chances with their basis; logged predictions + calibration |
| `timelines.json`, `news.json`, `claims.json`, `expert_takes.json`, `seen_items.json`, `source_report.json` | News, injury timelines, expert claims, crawler state |
| `memory.sqlite` | Every player-game with context (minutes, rest, teammates out, projections before tip) |
| `projlog_*.json`, `expert_scores*.json`, `proj_ratios.json` | Projection logging and grades |
| `usage_log.json`, `usage_debug.json`, `value_debug.json` | Usage grades; this week's biggest usage factors; valuation debug |
| `absence_debug.json`, `injuries_debug.json` | This week's biggest teammate-absence minute changes with reasons; injury-report statuses that raised a Sleeper label this run (Nov 28) |
| `league_study.json`, `leagues.sqlite` | Other-league study and its data |
| `winprob_log.json`, `alerts.json`, `reasons.json`, `kick.json` | Win-chance log, sent alerts, cached AI reasons, Worker kick status |
| `site_check.json`, `step_health.json`, `mobile.png`, `mobile_matchup.png` | Health of the last run: page check, step outcomes, phone-width screenshots |
| `projlog_done_<season>.json`, `ctx_prior_<season>.json`, `diag_run.json`, `diag_prior.json`, `llm_eval.json` | Graded projections kept a few days, last season's opponent-vs-position table, run diagnostics, AI model comparison |
| `availability_err.txt`, `*.corrupt` | Present only after a failure: the availability traceback; a damaged file moved aside by `state.sh` |

**`learning` branch** (real git history, one commit per nightly run; written only by the Train models workflow through
`tools/learning.sh`; never force-pushed):

| File | Holds |
|---|---|
| `learned.json` | The learned numbers (`models`: params, the version they replaced, since, watch status) and the trainer's log. The 15-minute job copies it to `data/state/learned.json` (`tools/learning.sh pull`; a failed fetch keeps the last copy) |
| `avail_graded.jsonl` | Every graded next-game play prediction, once each (the state log keeps only the newest 3,000) |
| `seasons/<year>.json.gz` | Box scores of the two seasons before this one from Sleeper's per-game stats, scored in this league's format (`{pid: [[date, fp, min], ...]}`), fetched once by the trainer and kept (only when the season is complete, 10,000+ games) |

**`site/static/`** (generated each run, not in git): `players`, `gamelog`, `priors`, `priors_min`, `participation`,
`quantiles`, `volatility`, `league`, `tips`, `availability`, `usage`, `context`, `experts`, `news`, `claims`, `insights`,
`league_study`, `moves`, `plan`, `learning`, `winprob`, `health`, `absence` (teammate-absence factors, section 4.1), `learned` (learned numbers for the engine, section 5).

**`app/data/`** (fitted constants, refit with `research/`): `availability_model.json`, `baseline_model.json`,
`usage_model.json`, `volatility_model.json`, `game_ratio_quantiles.json`, `absence_model.json` (`research/absence_fit.py`), `upside_model.json` (`research/boom_fit.py`; the upside trainer's factory).

**Worker KV**: `lineups_<season>_w<week>`, `opp_lineups_<season>_w<week>`, `sleeper_locks_<season>_w<week>`,
`sleeper_locks_status`, `elig`, `locks_w<week>`, `kick`, `day_<date>`, `league`, `my_roster`, `injuries_<date>` (the
injury watch: `{items, changes, kickedAt}`, 3-day expiry). Free plan: 1,000 writes/day, so it writes only on change.
`/state` returns `lineups`, `oppLineups` and `injuries`.

## 7. Secrets and configuration
Never in the repo. Names only:
- **GitHub Actions secrets**: `NTFY_TOPIC` (alerts), `OPENROUTER_API_KEY` (AI extraction/reasons),
  `CLOUDFLARE_API_TOKEN` (Worker deploy). **Variables**: `WORKER_URL`, `OPENROUTER_MODEL`, `OPENROUTER_MODEL_ADVICE`,
  `OPENROUTER_MODEL_NEWS`, `LEARNING` (optional; `off` stops the nightly trainer and makes the job use factory numbers).
- **Worker secrets**: `WRITE_KEY` (the site's key for saving answers; the site keeps it in localStorage from Ryan's
  setup link), `GH_TOKEN` (lets the minute cron start the update workflow), `SLEEPER_TOKEN` (Ryan's Sleeper login, for
  the lock record).
- The site's ⚙ Backend dialog shows Ryan's setup link, which contains `WRITE_KEY`: never ask him to paste or screenshot it.
- If the Sleeper token stops working, the Worker reads the public lock record instead (`source: "public"`, with
  `login_error`), so the feed status stays `ok`; only if both fail does the engine fall back to manual marks and
  inferred locks. The site's footer says which source is active. Ryan has to get a fresh token from the Sleeper app
  himself and set it with `wrangler secret put SLEEPER_TOKEN`. Never handle the token value.

## 8. Decisions and their evidence
Each of these can be re-checked. If new evidence overturns one, change it and update this list.

| Decision | Evidence | Re-check with |
|---|---|---|
| Lock bars = true opportunity cost with rotation on both sides | `test_bar_star.mjs` (Nov 10: bar 46.2 → 74.7 after the locked player's own later games stopped filling other slots) | `plan_debug.json` `bar_debug` |
| Bars × calibration from real Lock-In leagues, only when its 95% interval excludes 0 and the study used the right volatility tiers | The Nov 10 ×0.90 came from a study bug (every player got the bench tier); as of Nov 25 the best scale is 1.05 with CI [-0.49, 0.68], so **no calibration is applied** (`studyBarScale` returns 1) | `league_study.json` `best_scale`, `tier_units`; `studyBarScale` |
| The engine's lock rule beats real managers | as of Nov 10: +6.1% of projection (CI 2.5-9.7) | `league_study.json` `engine_minus_manager` |
| Opponent modeled with real managers' lock rates, not the engine's | other-league study; `test_human_locks.mjs`, `test_nov15_opp_final.mjs` | `league_study.json` `lock_rate_eligible` |
| Today's starters by expected points, not option value; +0.5 to whoever is already in the slot | option-value ranking benched stars for ~0.2-point edges inside model error. Nov 28 (Fri Nov 27: White 34.8 + 0.5 kept UTIL over Queta 34.9, who scored 70.5): paired study, 300 weeks x 3 seeds. Dropping the +0.5: +0.98 pts/week (CI 0.07-1.88) on Ryan's roster, -0.06 (CI -1.20 to 1.08) and +0.15 (CI -0.88 to 1.17) on the default league; pooled about +0.36 (CI about -0.23 to 0.95). Weighting upside (0.25-1x option value): no seed's interval above 0. So nothing changed | `test_today_pick.mjs`; `node tools/today_study.mjs [weeks] [seed] [plan_debug.json]` |
| Projection blend weights fitted on graded games (not inverse-MSE) | as of Nov 10: MAE 9.04 vs RotoWire 9.22, leave-one-day-out, n=1,995 | `experts.stack_weights`; `graded_rows` |
| Per-minute baseline for the model | `research/baseline_fit.py`: MAE 4.63 → 4.54 | rerun the fit |
| Per-player spread, shrunk hard | `research/volatility_fit.py`: small held-out gain | `output_vol.json` |
| GTD/DTD play far more than the published 48% | as of Nov 10: GTD 78.5% (n=158), DTD 91% (n=35); now blended | `availability_log.json` calibration |
| Teammates who play 10+ min count, by each player's own on/off record, shrunk toward a share of the teammate's minutes | Nov 28: walk-forward on 2021-24 box scores, each season held out in turn: FP error down 0.46 / 0.45 / 0.39 per game (95% intervals all below 0, ~23,000 games each); Robinson (17.5 min) was below the old 20-minute cut | `research/absence_fit.py`; `test_nov28_absence.py` |
| Absences change the range (upside), not the average projection | Nov 28: this season the blend already prices absences on average (no MAE gain from multiplying it in), but 1.35x+ games went 1.5x their projection 41% of the time vs 13%; the upside fit lowered pinball loss on later days (-0.008, CI -0.012 to -0.005, 2,508 games) and did no harm on earlier ones (CI -0.004 to 0.003) | `research/boom_fit.py`; `upside_model.json` `fit` |
| Team injury reports read every minute before tips, only toward sitting | Nov 16 Queta (ruled out 5:16 pm ET, Sleeper GTD 2+ h); the job runs every 15 min | `test_nov28_injury_watch.mjs`, `injuries_debug.json` |
| News "ruled out" beats a lagging Sleeper label | Nov 16 Queta: ruled out 5:16 pm ET, Sleeper GTD for 2+ h | `test_nov16_news_out.py` |
| Sleeper's lock record is authoritative when available | it's the app's own record; inference misread locks before (Oct 29, Nov 1, Nov 15) | `test_nov16_sleeper_locks.mjs` |
| Public `matchup_legs_raw` lock record as the fallback when the token fails | Nov 27: identical to the logged-in record, 112 of 112 locks, all teams, weeks 5-6 | `lock_source_check.json` `summary` |
| Trades in expected wins, 2.2 wins per unit of weekly score | Nov 15: final margins of 1,155 Lock-In matchups in 72 leagues (0.020-0.024 across band widths) | `test_nov15_trades.mjs` |
| Rotate lockable scores into the tightest slot | Nov 26: +1.4 to +1.75 pts/week, 95% CIs above 0 on three seeds (900 simulated weeks); cost measured that day at ~85 ms vs ~6 ms per plan | `node tools/rotate_study.mjs` |
| Lineups sampled four times a minute from `matchup_legs_raw`, both teams, plus a one-tap "won't lock" answer | Nov 26: once-a-minute REST samples missed Spencer's bench trip, 15-minute samples missed Edey's; Sleeper publishes no eligibility field (section 1, rule 3) | `test_nov26_bench_trip.mjs`; Spencer/Edey in `plan_debug.json` |
| Learned numbers go live only through the nightly gate (held-out days, 95% interval, limits, capped step, 7-day watch with automatic revert) | Nov 27: on Nov 13-25 first-sight records, the play-rate refit beat the live rates by 0.14 log loss per game (95% interval 0.05-0.23, 624 held-out games); Out a day ahead had been 0% while 42% played | `test_nov27_learning.py`; the Insights tab log; `learned.json` on the `learning` branch |
| Only tested code runs in the 15-min job (not the Worker) | a broken commit once ran in the 15-min job (review 2, 7b) | `tools/tested_code.sh`, `test_r2_7_tested_code.py` |

## 9. Known limits and open questions
- Rule 5 (what a never-locked slot keeps after a DNP) isn't fully confirmed.
- Rotation isn't modeled for the opponent, or inside trade and win-chance checks.
- A swap is never suggested for a player in a live game, though Sleeper may allow starting-to-starting moves mid-game.
- Only 1-3 game "out" reports override Sleeper. Longer absences need a news timeline with a minimum.
- Win chance is a normal approximation; it has few graded matchups so far (`winprob_log.json`).
- The bar calibration is measured on single-player bars (the study can't see other teams' benches) and applied to the full rotation bar.
- The lock record comes from Ryan's Sleeper token, or the public record if the token fails. If both fail, the inferred-lock checks (section 4.3, steps 3 and 5) read the feed's slot points, which mid-week show the latest game rather than the locked one (section 1, rule 7), so they can miss locks.
- The job's plan (`plan_debug.json`, alerts) and the site can briefly differ (section 3, "Site vs job").
- The logged win chance uses a simpler model than the displayed one (section 5).
- Lineup records are samples (15 s apart): a bench trip shorter than that is invisible unless Ryan taps "Sleeper won't
  let me lock this". The opponent has no such button.
- ESPN's injury report JSON layout is read defensively and wasn't verified from the sandbox (no network); the job log's
  `injury reports:` line shows how many it read and how many are current. Whether a note is current is read from
  its words (a few phrases, a weekday), which can misread an unusual note; the miss is toward Sleeper's own label. Team names map to Sleeper codes by a fixed table.
- The teammate-absence model has no depth chart and no lineup confirmations; it learns only from who actually played.
  Its factor for Queta on Nov 27 was 1.09 (normal bucket), so the upside model alone wouldn't have flipped that start.
- League and user ids are constants in `app/run.py`, `tools/moves.mjs`, `site/app.js` and `worker/src/index.js`.
