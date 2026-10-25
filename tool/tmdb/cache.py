"""Process-wide TTL cache of TMDb responses, shared across turns.

Keys are (path, sorted parameters) built before the credential is added, so the key
never contains it. Only successful responses are stored; values are read-only.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any

from .settings import CACHE_MAX_ENTRIES

CacheKey = tuple[str, tuple[tuple[str, str], ...]]


def cache_key(path: str, params: Mapping[str, str]) -> CacheKey:
    return path, tuple(sorted((key, str(value)) for key, value in params.items()))


class TtlCache:
    def __init__(
        self,
        ttl_seconds: int,
        *,
        max_entries: int = CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._items: OrderedDict[CacheKey, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0

    def get(self, key: CacheKey) -> Any | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, value = item
            if self._clock() >= expires_at:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def set(self, key: CacheKey, value: Any) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._items[key] = (self._clock() + self.ttl_seconds, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)
