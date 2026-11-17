"""Optional AI layer using the Claude API (set ANTHROPIC_API_KEY).

1. classify(): re-scores the highest-engagement posts/headlines in one batched
   call — much better than word lists at sarcasm and crypto context.
2. brief(): writes the daily analyst note shown at the top of the site,
   grounded only in the numbers and posts collected that day.
Without a key, both are skipped and the site falls back to a rules-based summary.
"""
from __future__ import annotations

import json
import logging
import os
import re

import requests

log = logging.getLogger("llm")
API = "https://api.anthropic.com/v1/messages"


def available(cfg: dict) -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and cfg.get("llm", {}).get("enabled", True)


def _call(cfg: dict, system: str, user: str, max_tokens: int) -> str:
    r = requests.post(API, timeout=120, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }, json={
        "model": cfg.get("llm", {}).get("model", "claude-sonnet-5-5"),
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    })
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


def classify(cfg: dict, items: list[dict]) -> dict[int, float]:
    """Returns {item_index: sentiment -1..+1} for the top-N items by engagement."""
    n = cfg.get("llm", {}).get("classify_max_items", 150)
    ranked = sorted(range(len(items)), key=lambda i: (items[i].get("score") or 0) + (items[i].get("comments") or 0),
                    reverse=True)
    pick = [i for i in ranked if items[i]["source"] != "News"][: int(n * 0.7)]
    pick += [i for i in ranked if items[i]["source"] == "News"][: n - len(pick)]
    lines = []
    for k, i in enumerate(pick):
        it = items[i]
        txt = f"{it.get('title', '')} {it.get('text', '')}".strip().replace("\n", " ")[:400]
        lines.append(f"{k}\t[{it['source']} {it['channel']}]\t{txt}")
    system = ("You score Bitcoin market sentiment in short texts from forums and news. For each line, output how "
              "bullish (+1) or bearish (-1) the author/headline is about BITCOIN'S PRICE OUTLOOK. 0 = neutral, "
              "off-topic, or unclear. Account for sarcasm, crypto slang, and that 'buy the dip' is bullish. "
              "Reply with ONLY a JSON array like [{\"i\":0,\"s\":0.4}, ...] covering every line.")
    try:
        raw = _call(cfg, system, "\n".join(lines), max_tokens=6000)
        arr = json.loads(re.search(r"\[.*\]", raw, re.S).group(0))
        return {pick[int(o["i"])]: max(-1.0, min(1.0, float(o["s"])))
                for o in arr if 0 <= int(o["i"]) < len(pick)}
    except Exception as e:  # noqa: BLE001
        log.warning("LLM classify failed, using VADER only: %s", e)
        return {}


def brief(cfg: dict, digest: dict) -> str | None:
    system = (
        "You are a disciplined crypto market analyst writing a short daily note for one reader who is deciding how "
        "to think about Bitcoin today. Use ONLY the data provided; never invent numbers, news or quotes. Be direct "
        "and specific, cite the figures that matter, and flag where signals conflict. Do not tell the reader to buy "
        "or sell; describe conditions, risks, and what would change the picture. Format in plain text with these "
        "exact headings, each starting with '### ': Bottom line, What the crowd is saying, Positioning & liquidity, "
        "Risks and what would change the view, Levels to watch. Use '- ' bullets under headings except Bottom line "
        "(2-3 sentences). Keep the whole note under 350 words.")
    try:
        return _call(cfg, system, "Today's data:\n" + json.dumps(digest, default=str)[:60000],
                     max_tokens=cfg.get("llm", {}).get("max_tokens_brief", 1400)).strip()
    except Exception as e:  # noqa: BLE001
        log.warning("LLM brief failed: %s", e)
        return None
