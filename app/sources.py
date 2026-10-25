"""Expert & news source registry + a polite crawler.

Rules the bot follows:
  * public pages only: no logins, no paywalls, no bypassing anything
  * robots.txt is checked for every URL before fetching (urllib.robotparser); disallowed = skipped
  * identifies itself with a descriptive User-Agent, waits between requests to the same site,
    and only fetches feeds/index pages every cycle (articles once each)
  * stores short summaries in our own words plus a link, never article text

Every few days `health_check()` re-tests every candidate (reachable? allowed? recent items? relevant?)
and writes data/state/source_report.json. Collection uses only sources that passed.
"""
import datetime as dt
import email.utils
import html
import json
import os
import re
import time
import urllib.robotparser
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import requests

STATE = os.path.join(os.path.dirname(__file__), "..", "data", "state")
UA = "we-back-lock-desk/1.0 (personal fantasy basketball assistant; +https://github.com/rwalwan/fantasybasketball)"
HEADERS = {"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.5"}
NBA_WORDS = re.compile(r"(?i)\bnba\b|fantasy basketball|basketball|waiver|start/sit|lakers|celtics|knicks|warriors|nuggets|bucks|"
                       r"thunder|cavaliers|rockets|spurs|pistons|magic|heat|hawks|hornets|bulls|pacers|raptors|nets|76ers|sixers|"
                       r"wizards|grizzlies|pelicans|mavericks|suns|clippers|kings|jazz|blazers|timberwolves")

# role: news = player status/role updates; advice = articles with recommendations; mixed = route per item
CANDIDATES = [
    {"name": "RotoWire news", "kind": "rss", "role": "news", "url": "https://www.rotowire.com/rss/news.php?sport=NBA"},
    {"name": "RealGM", "kind": "rss", "role": "news", "url": "https://basketball.realgm.com/rss/wiretap/0/0.xml"},
    {"name": "HoopsHype", "kind": "rss", "role": "news", "url": "https://hoopshype.com/feed/"},
    {"name": "ESPN NBA", "kind": "rss", "role": "news", "url": "https://www.espn.com/espn/rss/nba/news"},
    {"name": "Yahoo NBA", "kind": "rss", "role": "news", "url": "https://sports.yahoo.com/nba/rss/"},
    {"name": "CBS NBA", "kind": "rss", "role": "news", "url": "https://www.cbssports.com/rss/headlines/nba/"},
    {"name": "RotoBaller", "kind": "rss", "role": "mixed", "url": "https://www.rotoballer.com/category/nba/feed"},
    {"name": "RotoBaller waivers", "kind": "rss", "role": "advice", "url": "https://www.rotoballer.com/category/nba/nba-waiver-wire/feed"},
    {"name": "Razzball", "kind": "rss", "role": "advice", "url": "https://basketball.razzball.com/feed/"},
    {"name": "Fantrax HQ", "kind": "rss", "role": "advice", "url": "https://fantraxhq.com/category/nba/feed/"},
    {"name": "Fantrax HQ fantasy", "kind": "rss", "role": "advice", "url": "https://fantraxhq.com/category/fantasy-basketball/feed/"},
    {"name": "FantasyPros NBA", "kind": "rss", "role": "advice", "url": "https://www.fantasypros.com/feed/nba/"},
    {"name": "Yahoo fantasy basketball", "kind": "rss", "role": "advice", "url": "https://sports.yahoo.com/fantasy/basketball/rss/"},
    {"name": "FanDuel Research NBA", "kind": "rss", "role": "advice", "url": "https://www.fanduel.com/research/nba/feed"},
    {"name": "Fantasy Six Pack", "kind": "rss", "role": "advice", "url": "https://fantasysixpack.net/category/fantasy-basketball/feed/"},
    {"name": "Sports Illustrated fantasy", "kind": "rss", "role": "advice", "url": "https://www.si.com/.rss/full/fantasy"},
    {"name": "NBC Sports NBA", "kind": "rss", "role": "news", "url": "https://www.nbcsports.com/rss/nba"},
    {"name": "Reddit r/fantasybball", "kind": "rss", "role": "advice", "url": "https://www.reddit.com/r/fantasybball/top/.rss?t=day"},
    {"name": "Hashtag Basketball", "kind": "html", "role": "advice", "url": "https://hashtagbasketball.com/fantasy-basketball-news",
     "link": r"hashtagbasketball\.com/(?:fantasy-basketball/)?(?:content|article|news)/[\w-]+"},
    {"name": "Basketball Monster news", "kind": "html", "role": "news", "url": "https://basketballmonster.com/playernews.aspx",
     "link": r"basketballmonster\.com/playernews\.aspx\?[^\"']+"},
]

_robots, _last_hit = {}, {}


