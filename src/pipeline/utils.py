"""Utility functions and helpers for the pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

try:
    import psycopg
except ImportError:
    psycopg = None  # type: ignore[assignment, unused-ignore]

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

    def delete(self, key: str) -> None:
        """Delete a specific cache entry by key."""
        with self._lock:
            self._cache.pop(key, None)

    def delete_by_prefix(self, prefix: str) -> int:
        """Delete all entries where key starts with prefix. Returns count deleted."""
        with self._lock:
            keys_to_delete = [key for key in self._cache if key.startswith(prefix)]
            for key in keys_to_delete:
                self._cache.pop(key, None)
            return len(keys_to_delete)

    def _deep_copy(self, obj: Any) -> Any:
        """Create a deep copy of the object."""
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        elif isinstance(obj, (list, tuple)):
            return type(obj)(self._deep_copy(item) for item in obj)
        elif isinstance(obj, dict):
            return {k: self._deep_copy(v) for k, v in obj.items()}
        else:
            # For Pydantic models, use model_dump() for proper serialization
            if hasattr(obj, "model_dump"):
                return obj.model_dump()
            # For other complex objects, try JSON serialization/deserialization
            try:
                return json.loads(json.dumps(obj, default=str))
            except (TypeError, ValueError):
                # If JSON fails, return as-is (caller should handle immutable objects)
                return obj


class PostgresCache:
    """Postgres-backed persistent cache with TTL support."""

    def __init__(self, dsn: str, cache_type: str, default_ttl_seconds: int = 172800) -> None:
        """Initialize Postgres cache.

        Args:
            dsn: Postgres connection string
            cache_type: Type identifier for this cache ('llm' or 'enrichment')
            default_ttl_seconds: Default TTL in seconds (default: 48h = 172800)
        """
        if psycopg is None:
            raise ImportError("psycopg is required for PostgresCache. Install it with: pip install psycopg[binary]")
        self._dsn = dsn
        self._cache_type = cache_type
        self._default_ttl = default_ttl_seconds
        self._lock = threading.RLock()
        self._initialized = False
        self._init_lock = threading.Lock()
        self._set_count = 0  # Counter for batch cleanup

    def _ensure_initialized(self) -> None:
        """Ensure cache table is initialized (thread-safe)."""
        if self._initialized:
            return

        with self._init_lock:
            if self._initialized:
                return

            try:
                _init_cache_table(self._dsn)
                self._initialized = True
            except Exception:
                # Non-fatal: table might already exist or connection might fail
                # We'll try again on next operation
                pass

    def get(self, key: str) -> Any | None:
        """Get value from cache if not expired."""
        self._ensure_initialized()

        try:
            with psycopg.connect(self._dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT value, expires_at 
                        FROM cache_entries 
                        WHERE cache_key = %s 
                          AND cache_type = %s
                        """,
                        (key, self._cache_type),
                    )
                    row = cur.fetchone()

                    if not row:
                        return None

                    value_json, expires_at = row

                    # Check if expired
                    if expires_at < datetime.now(UTC):
                        # Delete expired entry
                        cur.execute(
                            "DELETE FROM cache_entries WHERE cache_key = %s AND cache_type = %s",
                            (key, self._cache_type),
                        )
                        return None

                    # Update access stats
                    cur.execute(
                        """
                        UPDATE cache_entries 
                        SET access_count = access_count + 1,
                            last_accessed_at = NOW()
                        WHERE cache_key = %s AND cache_type = %s
                        """,
                        (key, self._cache_type),
                    )

                    # psycopg automatically deserializes JSONB to Python objects (dict/list)
                    # So value_json is already a Python object, not a string
                    value = value_json

                    # Deep copy to avoid mutation
                    return self._deep_copy(value)

        except Exception as e:
            # Cache failures must be non-fatal, but log for debugging
            import logging

            logger = logging.getLogger(__name__)
            logger.debug(f"Cache get failed for key {key[:50]}...: {e}", exc_info=True)
            return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Set value in cache with TTL."""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        if ttl <= 0:
            return  # Skip caching if TTL is disabled

        self._ensure_initialized()

        try:
            expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
            # Serialize value to JSON
            value_json = json.dumps(value, default=str, ensure_ascii=False)

            with psycopg.connect(self._dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO cache_entries 
                        (cache_key, cache_type, value, expires_at, created_at, access_count, last_accessed_at)
                        VALUES (%s, %s, %s::jsonb, %s, NOW(), 0, NOW())
                        ON CONFLICT (cache_key) 
                        DO UPDATE SET 
                            value = EXCLUDED.value,
                            expires_at = EXCLUDED.expires_at,
                            created_at = NOW(),
                            access_count = 0,
                            last_accessed_at = NOW()
                        """,
                        (key, self._cache_type, value_json, expires_at),
                    )

            # Occasional batch cleanup (every 100 set operations)
            with self._lock:
                self._set_count += 1
                if self._set_count >= 100:
                    self._set_count = 0
                    self._cleanup_expired_batch()

        except Exception as e:
            # Cache failures must be non-fatal, but log for debugging
            import logging

            logger = logging.getLogger(__name__)
            logger.debug(f"Cache set failed for key {key[:50]}...: {e}", exc_info=True)
            pass

    def delete(self, key: str) -> None:
        """Delete a specific cache entry by key."""
        self._ensure_initialized()

        try:
            with psycopg.connect(self._dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM cache_entries WHERE cache_key = %s AND cache_type = %s",
                        (key, self._cache_type),
                    )
        except Exception as e:
            # Cache failures must be non-fatal, but log for debugging
            import logging

            logger = logging.getLogger(__name__)
            logger.debug(f"Cache set failed for key {key[:50]}...: {e}", exc_info=True)
            pass

    def delete_by_prefix(self, prefix: str) -> int:
        """Delete all entries where cache_key starts with prefix. Returns count deleted."""
        self._ensure_initialized()

        try:
            with psycopg.connect(self._dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM cache_entries 
                        WHERE cache_key LIKE %s AND cache_type = %s
                        """,
                        (f"{prefix}%", self._cache_type),
                    )
                    return cur.rowcount or 0
        except Exception:
            # Cache failures must be non-fatal
            return 0

    def clear(self) -> None:
        """Clear all cached values for this cache type."""
        self._ensure_initialized()

        try:
            with psycopg.connect(self._dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM cache_entries WHERE cache_type = %s", (self._cache_type,))
        except Exception as e:
            # Cache failures must be non-fatal, but log for debugging
            import logging

            logger = logging.getLogger(__name__)
            logger.debug(f"Cache clear failed: {e}", exc_info=True)
            pass

    def _cleanup_expired_batch(self) -> None:
        """Delete up to 100 expired entries (called occasionally)."""
        try:
            with psycopg.connect(self._dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM cache_entries 
                        WHERE expires_at < NOW() AND cache_type = %s
                        LIMIT 100
                        """,
                        (self._cache_type,),
                    )
        except Exception as e:
            # Cache failures must be non-fatal, but log for debugging
            import logging

            logger = logging.getLogger(__name__)
            logger.debug(f"Cache batch cleanup failed: {e}", exc_info=True)
            pass

    def _deep_copy(self, obj: Any) -> Any:
        """Create a deep copy of the object (reuse TTLCache logic)."""
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        elif isinstance(obj, (list, tuple)):
            return type(obj)(self._deep_copy(item) for item in obj)
        elif isinstance(obj, dict):
            return {k: self._deep_copy(v) for k, v in obj.items()}
        else:
            # For Pydantic models, use model_dump() for proper serialization
            if hasattr(obj, "model_dump"):
                return obj.model_dump()
            # For other complex objects, try JSON serialization/deserialization
            try:
                return json.loads(json.dumps(obj, default=str))
            except (TypeError, ValueError):
                # If JSON fails, return as-is (caller should handle immutable objects)
                return obj


