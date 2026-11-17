"""Offline tests: feed each collector responses shaped like the real APIs and
check the parsing. Run with:  python -m pytest -q"""
from __future__ import annotations

import time

import pytest

from agent.analysis import sentiment, signals, technicals
from agent.collectors import derivatives, flow, indicators, news, onchain, orderbook, social

CFG = {"orderbook": {"band_pcts": [1, 2], "wall_bucket_usd": 100, "wall_search_pct": 5, "top_walls": 3,
                     "large_order_btc": 10},
       "flow": {"large_trade_usd": 400_000},
       "reddit": {"subreddits": ["Bitcoin"], "listings": ["hot"], "posts_per_listing": 5,
                  "comments_from_top_posts": 1, "comments_per_post": 5},
       "bitcointalk": {"boards": {"57.0": "Speculation"}},
       "news": {"max_age_hours": 48, "feeds": {"Test": "https://feed.example/rss"}},
       "signal": {"weights": {k: 1 for k in ("trend", "momentum", "mean_reversion", "social_sentiment",
                                             "fear_greed_contrarian", "funding_contrarian", "orderbook_imbalance",
                                             "taker_flow")}}}


class FakeHttp:
    """Returns canned payloads keyed by URL substring; anything else raises (= blocked venue)."""
    timeout = 5

    def __init__(self, routes: dict):
        self.routes = routes

    def _find(self, url):
        for k, v in self.routes.items():
            if k in url:
                return v
        raise RuntimeError(f"blocked: {url}")

    def get_json(self, url, **kw):
        return self._find(url)

    def post_json(self, url, payload, **kw):
        return self._find(url)

    def get_text(self, url, **kw):
        return self._find(url)


MID = 100_000.0
BOOK_BIDS = [[str(MID - 5 - i * 50), "0.5"] for i in range(80)] + [[str(MID - 1500), "40"]]
BOOK_ASKS = [[str(MID + 5 + i * 50), "0.4"] for i in range(80)] + [[str(MID + 2200), "25"]]


def test_orderbook_walls_and_imbalance():
    http = FakeHttp({
        "coinbase.com/products/BTC-USD/book": {"bids": [b + [3] for b in BOOK_BIDS], "asks": [a + [2] for a in BOOK_ASKS]},
        "kraken.com/0/public/Depth": {"result": {"XXBTZUSD": {"bids": [b + [0] for b in BOOK_BIDS],
                                                              "asks": [a + [0] for a in BOOK_ASKS]}}},
    })
    r = orderbook.collect(http, CFG)
    assert set(r["exchanges"]) == {"Coinbase", "Kraken"}
    assert r["venue_status"]["Binance"].startswith("skipped")
    assert r["bid_walls"][0]["btc"] >= 80 and r["bid_walls"][0]["price"] < MID
    assert r["ask_walls"][0]["btc"] >= 50 and r["ask_walls"][0]["price"] > MID
    assert -1 <= r["aggregate"]["2"]["imbalance"] <= 1
    assert any(o["side"] == "bid" and o["btc"] == 40 for o in r["large_orders"])


def test_flow_taker_and_whales():
    now = time.time()
    http = FakeHttp({
        "binance.vision/api/v3/klines": [[0, "0", "0", "0", "0", "100", 0, "0", 0, "60", "0", "0"]] * 24,
        "coinbase.com/products/BTC-USD/trades": [
            {"time": "2026-11-17T10:00:00.000Z", "trade_id": 1, "price": "100000", "size": "5", "side": "sell"},
            {"time": "2026-11-17T10:01:00.000Z", "trade_id": 2, "price": "100000", "size": "0.1", "side": "buy"}],
        "kraken.com/0/public/Trades": {"result": {"XXBTZUSD": [["100000", "6", now, "s", "m", "", 1]], "last": "1"}},
    })
    r = flow.collect(http, CFG)
    assert r["taker_buy_btc_24h"] == pytest.approx(1440) and r["taker_imbalance"] == pytest.approx(0.2)
    sides = {(t["exchange"], t["side"]) for t in r["large_trades"]}
    assert ("Coinbase", "buy") in sides       # maker sell → taker buy
    assert ("Kraken", "sell") in sides


def test_derivatives_mix_of_venues():
    http = FakeHttp({
        "hyperliquid.xyz/info": [{"universe": [{"name": "ETH"}, {"name": "BTC"}]},
                                 [{"funding": "0.00002", "openInterest": "10", "markPx": "3000"},
                                  {"funding": "0.0000125", "openInterest": "20000", "markPx": "100000"}]],
        "deribit.com/api/v2/public/ticker": {"result": {"funding_8h": 0.0001, "open_interest": 1e9, "mark_price": 1e5}},
        "deribit.com/api/v2/public/get_book_summary_by_currency": {"result": [
            {"instrument_name": "BTC-27DEC26-90000-P", "open_interest": 300},
            {"instrument_name": "BTC-27DEC26-120000-C", "open_interest": 500}]},
    })
    r = derivatives.collect(http, CFG, spot=MID)
    assert {f["venue"] for f in r["funding"]} == {"Hyperliquid", "Deribit"}
    assert r["funding"][0]["rate_8h"] == pytest.approx(0.0001)
    assert r["put_call_oi"] == pytest.approx(0.6)
    assert r["oi_total_usd"] == pytest.approx(2e9 + 1e9)


