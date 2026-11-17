"""Leverage & positioning: perpetual funding rates, open interest, long/short
account ratios, and Deribit options put/call open-interest ratio.

Venues that geo-block US IPs (Binance futures, Bybit, sometimes OKX) are tried
but skipped silently when blocked; Hyperliquid and Deribit generally work from
GitHub's runners.
"""
from __future__ import annotations

from ..net import Http


def collect(http: Http, cfg: dict, spot: float | None = None) -> dict:
    funding, oi, status = [], [], {}
    ls_ratio, ls_src, pcr, oi_change = None, None, None, None

    # Hyperliquid (hourly funding)
    try:
        meta, ctxs = http.post_json("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
        idx = next(i for i, u in enumerate(meta["universe"]) if u["name"] == "BTC")
        c = ctxs[idx]
        funding.append({"venue": "Hyperliquid", "rate_8h": float(c["funding"]) * 8})
        px = float(c.get("markPx") or spot or 0)
        oi.append({"venue": "Hyperliquid", "btc": float(c["openInterest"]), "usd": float(c["openInterest"]) * px})
        status["Hyperliquid"] = "ok"
    except Exception as e:  # noqa: BLE001
        status["Hyperliquid"] = f"skipped ({str(e)[:70]})"

    # Deribit perp + options
    try:
        t = http.get_json("https://www.deribit.com/api/v2/public/ticker",
                          params={"instrument_name": "BTC-PERPETUAL"})["result"]
        funding.append({"venue": "Deribit", "rate_8h": float(t["funding_8h"])})
        oi.append({"venue": "Deribit", "usd": float(t["open_interest"]),  # inverse perp: OI in USD
                   "btc": float(t["open_interest"]) / float(t["mark_price"])})
        opts = http.get_json("https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
                             params={"currency": "BTC", "kind": "option"})["result"]
        puts = sum(o.get("open_interest") or 0 for o in opts if o["instrument_name"].endswith("-P"))
        calls = sum(o.get("open_interest") or 0 for o in opts if o["instrument_name"].endswith("-C"))
        if calls:
            pcr = puts / calls
        status["Deribit"] = "ok"
    except Exception as e:  # noqa: BLE001
        status["Deribit"] = f"skipped ({str(e)[:70]})"

    # OKX
    try:
        fr = http.get_json("https://www.okx.com/api/v5/public/funding-rate", params={"instId": "BTC-USDT-SWAP"})
        funding.append({"venue": "OKX", "rate_8h": float(fr["data"][0]["fundingRate"])})
        o = http.get_json("https://www.okx.com/api/v5/public/open-interest",
                          params={"instType": "SWAP", "instId": "BTC-USDT-SWAP"})["data"][0]
        oi.append({"venue": "OKX", "btc": float(o["oiCcy"]), "usd": float(o["oiCcy"]) * (spot or 0)})
        try:
            ls = http.get_json("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio",
                               params={"ccy": "BTC", "period": "1D"})["data"]
            ls_ratio, ls_src = float(ls[0][1]), "OKX accounts (1D)"
        except Exception:
            pass
        status["OKX"] = "ok"
    except Exception as e:  # noqa: BLE001
        status["OKX"] = f"skipped ({str(e)[:70]})"

    # Binance USDⓈ-M futures (blocked from US IPs — works if you self-host elsewhere)
    try:
        f = "https://fapi.binance.com"
        p = http.get_json(f"{f}/fapi/v1/premiumIndex", params={"symbol": "BTCUSDT"})
        funding.append({"venue": "Binance", "rate_8h": float(p["lastFundingRate"])})
        o = http.get_json(f"{f}/fapi/v1/openInterest", params={"symbol": "BTCUSDT"})
        oi.append({"venue": "Binance", "btc": float(o["openInterest"]),
                   "usd": float(o["openInterest"]) * float(p["markPrice"])})
        ls = http.get_json(f"{f}/futures/data/globalLongShortAccountRatio",
                           params={"symbol": "BTCUSDT", "period": "1d", "limit": 1})
        ls_ratio, ls_src = float(ls[-1]["longShortRatio"]), "Binance accounts (1D)"
        h = http.get_json(f"{f}/futures/data/openInterestHist", params={"symbol": "BTCUSDT", "period": "1d", "limit": 2})
        if len(h) == 2:
            a, b = float(h[0]["sumOpenInterestValue"]), float(h[1]["sumOpenInterestValue"])
            oi_change = (b / a - 1) * 100
        status["Binance"] = "ok"
    except Exception as e:  # noqa: BLE001
        status["Binance"] = f"skipped ({str(e)[:70]})"

    # Bybit (also US-blocked)
    try:
        r = http.get_json("https://api.bybit.com/v5/market/tickers",
                          params={"category": "linear", "symbol": "BTCUSDT"})["result"]["list"][0]
        funding.append({"venue": "Bybit", "rate_8h": float(r["fundingRate"])})
        oi.append({"venue": "Bybit", "btc": float(r["openInterest"]), "usd": float(r["openInterestValue"])})
        status["Bybit"] = "ok"
    except Exception as e:  # noqa: BLE001
        status["Bybit"] = f"skipped ({str(e)[:70]})"

    if not funding and pcr is None:
        raise RuntimeError("no derivatives venue reachable")

    for f_ in funding:
        f_["annualized"] = f_["rate_8h"] * 3 * 365
    # OI-weighted average funding where possible
    oi_by = {o["venue"]: o["usd"] for o in oi}
    wsum = sum(oi_by.get(f_["venue"], 0) for f_ in funding)
    if wsum:
        avg = sum(f_["rate_8h"] * oi_by.get(f_["venue"], 0) for f_ in funding) / wsum
    else:
        avg = sum(f_["rate_8h"] for f_ in funding) / len(funding) if funding else None

    return {
        "funding": funding,
        "funding_avg_8h": avg,
        "funding_avg_annualized": avg * 3 * 365 if avg is not None else None,
        "open_interest": oi,
        "oi_total_usd": sum(o["usd"] for o in oi) or None,
        "oi_change_24h_pct": oi_change,
        "long_short_ratio": ls_ratio,
        "long_short_source": ls_src,
        "put_call_oi": pcr,
        "venue_status": status,
    }