def allowed(url):
    host = urlparse(url).scheme + "://" + urlparse(url).netloc
    rp = _robots.get(host)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = requests.get(host + "/robots.txt", headers={"User-Agent": UA}, timeout=15)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception:
            rp.parse([])
        _robots[host] = rp
    return rp.can_fetch(UA, url)


def polite_get(url, timeout=30):
    host = urlparse(url).netloc
    wait = 2.0 - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r


def _date(s):
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s).astimezone(dt.timezone.utc)
    except Exception:
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except Exception:
            return None


def parse_feed_text(content):
    root = ET.fromstring(content)
    ns = {"a": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/"}
    out = []
    for it in root.iter("item"):
        g = lambda t: (it.findtext(t) or "").strip()
        out.append({"id": g("guid") or g("link"), "title": html.unescape(g("title")), "link": g("link"),
                    "text": html.unescape(re.sub(r"<[^>]+>", " ", g("description")))[:1500],
                    "author": (it.findtext("dc:creator", namespaces=ns) or g("author") or "").strip(),
                    "published": _date(g("pubDate") or it.findtext("dc:date", namespaces=ns))})
    for e in root.iter("{http://www.w3.org/2005/Atom}entry"):
        link = e.find("a:link", ns)
        href = link.get("href") if link is not None else ""
        content_el = e.find("a:content", ns) if e.find("a:content", ns) is not None else e.find("a:summary", ns)
        out.append({"id": e.findtext("a:id", namespaces=ns) or href, "title": html.unescape(e.findtext("a:title", namespaces=ns) or ""),
                    "link": href, "text": html.unescape(re.sub(r"<[^>]+>", " ", (content_el.text if content_el is not None else "") or ""))[:1500],
                    "author": (e.findtext("a:author/a:name", namespaces=ns) or "").strip(),
                    "published": _date(e.findtext("a:updated", namespaces=ns) or e.findtext("a:published", namespaces=ns))})
    return out


def fetch_items(src):
    """Items from one source (rss or html index). Raises on fetch errors; returns [] if robots disallow."""
    if not allowed(src["url"]):
        return []
    r = polite_get(src["url"])
    if src["kind"] == "rss":
        return parse_feed_text(r.content)
    links, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S | re.I):
        href = urljoin(src["url"], html.unescape(m.group(1)))
        title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        if re.search(src["link"], href) and href not in seen and len(title) > 12:
            seen.add(href)
            links.append({"id": href, "title": title, "link": href, "text": "", "author": "", "published": None})
    return links[:40]


def article_text(url):
    if not allowed(url):
        raise PermissionError("robots.txt disallows " + url)
    r = polite_get(url)
    body = re.sub(r"(?is)<(script|style|nav|footer|header|aside|form)[^>]*>.*?</\1>", " ", r.text)
    m = re.search(r"(?is)<article[^>]*>(.*?)</article>", body) or re.search(r'(?is)<div[^>]+class="[^"]*(?:entry-content|article-body|post-content)[^"]*"[^>]*>(.*?)</div>\s*</div>', body)
    text = re.sub(r"<[^>]+>", " ", m.group(1) if m else body)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()[:14000]


def health_check():
    report = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "sources": []}
    now = dt.datetime.now(dt.timezone.utc)
    for src in CANDIDATES:
        row = {k: src[k] for k in ("name", "kind", "role", "url")}
        try:
            if not allowed(src["url"]):
                row.update(ok=False, why="robots.txt disallows")
            else:
                items = fetch_items(src)
                dates = [i["published"] for i in items if i["published"]]
                newest = max(dates) if dates else None
                relevant = sum(1 for i in items if NBA_WORDS.search(i["title"] + " " + i["text"])) / max(1, len(items))
                fresh = newest is None or (now - newest).days <= 14
                ok = len(items) >= 3 and fresh and relevant >= 0.3
                row.update(ok=ok, items=len(items), newest=newest.isoformat(timespec="minutes") if newest else None,
                           relevant=round(relevant, 2),
                           why="ok" if ok else ("too few items" if len(items) < 3 else "stale" if not fresh else "not NBA-focused"))
        except Exception as e:
            row.update(ok=False, why=f"error: {str(e)[:120]}")
        report["sources"].append(row)
    os.makedirs(STATE, exist_ok=True)
    json.dump(report, open(os.path.join(STATE, "source_report.json"), "w"), indent=1)
    return report


def active_sources(max_age_days=3):
    path = os.path.join(STATE, "source_report.json")
    rep = None
    if os.path.exists(path):
        rep = json.load(open(path))
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(rep["at"])
        if age.days >= max_age_days:
            rep = None
    if rep is None:
        rep = health_check()
    ok = {r["name"] for r in rep["sources"] if r.get("ok")}
    return [s for s in CANDIDATES if s["name"] in ok], rep
