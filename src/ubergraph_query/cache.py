"""Simple thread-safe LRU cache with TTL expiry."""

import time
from collections import OrderedDict
from threading import Lock
from typing import Any

from . import config


class CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: float) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl


class LRUCache:
    """In-memory LRU cache with per-entry TTL.

    Thread-safe via a single lock (suitable for I/O-bound async workloads
    where the GIL provides adequate protection for pure-Python structures,
    and an explicit Lock covers threaded use).
    """

    def __init__(self, max_size: int = 512, ttl: float = 3600.0) -> None:
        self._max_size = max_size
        self._ttl = ttl
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> tuple[bool, Any]:
        """Return (found, value).  Moves hit entry to end (most-recent)."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return False, None
            if time.monotonic() > entry.expires_at:
                del self._store[key]
                self._misses += 1
                return False, None
            self._store.move_to_end(key)
            self._hits += 1
            return True, entry.value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Insert or update a cache entry."""
        ttl = ttl if ttl is not None else self._ttl
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = CacheEntry(value, ttl)
            while len(self._store) > self._max_size:
                self._store.popitem(last=False)  # evict LRU

    def invalidate(self, key: str) -> bool:
        """Remove a key. Returns True if it was present."""
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "size": len(self._store),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
            }


# Module-level singleton — created lazily so config is loaded first
_cache: LRUCache | None = None


def get_cache() -> LRUCache | None:
    """Return the shared cache instance, or None if caching is disabled."""
    global _cache
    if not config.ENABLE_QUERY_CACHE:
        return None
    if _cache is None:
        _cache = LRUCache(
            max_size=config.CACHE_MAX_SIZE,
            ttl=float(config.CACHE_TTL_SECONDS),
        )
    return _cache
