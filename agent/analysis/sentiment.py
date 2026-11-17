"""Text sentiment for forum posts, comments and headlines.

Base model: VADER with a crypto-slang lexicon (fast, free, deterministic).
If the LLM layer is enabled, the highest-engagement items are re-scored by
Claude, which handles sarcasm and context ("buy the dip" vs "it's dipping")
far better — those scores replace VADER's for those items.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

CRYPTO_LEXICON = {
    "moon": 2.5, "mooning": 3.0, "moonshot": 2.5, "bullish": 2.5, "bull": 1.5, "bulls": 1.2, "bullrun": 2.5,
    "bearish": -2.5, "bear": -1.5, "bears": -1.0, "dump": -2.5, "dumping": -2.8, "dumped": -2.3,
    "pump": 1.2, "pumping": 1.8, "rekt": -3.0, "hodl": 1.5, "hodling": 1.5, "fud": -1.5, "fomo": 0.8,
    "scam": -3.0, "rug": -3.0, "rugpull": -3.2, "capitulation": -2.5, "capitulate": -2.3, "ath": 2.0,
    "breakout": 2.0, "crash": -3.0, "crashing": -3.2, "liquidated": -2.5, "liquidation": -2.0,
    "liquidations": -2.0, "bagholder": -2.0, "bagholders": -2.0, "ngmi": -2.5, "wagmi": 2.5, "lfg": 2.0,
    "btfd": 1.5, "bleeding": -2.2, "correction": -1.2, "rally": 2.2, "rallies": 2.0, "surge": 2.2,
    "surges": 2.2, "soar": 2.5, "soars": 2.5, "plunge": -3.0, "plunges": -3.0, "tank": -2.5, "tanking": -2.8,
    "tanks": -2.5, "selloff": -2.5, "sell-off": -2.5, "outflows": -1.5, "inflows": 1.5, "accumulate": 1.5,
    "accumulating": 1.6, "accumulation": 1.5, "adoption": 1.5, "bottomed": 1.5, "rejected": -1.5,
    "rejection": -1.5, "resistance": -0.3, "support": 0.3, "squeeze": 0.8, "parabolic": 2.0, "bubble": -1.5,
    "ponzi": -3.0, "hack": -2.8, "hacked": -3.0, "exploit": -2.5, "ban": -2.0, "banned": -2.2,
    "crackdown": -2.2, "approval": 1.8, "approved": 1.8, "rekted": -3.0, "gm": 0.5, "rip": -1.5,
    "slips": -1.5, "slip": -1.3, "slides": -1.6, "falls": -1.6, "drops": -1.6, "sinks": -2.0, "tumbles": -2.3,
    "climbs": 1.6, "gains": 1.3, "jumps": 1.3, "rebounds": 1.8, "rebound": 1.5, "record": 1.0, "outflow": -1.5,
    "inflow": 1.5, "recession": -1.8, "stagflation": -2.0, "cuts": 0.5, "hike": -1.0, "hikes": -1.0,
}

STOP = set("""a an the and or but if then so to of in on at by for with from as is are was were be been being
it its this that these those i you he she we they me my your our their them us not no yes do does did done
have has had just about into over under more most less very can could would should will shall may might
than too also only up down out off what which who whom how when where why all any some each every own same
get got going go like know think really one two still even much many lot im dont cant its thats theres
i'm you're it's don't can't that's there's i've we're they're isn't won't didn't doesn't what's let's i'll
week day today again matter people time now back here right make want need say see well yeah
https http www com amp gt lt removed deleted reddit post comment thread daily discussion btc bitcoin crypto""".split())

TOPICS = {
    "ETFs / institutions": r"\betfs?\b|ibit|blackrock|fidelity|institution|inflow|outflow",
    "Fed / rates / macro": r"\bfed\b|fomc|powell|rate cut|rate hike|interest rate|inflation|cpi|treasury|yields?|recession|dxy",
    "Regulation / policy": r"\bsec\b|regulat|congress|senate|bill\b|lawsuit|gensler|atkins|strategic reserve|treasury|tariff",
    "Whales / treasuries": r"whale|saylor|microstrategy|\bmstr\b|strategy inc|treasury compan|corporate",
    "Leverage / liquidations": r"liquidat|leverage|funding|short squeeze|longs|shorts|open interest",
    "Mining / network": r"\bmin(?:er|ers|ing)\b|hashrate|difficulty|halving|mempool|fees",
    "Security / hacks": r"hack|exploit|stolen|breach|scam|phish",
    "Price targets / levels": r"\$?\d{2,3}k\b|target|support|resistance|all.time high|\bath\b",
}

_WORD = re.compile(r"[a-z][a-z0-9']{2,}")


class Scorer:
    def __init__(self):
        self.vader = SentimentIntensityAnalyzer()
        self.vader.lexicon.update(CRYPTO_LEXICON)

    def vader_score(self, text: str) -> float:
        return self.vader.polarity_scores(text)["compound"]


def _weight(it: dict) -> float:
    return 1 + math.log1p(max(it.get("score") or 0, 0)) + 0.5 * math.log1p(it.get("comments") or 0)


def _text(it: dict) -> str:
    return f"{it.get('title', '')}. {it.get('text', '')}".strip(". ")


def score_items(items: list[dict], llm_scores: dict[int, float] | None = None) -> None:
    """Adds 'sentiment' (-1..+1), 'weight' and 'method' to each item in-place."""
    s = Scorer()
    for i, it in enumerate(items):
        v = s.vader_score(_text(it))
        method = "vader"
        if llm_scores and i in llm_scores:
            v, method = llm_scores[i], "llm"
        if it.get("label") in ("Bullish", "Bearish"):  # StockTwits self-label
            v = 0.5 * v + 0.5 * (0.8 if it["label"] == "Bullish" else -0.8)
        it["sentiment"], it["weight"], it["method"] = round(v, 4), round(_weight(it), 3), method


def _agg(items: list[dict]) -> dict:
    if not items:
        return {"n": 0}
    w = sum(i["weight"] for i in items)
    mean = sum(i["sentiment"] * i["weight"] for i in items) / w
    pos = sum(1 for i in items if i["sentiment"] > 0.05)
    neg = sum(1 for i in items if i["sentiment"] < -0.05)
    return {"n": len(items), "weighted_mean": mean, "bullish_pct": pos / len(items) * 100,
            "bearish_pct": neg / len(items) * 100, "neutral_pct": (len(items) - pos - neg) / len(items) * 100}


def summarize(items: list[dict]) -> dict:
    social = [i for i in items if i["source"] != "News"]
    news = [i for i in items if i["source"] == "News"]
    by_source, by_channel = {}, {}
    for it in items:
        by_source.setdefault(it["source"], []).append(it)
        by_channel.setdefault(f"{it['source']} · {it['channel']}", []).append(it)

    def top(lst, sign, n=6):
        ranked = sorted([i for i in lst if i["sentiment"] * sign > 0.2],
                        key=lambda i: i["weight"] * abs(i["sentiment"]), reverse=True)
        out, seen = [], set()
        for i in ranked:
            key = re.sub(r"\W+", "", (i.get("title") or i.get("text") or "").lower())[:100]
            if key in seen:
                continue
            seen.add(key)
            out.append({k: i.get(k) for k in ("source", "channel", "kind", "title", "text", "url", "score",
                                               "comments", "sentiment", "thread")})
            if len(out) == n:
                break
        return out

    words, topics = Counter(), Counter()
    topic_sent: dict[str, list[float]] = {}
    for it in social + news:
        t = _text(it).lower()
        for name, rx in TOPICS.items():
            if re.search(rx, t):
                topics[name] += 1
                topic_sent.setdefault(name, []).append(it["sentiment"])
        if it in social:
            words.update(w for w in _WORD.findall(t) if w not in STOP and not w.isdigit())

    return {
        "social": _agg(social),
        "news": _agg(news),
        "by_source": {k: _agg(v) for k, v in by_source.items()},
        "by_channel": {k: _agg(v) for k, v in sorted(by_channel.items())},
        "top_bullish": top(social, +1),
        "top_bearish": top(social, -1),
        "top_headlines": sorted(news, key=lambda i: i["created"] or "", reverse=True)[:25],
        "topics": [{"topic": k, "mentions": v, "avg_sentiment": sum(topic_sent[k]) / len(topic_sent[k])}
                   for k, v in topics.most_common()],
        "trending_terms": words.most_common(30),
        "llm_scored": sum(1 for i in items if i.get("method") == "llm"),
    }
