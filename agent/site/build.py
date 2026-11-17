"""Renders the static website (index.html + JSON data files) from today's snapshot."""
from __future__ import annotations

import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Undefined, select_autoescape

TPL = Path(__file__).parent / "templates"


def _n(v):
    """Treat missing template values as None."""
    return None if v is None or isinstance(v, Undefined) else v


def money(v, digits=1):
    v = _n(v)
    if v is None:
        return "—"
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{'-' if v < 0 else ''}${a/div:,.{digits}f}{suf}"
    return f"{'-' if v < 0 else ''}${a:,.0f}"


def usd(v, digits=0):
    v = _n(v)
    return "—" if v is None else f"${v:,.{digits}f}"


def pct(v, digits=1, signed=True):
    v = _n(v)
    if v is None:
        return "—"
    return f"{v:+.{digits}f}%" if signed else f"{v:.{digits}f}%"


def num(v, digits=0):
    v = _n(v)
    return "—" if v is None else f"{v:,.{digits}f}"


def tone(v, thr=0.0):
    v = _n(v)
    if v is None:
        return "muted"
    return "pos" if v > thr else "neg" if v < -thr else "muted"


def brief_html(text: str) -> str:
    out, in_list = [], False
    for line in (text or "").splitlines():
        line = line.rstrip()
        if not line:
            continue
        esc = html.escape(line)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        esc = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", esc)
        if esc.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h4>{esc[4:]}</h4>")
        elif esc.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{esc[2:]}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{esc}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


NAMES = {
    "trend": "Trend (vs 50/200-day avg)", "momentum": "Momentum (30d + MACD)", "mean_reversion": "RSI stretch",
    "social_sentiment": "Forum & social mood", "news_sentiment": "News tone",
    "fear_greed_contrarian": "Fear & Greed (contrarian)", "funding_contrarian": "Perp funding (contrarian)",
    "long_short_contrarian": "Long/short ratio (contrarian)", "options_put_call": "Options put/call",
    "orderbook_imbalance": "Order-book depth ±2%", "taker_flow": "Aggressive buy/sell flow",
    "etf_flows": "Spot-ETF flows (5d)",
}


def build(snap: dict, history: list[dict], cfg: dict, out_dir: Path, data_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(TPL), autoescape=select_autoescape(["html", "j2"]))
    env.filters.update(money=money, usd=usd, pct=pct, num=num, tone=tone)
    env.tests["present"] = lambda v: _n(v) is not None

    ta = snap.get("technicals", {})
    charts = {
        "price": ta.get("chart", []),
        "history": history,
        "fg": (snap.get("fear_greed") or {}).get("history", []),
        "etf": (snap.get("etf") or {}).get("history", []),
        "attention": (snap.get("attention") or {}).get("history", []),
        "hashrate": (snap.get("onchain") or {}).get("hashrate_history", []),
        "bands": (snap.get("orderbook") or {}).get("aggregate", {}),
    }
    gen = datetime.fromisoformat(snap["generated_at"])
    page = env.get_template("index.html.j2").render(
        s=snap, cfg=cfg, charts_json=json.dumps(charts, default=str).replace("</", "<\\/"),
        brief=brief_html(snap.get("brief", "")), names=NAMES,
        updated=gen.strftime("%a %b %d, %Y · %H:%M UTC"),
        components=sorted(snap["signal"]["components"].items(),
                          key=lambda kv: abs(kv[1]["score"]) * kv[1]["weight"], reverse=True),
    )
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    (out_dir / "data").mkdir(exist_ok=True)
    for f in ("latest.json", "history.json"):
        if (Path(data_dir) / f).exists():
            shutil.copy(Path(data_dir) / f, out_dir / "data" / f)
    (out_dir / ".nojekyll").write_text("")
    return out_dir / "index.html"
