"""Small dependency-free helpers."""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Any

_MISSING = object()


def sha1_hex(text: str, n: int = 40) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


class LRUCache:
    """Thread-safe least-recently-used cache. ``maxsize <= 0`` disables caching."""

    def __init__(self, maxsize: int = 256):
        self.maxsize = maxsize
        self._d: OrderedDict[Any, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key, default=None):
        with self._lock:
            val = self._d.get(key, _MISSING)
            if val is _MISSING:
                return default
            self._d.move_to_end(key)
            return val

    def set(self, key, value) -> None:
        if self.maxsize <= 0:
            return
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)

    def __len__(self) -> int:
        return len(self._d)
