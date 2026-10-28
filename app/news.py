"""Expert repository part 2 + news impact.

Reads public RSS feeds, has an AI model (via OpenRouter) turn each item into structured data, and keeps:
  * news items: who, what happened, how long, who gains minutes  -> "what it means for your team"
  * expert claims from bylined articles: add/drop/start/sit/buy/sell on a player, by author
Claims are graded once their horizon has passed, which gives each expert a track record and a weight;
recent claims are combined into a weighted consensus per player.

Needs the OPENROUTER_API_KEY secret. Without it, raw headlines are still collected.
"""
import datetime as dt
import html
import json
import os
import re
import unicodedata
import xml.etree.ElementTree as ET

import requests

from . import sources

STATE = os.path.join(os.path.dirname(__file__), "..", "data", "state")
UA = {"User-Agent": "we-back-lock-desk (personal fantasy assistant; github.com/rwalwan/fantasybasketball)"}
MODEL = os.environ.get("OPENROUTER_MODEL") or "anthropic/claude-haiku-5.5"                 # why-notes, reasons
# News blurbs (status, minutes, injury timelines): DeepSeek V4.1 Flash. Oct 28 eval (tools/llm_eval.py): 96% of
# labeled injury timelines right vs Haiku's 86% (50 items), best news agreement (0.885), cheaper. Override with
# the OPENROUTER_MODEL_NEWS repo variable.
NEWS_MODEL = os.environ.get("OPENROUTER_MODEL_NEWS") or "deepseek/deepseek-v4.1-flash-1017"
# Expert articles use the same model by default. The Oct 2026 eval couldn't tell models apart on articles (5
# articles, every model 100%), and their output is display-only, so Sonnet's ~15x cost wasn't justified (review
# finding 13). Override with the OPENROUTER_MODEL_ADVICE repo variable.
ADVICE_MODEL = os.environ.get("OPENROUTER_MODEL_ADVICE") or MODEL

ADVICE_RE = re.compile(r"(?i)waiver|start|sit\b|pickup|pick-up|add|drop|sell|buy|trade|stream|sleeper|target|risers|fallers|week \d|rest of season|ros\b|must-|hold")
DRAFT_TITLE_RE = re.compile(r"(?i)draft|adp|mock|preseason|auction|keeper|dynasty|cheat sheet")
BULL = {"add", "start", "buy", "stream", "hold"}
BEAR = {"drop", "sit", "sell", "avoid"}
REPLACEMENT_FPG = 25.0      # research: player #180 averaged 23-26 FP/G in this scoring
MAX_LLM_ITEMS = 30          # per run, to bound cost and time


def _load(name, dflt):
    try:
        return json.load(open(os.path.join(STATE, name)))
    except FileNotFoundError:          # missing = first run; a corrupt file must fail loudly, not be overwritten
        return dflt


def _save(name, obj):
    os.makedirs(STATE, exist_ok=True)
    json.dump(obj, open(os.path.join(STATE, name), "w"), separators=(",", ":"))


def norm(name):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", "", s)).strip()


# common short first names in NBA coverage -> the name on the roster
NICK = {"cam": "cameron", "steph": "stephen", "nic": "nicolas", "nick": "nicolas", "mo": "moritz", "herb": "herbert",
        "alex": "alexandre", "zach": "zachary", "kj": "kenyon", "greg": "gregory", "matt": "matthew", "mike": "michael",
        "chris": "christopher", "nate": "nathan", "bub": "carlton", "kenny": "kenneth", "tim": "timothy", "joe": "joseph"}


class Names:
    """News name -> Sleeper player id. Exact name first, then a known short form of the first name, then a unique
    last name on the reported team. Ambiguous names (two players, no team to tell them apart) match nothing."""

    def __init__(self, meta):
        self.by_name, self.team = {}, {}
        for pid, m in meta.items():
            if m.get("team"):
                self.by_name.setdefault(norm(f"{m.get('first_name', '')} {m.get('last_name', '')}"), []).append(pid)
                self.team[pid] = m["team"]
        self.by_last = {}
        for name, pids in self.by_name.items():
            for p in pids:
                self.by_last.setdefault((name.split(" ")[-1], self.team[p]), []).append(p)

    def _pick(self, pids, team):
        if team:
            pids = [p for p in pids if self.team.get(p) == team] or ([] if len(pids) > 1 else pids)
        return pids[0] if len(pids) == 1 else None

    def pid(self, name, team=None):
        n = norm(name)
        if not n:
            return None
        if n in self.by_name:
            return self._pick(self.by_name[n], team)
        first, _, rest = n.partition(" ")
        full = NICK.get(first)
        if full and rest and f"{full} {rest}" in self.by_name:
            return self._pick(self.by_name[f"{full} {rest}"], team)
        if team:
            return self._pick(self.by_last.get((n.split(" ")[-1], team), []), team)
        return None


