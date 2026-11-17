"""Turns every input into a -1..+1 sub-score, then a weighted composite.

Philosophy
- Trend & flow inputs are read *with* the market (price above its averages = bullish).
- Crowd-positioning inputs are read *contrarian* (extreme greed, hot funding,
  crowded longs = elevated risk of a flush; extreme fear = opportunity).
- Missing inputs are skipped and weights re-normalised, so a blocked API never
  silently drags the score toward zero.
This is a research aid that summarises conditions — not a trading system.
"""
from __future__ import annotations

import math


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _t(x: float) -> float:
    return math.tanh(x)


def build(snap: dict, history: list[dict], cfg: dict) -> dict:
    sc = cfg.get("signal", {})
    W = sc.get("weights", {})
    px = snap.get("prices", {}).get("spot")
    ta = snap.get("technicals", {})
    sent = snap.get("sentiment", {})
    fg = snap.get("fear_greed") or {}
    der = snap.get("derivatives") or {}
    ob = snap.get("orderbook") or {}
    fl = snap.get("flow") or {}
    etf = snap.get("etf") or {}
    comp: dict[str, dict] = {}

    def add(key, val, why, raw=None):
        if val is None:
            return
        comp[key] = {"score": round(_clip(val), 3), "why": why, "raw": raw, "weight": W.get(key, 0)}

    # Trend: distance from 50d / 200d averages
    if px and ta.get("sma200") and ta.get("sma50"):
        d200, d50 = px / ta["sma200"] - 1, px / ta["sma50"] - 1
        add("trend", 0.5 * _t(d200 * 5) + 0.5 * _t(d50 * 10),
            f"Price is {d50*100:+.1f}% vs 50-day and {d200*100:+.1f}% vs 200-day average", None)
    elif px and ta.get("sma50"):
        d50 = px / ta["sma50"] - 1
        add("trend", _t(d50 * 10), f"Price is {d50*100:+.1f}% vs 50-day average")

    if ta.get("return_30d") is not None:
        r = ta["return_30d"] / 100
        macd_s = 0.3 if ta.get("macd_hist", 0) > 0 else -0.3
        add("momentum", 0.7 * _t(r * 5) + macd_s, f"30-day return {r*100:+.1f}%, MACD histogram "
            f"{'positive' if macd_s > 0 else 'negative'}")

    rsi = ta.get("rsi14")
    if rsi is not None:
        mr = -(rsi - 70) / 30 if rsi > 70 else (30 - rsi) / 30 if rsi < 30 else 0.0
        state = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral zone"
        add("mean_reversion", mr * 1.5, f"RSI(14) {rsi:.0f} — {state}", rsi)

    soc = (sent.get("social") or {}).get("weighted_mean")
    if soc is not None:
        prior = [h["social_sentiment"] for h in history[-7:] if h.get("social_sentiment") is not None]
        if len(prior) >= 3:
            delta = soc - sum(prior) / len(prior)
            add("social_sentiment", 0.5 * _t(soc * 3) + 0.5 * _t(delta * 8),
                f"Forum mood {soc:+.2f} ({delta:+.2f} vs 7-day avg)", soc)
        else:
            add("social_sentiment", _t(soc * 3), f"Forum mood {soc:+.2f} (building history for trend)", soc)

    nws = (sent.get("news") or {}).get("weighted_mean")
    if nws is not None:
        add("news_sentiment", _t(nws * 4), f"Headline tone {nws:+.2f} across {sent['news']['n']} stories", nws)

    if fg.get("value") is not None:
        v = fg["value"]
        add("fear_greed_contrarian", (50 - v) / 40,
            f"Fear & Greed {v} ({fg.get('label')}) — read contrarian", v)

    fa = der.get("funding_avg_annualized")
    if fa is not None:
        neutral = sc.get("neutral_funding_annualized", 0.10)
        add("funding_contrarian", -_t((fa - neutral) / 0.15),
            f"Perp funding {fa*100:+.1f}%/yr (neutral ≈ {neutral*100:.0f}%) — hot funding = crowded longs", fa)

    ls = der.get("long_short_ratio")
    if ls:
        add("long_short_contrarian", -_t((ls - 1.2) * 1.5), f"Long/short account ratio {ls:.2f} ({der.get('long_short_source')})", ls)

    pcr = der.get("put_call_oi")
    if pcr:
        add("options_put_call", _t((pcr - 0.6) * 3), f"Deribit put/call OI {pcr:.2f} — heavy put hedging is read contrarian", pcr)

    agg = (ob.get("aggregate") or {}).get("2")
    if agg:
        add("orderbook_imbalance", agg["imbalance"] * 2,
            f"Resting bids vs asks within ±2%: {agg['imbalance']*100:+.0f}% imbalance", agg["imbalance"])

    ti = fl.get("taker_imbalance")
    if ti is not None:
        add("taker_flow", ti * 4, f"Aggressive buys vs sells ({fl.get('taker_source')}): {ti*100:+.1f}%", ti)

    if etf.get("sum_5d_musd") is not None:
        s5 = etf["sum_5d_musd"]
        add("etf_flows", _t(s5 / 1500), f"US spot-ETF net flows, last 5 days: ${s5:,.0f}M", s5)

    tw = sum(c["weight"] for c in comp.values())
    composite = sum(c["score"] * c["weight"] for c in comp.values()) / tw if tw else 0.0
    score = round(composite * 100, 1)

    if score >= 40:
        label = "Strong bullish lean"
    elif score >= 15:
        label = "Bullish lean"
    elif score > -15:
        label = "Neutral / mixed"
    elif score > -40:
        label = "Bearish lean"
    else:
        label = "Strong bearish lean"

    sign = 1 if composite > 0 else -1
    voting = [c for c in comp.values() if abs(c["score"]) > 0.1]
    agree = sum(1 for c in voting if (c["score"] > 0) == (sign > 0)) / len(voting) if voting else 0
    conf = "High" if agree >= 0.75 and abs(score) >= 25 else "Medium" if agree >= 0.6 else "Low"
    if len(comp) < 6:            # too few inputs survived today's run to trust the reading
        conf = "Low"
    elif len(comp) < 9 and conf == "High":
        conf = "Medium"

    bid_walls = [w for w in ob.get("bid_walls", []) if px and w["price"] < px]
    ask_walls = [w for w in ob.get("ask_walls", []) if px and w["price"] > px]
    levels = {
        "support": sorted(bid_walls, key=lambda w: w["usd"], reverse=True)[:3],
        "resistance": sorted(ask_walls, key=lambda w: w["usd"], reverse=True)[:3],
    }
    return {"score": score, "label": label, "confidence": conf, "agreement_pct": round(agree * 100),
            "components": comp, "inputs_used": len(comp), "levels": levels}
