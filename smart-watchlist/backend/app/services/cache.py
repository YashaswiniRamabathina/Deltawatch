"""
Minimal thread-safe TTL cache used to de-duplicate concurrent fetch
requests for the same symbol (e.g. a user adds AAPL the same second the
background poller is refreshing it).

This is intentionally NOT Redis. For a single-process demo deployment, an
in-memory dict is simpler and has one less moving part to set up — exactly
the "keep it simple" trade-off the brief asks for. The interface below is
narrow enough that swapping in a Redis-backed implementation for a
multi-process deployment is a drop-in change, not a rewrite: any consumer
of `Cache` only ever calls get/set/lock.
"""
import threading
import time
from typing import Any, Optional


class Cache:
    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        self._store[key] = (time.time() + ttl_seconds, value)

    def lock_for(self, key: str) -> threading.Lock:
        with self._locks_guard:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]


cache = Cache()
