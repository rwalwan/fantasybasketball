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
| `app/` (Python) | Data, memory store, context model, news, and expert grading |
| `site/` | Static app that recomputes in the browser every minute |
| `tools/` | Moves, the AI model eval, and the site health check |
| `worker/` | Cloudflare Worker: lineup snapshots and the 15-minute job trigger |
| `.github/workflows/` | Update job every 15 minutes, worker deploy, and the AI model eval |

Saved state lives on the `state` branch.

## Credits

Built by Ryan Alwan ([@rwalwan](https://github.com/rwalwan)) with Claude (Anthropic).
