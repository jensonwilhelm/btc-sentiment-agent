"""Network health from mempool.space: fees, mempool congestion, hashrate,
difficulty adjustment. Rising fees/mempool = on-chain demand; hashrate trend =
miner confidence."""
from __future__ import annotations

from datetime import datetime, timezone

from ..net import Http

MP = "https://mempool.space/api"


def collect(http: Http, cfg: dict) -> dict:
    out: dict = {}
    out["fees"] = http.get_json(f"{MP}/v1/fees/recommended")
    m = http.get_json(f"{MP}/mempool")
    out["mempool_tx"] = m.get("count")
    out["mempool_vsize_mb"] = (m.get("vsize") or 0) / 1e6
    out["block_height"] = int(http.get_text(f"{MP}/blocks/tip/height").strip())
    try:
        d = http.get_json(f"{MP}/v1/difficulty-adjustment")
        out["difficulty_change_pct"] = d.get("difficultyChange")
        out["retarget_progress_pct"] = d.get("progressPercent")
        out["remaining_blocks"] = d.get("remainingBlocks")
        if d.get("estimatedRetargetDate"):
            out["next_retarget"] = datetime.fromtimestamp(d["estimatedRetargetDate"] / 1000, tz=timezone.utc
                                                          ).strftime("%Y-%m-%d")
    except Exception:
        pass
    try:
        h = http.get_json(f"{MP}/v1/mining/hashrate/3m")
        rates = h.get("hashrates", [])
        out["hashrate_eh"] = (h.get("currentHashrate") or 0) / 1e18
        if len(rates) > 30:
            now, then = rates[-1]["avgHashrate"], rates[-31]["avgHashrate"]
            out["hashrate_change_30d_pct"] = (now / then - 1) * 100
        out["hashrate_history"] = [
            {"date": datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d"),
             "eh": r["avgHashrate"] / 1e18} for r in rates]
    except Exception:
        pass
    return out
