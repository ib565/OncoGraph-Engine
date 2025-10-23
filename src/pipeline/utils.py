"""Utility functions and helpers for the pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any, TypeVar

T = TypeVar("T")


class TTLCache:
    """Thread-safe in-memory TTL cache with configurable expiration."""

    def __init__(self, default_ttl_seconds: int = 1800) -> None:
        """Initialize cache with default TTL in seconds."""
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.RLock()
        self._default_ttl = default_ttl_seconds

    def get(self, key: str) -> Any | None:
        """Get value from cache if not expired."""
        with self._lock:
            if key not in self._cache:
                return None

            value, expiry = self._cache[key]
            if time.time() > expiry:
                del self._cache[key]
                return None

            # Deep copy to avoid mutation of cached values
            return self._deep_copy(value)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Set value in cache with TTL."""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        if ttl <= 0:
            return  # Skip caching if TTL is disabled

        with self._lock:
            expiry = time.time() + ttl
            # Deep copy to avoid mutation of cached values
            self._cache[key] = (self._deep_copy(value), expiry)

    def clear(self) -> None:
        """Clear all cached values."""
        with self._lock:
            self._cache.clear()

    def _deep_copy(self, obj: Any) -> Any:
        """Create a deep copy of the object."""
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        elif isinstance(obj, (list, tuple)):
            return type(obj)(self._deep_copy(item) for item in obj)
        elif isinstance(obj, dict):
            return {k: self._deep_copy(v) for k, v in obj.items()}
        else:
            # For complex objects, try JSON serialization/deserialization
            try:
                return json.loads(json.dumps(obj, default=str))
            except (TypeError, ValueError):
                # If JSON fails, return as-is (caller should handle immutable objects)
                return obj


def stable_hash(obj: Any) -> str:
    """Create a stable hash of an object for cache keys."""
    # Sort dict keys and use consistent JSON formatting
    json_str = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(json_str.encode()).hexdigest()


def get_cache_ttl() -> int:
    """Get cache TTL from environment variables."""
    return int(os.getenv("CACHE_TTL_SECONDS", "1800"))


def get_llm_cache_ttl() -> int:
    """Get LLM-specific cache TTL from environment variables."""
    return int(os.getenv("LLM_CACHE_TTL_SECONDS", os.getenv("CACHE_TTL_SECONDS", "1800")))


# Global cache instances
_enrichment_cache = TTLCache(get_cache_ttl())
_llm_cache = TTLCache(get_llm_cache_ttl())


def get_enrichment_cache() -> TTLCache:
    """Get the enrichment analysis cache instance."""
    return _enrichment_cache


def get_llm_cache() -> TTLCache:
    """Get the LLM cache instance."""
    return _llm_cache
