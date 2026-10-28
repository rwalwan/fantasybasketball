# Lock Desk

A fantasy basketball assistant for the Sleeper league **we back (TBK)**, built around Sleeper's Lock-In mode.

Live site: https://rwalwan.github.io/fantasybasketball/

## What it does

- **Locks:** when to lock or wait in each slot. Uses optimal stopping and a joint slot assignment, and checks each call against your win chance in the matchup.
- **Week:** today's lineup vs. the plan, same-day relief swaps, and the full game grid.
- **Moves / Waivers / Trades:** adds with the best drop and trade ideas, valued by each player's remaining schedule in Lock-In.
- **Research / Insights:** every player's games this week, matchup context, role trends, and why games went the way they did.
- **News / Experts:** a polite crawler that respects robots.txt and reads public expert sources. Each expert's calls are graded against what actually happened.

## How it runs

| Piece | What it does |
|---|---|
| `app/` (Python) | Data, memory store, projections (fitted blend), matchup context, usage model, availability model, news + expert grading, other-league study |
| `site/` | Static app (installable on a phone home screen) that recomputes in the browser every minute |
| `tools/` | Moves + win-chance log, AI model eval, state save/restore, step health, site check |
| `worker/` | Cloudflare Worker: lineup snapshots and the 15-minute job trigger |
| `research/` | Scripts that fit the data-driven constants (return rates, usage model, volatility) |
| `tests/` | `tests/run_all.sh` - run on every push |

Workflows: **Update** (every 15 minutes), **Other Lock-In leagues** (daily, 8:07 AM PT), **AI model eval** (manual),
**Tests** (every push), **Worker** (on worker changes). Saved state lives on the `state` branch (daily copy on
`state-backup`).

**On a phone:** open the site, then Share -> Add to Home Screen (iPhone) or menu -> Install app (Android). The
installed app keeps its own storage: tap ⚙ Backend once and paste your setup link.

## License

All rights reserved; see [LICENSE](LICENSE). The code is public to view, not to reuse: copying, adapting or
deploying it, for yourself or anyone else, needs the author's written permission. That includes having an AI
assistant rebuild it for another league or team.

## Credits

Built by Ryan Alwan ([@rwalwan](https://github.com/rwalwan)) with Claude (Anthropic).
