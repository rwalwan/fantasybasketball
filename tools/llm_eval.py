"""Head-to-head test of AI models on OUR tasks (run by .github/workflows/llm-eval.yml).

Tasks, with the exact prompts the app uses (timelines are scored against tests/fixtures/timeline_labels.json):
  news    one news blurb -> player / status / kind / minutes effect        (high volume, simple)
  advice  one expert article -> in-season calls + per-player takes        (low volume, nuanced; feeds expert grading)

There's no hand-labelled answer key, so each model is scored against the CONSENSUS of the other models on the
same input (a field counts as right if it matches what most of the others said). Also: valid-JSON rate, latency,
and the real billed cost OpenRouter reports per call. Writes data/state/llm_eval.json.
"""
import collections
import json
import os
import statistics
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import news, sources  # noqa: E402

STATE = os.path.join(os.path.dirname(__file__), "..", "data", "state")
KEY = os.environ.get("OPENROUTER_API_KEY", "")
LABELS = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "timeline_labels.json")
CONFIGS = [  # (label, model, extra request params)
    ("Claude Haiku 5.5", "anthropic/claude-haiku-5.5", {}),
    ("Claude Haiku 5.5 + reasoning (low)", "anthropic/claude-haiku-5.5", {"reasoning": {"effort": "low"}}),
    ("GPT-6 Luna", "openai/gpt-6-luna", {}),
    ("DeepSeek V4.1 Flash", "deepseek/deepseek-v4.1-flash-1017", {}),
    ("Gemini 3.5 Flash Lite", "google/gemini-3.5-flash-lite", {}),
    ("Claude Sonnet 5.5", "anthropic/claude-sonnet-5.5", {}),
]
N_NEWS, N_ADVICE = int(os.environ.get("EVAL_NEWS", 40)), int(os.environ.get("EVAL_ADVICE", 6))


