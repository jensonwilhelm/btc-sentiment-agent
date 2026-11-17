"""Small HTTP helper: retries with backoff, timeouts, a descriptive User-Agent,
and a per-host politeness delay so forums aren't hammered."""
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger("net")


class Http:
    def __init__(self, cfg: dict):
        h = cfg.get("http", {})
        self.timeout = h.get("timeout", 20)
        self.retries = h.get("retries", 3)
        self.delay = h.get("polite_delay_sec", 1.0)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": h.get("user_agent", "btc-sentiment-agent/1.0"),
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        })
        self._last_hit: dict[str, float] = {}

    def _wait_for_host(self, url: str) -> None:
        host = urlparse(url).netloc
        last = self._last_hit.get(host)
        if last is not None:
            gap = time.time() - last
            if gap < self.delay:
                time.sleep(self.delay - gap)
        self._last_hit[host] = time.time()

    def request(self, method: str, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        err: Exception | None = None
        for attempt in range(self.retries):
            self._wait_for_host(url)
            try:
                r = self.session.request(method, url, **kw)
                if r.status_code == 429 or r.status_code >= 500:
                    wait = float(r.headers.get("Retry-After", 2 ** (attempt + 1)))
                    log.warning("%s %s -> %s, retry in %.0fs", method, url, r.status_code, wait)
                    time.sleep(min(wait, 30))
                    err = requests.HTTPError(f"HTTP {r.status_code}")
                    continue
                r.raise_for_status()
                return r
            except requests.RequestException as e:  # network errors, 4xx
                err = e
                if isinstance(e, requests.HTTPError) and e.response is not None and 400 <= e.response.status_code < 500 \
                        and e.response.status_code != 429:
                    break  # 403/451 etc. won't fix themselves
                time.sleep(2 ** attempt)
        raise RuntimeError(f"{method} {url} failed: {err}")

    def get_json(self, url: str, **kw):
        return self.request("GET", url, **kw).json()

    def get_text(self, url: str, **kw) -> str:
        return self.request("GET", url, **kw).text

    def post_json(self, url: str, payload: dict, **kw):
        return self.request("POST", url, json=payload, **kw).json()
