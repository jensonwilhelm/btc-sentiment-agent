"""Order books from several exchanges → depth imbalance and the biggest
resting buy/sell walls (clustered across venues).

Notes
- Binance's main API (api.binance.com) blocks US IPs, including GitHub's runners.
  We use data-api.binance.vision (market-data mirror) and simply skip it if blocked.
- Books are a snapshot at run time. Large walls can be spoofed/pulled, so treat
  them as "where liquidity sits right now", not a promise.
"""
from __future__ import annotations

import math
from collections import defaultdict

from ..net import Http


def _coinbase(http: Http):
    b = http.get_json("https://api.exchange.coinbase.com/products/BTC-USD/book", params={"level": 2})
    return [(float(p), float(q)) for p, q, *_ in b["bids"]], [(float(p), float(q)) for p, q, *_ in b["asks"]]


def _kraken(http: Http):
    r = http.get_json("https://api.kraken.com/0/public/Depth", params={"pair": "XBTUSD", "count": 500})
    book = next(iter(r["result"].values()))
    return [(float(p), float(q)) for p, q, *_ in book["bids"]], [(float(p), float(q)) for p, q, *_ in book["asks"]]


def _bitstamp(http: Http):
    b = http.get_json("https://www.bitstamp.net/api/v2/order_book/btcusd/")
    return [(float(p), float(q)) for p, q in b["bids"]], [(float(p), float(q)) for p, q in b["asks"]]


def _binance(http: Http):
    b = http.get_json("https://data-api.binance.vision/api/v3/depth", params={"symbol": "BTCUSDT", "limit": 5000})
    return [(float(p), float(q)) for p, q in b["bids"]], [(float(p), float(q)) for p, q in b["asks"]]


def _okx(http: Http):
    r = http.get_json("https://www.okx.com/api/v5/market/books", params={"instId": "BTC-USDT", "sz": 400})
    d = r["data"][0]
    return [(float(x[0]), float(x[1])) for x in d["bids"]], [(float(x[0]), float(x[1])) for x in d["asks"]]


def _gemini(http: Http):
    b = http.get_json("https://api.gemini.com/v1/book/btcusd", params={"limit_bids": 0, "limit_asks": 0})
    return ([(float(x["price"]), float(x["amount"])) for x in b["bids"]],
            [(float(x["price"]), float(x["amount"])) for x in b["asks"]])


VENUES = {"Coinbase": _coinbase, "Kraken": _kraken, "Bitstamp": _bitstamp,
          "Binance": _binance, "OKX": _okx, "Gemini": _gemini}


def collect(http: Http, cfg: dict) -> dict:
    oc = cfg.get("orderbook", {})
    bands = oc.get("band_pcts", [0.5, 1, 2, 5])
    bucket = oc.get("wall_bucket_usd", 250)
    search = oc.get("wall_search_pct", 6) / 100
    big_btc = oc.get("large_order_btc", 20)

    books, status = {}, {}
    for name, fn in VENUES.items():
        try:
            bids, asks = fn(http)
            if bids and asks:
                books[name] = (sorted(bids, reverse=True), sorted(asks))
                status[name] = "ok"
        except Exception as e:  # noqa: BLE001
            status[name] = f"skipped ({str(e)[:80]})"
    if not books:
        raise RuntimeError("no order book reachable")

    mids = [(b[0][0] + a[0][0]) / 2 for b, a in books.values()]
    mid = sorted(mids)[len(mids) // 2]

    exchanges, agg = {}, {str(x): {"bid_usd": 0.0, "ask_usd": 0.0} for x in bands}
    bid_buckets, ask_buckets = defaultdict(lambda: [0.0, 0.0, set()]), defaultdict(lambda: [0.0, 0.0, set()])
    large = []
    for name, (bids, asks) in books.items():
        ex_mid = (bids[0][0] + asks[0][0]) / 2
        row = {"mid": ex_mid, "spread_bps": (asks[0][0] - bids[0][0]) / ex_mid * 1e4, "bands": {}}
        deepest_bid = bids[-1][0]
        deepest_ask = asks[-1][0]
        for x in bands:
            lo, hi = mid * (1 - x / 100), mid * (1 + x / 100)
            b_usd = sum(p * q for p, q in bids if p >= lo)
            a_usd = sum(p * q for p, q in asks if p <= hi)
            # flag bands the exchange's returned book doesn't fully cover
            covered = deepest_bid <= lo and deepest_ask >= hi
            row["bands"][str(x)] = {"bid_usd": b_usd, "ask_usd": a_usd, "full": covered}
            agg[str(x)]["bid_usd"] += b_usd
            agg[str(x)]["ask_usd"] += a_usd
        exchanges[name] = row

        for p, q in bids:
            if p < mid * (1 - search):
                break
            k = math.floor(p / bucket) * bucket
            bid_buckets[k][0] += p * q
            bid_buckets[k][1] += q
            bid_buckets[k][2].add(name)
            if q >= big_btc:
                large.append({"exchange": name, "side": "bid", "price": p, "btc": q, "usd": p * q,
                              "dist_pct": (p / mid - 1) * 100})
        for p, q in asks:
            if p > mid * (1 + search):
                break
            k = math.floor(p / bucket) * bucket
            ask_buckets[k][0] += p * q
            ask_buckets[k][1] += q
            ask_buckets[k][2].add(name)
            if q >= big_btc:
                large.append({"exchange": name, "side": "ask", "price": p, "btc": q, "usd": p * q,
                              "dist_pct": (p / mid - 1) * 100})

    for x in agg.values():
        tot = x["bid_usd"] + x["ask_usd"]
        x["imbalance"] = (x["bid_usd"] - x["ask_usd"]) / tot if tot else 0.0

    def walls(buckets, n):
        rows = [{"price": k + bucket / 2, "usd": v[0], "btc": v[1], "exchanges": sorted(v[2]),
                 "dist_pct": ((k + bucket / 2) / mid - 1) * 100} for k, v in buckets.items()]
        return sorted(rows, key=lambda r: r["usd"], reverse=True)[:n]

    n = oc.get("top_walls", 8)
    return {
        "mid": mid,
        "exchanges": exchanges,
        "aggregate": agg,
        "bid_walls": walls(bid_buckets, n),
        "ask_walls": walls(ask_buckets, n),
        "large_orders": sorted(large, key=lambda r: r["usd"], reverse=True)[:20],
        "venue_status": status,
        "bucket_usd": bucket,
    }
