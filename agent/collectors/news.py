"""Crypto news headlines from RSS feeds (last N hours, Bitcoin-related only)."""
from __future__ import annotations

import calendar
import html
import re
from datetime import datetime, timezone

import feedparser

from ..net import Http

_BTC = re.compile(r"\b(bitcoin|btc|satoshi|sats|spot etf|ibit|saylor|strategy|halving)\b", re.I)
_TAG = re.compile(r"<[^>]+>")


def _clean(s: str, n: int = 400) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", s or ""))).strip()[:n]


def collect(http: Http, cfg: dict) -> dict:
    nc = cfg.get("news", {})
    max_age = nc.get("max_age_hours", 36) * 3600
    now = datetime.now(timezone.utc).timestamp()
    arts, seen, status = [], set(), {}
    for name, url in nc.get("feeds", {}).items():
        try:
            feed = feedparser.parse(http.get_text(url, headers={"Accept": "application/rss+xml, application/xml"}))
            n = 0
            for e in feed.entries:
                t = e.get("published_parsed") or e.get("updated_parsed")
                ts = calendar.timegm(t) if t else now
                if now - ts > max_age:
                    continue
                title = _clean(e.get("title", ""), 250)
                summary = _clean(e.get("summary", ""))
                if not _BTC.search(title + " " + summary):
                    continue
                key = re.sub(r"\W+", "", title.lower())[:80]
                if key in seen:
                    continue
                seen.add(key)
                arts.append({"source": "News", "channel": name, "kind": "headline", "title": title,
                             "text": summary, "url": e.get("link"), "score": 0, "comments": 0,
                             "created": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()})
                n += 1
            status[name] = f"ok ({n})"
        except Exception as e:  # noqa: BLE001
            status[name] = f"failed ({str(e)[:80]})"
    if not arts:
        raise RuntimeError(f"no headlines: {status}")
    arts.sort(key=lambda a: a["created"], reverse=True)
    return {"items": arts, "status": status}
