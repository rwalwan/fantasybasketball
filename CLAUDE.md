# Lock Desk: working on this repo

Lock Desk is Ryan Alwan's (GitHub `rwalwan`) assistant for his Sleeper fantasy basketball league **we back (TBK)**,
which plays in Sleeper's **Lock-In** mode. It tells him when to lock or pass in each lineup slot and who to start,
and it suggests waiver adds and trades. **How the system works is in [`docs/SYSTEM.md`](docs/SYSTEM.md). Read it
before you change anything.** This file covers how to work here.

The code and the tests are the source of truth. When this file or SYSTEM.md disagrees with the code, the code wins.
Fix the doc in the same commit and tell Ryan what was wrong. Re-check a decision before building on it; don't take
it on trust. Each one in SYSTEM.md lists its evidence so you can.

## Hard rules

- **The repo stays public.** Never put a secret in a file, a commit, a log line, a test fixture or a chat reply.
  Secrets live only in GitHub Actions secrets and Cloudflare Worker secrets (see SYSTEM.md, "Secrets"). If a
  secret ever shows up in a screenshot, attachment or chat (Ryan's Sleeper token, `WRITE_KEY`, a Cloudflare or
  GitHub token): don't read it out, record it or use it, and tell Ryan to rotate it. Tokens pasted earlier must
  never be used. Never write `Authorization` headers or the Sleeper websocket URL token anywhere.
- **Never buy anything** (apps, subscriptions, paid tiers of tools) and never sign up for services for Ryan.
- **Ask before** force-pushing any branch, touching the `state` or `state-backup` branches by hand, deleting
  workflow runs or saved state, changing repository or Worker settings, or anything else you can't undo.
- **The license is "all rights reserved"** (see `LICENSE`). Don't relicense, and don't help adapt the code for another
  league or team.
- Ryan's email and Sleeper user id are private. They're already in the code (the ids) as constants; don't
  spread them further.

## How a change goes

1. **Reproduce.** Find the case in live state (see "Reading live state") or build a small fixture. Every bug report
   from Ryan should become a test that fails before the fix.
2. **Write the test** as `tests/test_<mon><day>_<topic>.mjs` (engine/site) or `.py` (job). Put the real case and the
   rule in the opening comment: what Ryan saw, what the right answer is, and why. Use existing tests as templates:
   `tests/test_nov26_rotate.mjs` (engine fixture), `tests/test_nov16_news_out.py` (job module with a temp state dir).
3. **Fix it.** Comment non-obvious code with the date, the case and the evidence (that is the house style; see
   engine.js). Keep explanations in plain words. Ryan reads the site and alert text on his phone.
4. **Run everything:** `bash tests/run_all.sh` (runs every `tests/test_*.mjs` with node and `tests/test_*.py` with python3;
   stops at the first failure). Also `node --check site/app.js site/engine.js` after editing the site.
5. **Update docs/SYSTEM.md** in the same commit if behavior, a rule, a data file or a decision changed.
6. **Commit and push to `main`** (identity below). Pushing to main is how changes ship.
7. **Deploy:** wait for the **Tests** workflow to pass on your commit, *then* start **Update Lock Desk**. The update job
   only runs code that has passed Tests (`tools/tested_code.sh`), so starting it before Tests finish runs the old code.
   ```bash
   sha=$(git rev-parse HEAD)
   gh api "repos/rwalwan/fantasybasketball/actions/runs?head_sha=$sha" --jq '.workflow_runs[]|"\(.name) \(.status) \(.conclusion)"'
   gh api -X POST repos/rwalwan/fantasybasketball/actions/workflows/update.yml/dispatches -f ref=main
   gh api "repos/rwalwan/fantasybasketball/actions/workflows/update.yml/runs?per_page=1" --jq '.workflow_runs[0]|"\(.status) \(.conclusion) \(.head_sha[0:7])"'
   ```
   The site (GitHub Pages) and the phone alerts change only after that run. Worker changes deploy on their own when
   `worker/**` changes on main (Worker workflow).
