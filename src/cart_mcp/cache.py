"""Bounded LRU cache for SDA responses.

Cache hits return the parsed SDAResult, avoiding ~10 s SDA round trips on repeat
AOIs. The cache is keyed on (endpoint, query) - the query string already embeds
the landunit, WKT, and concern set, so it covers the full logical key. Entries
expire on a wall-clock TTL: SSURGO is republished occasionally, and an entry that
never expired would serve stale ratings after a republish (a catastrophic hit).
Set SDA_CACHE=0 to disable caching entirely (e.g. live regression tests).
"""
from __future__ import annotations

import os
import time
from collections import OrderedDict
from dataclasses import dataclass

CACHE_ENABLED = os.environ.get("SDA_CACHE", "1") != "0"
MAX_ENTRIES = int(os.environ.get("SDA_CACHE_MAX", "100"))
TTL_SECONDS = float(os.environ.get("SDA_CACHE_TTL", "3600"))


@dataclass
class CacheEntry:
    value: object
    expires_at: float


class LRUCache:
    """Thread-unsafe, size-bounded LRU with per-entry TTL expiry."""

    def __init__(self, max_entries: int = MAX_ENTRIES, ttl: float = TTL_SECONDS):
        self.max_entries = max(1, max_entries)
        self.ttl = ttl
        self._data: OrderedDict[str, CacheEntry] = OrderedDict()

    def _now(self) -> float:
        return time.monotonic()

    def get(self, key: str):
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry.expires_at < self._now():
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return entry.value

    def put(self, key: str, value: object) -> None:
        self._data[key] = CacheEntry(value, self._now() + self.ttl)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


def make_cache() -> LRUCache | None:
    """Return the shared cache, or None when caching is disabled."""
    if not CACHE_ENABLED:
        return None
    return LRUCache()


_cache: LRUCache | None = make_cache()


def get_cached(key: str):
    if _cache is None:
        return None
    return _cache.get(key)


def put_cached(key: str, value: object) -> None:
    if _cache is not None:
        _cache.put(key, value)


def clear_cache() -> None:
    if _cache is not None:
        _cache.clear()


def cache_key(endpoint: str, query: str) -> str:
    return f"{endpoint}\n{query}"
