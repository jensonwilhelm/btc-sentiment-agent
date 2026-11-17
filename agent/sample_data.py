"""Synthetic data in exactly the shapes the live collectors return.
Used by `--sample` to demo/test the pipeline and website with no network.
Nothing here reflects the real market."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

STATUS = {k: {"ok": True, "secs": 0.0, "detail": "sample data"} for k in (
    "Prices & history", "Order books / walls", "Taker flow & whale trades", "Derivatives (funding/OI/options)",
    "On-chain (mempool.space)", "Fear & Greed index", "Wikipedia attention", "Macro (Yahoo Finance)",
    "Spot-ETF flows (Farside)", "Reddit", "BitcoinTalk", "StockTwits", "News RSS")}

POSTS = [
    ("r/Bitcoin", "Just keep stacking sats. Every dip has been a gift in hindsight.", 540, 88),
    ("r/Bitcoin", "ETF inflows quietly back above $400M this week — institutions aren't leaving", 1220, 301),
    ("r/BitcoinMarkets", "Funding is getting hot again, wouldn't be surprised by a long squeeze to the 50 day", 210, 140),
    ("r/BitcoinMarkets", "Daily chart looks heavy. Rejected at resistance twice, I'm flat until we reclaim.", 95, 60),
    ("r/CryptoCurrency", "Feels like 2021 euphoria again, my barber is asking about bitcoin", 860, 412),
    ("r/CryptoCurrency", "Another exchange hack. This space never learns.", 410, 233),
    ("r/btc", "Fees are low and the network is humming. Great time to consolidate UTXOs", 75, 22),
    ("r/CryptoMarkets", "Capitulation incoming? Liquidations piling up under the lows", 130, 97),
    ("r/Bitcoin", "Saylor's company bought more again. Corporate treasuries keep accumulating.", 980, 255),
    ("r/BitcoinMarkets", "Breakout above the range would put new ATH in play, watching volume", 160, 74),
    ("r/CryptoCurrency", "Fed meeting next week, rate cut odds dropping — risk assets wobbling", 330, 190),
    ("r/Bitcoin", "Bought the dip this morning. HODL.", 290, 41),
]
COMMENTS = ["wagmi", "this is the bottom, loading up", "ngmi if you're shorting here", "rekt again lol",
            "bearish divergence on the 4h", "accumulating every week no matter what",
            "this rally is fake, volume is garbage", "moon soon", "I'm worried about the macro picture",
            "Funding reset is healthy", "ETF outflows are a red flag", "sold half, taking profits",
            "Buy the dip, not complicated", "crash to 60k incoming", "strong support at the 200 day"]
TALK = ["Will BTC break the all-time high before year end?", "Bear market confirmed? Discuss",
        "Long-term holders are not selling — on-chain data", "Is this the top? Funding says yes",
        "Bitcoin price prediction thread", "Miners capitulating after difficulty jump?",
        "Accumulation zone analysis", "Regulation crackdown rumors in Asia"]
HEAD = ["Bitcoin climbs as spot ETF inflows return for third straight day",
        "Bitcoin slips below key level as traders brace for Fed decision",
        "Analysts: BTC options market shows rising demand for downside protection",
        "Corporate treasury firm adds to bitcoin holdings",
        "Bitcoin hashrate hits new record as miners expand",
        "Crypto exchange suffers exploit; bitcoin largely unaffected",
        "Bitcoin funding rates jump, raising liquidation risk",
        "Senate committee advances crypto market-structure bill"]


def generate(store) -> dict:
    rnd = random.Random(42)
    today = datetime.now(timezone.utc).date()
    p = 68000.0
    hist = []
    for i in range(365, -1, -1):
        p *= 1 + rnd.gauss(0.0012, 0.028)
        hist.append({"date": (today - timedelta(days=i)).isoformat(), "close": p, "volume": rnd.uniform(2e10, 6e10)})
    spot = hist[-1]["close"]

    if not store.load_history():  # seed a back-history so charts have something to draw
        for i, h in enumerate(hist[-61:-1]):
            store.append({"date": h["date"], "price": h["close"], "score": round(rnd.uniform(-45, 45), 1),
                          "label": "", "social_sentiment": rnd.uniform(-0.1, 0.35),
                          "news_sentiment": rnd.uniform(-0.15, 0.25), "fear_greed": rnd.randint(25, 80),
                          "funding_ann": rnd.uniform(0.0, 0.25), "oi_usd": rnd.uniform(5e10, 8e10),
                          "ob_imbalance_2": rnd.uniform(-0.2, 0.2), "taker_imbalance": rnd.uniform(-0.05, 0.05),
                          "etf_5d": rnd.uniform(-800, 1500), "social_n": 900})

    def walls(side):
        out = []
        for _ in range(8):
            d = rnd.uniform(0.3, 5.5) * (-1 if side == "bid" else 1)
            usd = rnd.uniform(8e6, 60e6)
            pr = spot * (1 + d / 100)
            out.append({"price": pr, "usd": usd, "btc": usd / pr, "dist_pct": d,
                        "exchanges": rnd.sample(["Coinbase", "Kraken", "Bitstamp", "OKX", "Gemini"], 2)})
        return sorted(out, key=lambda w: w["usd"], reverse=True)

    agg = {}
    for b in ("0.5", "1", "2", "5"):
        f = float(b)
        bid, ask = rnd.uniform(40e6, 90e6) * f, rnd.uniform(40e6, 90e6) * f
        agg[b] = {"bid_usd": bid, "ask_usd": ask, "imbalance": (bid - ask) / (bid + ask)}
    exs = {n: {"mid": spot, "spread_bps": rnd.uniform(0.1, 2), "bands": {}} for n in ("Coinbase", "Kraken", "Bitstamp", "OKX", "Gemini")}
    large = [{"exchange": rnd.choice(list(exs)), "side": s, "price": spot * (1 + d / 100), "btc": q,
              "usd": q * spot * (1 + d / 100), "dist_pct": d}
             for s, d, q in [("bid", -1.8, 120), ("ask", 2.4, 95), ("bid", -3.1, 80), ("ask", 0.9, 44), ("bid", -0.6, 31)]]

    trades = [{"exchange": rnd.choice(["Coinbase", "Kraken", "Binance"]), "side": rnd.choice(["buy", "sell"]),
               "price": spot * (1 + rnd.uniform(-0.002, 0.002)), "btc": q, "usd": q * spot,
               "time": f"{today} {rnd.randint(10, 23):02d}:{rnd.randint(0, 59):02d} UTC"}
              for q in sorted([rnd.uniform(6, 40) for _ in range(12)], reverse=True)]

    items = []
    for ch, t, s, c in POSTS:
        items.append({"source": "Reddit", "channel": ch, "kind": "post", "title": t, "text": "",
                      "url": "https://www.reddit.com/r/Bitcoin/", "score": s, "comments": c, "created": None})
    for _ in range(140):
        items.append({"source": "Reddit", "channel": rnd.choice(["r/Bitcoin", "r/BitcoinMarkets", "r/CryptoCurrency"]),
                      "kind": "comment", "title": "", "text": rnd.choice(COMMENTS), "url": "https://www.reddit.com/",
                      "score": rnd.randint(0, 120), "comments": 0, "created": None, "thread": "Daily Discussion"})
    for t in TALK:
        items.append({"source": "BitcoinTalk", "channel": rnd.choice(["Speculation", "Bitcoin Discussion"]),
                      "kind": "topic", "title": t, "text": "", "url": "https://bitcointalk.org/",
                      "score": rnd.randint(5, 80), "comments": rnd.randint(3, 400), "created": None})
    for _ in range(30):
        lab = rnd.choice(["Bullish", "Bullish", "Bearish", None])
        items.append({"source": "StockTwits", "channel": "BTC.X", "kind": "message", "title": "",
                      "text": rnd.choice(COMMENTS), "url": "https://stocktwits.com/symbol/BTC.X",
                      "score": rnd.randint(0, 20), "comments": 0, "created": None, "label": lab})
    now = datetime.now(timezone.utc)
    for i, h in enumerate(HEAD):
        items.append({"source": "News", "channel": rnd.choice(["CoinDesk", "Decrypt", "The Block", "Google News"]),
                      "kind": "headline", "title": h, "text": "", "url": "https://www.coindesk.com/",
                      "score": 0, "comments": 0, "created": (now - timedelta(hours=i * 3)).isoformat()})
    st = [i for i in items if i["source"] == "StockTwits"]
    bull = sum(1 for i in st if i["label"] == "Bullish")
    bear = sum(1 for i in st if i["label"] == "Bearish")

    fg_hist = [{"date": (today - timedelta(days=i)).isoformat(), "value": rnd.randint(30, 78)} for i in range(90, -1, -1)]
    views = [{"date": (today - timedelta(days=i)).isoformat(), "views": rnd.randint(9000, 26000)} for i in range(90, 0, -1)]
    v = [x["views"] for x in views]
    etf_hist = [{"date": (today - timedelta(days=i)).isoformat(), "net_musd": rnd.uniform(-450, 700)} for i in range(30, 0, -1)]
    hr = [{"date": (today - timedelta(days=i)).isoformat(), "eh": 820 + i * -0.8 + rnd.uniform(-25, 25)} for i in range(90, -1, -1)]
    funding = [{"venue": n, "rate_8h": r} for n, r in [("Hyperliquid", 0.00013), ("Deribit", 0.00009), ("OKX", 0.00011)]]
    for f in funding:
        f["annualized"] = f["rate_8h"] * 3 * 365

    return {
        "prices": {"spot": spot, "change_24h": (spot / hist[-2]["close"] - 1) * 100,
                   "change_7d": (spot / hist[-8]["close"] - 1) * 100, "change_30d": (spot / hist[-31]["close"] - 1) * 100,
                   "market_cap": spot * 19.96e6, "volume_24h": 3.8e10, "high_24h": spot * 1.012, "low_24h": spot * 0.981,
                   "ath": max(h["close"] for h in hist) * 1.02, "ath_change_pct": (spot / (max(h["close"] for h in hist) * 1.02) - 1) * 100,
                   "btc_dominance": 58.4, "total_crypto_mcap": spot * 19.96e6 / 0.584, "source": "sample", "history": hist},
        "orderbook": {"mid": spot, "exchanges": exs, "aggregate": agg, "bid_walls": walls("bid"),
                      "ask_walls": walls("ask"), "large_orders": large, "bucket_usd": 250,
                      "venue_status": {n: "ok" for n in exs} | {"Binance": "skipped (HTTP 451 — US IP)"}},
        "flow": {"taker_buy_btc_24h": 41200, "taker_sell_btc_24h": 39650, "taker_imbalance": (41200 - 39650) / 80850,
                 "taker_source": "sample", "large_trades": trades,
                 "large_buy_usd": sum(t["usd"] for t in trades if t["side"] == "buy"),
                 "large_sell_usd": sum(t["usd"] for t in trades if t["side"] == "sell"),
                 "large_trade_threshold_usd": 500000, "venue_status": {}},
        "derivatives": {"funding": funding, "funding_avg_8h": 0.00011, "funding_avg_annualized": 0.00011 * 1095,
                        "open_interest": [{"venue": "Hyperliquid", "btc": 31000, "usd": 31000 * spot},
                                          {"venue": "Deribit", "btc": 12000, "usd": 12000 * spot},
                                          {"venue": "OKX", "btc": 24000, "usd": 24000 * spot}],
                        "oi_total_usd": 67000 * spot, "oi_change_24h_pct": None, "long_short_ratio": 1.46,
                        "long_short_source": "OKX accounts (1D)", "put_call_oi": 0.71, "venue_status": {}},
        "onchain": {"fees": {"fastestFee": 6, "halfHourFee": 4, "hourFee": 3, "economyFee": 2, "minimumFee": 1},
                    "mempool_tx": 48211, "mempool_vsize_mb": 31.2, "block_height": 925_412,
                    "difficulty_change_pct": 2.1, "retarget_progress_pct": 61.0, "remaining_blocks": 786,
                    "next_retarget": (today + timedelta(days=5)).isoformat(), "hashrate_eh": hr[-1]["eh"],
                    "hashrate_change_30d_pct": 3.4, "hashrate_history": hr},
        "fear_greed": {"value": 71, "label": "Greed", "history": fg_hist,
                       "avg_7d": sum(x["value"] for x in fg_hist[-7:]) / 7},
        "attention": {"history": views, "latest": v[-1], "avg_7d": sum(v[-7:]) / 7, "avg_90d": sum(v) / len(v),
                      "ratio_7d_vs_90d": (sum(v[-7:]) / 7) / (sum(v) / len(v))},
        "macro": {"assets": [
            {"name": "S&P 500", "symbol": "^GSPC", "price": 6810.2, "change_1d_pct": -0.4, "change_5d_pct": 1.1},
            {"name": "Nasdaq", "symbol": "^IXIC", "price": 23120.5, "change_1d_pct": -0.7, "change_5d_pct": 1.6},
            {"name": "US Dollar (DXY)", "symbol": "DX-Y.NYB", "price": 99.4, "change_1d_pct": 0.2, "change_5d_pct": -0.5},
            {"name": "Gold", "symbol": "GC=F", "price": 4010.0, "change_1d_pct": 0.3, "change_5d_pct": 2.2},
            {"name": "US 10y yield", "symbol": "^TNX", "price": 4.12, "change_1d_pct": 0.5, "change_5d_pct": -1.2},
            {"name": "IBIT (BlackRock BTC ETF)", "symbol": "IBIT", "price": 61.3, "change_1d_pct": 1.2,
             "change_5d_pct": 3.9, "volume_vs_20d": 1.34}]},
        "etf": {"history": etf_hist, "latest": etf_hist[-1], "sum_5d_musd": sum(x["net_musd"] for x in etf_hist[-5:]),
                "sum_20d_musd": sum(x["net_musd"] for x in etf_hist[-20:])},
        "reddit": {"items": [i for i in items if i["source"] == "Reddit"], "mode": "sample"},
        "bitcointalk": {"items": [i for i in items if i["source"] == "BitcoinTalk"]},
        "stocktwits": {"items": st, "bullish": bull, "bearish": bear, "bull_ratio": bull / (bull + bear)},
        "news": {"items": [i for i in items if i["source"] == "News"]},
    }