def parse_feed(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter("item"):
        g = lambda tag: (it.findtext(tag) or "").strip()
        creator = it.findtext("{http://purl.org/dc/elements/1.1/}creator") or ""
        out.append({"id": g("guid") or g("link"), "title": html.unescape(g("title")), "link": g("link"),
                    "text": html.unescape(re.sub(r"<[^>]+>", " ", g("description")))[:1500],
                    "author": creator.strip(), "published": g("pubDate")})
    return out


def article_text(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    body = re.sub(r"(?is)<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>", " ", r.text)
    m = re.search(r"(?is)<article[^>]*>(.*?)</article>", body)
    text = re.sub(r"<[^>]+>", " ", m.group(1) if m else body)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()[:14000]


def llm_json(system, user, model=None):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", timeout=90,
                      headers={"Authorization": f"Bearer {key}", "X-Title": "Lock Desk", "HTTP-Referer": "https://rwalwan.github.io/fantasybasketball/"},
                      json={"model": model or MODEL, "temperature": 0, "response_format": {"type": "json_object"},
                            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else None


NEWS_PROMPT = """You turn one NBA news blurb into JSON for a fantasy basketball tool. Reply with ONE JSON object:
{"player": "<full name or empty>", "team": "<NBA abbreviation or empty>",
 "kind": "injury|return|minutes|role|lineup|trade|signing|suspension|other",
 "status": "out|doubtful|questionable|probable|available|unknown",
 "games_out_estimate": <integer or null>,
 "out_min_days": <integer or null>, "out_max_days": <integer or null>,
 "minutes_effect": "up|down|none|unknown",
 "beneficiaries": ["<teammates likely to gain minutes or usage, only if the blurb or obvious depth chart implies it>"],
 "summary": "<one short sentence in your own words>"}
out_min_days / out_max_days = the reported absence timeline in DAYS from this report, only if the text gives one:
"out 2-4 weeks" -> 14, 28; "at least a week" -> 7, null; "expected back Friday" -> both = days until then;
"about two months" -> 45, 75 (about N -> 0.75N to 1.25N); "out for the season" -> 200, 200; "day-to-day" -> 0, 3; "indefinitely" or no timeline -> null, null.
Use only what the text supports. Do not copy sentences from the source."""

CLAIMS_PROMPT = """You read one fantasy basketball article or post for a tool that tracks expert opinion. Reply with ONE JSON object:
{"claims": [{"player": "<full name>", "action": "add|drop|start|sit|buy|sell|stream|hold|avoid",
             "horizon": "day|week|season", "conviction": 1-3, "reason": "<under 15 words, your own words>"}],
 "takes":  [{"player": "<full name>", "lean": "up|down|neutral", "take": "<under 20 words, your own words>"}]}
claims = explicit IN-SEASON recommendations (pick up, drop, start, sit, trade for, trade away now).
takes  = any substantive opinion about a specific NBA player's outlook (role, minutes, usage, injury, matchup, trend),
         even without a recommendation. One take per player, the most important point.
Exclude draft advice (draft picks, ADP, "worth a late pick", keeper/dynasty stashes) and general strategy.
Never copy sentences from the source. If there is nothing, return {"claims": [], "takes": []}."""


def collect(meta, my_players, fa_ids, today):
    """Fetch feeds, extract with the LLM, update news + claims state. Returns (news_items, claims)."""
    names = Names(meta)
    seen = _load("seen_items.json", {})
    news = _load("news.json", [])
    claims = _load("claims.json", [])
    budget = MAX_LLM_ITEMS
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")

    srcs, report = sources.active_sources()
    takes = _load("expert_takes.json", [])
    news_budget, advice_budget = MAX_LLM_ITEMS // 2, MAX_LLM_ITEMS - MAX_LLM_ITEMS // 2
    full_budget = 6                    # full-article reads for cut-off injury teasers, per run
    advice_items = []
    for src in srcs:
        try:
            items = sources.fetch_items(src)
        except Exception as e:
            print("feed failed", src["name"], e)
            continue
        for it in items:
            if it["id"] in seen:
                continue
            is_advice = src["role"] == "advice" or (src["role"] == "mixed" and ADVICE_RE.search(it["title"]))
            if is_advice:
                advice_items.append((src, it))
                continue
            seen[it["id"]] = today
            if re.search(r"(?i)how to watch|live stream|get your latest|tv channel|betting|odds|picks? &|prediction|wnba|viewers|revenue|ratings", it["title"]):
                continue
            if src["role"] != "news" and not sources.NBA_WORDS.search(it["title"] + " " + it["text"]):
                continue
            rec = {"source": src["name"], "title": it["title"], "link": it["link"], "at": now, "text": it["text"][:400]}
            if news_budget > 0 and os.environ.get("OPENROUTER_API_KEY"):
                try:
                    x = llm_json(NEWS_PROMPT, f"Title: {it['title']}\n\n{it['text']}", model=NEWS_MODEL)
                    news_budget -= 1
                    rec["llm_tried"] = True
                    if full_budget > 0 and it.get("link") and needs_full_text(it["title"], it["text"], x):
                        full_budget -= 1
                        try:     # robots.txt-checked, polite fetch of the article itself, then re-read
                            body = sources.article_text(it["link"])[:4000]
                            y = llm_json(NEWS_PROMPT, f"Title: {it['title']}\n\n{body}", model=NEWS_MODEL)
                            if y and (y.get("out_min_days") is not None or y.get("out_max_days") is not None):
                                x, rec["full_text"] = y, True
                        except Exception as e:
                            print("full text failed:", it["link"], e)
                    if x:
                        rec.update({k: x.get(k) for k in ("player", "team", "kind", "status", "games_out_estimate",
                                                          "out_min_days", "out_max_days", "minutes_effect", "beneficiaries", "summary")})
                except Exception as e:
                    print("llm news failed:", e)
            rec["pid"] = names.pid(rec.get("player") or it["title"].split(":")[0], rec.get("team") or None)
            rec["beneficiary_pids"] = [p for p in (names.pid(b) for b in (rec.get("beneficiaries") or [])) if p]
            news.append(rec)
    budget = news_budget + 10

    # backfill: items collected before the AI key existed (or that failed) get processed now, newest first
    for rec in reversed(news):
        if budget <= 0 or not os.environ.get("OPENROUTER_API_KEY"):
            break
        # also re-read injury items processed before the prompt asked for a return timeline
        needs_tl = rec.get("kind") == "injury" and "out_min_days" not in rec and not rec.get("tl_tried")
        if (rec.get("kind") or rec.get("llm_tried")) and not needs_tl:
            continue
        rec["llm_tried"] = rec["tl_tried"] = True
        try:
            x = llm_json(NEWS_PROMPT, f"Title: {rec['title']}\n\n{rec.get('text', '')}", model=NEWS_MODEL)
            budget -= 1
            if x:
                rec.update({k: x.get(k) for k in ("player", "team", "kind", "status", "games_out_estimate",
                                                  "out_min_days", "out_max_days", "minutes_effect", "beneficiaries", "summary")})
                rec["pid"] = names.pid(rec.get("player") or "", rec.get("team") or None) or rec.get("pid")
                rec["beneficiary_pids"] = [p for p in (names.pid(b) for b in (rec.get("beneficiaries") or [])) if p]
        except Exception as e:
            print("llm backfill failed:", e)

    # advice: newest first; each article once. Without an AI key, leave them for later.
    advice_items.sort(key=lambda x: x[1]["published"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    for src, it in advice_items:
        if advice_budget <= 0 or not os.environ.get("OPENROUTER_API_KEY"):
            break
        title = it["title"]
        if DRAFT_TITLE_RE.search(title):
            seen[it["id"]] = today
            continue
        seen[it["id"]] = today
        try:
            text = it["text"] if len(it["text"]) > 900 else sources.article_text(it["link"])
            x = llm_json(CLAIMS_PROMPT, f"Source: {src['name']}\nTitle: {title}\nAuthor: {it['author']}\n\n{text}", model=ADVICE_MODEL)
            advice_budget -= 1
        except Exception as e:
            print("article failed:", src["name"], e)
            continue
        expert = f"{it['author'] or 'Staff'} ({src['name']})" if not src["name"].startswith("Reddit") else "r/fantasybball community"
        for c in (x or {}).get("claims", [])[:25]:
            pid = names.pid(c.get("player", ""))
            if not pid or c.get("action") not in BULL | BEAR:
                continue
            claims.append({"expert": expert, "site": src["name"], "date": today, "pid": pid, "player": c.get("player"),
                           "action": c["action"], "horizon": c.get("horizon") or "week", "conviction": c.get("conviction") or 2,
                           "reason": (c.get("reason") or "")[:120], "title": title, "link": it["link"]})
        for t in (x or {}).get("takes", [])[:30]:
            pid = names.pid(t.get("player", ""))
            if not pid or not t.get("take"):
                continue
            takes.append({"pid": pid, "player": t.get("player"), "lean": t.get("lean") or "neutral", "take": t["take"][:160],
                          "expert": expert, "source": src["name"], "date": today, "title": title, "link": it["link"]})

    takes_cut = (dt.date.fromisoformat(today) - dt.timedelta(days=21)).isoformat()
    takes = [t for t in takes if t["date"] >= takes_cut and not DRAFT_RE.search(t["take"])][-1500:]
    _save("expert_takes.json", takes)
    collect.report = report
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=21)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    # injury timelines outlive the 7-day news window: keep the latest reported timeline per player (availability.py)
    tl = update_timelines(_load("timelines.json", {}), news, lambda pid: (meta.get(pid) or {}).get("team"))
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=120)).isoformat()
    _save("timelines.json", {k: v for k, v in tl.items() if v["at"][:10] >= cutoff})
    news = [n for n in news if n["at"][:10] >= (dt.date.fromisoformat(today) - dt.timedelta(days=7)).isoformat()][-400:]
    _save("seen_items.json", seen)
    _save("news.json", news)
    claims = purge_draft_claims(claims)
    _save("claims.json", claims)
    return news, claims


DRAFT_RE = re.compile(r"(?i)\bdraft|\bpick\b|\badp\b|preseason|dynasty|stash|mock")


def _window(n, team_of):
    """Validated (min_days, max_days) from one extracted news item, or None. Rules (review finding 4):
    injury/return items only; extracted team must match the player's team; max-only means out at least half the
    max; a 0-day timeline counts only if the item says he's available; 0 <= min <= max <= 200."""
    if n.get("kind") not in ("injury", "return"):
        return None
    t = team_of(n.get("pid"))
    if t and n.get("team") and n["team"] != t:
        return None
    try:
        mn = None if n.get("out_min_days") is None else int(n["out_min_days"])
        mx = None if n.get("out_max_days") is None else int(n["out_max_days"])
    except (TypeError, ValueError):
        return None
    if mn is None and mx is None:
        return None
    if mn is None:
        mn = mx // 2
    if not (0 <= mn <= 200) or (mx is not None and not (mn <= mx <= 200)):
        return None
    if mn == 0 and not mx and n.get("status") != "available":
        return None
    return mn, mx


TEASER_END = re.compile(r"(\[(…|\.\.\.)\]|…)\s*$")
TIMELINE_WORDS = re.compile(r"(?i)\b(weeks?|months?|until|timeline|sidelined|indefinitely|season|surgery|re-?evaluated|miss(es|ing)? (time|games)|out for)\b")


def needs_full_text(title, text, x):
    """An injury item whose feed text is a cut-off teaser ('… […]') with timeline words in the title but no
    timeline extracted: worth reading the full article (review finding 12: 'Sidelined Until December')."""
    x = x or {}
    return (x.get("kind") == "injury" and x.get("out_min_days") is None and x.get("out_max_days") is None
            and bool(TEASER_END.search(text or "")) and bool(TIMELINE_WORDS.search(title or "")))


def approx(w):
    """'About two months' is extracted as an exact (60, 60); read an exact window of 2+ weeks (short of the season)
    as about +/-25% (review 2, finding 2). Short exact ones ('back Friday') stay as they are."""
    mn, mx = w[0], w[1]
    if mx is not None and mn == mx and 14 <= mn < 200:
        return [round(0.75 * mn), round(1.25 * mn)]
    return list(w)


def update_timelines(tl, items, team_of, window_h=48):
    """Latest reported injury timeline per player. Every validated report is kept; within 48 h of a player's
    newest report each OUTLET gets one vote (its latest report), so one aggregator's copies can't decide it, and
    the most-voted window wins (ties: the latest). A newer 'available' report wins outright (review 2, finding 2)."""
    for v in tl.values():                                   # entries saved before validation existed
        if "reports" not in v:
            w = _window(dict(v, kind="injury", pid=None), lambda _p: None)
            v["reports"] = [{"at": v["at"], "w": list(w), "source": v.get("source"), "summary": v.get("summary"),
                             "player": v.get("player"), "key": v["at"] + "|stored"}] if w else []
    for n in sorted(items, key=lambda x: x.get("at", "")):
        pid = n.get("pid")
        w = _window(n, team_of) if pid else None
        if not w:
            continue
        e = tl.setdefault(pid, {"reports": []})
        key = f"{n['at']}|{n.get('source')}|{n.get('title', '')}"
        if any(r["key"] == key for r in e["reports"]):
            continue
        e["reports"].append({"at": n["at"], "w": list(w), "source": n.get("source"), "summary": n.get("summary"),
                             "player": n.get("player"), "key": key})
    out = {}
    for pid, e in tl.items():
        reps = sorted(e.get("reports", []), key=lambda r: r["at"])
        if not reps:
            continue
        newest = dt.datetime.fromisoformat(reps[-1]["at"])
        recent = [r for r in reps if (newest - dt.datetime.fromisoformat(r["at"])).total_seconds() <= window_h * 3600]
        latest = {}
        for r in recent:                                    # sorted by time: each outlet's latest report
            latest[r.get("source") or r["key"]] = r
        votes = sorted(latest.values(), key=lambda r: r["at"])
        if reps[-1]["w"][0] == 0 and not reps[-1]["w"][1]:  # newest report says he's available: it wins
            pick, best = reps[-1], 1
        else:
            count = {}
            for r in votes:
                count[tuple(approx(r["w"]))] = count.get(tuple(approx(r["w"])), 0) + 1
            best = max(count.values())
            pick = [r for r in votes if count[tuple(approx(r["w"]))] == best][-1]
        w = approx(pick["w"])
        out[pid] = {"at": pick["at"], "out_min_days": w[0], "out_max_days": w[1],
                    "summary": pick["summary"], "source": pick["source"], "player": pick["player"],
                    "cited": best, "outlets": len(votes), "reports": recent[-30:]}
    return out


def purge_draft_claims(claims):
    return [c for c in claims if not (DRAFT_RE.search(c.get("reason", "")) or DRAFT_RE.search(c.get("title", "")))]


GRADE_V = 2   # v1 graded on live stat lines and gave bearish calls a free win when the player sat


def grade(claims, book, today):
    """Grade claims whose horizon has passed, on FINAL games only.
    add/hold/buy/stream: right if he then averaged replacement level or better; drop/sell/avoid: right if he didn't.
    start/sit: right if his next game beat (start) or missed (sit) his own average before the call.
    No games in the window = ungradeable either way (sitting out proves nothing about the call)."""
    horizon_days = {"day": 2, "week": 8, "season": 21}
    for c in claims:
        if c.get("graded_v") != GRADE_V:
            c.pop("correct", None)
            c.pop("outcome_fpg", None)
        if "correct" in c:
            continue
        end = (dt.date.fromisoformat(c["date"]) + dt.timedelta(days=horizon_days.get(c["horizon"], 8))).isoformat()
        if end > today:
            continue
        done = book.done(c["pid"])
        games = [g for g in done if c["date"] < g[0] <= end]
        c["graded_v"] = GRADE_V
        if not games:
            c["correct"] = None
            continue
        avg = sum(g[1] for g in games) / len(games)
        if c["action"] in ("start", "sit"):
            prior = [g[1] for g in done if g[0] <= c["date"]]
            ref = sum(prior) / len(prior) if prior else (book.prior.get(c["pid"]) or REPLACEMENT_FPG)
            good = games[0][1] >= ref
        else:
            good = avg >= REPLACEMENT_FPG
        c["correct"] = good if c["action"] in BULL else not good
        c["outcome_fpg"] = round(avg, 1)
    _save("claims.json", claims)
    return claims


def _kind(action):
    return "startsit" if action in ("start", "sit") else ("bull" if action in BULL else "bear")


def experts_table(claims):
    """Per expert: hit rate AND edge over the base rate for the same kind of call.
    "Add a decent player" is right most of the time for anyone, so raw hit rate rewards easy calls. Edge =
    hits minus what an average expert would have hit on those same call types; weight = 50% + shrunk edge
    (10 pseudo-calls of zero edge), clipped to 20-80%."""
    graded = [c for c in claims if c.get("correct") is not None]
    base = {}
    for k in ("bull", "bear", "startsit"):
        g = [c for c in graded if _kind(c["action"]) == k]
        base[k] = (sum(1 for c in g if c["correct"]) + 5) / (len(g) + 10)     # shrunk toward 50%
    t = {}
    for c in claims:
        e = t.setdefault(c["expert"], {"expert": c["expert"], "site": c["site"], "calls": 0, "graded": 0, "hits": 0, "exp": 0.0})
        e["calls"] += 1
        if c.get("correct") is not None:
            e["graded"] += 1
            e["hits"] += 1 if c["correct"] else 0
            e["exp"] += base[_kind(c["action"])]
    for e in t.values():
        e["hit_rate"] = round(e["hits"] / e["graded"], 3) if e["graded"] else None
        e["base_rate"] = round(e["exp"] / e["graded"], 3) if e["graded"] else None
        edge = (e["hits"] - e["exp"]) / (e["graded"] + 10)
        e["edge"] = round(edge, 3) if e["graded"] else None
        e["weight"] = round(min(0.8, max(0.2, 0.5 + edge)), 3)
        del e["exp"]
    return sorted(t.values(), key=lambda e: (-e["weight"], -e["calls"]))


def consensus(claims, table, today, days=7):
    """Weighted share of bullish vs bearish calls per player over the last `days`.
    One vote per site per player (its latest call): a site repeating itself, or several writers on one site
    echoing the same report, shouldn't count as several independent opinions."""
    w = {e["expert"]: e["weight"] for e in table}
    since = (dt.date.fromisoformat(today) - dt.timedelta(days=days)).isoformat()
    latest = {}
    for c in claims:
        if c["date"] >= since:
            k = (c["pid"], c.get("site") or c["expert"])
            if k not in latest or c["date"] >= latest[k]["date"]:
                latest[k] = c
    out = {}
    for c in latest.values():
        o = out.setdefault(c["pid"], {"player": c["player"], "bull": 0.0, "bear": 0.0, "n": 0, "calls": []})
        weight = w.get(c["expert"], 0.5) * (0.6 + 0.2 * (c.get("conviction") or 2))
        o["bull" if c["action"] in BULL else "bear"] += weight
        o["n"] += 1
        o["calls"].append({k: c[k] for k in ("expert", "action", "reason", "date", "link")})
    for o in out.values():
        tot = o["bull"] + o["bear"]
        o["bull_share"] = round(o["bull"] / tot, 3) if tot else None
        o["bull"], o["bear"] = round(o["bull"], 2), round(o["bear"], 2)
    return out


def impact(news, my_players, fa_ids, book):
    """News that matters to this roster, newest first, with a plain 'what it means' line."""
    mine, fas = set(my_players), set(fa_ids)
    out = []
    for n in reversed(news):
        pid, bens = n.get("pid"), set(n.get("beneficiary_pids") or [])
        means = None
        if pid in mine and n.get("status") in ("out", "doubtful"):
            means = "One of your players may sit: keep a bench option who plays the same day ready for his slot."
        elif pid in mine and n.get("minutes_effect") == "down":
            means = "Your player's role is shrinking: lower his lock bar expectations and watch waivers."
        elif pid in mine and n.get("kind") == "return":
            means = "Your player is back: expect ~80-85% of normal production in his first game (research), full by game 3."
        elif bens & mine:
            means = "A teammate is out, so your player should see more minutes (teammates gained ~13-16% in research)."
        elif bens & fas:
            names = ", ".join(book.name(p) for p in bens & fas)
            means = f"Waiver angle: {names} could gain minutes."
        if means:
            out.append({**{k: n.get(k) for k in ("title", "summary", "source", "link", "at", "status", "player")}, "means": means})
    return out[:40]
