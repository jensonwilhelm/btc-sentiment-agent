"""Market-wide mood and context indicators:
- Crypto Fear & Greed index (alternative.me)
- Retail attention: Wikipedia daily pageviews of the "Bitcoin" article
- Macro backdrop: S&P 500, Nasdaq, US Dollar Index, gold, 10y yield, IBIT (spot ETF) via Yahoo Finance
- Spot-ETF net flows (Farside Investors table; best-effort, often bot-protected)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from ..net import Http


def fear_greed(http: Http, cfg: dict) -> dict:
    r = http.get_json("https://api.alternative.me/fng/", params={"limit": 120})
    data = r["data"]
    hist = [{"date": datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"),
             "value": int(d["value"])} for d in data]
    hist.sort(key=lambda x: x["date"])
    return {"value": int(data[0]["value"]), "label": data[0]["value_classification"], "history": hist,
            "avg_7d": sum(h["value"] for h in hist[-7:]) / min(7, len(hist))}


def attention(http: Http, cfg: dict) -> dict:
    end = datetime.now(timezone.utc) - timedelta(days=1)
    start = end - timedelta(days=90)
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
           f"Bitcoin/daily/{start:%Y%m%d}/{end:%Y%m%d}")
    items = http.get_json(url)["items"]
    hist = [{"date": f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}-{i['timestamp'][6:8]}", "views": i["views"]}
            for i in items]
    v = [h["views"] for h in hist]
    return {"history": hist, "latest": v[-1], "avg_7d": sum(v[-7:]) / 7, "avg_90d": sum(v) / len(v),
            "ratio_7d_vs_90d": (sum(v[-7:]) / 7) / (sum(v) / len(v))}


MACRO = {"S&P 500": "^GSPC", "Nasdaq": "^IXIC", "US Dollar (DXY)": "DX-Y.NYB", "Gold": "GC=F",
         "US 10y yield": "^TNX", "IBIT (BlackRock BTC ETF)": "IBIT", "MSTR (Strategy)": "MSTR"}


def macro(http: Http, cfg: dict) -> dict:
    import yfinance as yf  # imported lazily so the rest works without it

    assets = []
    for name, sym in MACRO.items():
        try:
            h = yf.Ticker(sym).history(period="1mo", interval="1d", auto_adjust=False)
            closes = h["Close"].dropna()
            if len(closes) < 6:
                continue
            row = {"name": name, "symbol": sym, "price": float(closes.iloc[-1]),
                   "change_1d_pct": float((closes.iloc[-1] / closes.iloc[-2] - 1) * 100),
                   "change_5d_pct": float((closes.iloc[-1] / closes.iloc[-6] - 1) * 100)}
            if sym == "IBIT" and "Volume" in h:
                vol = h["Volume"].dropna()
                row["volume_vs_20d"] = float(vol.iloc[-1] / vol.tail(20).mean())
            assets.append(row)
        except Exception:
            continue
    if not assets:
        raise RuntimeError("yfinance returned nothing")
    return {"assets": assets}


def etf_flows(http: Http, cfg: dict) -> dict:
    """Parses farside.co.uk/btc — daily US spot BTC ETF net flows ($m). Fragile by nature."""
    html = http.get_text("https://farside.co.uk/btc/", headers={"Accept": "text/html"})
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 3 or not re.match(r"\d{1,2} \w{3} \d{4}", cells[0]):
            continue
        try:
            date = datetime.strptime(cells[0], "%d %b %Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        tot = cells[-1].replace(",", "")
        neg = tot.startswith("(") and tot.endswith(")")
        tot = tot.strip("()")
        if tot in ("", "-"):
            continue
        try:
            val = float(tot) * (-1 if neg else 1)
        except ValueError:
            continue
        rows.append({"date": date, "net_musd": val})
    if not rows:
        raise RuntimeError("could not parse ETF flow table (site layout or bot protection)")
    rows.sort(key=lambda r: r["date"])
    last = rows[-30:]
    return {"history": last, "latest": last[-1], "sum_5d_musd": sum(r["net_musd"] for r in last[-5:]),
            "sum_20d_musd": sum(r["net_musd"] for r in last[-20:])}
