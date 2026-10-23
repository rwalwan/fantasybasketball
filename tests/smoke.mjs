// Node smoke test: run the browser engine on live league data.
// Usage (after `python -m app.run` has written site/static/*.json):  node tests/smoke.mjs
import fs from "node:fs";
import { Book, WeekPlan, weekDays } from "../site/engine.js";

const LEAGUE = "1400915575915491328", USER = "1388708038000533504";
const S1 = "https://api.sleeper.app/v1", S2 = "https://api.sleeper.com";
const get = async u => (await fetch(u)).json();
const st = n => JSON.parse(fs.readFileSync(`site/static/${n}.json`, "utf8"));

const league = await get(`${S1}/league/${LEAGUE}`), season = league.season;
const schedule = await get(`${S2}/schedule/nba/regular/${season}`);
const today = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const week = schedule.filter(g => g.week && g.date <= today).map(g => g.week).sort((a, b) => a - b).at(-1);
const days = weekDays(schedule, week);
const [rosters, matchups, stats, proj] = await Promise.all([
  get(`${S1}/league/${LEAGUE}/rosters`), get(`${S1}/league/${LEAGUE}/matchups/${week}`),
  get(`${S2}/stats/nba/${season}/${week}?season_type=regular`), get(`${S2}/projections/nba/${season}/${week}?season_type=regular`)]);
const tips = {};
for (const d of days) {
  const sb = await get(`https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=${d.replace(/-/g, "")}`);
  for (const e of sb.events || []) for (const c of e.competitions[0].competitors) {
    const a = c.team.abbreviation; tips[`${d}|${({ NY: "NYK", GS: "GSW", SA: "SAS", NO: "NOP", UTAH: "UTA", WSH: "WAS" })[a] || a}`] = e.date;
  }
}
const state = n => { try { return JSON.parse(fs.readFileSync(`data/state/${n}`, "utf8")); } catch { return {}; } };
const ov = state("eligibility_overrides.json"), snaps = state(`lineups_${season}_w${week}.json`), locks = state(`locks_w${week}.json`);

const book = new Book({ scoring: league.scoring_settings, players: st("players"), priors: st("priors"), gamelog: st("gamelog").games });
book.addStats(stats); book.addProjections(proj);
const mine = rosters.find(r => r.owner_id === USER), my = matchups.find(m => m.roster_id === mine.roster_id);
const elig = (p, d) => { const k = `${d}|${p}`; if (k in ov) return ov[k]; const s = snaps[k]; return s && s.frozen ? s.slot != null : null; };
const wp = new WeekPlan({ Q: st("quantiles").quantiles, book, schedule, week, today, rosterPositions: league.roster_positions,
  roster: mine, matchup: my, rosters, tips, elig, locks });
const plan = wp.build();
for (const s of plan.slots) console.log(s.slot.padEnd(4), s.name.padEnd(22), s.action.padEnd(8), s.detail);
console.log("\nTODAY:", plan.lineup.map(x => `${x.slot}:${x.name}${x.move ? "*" : ""}`).join("  "));
console.log("IDLE:", plan.idle.map(x => x.name).join(", "));
const w = wp.waivers([]);
console.log("\nWAIVERS (worst", w.worst + "):", w.list.slice(0, 6).map(x => `${x.name} ${x.fpg}`).join(" | "));
