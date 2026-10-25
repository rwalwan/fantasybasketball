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
MODEL = os.environ.get("OPENROUTER_MODEL") or "anthropic/claude-haiku-5.5"

ADVICE_RE = re.compile(r"(?i)waiver|start|sit\b|pickup|pick-up|add|drop|sell|buy|trade|stream|sleeper|target|risers|fallers|week \d|rest of season|ros\b|must-|hold")
DRAFT_TITLE_RE = re.compile(r"(?i)draft|adp|mock|preseason|auction|keeper|dynasty|cheat sheet")
BULL = {"add", "start", "buy", "stream", "hold"}
BEAR = {"drop", "sit", "sell", "avoid"}
REPLACEMENT_FPG = 25.0      # research: player #180 averaged 23-26 FP/G in this scoring
MAX_LLM_ITEMS = 30          # per run, to bound cost and time


def _load(name, dflt):
    try:
        return json.load(open(os.path.join(STATE, name)))
    except Exception:
        return dflt


def _save(name, obj):
    os.makedirs(STATE, exist_ok=True)
    json.dump(obj, open(os.path.join(STATE, name), "w"), separators=(",", ":"))


def norm(name):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    return re.sub(r"[^a-z ]", "", s).strip()


class Names:
    def __init__(self, meta):
        self.by_name = {}
        for pid, m in meta.items():
            if m.get("team"):
                self.by_name.setdefault(norm(f"{m.get('first_name', '')} {m.get('last_name', '')}"), pid)

    def pid(self, name):
        return self.by_name.get(norm(name))


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


def llm_json(system, user):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", timeout=90,
                      headers={"Authorization": f"Bearer {key}", "X-Title": "Lock Desk", "HTTP-Referer": "https://rwalwan.github.io/fantasybasketball/"},
                      json={"model": MODEL, "temperature": 0, "response_format": {"type": "json_object"},
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
 "minutes_effect": "up|down|none|unknown",
 "beneficiaries": ["<teammates likely to gain minutes or usage, only if the blurb or obvious depth chart implies it>"],
 "summary": "<one short sentence in your own words>"}
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
                    x = llm_json(NEWS_PROMPT, f"Title: {it['title']}\n\n{it['text']}")
                    news_budget -= 1
                    rec["llm_tried"] = True
                    if x:
                        rec.update({k: x.get(k) for k in ("player", "team", "kind", "status", "games_out_estimate",
                                                          "minutes_effect", "beneficiaries", "summary")})
                except Exception as e:
                    print("llm news failed:", e)
            rec["pid"] = names.pid(rec.get("player") or it["title"].split(":")[0])
            rec["beneficiary_pids"] = [p for p in (names.pid(b) for b in (rec.get("beneficiaries") or [])) if p]
            news.append(rec)
    budget = news_budget

    # backfill: items collected before the AI key existed (or that failed) get processed now, newest first
    for rec in reversed(news):
        if budget <= 0 or not os.environ.get("OPENROUTER_API_KEY"):
            break
        if rec.get("kind") or rec.get("llm_tried"):
            continue
        rec["llm_tried"] = True
        try:
            x = llm_json(NEWS_PROMPT, f"Title: {rec['title']}\n\n{rec.get('text', '')}")
            budget -= 1
            if x:
                rec.update({k: x.get(k) for k in ("player", "team", "kind", "status", "games_out_estimate",
                                                  "minutes_effect", "beneficiaries", "summary")})
                rec["pid"] = names.pid(rec.get("player") or "") or rec.get("pid")
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
            x = llm_json(CLAIMS_PROMPT, f"Source: {src['name']}\nTitle: {title}\nAuthor: {it['author']}\n\n{text}")
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
    news = [n for n in news if n["at"][:10] >= (dt.date.fromisoformat(today) - dt.timedelta(days=7)).isoformat()][-400:]
    _save("seen_items.json", seen)
    _save("news.json", news)
    claims = purge_draft_claims(claims)
    _save("claims.json", claims)
    return news, claims


DRAFT_RE = re.compile(r"(?i)\bdraft|\bpick\b|\badp\b|preseason|dynasty|stash|mock")


def purge_draft_claims(claims):
    return [c for c in claims if not (DRAFT_RE.search(c.get("reason", "")) or DRAFT_RE.search(c.get("title", "")))]


def grade(claims, book, today):
    """Grade claims whose horizon has passed. Bullish calls are right if the player then produced above
    replacement level (start: above his own average that day); bearish calls are right if he didn't."""
    horizon_days = {"day": 2, "week": 8, "season": 21}
    for c in claims:
        if "correct" in c:
            continue
        end = (dt.date.fromisoformat(c["date"]) + dt.timedelta(days=horizon_days.get(c["horizon"], 8))).isoformat()
        if end > today:
            continue
        games = [g for g in book.games.get(c["pid"], []) if c["date"] < g[0] <= end]
        if not games:
            c["correct"] = None if c["action"] in BULL else True   # no games: bullish ungradeable, bearish right
            continue
        avg = sum(g[1] for g in games) / len(games)
        if c["action"] in ("start", "sit"):
            prior = [g[1] for g in book.games.get(c["pid"], []) if g[0] <= c["date"]]
            ref = sum(prior) / len(prior) if prior else REPLACEMENT_FPG
            good = games[0][1] >= ref
        else:
            good = avg >= REPLACEMENT_FPG
        c["correct"] = good if c["action"] in BULL else not good
        c["outcome_fpg"] = round(avg, 1)
    _save("claims.json", claims)
    return claims


def experts_table(claims):
    """Per expert: graded calls, hit rate, and a weight = Bayesian hit rate (prior 50% over 10 calls)."""
    t = {}
    for c in claims:
        e = t.setdefault(c["expert"], {"expert": c["expert"], "site": c["site"], "calls": 0, "graded": 0, "hits": 0})
        e["calls"] += 1
        if c.get("correct") is not None and "correct" in c:
            e["graded"] += 1
            e["hits"] += 1 if c["correct"] else 0
    for e in t.values():
        e["hit_rate"] = round(e["hits"] / e["graded"], 3) if e["graded"] else None
        e["weight"] = round((e["hits"] + 5) / (e["graded"] + 10), 3)
    return sorted(t.values(), key=lambda e: (-e["weight"], -e["calls"]))


def consensus(claims, table, today, days=7):
    """Weighted share of bullish vs bearish calls per player over the last `days`."""
    w = {e["expert"]: e["weight"] for e in table}
    since = (dt.date.fromisoformat(today) - dt.timedelta(days=days)).isoformat()
    out = {}
    for c in claims:
        if c["date"] < since:
            continue
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
