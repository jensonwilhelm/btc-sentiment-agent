"""Loads config.yaml (path overridable with BTC_AGENT_CONFIG)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | None = None) -> dict:
    cfg_path = Path(path or os.environ.get("BTC_AGENT_CONFIG", ROOT / "config.yaml"))
    with open(cfg_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
