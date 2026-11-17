"""Daily run: collect → score → signal → AI brief → save history → build website.

    python -m agent.main            # live run
    python -m agent.main --sample   # offline demo with synthetic data (no network)
    python -m agent.main --no-llm   # skip Claude even if ANTHROPIC_API_KEY is set
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from .analysis import llm, sentiment, signals, technicals
from .collectors import derivatives, flow, indicators, news, onchain, orderbook, prices, social
from .config import ROOT, load_config
from .net import Http
from .site import build as site_build
from .storage import Store

log = logging.getLogger("agent")


def _collect_live(cfg: dict, status: dict) -> dict:
    http = Http(cfg)
    raw: dict = {}

    def safe(key: str, label: str, fn, *args):
        t0 = time.time()
        try:
            res = fn(http, cfg, *args)
            detail = res.get("venue_status") or res.get("status") if isinstance(res, dict) else None
            status[label] = {"ok": True, "secs": round(time.time() - t0, 1), "detail": detail}
            raw[key] = res
        except Exception as e:  # noqa: BLE001
            log.warning("%s failed: %s", label, e)
            status[label] = {"ok": False, "secs": round(time.time() - t0, 1), "detail": str(e)[:300]}

    safe("prices", "Prices & history", prices.collect)
    spot = (raw.get("prices") or {}).get("spot")
    safe("orderbook", "Order books / walls", orderbook.collect)
    safe("flow", "Taker flow & whale trades", flow.collect)
    safe("derivatives", "Derivatives (funding/OI/options)", derivatives.collect, spot)
    safe("onchain", "On-chain (mempool.space)", onchain.collect)
    safe("fear_greed", "Fear & Greed index", indicators.fear_greed)
    safe("attention", "Wikipedia attention", indicators.attention)
    safe("macro", "Macro (Yahoo Finance)", indicators.macro)
    safe("etf", "Spot-ETF flows (Farside)", indicators.etf_flows)
    if cfg.get("reddit", {}).get("enabled", True):
        safe("reddit", "Reddit", social.reddit)
    if cfg.get("bitcointalk", {}).get("enabled", True):
        safe("bitcointalk", "BitcoinTalk", social.bitcointalk)
    if cfg.get("stocktwits", {}).get("enabled", True):
        safe("stocktwits", "StockTwits", social.stocktwits)
    if cfg.get("news", {}).get("enabled", True):
        safe("news", "News RSS", news.collect)
    return raw


def _digest(snap: dict) -> dict:
    """Compact view of the day for the LLM (keeps token use small)."""
    s = snap.get("sentiment", {})
    pick = lambda lst, n: [{k: i.get(k) for k in ("channel", "title", "text", "sentiment")} for i in (lst or [])[:n]]
    return {
        "price": {k: snap.get("prices", {}).get(k) for k in ("spot", "change_24h", "change_7d", "change_30d",
                                                             "ath", "ath_change_pct", "btc_dominance")},
        "technicals": {k: v for k, v in snap.get("technicals", {}).items() if k != "chart"},
        "signal": {k: snap["signal"][k] for k in ("score", "label", "confidence", "agreement_pct")},
        "components": {k: {"score": v["score"], "why": v["why"]} for k, v in snap["signal"]["components"].items()},
        "levels": snap["signal"]["levels"],
        "social": s.get("social"), "news": s.get("news"), "by_source": s.get("by_source"),
        "topics": s.get("topics"), "trending_terms": s.get("trending_terms", [])[:15],
        "most_bullish_posts": pick(s.get("top_bullish"), 5), "most_bearish_posts": pick(s.get("top_bearish"), 5),
        "headlines": [h["title"] for h in (s.get("top_headlines") or [])[:15]],
        "fear_greed": {k: (snap.get("fear_greed") or {}).get(k) for k in ("value", "label", "avg_7d")},
        "derivatives": {k: v for k, v in (snap.get("derivatives") or {}).items() if k != "venue_status"},
        "etf": {k: (snap.get("etf") or {}).get(k) for k in ("latest", "sum_5d_musd", "sum_20d_musd")},
        "onchain": {k: v for k, v in (snap.get("onchain") or {}).items() if k != "hashrate_history"},
        "macro": (snap.get("macro") or {}).get("assets"),
        "whale_trades": {k: (snap.get("flow") or {}).get(k) for k in ("large_buy_usd", "large_sell_usd", "taker_imbalance")},
    }


def _rules_brief(snap: dict) -> str:
    sig = snap["signal"]
    comps = sorted(sig["components"].items(), key=lambda kv: kv[1]["score"] * kv[1]["weight"])
    bears = [c for c in comps if c[1]["score"] < -0.15][:3]
    bulls = [c for c in reversed(comps) if c[1]["score"] > 0.15][:3]
    s = snap.get("sentiment", {})
    lines = ["### Bottom line",
             f"Composite reading is {sig['score']:+.0f} ({sig['label']}, {sig['confidence'].lower()} confidence; "
             f"{sig['agreement_pct']}% of active inputs agree)."]
    lines.append("### Supporting the bulls")
    lines += [f"- {v['why']}" for _, v in bulls] or ["- Nothing notable today."]
    lines.append("### Supporting the bears")
    lines += [f"- {v['why']}" for _, v in bears] or ["- Nothing notable today."]
    if s.get("topics"):
        lines.append("### What the crowd is talking about")
        lines += [f"- {t['topic']}: {t['mentions']} mentions, tone {t['avg_sentiment']:+.2f}" for t in s["topics"][:4]]
    lv = sig.get("levels", {})
    if lv.get("support") or lv.get("resistance"):
        lines.append("### Levels to watch (largest resting liquidity)")
        lines += [f"- Bid wall ≈ ${w['price']:,.0f} (${w['usd']/1e6:,.1f}M)" for w in lv.get("support", [])[:2]]
        lines += [f"- Ask wall ≈ ${w['price']:,.0f} (${w['usd']/1e6:,.1f}M)" for w in lv.get("resistance", [])[:2]]
    lines.append("_Add an ANTHROPIC_API_KEY to replace this rules-based note with an AI-written analyst brief._")
    return "\n".join(lines)


def run(sample: bool = False, no_llm: bool = False) -> dict:
    cfg = load_config()
    status: dict = {}
    now = datetime.now(timezone.utc)
    data_dir = ROOT / ("data_sample" if sample else "data")
    store = Store(data_dir, cfg.get("site", {}).get("history_days", 730))

    if sample:
        from . import sample_data
        raw = sample_data.generate(store)
        status = sample_data.STATUS
    else:
        raw = _collect_live(cfg, status)

    if "prices" not in raw:
        raise SystemExit("Price data unavailable — aborting so the site keeps yesterday's version.")

    items = []
    for k in ("reddit", "bitcointalk", "stocktwits", "news"):
        items += (raw.get(k) or {}).get("items", [])

    use_llm = (not no_llm) and (not sample) and llm.available(cfg)
    llm_scores = llm.classify(cfg, items) if use_llm and items else {}
    sentiment.score_items(items, llm_scores)

    snap = {
        "generated_at": now.isoformat(), "date": now.strftime("%Y-%m-%d"), "sample": sample,
        "prices": {k: v for k, v in raw["prices"].items() if k != "history"},
        "technicals": technicals.compute(raw["prices"].get("history", [])),
        "sentiment": sentiment.summarize(items),
        **{k: raw.get(k) for k in ("orderbook", "flow", "derivatives", "onchain", "fear_greed",
                                   "attention", "macro", "etf")},
        "stocktwits_ratio": (raw.get("stocktwits") or {}).get("bull_ratio"),
        "reddit_mode": (raw.get("reddit") or {}).get("mode"),
        "status": status,
    }
    history = store.load_history()
    snap["signal"] = signals.build(snap, history, cfg)

    brief = llm.brief(cfg, _digest(snap)) if use_llm else None
    snap["brief"], snap["brief_source"] = (brief, "Claude") if brief else (_rules_brief(snap), "rules")

    der, ob, fl = snap.get("derivatives") or {}, snap.get("orderbook") or {}, snap.get("flow") or {}
    history = store.append({
        "date": snap["date"], "price": snap["prices"]["spot"], "score": snap["signal"]["score"],
        "label": snap["signal"]["label"],
        "social_sentiment": (snap["sentiment"].get("social") or {}).get("weighted_mean"),
        "news_sentiment": (snap["sentiment"].get("news") or {}).get("weighted_mean"),
        "social_n": (snap["sentiment"].get("social") or {}).get("n"),
        "fear_greed": (snap.get("fear_greed") or {}).get("value"),
        "funding_ann": der.get("funding_avg_annualized"), "oi_usd": der.get("oi_total_usd"),
        "ob_imbalance_2": ((ob.get("aggregate") or {}).get("2") or {}).get("imbalance"),
        "taker_imbalance": fl.get("taker_imbalance"),
        "etf_5d": (snap.get("etf") or {}).get("sum_5d_musd"),
    })
    store.save_latest(snap)
    out = ROOT / cfg.get("site", {}).get("output_dir", "site_out")
    site_build.build(snap, history, cfg, out, data_dir)
    log.info("Done: score %s (%s). Site written to %s", snap["signal"]["score"], snap["signal"]["label"], out)
    return snap


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="offline demo with synthetic data")
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run(sample=a.sample, no_llm=a.no_llm)
