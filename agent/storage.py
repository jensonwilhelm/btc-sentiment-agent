"""Daily history (data/history.json) + full latest snapshot (data/latest.json)."""
from __future__ import annotations

import json
from pathlib import Path


class Store:
    def __init__(self, data_dir: Path, keep_days: int = 730):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.keep = keep_days

    @property
    def history_path(self) -> Path:
        return self.dir / "history.json"

    def load_history(self) -> list[dict]:
        if self.history_path.exists():
            return json.loads(self.history_path.read_text())
        return []

    def append(self, row: dict) -> list[dict]:
        hist = [h for h in self.load_history() if h.get("date") != row["date"]]  # re-runs overwrite the day
        hist.append(row)
        hist.sort(key=lambda h: h["date"])
        hist = hist[-self.keep:]
        self.history_path.write_text(json.dumps(hist, indent=1))
        return hist

    def save_latest(self, snap: dict) -> None:
        (self.dir / "latest.json").write_text(json.dumps(snap, indent=1, default=str))