def _dict_sort_key(item: Any) -> str:
    """Create a stable sort key for a dict item by hashing its JSON representation."""
    return hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _normalize_for_hashing(obj: Any) -> Any:
    """Normalize an object for consistent hashing.

    Handles:
    - Sorting lists of dicts by their content hash
    - Normalizing floating point numbers to avoid precision issues
    - Ensuring dict key order is consistent
    """
    if isinstance(obj, float):
        # Round to 10 decimal places to avoid precision issues
        return round(obj, 10)
    elif isinstance(obj, list):
        # For lists of dicts, sort by their normalized content
        if obj and isinstance(obj[0], dict):
            # Sort by hash of normalized dict to ensure consistent order
            normalized_items = [_normalize_for_hashing(item) for item in obj]
            return sorted(normalized_items, key=_dict_sort_key)
        else:
            return [_normalize_for_hashing(item) for item in obj]
    elif isinstance(obj, dict):
        # Recursively normalize dict values and ensure key order
        return {k: _normalize_for_hashing(v) for k, v in sorted(obj.items())}
    else:
        return obj


def stable_hash(obj: Any) -> str:
    """Create a stable hash of an object for cache keys."""
    # Normalize the object first to handle list ordering and float precision
    normalized = _normalize_for_hashing(obj)
    # Sort dict keys and use consistent JSON formatting
    json_str = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(json_str.encode()).hexdigest()


