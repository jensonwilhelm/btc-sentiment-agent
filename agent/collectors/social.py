"""Forum / social scraping: Reddit, BitcoinTalk, StockTwits.

Every item is normalised to:
  {source, channel, kind, title, text, url, score, comments, created(ISO), label?}

Reddit: set REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET (free "script" app at
https://www.reddit.com/prefs/apps) — Reddit often blocks anonymous requests
from cloud servers such as GitHub Actions, while app-only OAuth is allowed.
"""
from __future__ import annotations

import html
import logging
import os
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..net import Http

log = logging.getLogger("social")
_TAG = re.compile(r"<[^>]+>")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _clean(s: str | None, n: int = 600) -> str:
    s = html.unescape(_TAG.sub(" ", s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


# ───────────────────────── Reddit ─────────────────────────
class _Reddit:
    def __init__(self, http: Http):
        self.http = http
        self.base, self.suffix, self.headers = "https://www.reddit.com", ".json", {}
        cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
        if cid and sec:
            tok = http.session.post("https://www.reddit.com/api/v1/access_token", auth=(cid, sec),
                                    data={"grant_type": "client_credentials"}, timeout=http.timeout).json()
            if "access_token" in tok:
                self.base, self.suffix = "https://oauth.reddit.com", ""
                self.headers = {"Authorization": f"bearer {tok['access_token']}"}
                self.mode = "oauth"
                return
        self.mode = "anonymous"

    def get(self, path: str, **params):
        return self.http.get_json(f"{self.base}{path}{self.suffix}", params={**params, "raw_json": 1},
                                  headers=self.headers)


def reddit(http: Http, cfg: dict) -> dict:
    rc = cfg.get("reddit", {})
    api = _Reddit(http)
    items, seen, status = [], set(), {}
    for sub in rc.get("subreddits", []):
        posts = []
        try:
            for listing in rc.get("listings", ["hot"]):
                if listing == "top_day":
                    data = api.get(f"/r/{sub}/top", t="day", limit=rc.get("posts_per_listing", 75))
                else:
                    data = api.get(f"/r/{sub}/{listing}", limit=rc.get("posts_per_listing", 75))
                for ch in data["data"]["children"]:
                    p = ch["data"]
                    if p["id"] in seen:
                        continue
                    seen.add(p["id"])
                    posts.append(p)
            status[sub] = f"ok ({len(posts)} posts)"
        except Exception as e:  # noqa: BLE001
            status[sub] = f"failed ({str(e)[:80]})"
            continue

        for p in posts:
            items.append({
                "source": "Reddit", "channel": f"r/{sub}", "kind": "post",
                "title": _clean(p.get("title"), 300), "text": _clean(p.get("selftext")),
                "url": "https://www.reddit.com" + p.get("permalink", ""),
                "score": p.get("score", 0), "comments": p.get("num_comments", 0),
                "created": _iso(p.get("created_utc", 0)), "flair": p.get("link_flair_text"),
            })

        # Comments: daily discussion thread(s) + the best-scoring posts
        targets = []
        if rc.get("include_daily_discussion", True):
            targets += [p for p in posts if p.get("stickied") and re.search(r"daily|discussion", p.get("title", ""), re.I)]
        n_top = rc.get("comments_from_top_posts", 4)
        targets += sorted([p for p in posts if not p.get("stickied")], key=lambda p: p.get("score", 0), reverse=True)[:n_top]
        for p in targets:
            try:
                thread = api.get(f"/r/{sub}/comments/{p['id']}", sort="top", depth=1,
                                 limit=rc.get("comments_per_post", 40))
                for ch in thread[1]["data"]["children"]:
                    c = ch.get("data", {})
                    body = c.get("body")
                    if ch.get("kind") != "t1" or not body or body in ("[deleted]", "[removed]") \
                            or c.get("author") == "AutoModerator":
                        continue
                    items.append({
                        "source": "Reddit", "channel": f"r/{sub}", "kind": "comment",
                        "title": "", "text": _clean(body, 500),
                        "url": "https://www.reddit.com" + c.get("permalink", ""),
                        "score": c.get("score", 0), "comments": 0,
                        "created": _iso(c.get("created_utc", 0)),
                        "thread": _clean(p.get("title"), 120),
                    })
            except Exception:
                continue
    if not items:
        raise RuntimeError(f"no Reddit data ({api.mode}): {status}")
    return {"items": items, "status": status, "mode": api.mode}


# ─────────────────────── BitcoinTalk ───────────────────────
def bitcointalk(http: Http, cfg: dict) -> dict:
    items, status = [], {}
    for board, label in cfg.get("bitcointalk", {}).get("boards", {}).items():
        try:
            page = http.get_text(f"https://bitcointalk.org/index.php?board={board}",
                                 headers={"Accept": "text/html"})
            soup = BeautifulSoup(page, "html.parser")
            n = 0
            for span in soup.select('span[id^="msg_"]'):
                a = span.find("a")
                if not a:
                    continue
                tr = span.find_parent("tr")
                nums = [int(td.get_text(strip=True)) for td in tr.find_all("td")
                        if td.get_text(strip=True).isdigit()] if tr else []
                replies = nums[0] if nums else 0
                views = nums[1] if len(nums) > 1 else 0
                items.append({
                    "source": "BitcoinTalk", "channel": label, "kind": "topic",
                    "title": _clean(a.get_text(), 300), "text": "", "url": a.get("href"),
                    "score": views // 100, "comments": replies, "created": None, "views": views,
                })
                n += 1
            status[label] = f"ok ({n} topics)"
        except Exception as e:  # noqa: BLE001
            status[label] = f"failed ({str(e)[:80]})"
    if not items:
        raise RuntimeError(f"no BitcoinTalk data: {status}")
    return {"items": items, "status": status}


# ─────────────────────── StockTwits ───────────────────────
def stocktwits(http: Http, cfg: dict) -> dict:
    items = []
    for sym in cfg.get("stocktwits", {}).get("symbols", ["BTC.X"]):
        r = http.get_json(f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json")
        for m in r.get("messages", []):
            label = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
            items.append({
                "source": "StockTwits", "channel": sym, "kind": "message",
                "title": "", "text": _clean(m.get("body"), 400),
                "url": f"https://stocktwits.com/message/{m.get('id')}",
                "score": (m.get("likes") or {}).get("total", 0), "comments": 0,
                "created": m.get("created_at"), "label": label,
            })
    if not items:
        raise RuntimeError("no StockTwits messages")
    bull = sum(1 for i in items if i["label"] == "Bullish")
    bear = sum(1 for i in items if i["label"] == "Bearish")
    return {"items": items, "bullish": bull, "bearish": bear,
            "bull_ratio": bull / (bull + bear) if bull + bear else None}
