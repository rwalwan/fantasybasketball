# Lock Desk — review brief (state as of 2026-11-10)

Lock Desk is a fantasy-basketball assistant for one Sleeper league in **Lock-In mode**. Each starting slot keeps ONE
game's score per week: after a game you either lock that score (the slot is done for the week) or pass and hope a
later game (same player or anyone eligible you rotate in) scores more. If you never lock, the slot keeps its last
game. Live repo (public, read-only): https://github.com/rwalwan/fantasybasketball

## Where everything is (paths in the repo, main branch)
| Path | What it is |
|---|---|
| `site/engine.js` | The whole decision engine (runs in the browser every minute and in the 15-min job). Start here. |
| `app/*.py` | The job: data, projections (`model.py`, `experts.py`), availability (`availability.py`), usage (`usage.py`), volatility (`volatility.py`), other-league study (`league_study.py`), learning/grading (`learn.py`) |
| `app/data/*.json` | Fitted constants (availability, usage, volatility, baseline, game-ratio quantiles) |
| `tests/` | Regression tests; each names the bug or claim it protects (`tests/run_all.sh`) |
| `research/*.py` + `research/data/*.parquet` | Fits on 2021-24 NBA box scores (`games.parquet` = player-games, `panel.parquet` = player x team-game with played flag). Re-runnable: `python research/<file>.py research/data/games.parquet ...` |
| `review/data/graded_games_2026.csv` | Every graded game this season (3,479): actual FP, RotoWire projection, our model, matchup context, usage |
| `review/data/decisions_graded.csv` | Logged lock/pass calls and lineup moves with counterfactual and regret |
| `review/data/availability_log.json` | Logged play probabilities vs whether he played (`graded`), and calibration table |
| `review/data/league_study.json` | Other Lock-In leagues: engine rule vs real managers, bar-scale replay, human lock rates |
| `review/data/winprob_log.json` | Win-chance predictions per matchup and stage, graded |
| `review/data/plan_debug.json` | The engine's current plan for this week incl. `bar_debug` (how each bar is built) |
| `review/data/usage_log.json`, `output_*.json` | Usage grades by horizon; research fit outputs |
| `review/commit_log_since_review2.txt` | Every change since the last review, one line each |
| branch `state` | Live job state (refreshed every 15 min; `memory.sqlite` holds everything above) |

## How the engine decides (engine.js, WeekPlan.build)
1. **Per game**: projection mu (blend of RotoWire/model/context, bias-scaled), play probability q, outcome = mu x R
   with R from 100 quantiles of the player's FP/G tier, scaled per player by his own spread (volatility.py).
2. **Continuation value** `contStats`: optimal stopping over a sequence of games, W_j = q E[max(X_j, W_{j+1})] + (1-q) W_{j+1}.
3. **Week plan**: Hungarian assignment of players to open slots (value = continuation W, or max(lockable score, W));
   idle bench players fill days a slot's player doesn't play (`streams`, each idle player in one slot).
4. **Lock bar** for a lockable score = (week value if this slot passes) - (week value with this slot closed and the
   player gone), times a calibration factor from the other-league study when significant (now 0.90).
   Lock if score >= bar x (1 + user lock style). Matchup-aware override if it changes win probability by 2+ points.
5. **Today**: starters = best expected games today across every slot each player fits; keep-line = rest-of-week loss
   with that slot and player removed (re-planned); same-day relief if a later game tips 2.5 h+ after.
6. **Win chance**: normal approximation of my total vs opponent's (opponent modeled with real managers' lock rates).
7. **Waivers/trades** (Valuer): rest-of-season lock-in value per week, per-minute baseline, FA counterfactual.

## Claims to verify (each with where the evidence is)
| # | Claim | Evidence |
|---|---|---|
| C1 | contStats matches simulation | brute force: 3 cases agree to 0.05 FP (recompute: simulate with engine.js `contStats`) |
| C2 | Lock bars were understated (fixed Nov 10): the 'lock' side let the locked player's later games fill other slots | `tests/test_bar_star.mjs` (46.2 before, 74.7 after); `plan_debug.json` bar_debug |
| C3 | Game-to-game spreads are calibrated | graded_games_2026.csv: share of actuals below the engine's 10/25/50/75/90th pct = .107/.263/.511/.760/.887 (proj x 0.984; scale now 0.969) |
| C4 | Projection blend beats RotoWire held out | experts.stack_weights on graded rows: MAE 9.04 vs 9.22 leave-one-day-out, scale 0.969, n=1,995 |
| C5 | Sleeper GTD/DTD play more than the published 48% | availability_log graded: GTD 78.5% (n=158), DTD 91% (n=35); now blended (published = 50 games) -> 0.741 |
| C6 | Healthy next-game play rate ~0.999 this season | availability_log graded: 1,005 healthy predictions, 99.9% played |
| C7 | Bars ~10% high; x0.90 scores +2.2% of projection (CI 0.4-4.1) | league_study.json `bar_scale`, `best_scale`; method in league_study.py (lineup-checked weeks only, DNP=0, player-week bootstrap) |
| C8 | Engine rule beats real managers by 6.1% of projection (CI 2.5-9.7) | league_study.json `engine_minus_manager` |
| C9 | Per-minute baseline beats per-game blend | research/baseline_fit.py: MAE 4.63 -> 4.54 (first 5 games 4.97 -> 4.81; short last season 5.83 -> 5.59) |
| C10 | Benched healthy players play less (93/75/61/47/37/13% by games played of last 5) | research: panel.parquet; applied only to players < 20 min/game |
| C11 | Per-player spread beats tier spread on held-out seasons (small: quantile loss -0.3%) | research/volatility_fit.py, output_vol.json |
| C12 | Hazard of return after k missed games (refit, censoring) | research/hazard_refit.py |
| C13 | Teammate-injury usage effect is real out of sample | research/usage_fit.py (no-hindsight baseline), usage_log.json by horizon |
| C14 | Past lock calls had negative regret (good) | decisions_graded.csv: pass calls mean regret -10.4 (n=50), lock calls -12.4 (n=21); counterfactual replays the same player only |

## Known gaps I am aware of (verify or refute; don't take my word)
- G1 A slot whose player sits his last game: the math scores 0; Sleeper may keep the previous score. Simulated effect +0.5-1.5 FP on waiting value. Unverified rule.
- G2 RotoWire runs 7-11% high for projections 18-42 FP, 19% low under 18 (graded games include only games played: selection?).
- G3 Win chance: only 12 graded matchups.
- G4 The bar calibration (C7) is measured on a single-player bar (the study cannot see benches); applied to the full rotation bar.
- G5 Today's starters are chosen by expected points, not option value (a deliberate choice: option-value ranking benched stars over ~0.2-point edges inside model error).
- G6 Decision grading (C14) only replays the same player's later games, not the slot's rotation: conservative for passes.