def get_cache_ttl() -> int:
    """Get cache TTL from environment variables."""
    return int(os.getenv("CACHE_TTL_SECONDS", "1800"))


def get_llm_cache_ttl() -> int:
    """Get LLM-specific cache TTL from environment variables (default: 48h = 172800s)."""
    return int(os.getenv("LLM_CACHE_TTL_SECONDS", os.getenv("CACHE_TTL_SECONDS", "172800")))


def get_enrichment_cache_ttl() -> int:
    """Get enrichment-specific cache TTL from environment variables (default: 48h = 172800s)."""
    return int(os.getenv("ENRICHMENT_CACHE_TTL_SECONDS", os.getenv("CACHE_TTL_SECONDS", "172800")))


def _get_cache_dsn() -> str | None:
    """Get Postgres DSN for cache from environment variables."""
    return os.getenv("CACHE_DATABASE_URL") or os.getenv("TRACE_DATABASE_URL") or os.getenv("DATABASE_URL")


def _init_cache_table(dsn: str) -> None:
    """Initialize the cache_entries table schema.

    Expects a table created via:
      CREATE TABLE IF NOT EXISTS cache_entries (
        cache_key TEXT PRIMARY KEY,
        cache_type VARCHAR(50) NOT NULL,
        value JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMPTZ NOT NULL,
        access_count INTEGER DEFAULT 0,
        last_accessed_at TIMESTAMPTZ DEFAULT NOW()
      );
      CREATE INDEX IF NOT EXISTS idx_cache_expires_at ON cache_entries(expires_at);
      CREATE INDEX IF NOT EXISTS idx_cache_type_expires ON cache_entries(cache_type, expires_at);
    """
    if psycopg is None:
        return

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cache_entries (
                        cache_key TEXT PRIMARY KEY,
                        cache_type VARCHAR(50) NOT NULL,
                        value JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        expires_at TIMESTAMPTZ NOT NULL,
                        access_count INTEGER DEFAULT 0,
                        last_accessed_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires_at ON cache_entries(expires_at)")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cache_type_expires ON cache_entries(cache_type, expires_at)"
                )
    except Exception:
        # Non-fatal: table might already exist or connection might fail
        pass


# Global cache instances (lazy initialization)
_enrichment_cache: TTLCache | PostgresCache | None = None
_llm_cache: TTLCache | PostgresCache | None = None
_cache_lock = threading.Lock()


def get_enrichment_cache() -> TTLCache | PostgresCache:
    """Get the enrichment analysis cache instance."""
    global _enrichment_cache

    if _enrichment_cache is not None:
        return _enrichment_cache

    with _cache_lock:
        if _enrichment_cache is not None:
            return _enrichment_cache

        dsn = _get_cache_dsn()
        if dsn and psycopg is not None:
            try:
                _enrichment_cache = PostgresCache(dsn, "enrichment", get_enrichment_cache_ttl())
            except Exception:
                # Fall back to in-memory cache if Postgres fails
                _enrichment_cache = TTLCache(get_enrichment_cache_ttl())
        else:
            _enrichment_cache = TTLCache(get_enrichment_cache_ttl())

        return _enrichment_cache


def get_llm_cache() -> TTLCache | PostgresCache:
    """Get the LLM cache instance."""
    global _llm_cache

    if _llm_cache is not None:
        return _llm_cache

    with _cache_lock:
        if _llm_cache is not None:
            return _llm_cache

        dsn = _get_cache_dsn()
        if dsn and psycopg is not None:
            try:
                _llm_cache = PostgresCache(dsn, "llm", get_llm_cache_ttl())
            except Exception:
                # Fall back to in-memory cache if Postgres fails
                _llm_cache = TTLCache(get_llm_cache_ttl())
        else:
            _llm_cache = TTLCache(get_llm_cache_ttl())

        return _llm_cache
