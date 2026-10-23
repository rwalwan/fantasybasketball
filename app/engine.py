"""Builds the week plan for one roster: per-slot lock calls, today's lineup, weekly grid, waiver targets."""
import datetime as dt

from .lockin import Game, continuation_values, eligible, expected_max, lock_bar, percentile_range


def week_dates(schedule, week):
    dates = sorted({g["date"] for g in schedule if g.get("week") == week})
    if not dates:
        return []
    start = dt.date.fromisoformat(dates[0])
    start -= dt.timedelta(days=start.weekday())          # Monday
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(7)]


def team_game_dates(schedule):
    out = {}
    for g in schedule:
        for side in ("home", "away"):
            t = (g.get(side) or {}).get("team")
            if t:
                out.setdefault(t, {})[g["date"]] = {"opp": (g.get("away" if side == "home" else "home") or {}).get("team", ""),
                                                   "home": side == "home", "status": g.get("status")}
    return out


class WeekPlan:
    def __init__(self, book, schedule, week, today, roster_positions, my_roster, my_matchup, all_rosters):
        self.b = book
        self.week = week
        self.today = today
        self.days = week_dates(schedule, week)
        self.tg = team_game_dates(schedule)
        self.slots = [s for s in roster_positions if s not in ("BN", "IR")]
        self.roster = my_roster
        self.matchup = my_matchup
        self.rostered = {p for r in all_rosters for p in (r.get("players") or [])}

    # ---- schedule helpers --------------------------------------------------------------------------
    def team_days(self, team):
        return sorted(d for d in self.tg.get(team, {}) if d in self.days)

    def played_this_week(self, pid):
        return [g for g in self.b.games.get(pid, []) if g[0] in self.days]

    def upcoming(self, pid):
        """Games this week not yet played, as lockin.Game objects with mu and play probability."""
        team = self.b.team(pid)
        played_dates = {g[0] for g in self.played_this_week(pid)}
        all_days = sorted(self.tg.get(team, {}))
        out = []
        for d in self.team_days(team):
            if d in played_dates or d < self.today:
                continue
            prev = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
            b2b = prev in all_days
            ahead = (dt.date.fromisoformat(d) - dt.date.fromisoformat(self.today)).days
            info = self.tg[team][d]
            out.append(Game(d, self.b.game_mu(pid, d), self.b.play_prob(pid, d, ahead, b2b), info["opp"], b2b))
        return out

    # ---- lock inference ----------------------------------------------------------------------------
    def lock_state(self, pid):
        """Infer from players_points: if it matches a game EARLIER than his latest game this week, that game
        is locked. If it matches his latest game, the decision may still be open."""
        pts = (self.matchup.get("players_points") or {}).get(pid)
        played = self.played_this_week(pid)
        if not played or pts is None:
            return "none", None
        pts = round(pts / 10.0, 2)   # matchups report points x10
        latest = played[-1]
        for g in played[:-1]:
            if abs(g[1] - pts) < 0.01 and abs(latest[1] - pts) >= 0.01:
                return "locked", g
        return "open", latest

    # ---- the plan ------------------------------------------------------------------------------------
    def build(self, manual_locks=None):
        manual_locks = manual_locks or {}
        starters = list(self.matchup.get("starters") or [])
        players = [p for p in (self.roster.get("players") or []) if p not in (self.roster.get("reserve") or [])]
        locked = {}
        for slot, pid in zip(self.slots, starters):
            st, g = self.lock_state(pid)
            if st == "locked" or manual_locks.get(pid):
                locked[pid] = g or (self.played_this_week(pid) or [None])[-1]

        # value of each unlocked player from his next unplayed game onward
        cont = {}
        for p in players:
            if p in locked:
                continue
            ups = self.upcoming(p)
            cont[p] = (continuation_values(ups)[0] if ups else 0.0, ups)

        # Two passes: (1) a starter whose just-played game beats his own bar is a lock candidate;
        # (2) every other open slot gets its best remaining candidate (scarcest slots first), and a lock
        # candidate is dropped back to "pass" if a bench player's continuation value beats his score.
        open_slots = [(i, s) for i, (s, pid) in enumerate(zip(self.slots, starters)) if pid not in locked]
        pending = {}
        for i, s in open_slots:
            pid = starters[i]
            st, last = self.lock_state(pid)
            if st == "open" and last is not None:
                pending[pid] = last
        will_lock = {p for p, last in pending.items() if last[1] >= lock_bar(cont.get(p, (0, []))[1])}
        for _ in range(2):
            pool = {p: v for p, v in cont.items() if p not in will_lock}
            slots_left = [(i, s) for i, s in open_slots if starters[i] not in will_lock]
            slots_left.sort(key=lambda x: sum(1 for p in pool if eligible(x[1], self.b.positions(p))))
            taken, best_for_slot = set(), {}
            for i, s in slots_left:
                cands = sorted(((pool[p][0], p) for p in pool if p not in taken and eligible(s, self.b.positions(p))), reverse=True)
                if cands:
                    best_for_slot[i] = cands[0]
                    taken.add(cands[0][1])
            # a lock candidate's slot alternative = best pool player eligible for that slot not used elsewhere
            for i, s in open_slots:
                pid = starters[i]
                if pid in will_lock:
                    alt = max((pool[p][0] for p in pool if p not in taken and eligible(s, self.b.positions(p))), default=0.0)
                    best_for_slot[i] = (alt, None)
                    if pending[pid][1] < alt:
                        will_lock.discard(pid)

        decisions = []
        for i, (slot, pid) in enumerate(zip(self.slots, starters)):
            name = self.b.name(pid) if pid and pid != "0" else "(empty)"
            if pid in locked:
                g = locked[pid]
                decisions.append(dict(slot=slot, pid=pid, name=name, action="locked",
                                      detail=f"Locked {g[1]:.1f} on {g[0]}" if g else "Locked", score=g[1] if g else None))
                continue
            st, last = self.lock_state(pid)
            ups = cont.get(pid, (0.0, []))[1]
            own_bar = lock_bar(ups)
            slot_best = best_for_slot.get(i, (0.0, None))
            bar = max(own_bar, slot_best[0])
            if st == "open" and last is not None:
                score = last[1]
                if not ups and slot_best[1] in (None, pid):
                    action, why = "lock", "No games left this week; this game counts either way."
                elif score >= bar:
                    action, why = "lock", f"{score:.1f} beats the bar of {bar:.1f}."
                else:
                    alt = slot_best[1]
                    swap = f" Swap in {self.b.name(alt)} before his next game." if alt and alt != pid else ""
                    action, why = "pass", f"{score:.1f} is under the bar of {bar:.1f}; expected value of waiting is higher.{swap}"
                decisions.append(dict(slot=slot, pid=pid, name=name, action=action, detail=why, score=score,
                                      bar=round(bar, 1), last_date=last[0], deadline=ups[0].date if ups else None))
            else:
                nxt = ups[0] if ups else None
                if nxt is None:
                    action, why = "fallback-risk", "No games left and nothing locked: this slot scores his last game."
                else:
                    lo, hi = percentile_range(nxt.mu)
                    action, why = "start", f"Next game {nxt.date} vs {nxt.opp}: {nxt.mu:.1f} projected ({lo}-{hi}), plays {int(nxt.q * 100)}%."
                decisions.append(dict(slot=slot, pid=pid, name=name, action=action, detail=why, bar=round(bar, 1)))

        fixed = {**locked, **{p: pending[p] for p in will_lock}}
        return dict(week=self.week, today=self.today, days=self.days, slots=decisions,
                    today_lineup=self.today_lineup(starters, fixed, {p: v for p, v in cont.items() if p not in will_lock}),
                    grid=self.grid(players, locked), unlocked=len(open_slots))

    def today_lineup(self, starters, locked, cont):
        """Unlocked slots should hold players who play TODAY (only a starter's game can be locked)."""
        today_players = [p for p in cont if any(g.date == self.today for g in cont[p][1])]
        open_slots = [s for s, pid in zip(self.slots, starters) if pid not in locked]
        # option gain of sampling a player today = E[max(X_today, W_after)] - W_after
        gain = {}
        for p in today_players:
            ups = cont[p][1]
            after = continuation_values(ups[1:])[0] if len(ups) > 1 else 0.0
            gain[p] = ups[0].q * (expected_max(ups[0].mu, after) - after) + (after if len(ups) == 1 else 0)
        order = sorted(open_slots, key=lambda s: sum(1 for p in today_players if eligible(s, self.b.positions(p))))
        used, plan = set(), []
        for s in order:
            c = sorted(((gain[p], p) for p in today_players if p not in used and eligible(s, self.b.positions(p))), reverse=True)
            if c:
                used.add(c[0][1])
                plan.append(dict(slot=s, pid=c[0][1], name=self.b.name(c[0][1]), gain=round(c[0][0], 1)))
            else:
                plan.append(dict(slot=s, pid=None, name="(nobody eligible plays today)", gain=0))
        idle = [dict(pid=p, name=self.b.name(p)) for p in today_players if p not in used]
        return dict(slots=plan, playing_not_startable=idle)

    def grid(self, players, locked):
        rows = []
        for p in players:
            team = self.b.team(p)
            played = {g[0]: g[1] for g in self.played_this_week(p)}
            cells = []
            for d in self.days:
                info = self.tg.get(team, {}).get(d)
                if not info:
                    cells.append(None)
                elif d in played:
                    cells.append(dict(kind="played", fp=round(played[d], 1), opp=info["opp"]))
                else:
                    cells.append(dict(kind="upcoming", mu=self.b.game_mu(p, d), opp=info["opp"]))
            rows.append(dict(pid=p, name=self.b.name(p), team=team, pos="/".join(self.b.positions(p)),
                             status=self.b.status(p), locked=p in locked, cells=cells,
                             games_left=sum(1 for c in cells if c and c["kind"] == "upcoming")))
        rows.sort(key=lambda r: -self.b.baseline(r["pid"]))
        return rows

    # ---- waivers -------------------------------------------------------------------------------------
    def waivers(self, trending, limit=25):
        trend = {t["player_id"]: t["count"] for t in trending}
        mine = [p for p in (self.roster.get("players") or [])]
        worst_bench = min((self.b.baseline(p) for p in mine), default=0)
        out = []
        for pid, m in self.b.meta.items():
            if pid in self.rostered or not m.get("team") or m.get("active") is False:
                continue
            if m.get("injury_status") in ("Out", "IR"):
                continue
            ups = self.upcoming(pid)
            has_proj = any(self.b.proj.get((pid, g.date)) for g in ups)
            if not self.b.games.get(pid) and not has_proj:
                continue                     # no games and no projection: not in a rotation right now
            base = self.b.baseline(pid)
            if base < 15:
                continue
            week_val = continuation_values(ups)[0] if ups else 0.0
            recent = [g[1] for g in self.b.games.get(pid, [])][-3:]
            out.append(dict(pid=pid, name=self.b.name(pid), team=m.get("team"), pos="/".join(m.get("fantasy_positions") or []),
                            fpg=round(base, 1), over_worst=round(base - worst_bench, 1), games_left=len(ups),
                            week_value=round(week_val, 1), recent=[round(x, 1) for x in recent],
                            trend=trend.get(pid, 0)))
        out.sort(key=lambda r: (r["over_worst"] > 0, r["fpg"] + 0.15 * r["week_value"]), reverse=True)
        for r in out[:limit]:
            r["faab"] = suggest_faab(r)
        return out[:limit], round(worst_bench, 1)


def suggest_faab(r):
    """Rough bid on a $100 budget. Real role changes justify more than a hot game."""
    gap = r["over_worst"]
    if gap <= 0:
        return 0
    bid = 1 + gap * 0.8 + min(r["trend"], 20000) / 4000
    return int(min(40, round(bid)))