def call(model, extra, system, user):
    t = time.time()
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", timeout=180,
                      headers={"Authorization": f"Bearer {KEY}", "X-Title": "Lock Desk eval"},
                      json={"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                            "usage": {"include": True}, **extra,
                            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    dt_ = time.time() - t
    if not r.ok:
        return {"error": f"{r.status_code} {r.text[:160]}", "sec": dt_}
    j = r.json()
    txt = (j.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    u = j.get("usage") or {}
    out = {"sec": dt_, "cost": u.get("cost"), "in": u.get("prompt_tokens"), "out": u.get("completion_tokens")}
    try:
        s = txt[txt.index("{"): txt.rindex("}") + 1]
        out["json"] = json.loads(s)
    except Exception:
        out["json"] = None
    return out


def norm(x):
    return (str(x or "")).strip().lower()


def family(label):
    return next(c[1] for c in CONFIGS if c[0] == label).split("/")[0]


def panel(label, labels):
    """Who judges `label` by consensus: one model per OTHER family (same-family models agree with each other,
    so letting Haiku vote for Haiku inflated its score)."""
    out, fams = [], {family(label)}
    for x in labels:
        if family(x) not in fams:
            out.append(x)
            fams.add(family(x))
    return out


def timeline_match(pred, label):
    """(min, max) days vs the hand label: each end within max(3 days, 15%), and None only matches None."""
    for p, l in zip(pred, label):
        if (p is None) != (l is None):
            return False
        if p is not None and abs(p - l) > max(3, 0.15 * l):
            return False
    return True


def score_timelines(preds, items):
    """(raw accuracy, accuracy after the app's validation rules) of extracted timelines vs labels."""
    raw = eff = 0
    for (pmin, pmax), it in zip(preds, items):
        lab = (it["label"]["out_min_days"], it["label"]["out_max_days"])
        raw += timeline_match((pmin, pmax), lab)
        norm = lambda mn, mx: news._window({"kind": "injury", "status": it.get("status"), "out_min_days": mn, "out_max_days": mx},
                                           lambda _p: None) or (None, None)
        eff += timeline_match(norm(pmin, pmax), norm(*lab))
    return raw / max(1, len(items)), eff / max(1, len(items))


def main():
    old = json.load(open(os.path.join(STATE, "news.json"))) if os.path.exists(os.path.join(STATE, "news.json")) else []
    blurbs = [n for n in reversed(old) if n.get("text")][:N_NEWS]
    arts = []
    for src in sources.CANDIDATES:
        if src["role"] != "advice" or len(arts) >= N_ADVICE:
            continue
        try:
            for it in sources.fetch_items(src)[:3]:
                if news.DRAFT_TITLE_RE.search(it["title"]):
                    continue
                text = it["text"] if len(it["text"]) > 900 else sources.article_text(it["link"])
                arts.append({"src": src["name"], "title": it["title"], "author": it["author"], "text": text})
                if len(arts) >= N_ADVICE:
                    break
        except Exception as e:
            print("skip", src["name"], e)
    print(f"{len(blurbs)} news blurbs, {len(arts)} articles")

    labeled = json.load(open(LABELS))["items"]
    res = collections.defaultdict(lambda: {"news": [], "advice": [], "timeline": []})
    for label, model, extra in CONFIGS:
        for it in labeled:
            x = call(model, extra, news.NEWS_PROMPT, f"Title: {it['title']}\n\n{it['text']}")
            j = x.get("json") or {}
            res[label]["timeline"].append((j.get("out_min_days"), j.get("out_max_days")))
        for b in blurbs:
            res[label]["news"].append(call(model, extra, news.NEWS_PROMPT, f"Title: {b['title']}\n\n{b['text']}"))
        for a in arts:
            res[label]["advice"].append(call(model, extra, news.CLAIMS_PROMPT,
                                             f"Source: {a['src']}\nTitle: {a['title']}\nAuthor: {a['author']}\n\n{a['text']}"))
        print(label, "done")

    labels = [c[0] for c in CONFIGS]
    report = {"at": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()), "n_news": len(blurbs), "n_advice": len(arts), "models": []}
    for label in labels:
        others = panel(label, labels)
        # news: field agreement with the majority of the other models
        agree = collections.Counter()
        tot = collections.Counter()
        for i, r in enumerate(res[label]["news"]):
            mine = r.get("json") or {}
            for f in ("player", "status", "kind", "minutes_effect"):
                votes = collections.Counter(norm((res[o]["news"][i].get("json") or {}).get(f)) for o in others
                                            if res[o]["news"][i].get("json"))
                if not votes:
                    continue
                maj, cnt = votes.most_common(1)[0]
                if cnt * 2 < sum(votes.values()):
                    continue                                   # others don't agree either: skip the item
                tot[f] += 1
                agree[f] += norm(mine.get(f)) == maj
        # advice: (player, action) calls and take players, precision/recall vs calls most others made
        P = R = 0.0
        pr_n = 0
        tk = []
        for i, r in enumerate(res[label]["advice"]):
            def pairs(x):
                j = x.get("json") or {}
                return ({(norm(c.get("player")), norm(c.get("action"))) for c in j.get("claims") or []},
                        {norm(t.get("player")) for t in j.get("takes") or []})
            mine_c, mine_t = pairs(r)
            cnt_c, cnt_t = collections.Counter(), collections.Counter()
            for o in others:
                c, t_ = pairs(res[o]["advice"][i])
                cnt_c.update(c)
                cnt_t.update(t_)
            need = len(others) / 2
            ref_c = {k for k, v in cnt_c.items() if v >= need}
            ref_t = {k for k, v in cnt_t.items() if v >= need}
            if ref_c or mine_c:
                P += len(mine_c & ref_c) / len(mine_c) if mine_c else (1.0 if not ref_c else 0.0)
                R += len(mine_c & ref_c) / len(ref_c) if ref_c else 1.0
                pr_n += 1
            if ref_t:
                tk.append(len(mine_t & ref_t) / len(ref_t))
        allc = res[label]["news"] + res[label]["advice"]
        costs = [x["cost"] for x in allc if x.get("cost") is not None]
        nc = [x["cost"] for x in res[label]["news"] if x.get("cost") is not None]
        ac = [x["cost"] for x in res[label]["advice"] if x.get("cost") is not None]
        report["models"].append({
            "label": label, "model": next(c[1] for c in CONFIGS if c[0] == label),
            "errors": sum(1 for x in allc if x.get("error")), "first_error": next((x["error"] for x in allc if x.get("error")), None),
            "json_ok": round(sum(1 for x in allc if x.get("json") is not None) / max(1, len(allc)), 3),
            "news_agree": {f: round(agree[f] / tot[f], 3) for f in tot},
            "news_agree_avg": round(sum(agree.values()) / max(1, sum(tot.values())), 3),
            "calls_precision": round(P / pr_n, 3) if pr_n else None, "calls_recall": round(R / pr_n, 3) if pr_n else None,
            "takes_recall": round(sum(tk) / len(tk), 3) if tk else None,
            "timeline_raw": round(score_timelines(res[label]["timeline"], labeled)[0], 3),
            "timeline_effective": round(score_timelines(res[label]["timeline"], labeled)[1], 3),
            "sec_median": round(statistics.median([x["sec"] for x in allc]), 2) if allc else None,
            "cost_total": round(sum(costs), 5), "cost_per_news": round(statistics.mean(nc), 6) if nc else None,
            "cost_per_article": round(statistics.mean(ac), 6) if ac else None,
            "out_tokens_per_article": round(statistics.mean([x["out"] for x in res[label]["advice"] if x.get("out")]), 0)
            if any(x.get("out") for x in res[label]["advice"]) else None,
        })
        # projected monthly cost at our volume (about 200 news blurbs + 15 articles a day)
        m = report["models"][-1]
        if m["cost_per_news"] is not None and m["cost_per_article"] is not None:
            m["monthly_est"] = round(30 * (200 * m["cost_per_news"] + 15 * m["cost_per_article"]), 2)
    json.dump(report, open(os.path.join(STATE, "llm_eval.json"), "w"), indent=1)
    for m in report["models"]:
        print(json.dumps(m))


if __name__ == "__main__":
    main()
