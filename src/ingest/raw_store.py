from __future__ import annotations
import json
from pathlib import Path


class RawStore:
    """Cache-first disk store. Saves raw API/scrape responses before any processing.
    source = logical source name (e.g. "adzuna", "firecrawl/demand")
    key    = identifier within source (e.g. "2026-06", "2026-06/stripe")
    """

    def __init__(self, base_dir: str = "data/raw"):
        self._base = Path(base_dir)

    def path(self, source: str, key: str) -> Path:
        return self._base / source / f"{key}.json"

    def exists(self, source: str, key: str) -> bool:
        return self.path(source, key).exists()

    def load(self, source: str, key: str) -> list | dict | None:
        p = self.path(source, key)
        if not p.exists():
            return None
        with p.open() as f:
            return json.load(f)

    def save(self, source: str, key: str, data: list | dict) -> Path:
        p = self.path(source, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w") as f:
            json.dump(data, f, separators=(",", ":"))
        return p
