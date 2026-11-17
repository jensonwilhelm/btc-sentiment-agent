"""Price-based indicators computed from daily closes."""
from __future__ import annotations

import math

import pandas as pd


def compute(history: list[dict]) -> dict:
    if len(history) < 30:
        return {}
    df = pd.DataFrame(history)
    c = df["close"].astype(float)
    out: dict = {}
    for n in (20, 50, 200):
        if len(c) >= n:
            out[f"sma{n}"] = float(c.rolling(n).mean().iloc[-1])
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-9)
    out["rsi14"] = float(100 - 100 / (1 + rs.iloc[-1]))
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sig = macd.ewm(span=9, adjust=False).mean()
    out["macd"], out["macd_signal"], out["macd_hist"] = float(macd.iloc[-1]), float(sig.iloc[-1]), float((macd - sig).iloc[-1])
    rets = c.pct_change().dropna()
    out["realized_vol_30d"] = float(rets.tail(30).std() * math.sqrt(365) * 100)
    out["return_7d"] = float((c.iloc[-1] / c.iloc[-8] - 1) * 100) if len(c) > 8 else None
    out["return_30d"] = float((c.iloc[-1] / c.iloc[-31] - 1) * 100) if len(c) > 31 else None
    out["return_90d"] = float((c.iloc[-1] / c.iloc[-91] - 1) * 100) if len(c) > 91 else None
    hi = float(c.max())
    out["high_365d"], out["drawdown_from_high_pct"] = hi, float((c.iloc[-1] / hi - 1) * 100)
    out["low_365d"] = float(c.min())
    if "sma200" in out:
        out["mayer_multiple"] = float(c.iloc[-1] / out["sma200"])
    # series for charts (last 180 days)
    tail = df.tail(180).copy()
    tail["sma50"] = c.rolling(50).mean().tail(180)
    tail["sma200"] = c.rolling(200).mean().tail(180)
    out["chart"] = [{"date": r.date, "close": round(r.close, 2),
                     "sma50": None if pd.isna(r.sma50) else round(r.sma50, 2),
                     "sma200": None if pd.isna(r.sma200) else round(r.sma200, 2)} for r in tail.itertuples()]
    return out