8. **Verify in live output, not just tests:** after the run, read `plan_debug.json` (and `site_check.json`,
   `step_health.json`, `mobile.png`, `mobile_matchup.png`) from the `state` branch and check the case is fixed.
9. **Tell Ryan** what was wrong, what changed, and what he'll see, in plain words, without code-level detail unless he asks.

### Commit identity

Commits need Ryan as author and Claude as committer (a repository hook asks for this):
```bash
git -c user.name=Claude -c user.email=noreply@anthropic.com commit \
  --author="rwalwan <185106406+rwalwan@users.noreply.github.com>" -m "<summary>

<why, the case, the evidence>

Co-Authored-By: Claude <noreply@anthropic.com>"
```
Use the attribution trailer lines your session's instructions give you, if they differ from the one above.

## Reading live state

The job saves everything to the `state` branch every 15 minutes:
```bash
git fetch -q origin state
git show origin/state:plan_debug.json | python3 -m json.tool | less    # this week's plan: slots, actions, outlook, rotation, bar_debug
git ls-tree --name-only origin/state                                    # every state file (SYSTEM.md lists what each holds)
gh run view <run-id> --log | grep -i "availability\|news\|error"        # what the job printed
```
- **The cloud sandbox can't reach Sleeper, ESPN or the Worker** (network allowlist); GitHub works through `gh` and git.
  To check live behavior: read the state branch, or start the update workflow and read its log and outputs.
- The page can't be loaded from the sandbox with live data. To check UI changes, either render the changed piece with a
  fixture plan in headless Chromium (Playwright is preinstalled; build the plan with `site/engine.js` the way
  `tests/test_nov26_rotate.mjs` does) or read the job's screenshots (`mobile.png` = Locks tab, `mobile_matchup.png`
  = Matchup tab) from the state branch after a run. `#tab=<name>` in the site URL opens a tab.
- Check phone width (390 px) and both light and dark themes for any UI change.

## Simulations and studies

- `node tools/week_sim.mjs` plays whole simulated weeks with the engine making the calls, against outcomes drawn from
  the same quantiles. Use it to test a decision rule before shipping it.
- `node tools/rotate_study.mjs [weeks] [seed] [plan_debug.json]` is the template for a paired A/B on the same weeks.
  Report a mean difference with a 95% interval and more than one seed. Don't ship a rule change on a single number.
- `research/*.py` refits the fitted constants in `app/data/*.json` from 2021-24 box scores (`research/data/*.parquet`).

## Where to look

| You're changing | Start in |
|---|---|
| Lock/pass calls, bars, today's lineup, rotation, projected final, win chance | `site/engine.js` (`WeekPlan`) |
| What the page shows, tabs, wording | `site/app.js`, `site/index.html` (inline CSS) |
| Phone alerts | `app/alerts.py` (reads `site/static/plan.json` / `moves.json` from `tools/moves.mjs`) |
| Waivers, trades, IR | `site/engine.js` (`Valuer`, `tradeIdeas`, `waiverMoves`, `irMoves`) + `tools/moves.mjs` |
| Will he play (injury designations, news timelines) | `app/availability.py`, `app/news.py` |
| Projections | `app/model.py`, `app/experts.py`, `app/memory.py` (context), `app/usage.py`, `app/volatility.py` |
| Lock eligibility records | `worker/src/index.js` (minute snapshots), `app/lineups.py`, engine `eligFromSnaps` / `lockState` |
| Sleeper's own lock record | `worker/src/index.js` (`sleeperLocks`), engine `sleeperLocksFor` / `lockState` |
| Other-league study (bar calibration, opponent lock rates) | `app/leagues.py`, `app/league_study.py`, `app/league_run.py` |
| Job order, what gets written | `app/run.py`, `.github/workflows/update.yml` |

`review/` holds an outside review from Nov 10 (`REVIEW_BRIEF.md`, `REVIEW_3.md`) and data exported for it. It's
history: useful context, not the current spec.
