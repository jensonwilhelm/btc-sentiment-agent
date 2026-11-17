"""Spot price, market stats and ~1 year of daily closes.
Primary: CoinGecko (free, works from US IPs). Fallbacks: Kraken, Coinbase."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from ..net import Http

CG = "https://api.coingecko.com/api/v3"


def _cg_headers() -> dict:
    key = os.environ.get("COINGECKO_API_KEY")  # optional free "demo" key raises rate limits
    return {"x-cg-demo-api-key": key} if key else {}


def _pct(a: float, b: float) -> float | None:
    return (a / b - 1) * 100 if a and b else None


def collect(http: Http, cfg: dict) -> dict:
    out: dict = {"source": None}
    hdr = _cg_headers()

    # ── Market snapshot ──
    try:
        m = http.get_json(f"{CG}/coins/markets", params={
            "vs_currency": "usd", "ids": "bitcoin",
            "price_change_percentage": "24h,7d,30d"}, headers=hdr)[0]
        out.update({
            "spot": m["current_price"],
            "change_24h": m.get("price_change_percentage_24h_in_currency"),
            "change_7d": m.get("price_change_percentage_7d_in_currency"),
            "change_30d": m.get("price_change_percentage_30d_in_currency"),
            "market_cap": m.get("market_cap"),
            "volume_24h": m.get("total_volume"),
            "high_24h": m.get("high_24h"), "low_24h": m.get("low_24h"),
            "ath": m.get("ath"), "ath_change_pct": m.get("ath_change_percentage"),
            "ath_date": (m.get("ath_date") or "")[:10],
            "source": "coingecko",
        })
        g = http.get_json(f"{CG}/global", headers=hdr)["data"]
        out["btc_dominance"] = g["market_cap_percentage"].get("btc")
        out["total_crypto_mcap"] = g["total_market_cap"].get("usd")
    except Exception as e:  # noqa: BLE001
        out["snapshot_error"] = str(e)

    # ── Daily history ──
    hist = []
    try:
        mc = http.get_json(f"{CG}/coins/bitcoin/market_chart",
                           params={"vs_currency": "usd", "days": 365, "interval": "daily"}, headers=hdr)
        vols = {int(t): v for t, v in mc.get("total_volumes", [])}
        for t, p in mc["prices"]:
            d = datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            hist.append({"date": d, "close": p, "volume": vols.get(int(t))})
        out["history_source"] = "coingecko"
    except Exception:
        try:  # Kraken OHLC fallback (720 daily candles max)
            r = http.get_json("https://api.kraken.com/0/public/OHLC", params={"pair": "XBTUSD", "interval": 1440})
            key = next(k for k in r["result"] if k != "last")
            for c in r["result"][key][-400:]:
                d = datetime.fromtimestamp(c[0], tz=timezone.utc).strftime("%Y-%m-%d")
                hist.append({"date": d, "close": float(c[4]), "volume": float(c[6]) * float(c[4])})
            out["history_source"] = "kraken"
        except Exception as e:  # noqa: BLE001
            out["history_error"] = str(e)

    # de-duplicate dates (CoinGecko appends a live "today" point)
    dedup = {}
    for row in hist:
        dedup[row["date"]] = row
    out["history"] = [dedup[k] for k in sorted(dedup)]

    # ── Fill gaps from history / Coinbase ──
    if "spot" not in out:
        try:
            t = http.get_json("https://api.exchange.coinbase.com/products/BTC-USD/ticker")
            out["spot"] = float(t["price"])
            out["source"] = "coinbase"
        except Exception:
            if out["history"]:
                out["spot"] = out["history"][-1]["close"]
                out["source"] = out.get("history_source")
    closes = [r["close"] for r in out["history"]]
    if closes and out.get("change_7d") is None and len(closes) > 8:
        out["change_7d"] = _pct(closes[-1], closes[-8])
    if closes and out.get("change_30d") is None and len(closes) > 31:
        out["change_30d"] = _pct(closes[-1], closes[-31])
    if "spot" not in out:
        raise RuntimeError("no price source reachable")
    return out
