"""Who is hitting the market: 24h taker buy vs sell volume (aggressive flow)
plus recent whale-sized prints.

- 24h taker split: Binance hourly klines (field 9 = taker-buy volume) via the
  market-data mirror; fallback = Kraken's last 1000 trades.
- Whale prints: last ~1000 trades on Coinbase, Kraken and Binance, filtered by size.
  Exchanges only expose a few minutes-to-hours of trade history publicly, so this
  is a snapshot of what's happening when the agent runs.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..net import Http


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _coinbase_trades(http: Http):
    rows = http.get_json("https://api.exchange.coinbase.com/products/BTC-USD/trades", params={"limit": 1000})
    out = []
    for t in rows:
        # Coinbase "side" is the MAKER side → taker is the opposite
        taker = "buy" if t["side"] == "sell" else "sell"
        ts = datetime.fromisoformat(t["time"].replace("Z", "+00:00")).timestamp()
        out.append(("Coinbase", taker, float(t["price"]), float(t["size"]), ts))
    return out


def _kraken_trades(http: Http):
    r = http.get_json("https://api.kraken.com/0/public/Trades", params={"pair": "XBTUSD", "count": 1000})
    key = next(k for k in r["result"] if k != "last")
    return [("Kraken", "buy" if t[3] == "b" else "sell", float(t[0]), float(t[1]), float(t[2]))
            for t in r["result"][key]]


def _binance_trades(http: Http):
    rows = http.get_json("https://data-api.binance.vision/api/v3/aggTrades", params={"symbol": "BTCUSDT", "limit": 1000})
    # m = buyer is maker → taker sold
    return [("Binance", "sell" if t["m"] else "buy", float(t["p"]), float(t["q"]), t["T"] / 1000) for t in rows]


def collect(http: Http, cfg: dict) -> dict:
    thr = cfg.get("flow", {}).get("large_trade_usd", 500_000)
    out: dict = {}

    # ── 24h taker flow ──
    try:
        kl = http.get_json("https://data-api.binance.vision/api/v3/klines",
                           params={"symbol": "BTCUSDT", "interval": "1h", "limit": 24})
        vol = sum(float(k[5]) for k in kl)
        buy = sum(float(k[9]) for k in kl)
        out.update({"taker_buy_btc_24h": buy, "taker_sell_btc_24h": vol - buy,
                    "taker_source": "Binance spot, last 24h"})
    except Exception:
        pass

    trades, status = [], {}
    for name, fn in {"Coinbase": _coinbase_trades, "Kraken": _kraken_trades, "Binance": _binance_trades}.items():
        try:
            t = fn(http)
            trades += t
            span_min = (max(x[4] for x in t) - min(x[4] for x in t)) / 60 if t else 0
            status[name] = f"ok ({len(t)} trades / {span_min:.0f} min)"
        except Exception as e:  # noqa: BLE001
            status[name] = f"skipped ({str(e)[:80]})"
    out["venue_status"] = status

    if "taker_buy_btc_24h" not in out and trades:
        buy = sum(q for _, s, _, q, _ in trades if s == "buy")
        sell = sum(q for _, s, _, q, _ in trades if s == "sell")
        out.update({"taker_buy_btc_24h": buy, "taker_sell_btc_24h": sell,
                    "taker_source": "recent trades sample (24h data unavailable)"})

    b, s = out.get("taker_buy_btc_24h"), out.get("taker_sell_btc_24h")
    if b is not None and (b + s) > 0:
        out["taker_imbalance"] = (b - s) / (b + s)

    whales = [{"exchange": ex, "side": side, "price": p, "btc": q, "usd": p * q, "time": _iso(ts)}
              for ex, side, p, q, ts in trades if p * q >= thr]
    whales.sort(key=lambda r: r["usd"], reverse=True)
    out["large_trades"] = whales[:25]
    out["large_buy_usd"] = sum(w["usd"] for w in whales if w["side"] == "buy")
    out["large_sell_usd"] = sum(w["usd"] for w in whales if w["side"] == "sell")
    out["large_trade_threshold_usd"] = thr
    if not trades and "taker_imbalance" not in out:
        raise RuntimeError("no trade data reachable")
    return out