def test_onchain_and_fear_greed():
    http = FakeHttp({
        "fees/recommended": {"fastestFee": 5, "halfHourFee": 4, "hourFee": 3, "economyFee": 2, "minimumFee": 1},
        "mempool.space/api/mempool": {"count": 1000, "vsize": 2_000_000},
        "blocks/tip/height": "925000",
        "difficulty-adjustment": {"difficultyChange": 1.5, "progressPercent": 40, "remainingBlocks": 1200,
                                  "estimatedRetargetDate": 1_800_000_000_000},
        "hashrate/3m": {"currentHashrate": 8e20, "hashrates": [{"timestamp": 1_700_000_000 + i * 86400,
                                                                "avgHashrate": 7e20 + i * 1e18} for i in range(60)]},
        "alternative.me/fng": {"data": [{"value": "72", "value_classification": "Greed", "timestamp": "1763337600"},
                                        {"value": "65", "value_classification": "Greed", "timestamp": "1763251200"}]},
    })
    oc = onchain.collect(http, CFG)
    assert oc["block_height"] == 925000 and oc["hashrate_eh"] == pytest.approx(800)
    assert oc["hashrate_change_30d_pct"] > 0
    fg = indicators.fear_greed(http, CFG)
    assert fg["value"] == 72 and fg["history"][-1]["value"] == 72


def test_reddit_bitcointalk_news():
    post = {"id": "abc", "title": "Bitcoin breakout, bullish!", "selftext": "", "permalink": "/r/Bitcoin/abc",
            "score": 500, "num_comments": 50, "created_utc": time.time(), "stickied": False}
    daily = dict(post, id="dd", title="Daily Discussion, November 17, 2026", stickied=True)
    http = FakeHttp({
        "/r/Bitcoin/hot": {"data": {"children": [{"data": post}, {"data": daily}]}},
        "/r/Bitcoin/comments/": [{}, {"data": {"children": [
            {"kind": "t1", "data": {"body": "rekt again", "score": 3, "permalink": "/x", "created_utc": time.time(),
                                    "author": "u1"}},
            {"kind": "t1", "data": {"body": "[removed]", "score": 1, "permalink": "/y", "created_utc": 0, "author": "u2"}},
            {"kind": "more", "data": {}}]}}],
        "bitcointalk.org": """<table><tr><td></td><td><span id="msg_1"><a href="https://bitcointalk.org/index.php?topic=1.0">
            BTC to the moon?</a></span></td><td>starter</td><td>42</td><td>1234</td></tr></table>""",
        "feed.example": """<?xml version="1.0"?><rss><channel><item><title>Bitcoin surges past record</title>
            <link>https://x/1</link><pubDate>%s</pubDate></item><item><title>Ethereum upgrade ships</title>
            <link>https://x/2</link><pubDate>%s</pubDate></item></channel></rss>""" % (
            (time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime()),) * 2),
    })
    http.session = None
    r = social.reddit(http, CFG)
    kinds = [i["kind"] for i in r["items"]]
    assert kinds.count("post") == 2 and kinds.count("comment") == 2  # daily + top post, [removed] dropped
    bt = social.bitcointalk(http, CFG)
    assert bt["items"][0]["comments"] == 42 and bt["items"][0]["views"] == 1234
    nw = news.collect(http, CFG)
    assert [a["title"] for a in nw["items"]] == ["Bitcoin surges past record"]  # non-BTC filtered

    items = r["items"] + bt["items"] + nw["items"]
    sentiment.score_items(items)
    summ = sentiment.summarize(items)
    assert summ["social"]["n"] == 5 and summ["news"]["weighted_mean"] > 0


def test_signal_contrarian_logic():
    hist = [{"date": f"2026-01-{i % 28 + 1:02d}", "close": 50_000 + i * 150} for i in range(260)]
    ta = technicals.compute(hist)
    snap = {"prices": {"spot": hist[-1]["close"]}, "technicals": ta,
            "sentiment": {"social": {"weighted_mean": 0.2}, "news": {}},
            "fear_greed": {"value": 92, "label": "Extreme Greed"},
            "derivatives": {"funding_avg_annualized": 0.45}}
    sig = signals.build(snap, [], CFG)
    c = sig["components"]
    assert c["trend"]["score"] > 0                    # uptrend reads bullish
    assert c["fear_greed_contrarian"]["score"] < 0    # extreme greed reads bearish
    assert c["funding_contrarian"]["score"] < 0       # hot funding reads bearish
    assert sig["confidence"] == "Low"                 # too few inputs to trust
