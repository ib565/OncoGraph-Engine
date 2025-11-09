"""Tests for utility functions and caching."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from pipeline.utils import (
    PostgresCache,
    TTLCache,
    get_cache_ttl,
    get_enrichment_cache_ttl,
    get_llm_cache_ttl,
    stable_hash,
)


class TestTTLCache:
    """Test the TTLCache class."""

    def test_cache_basic_operations(self):
        """Test basic cache set/get operations."""
        cache = TTLCache(default_ttl_seconds=60)

        # Test setting and getting values
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Test non-existent key
        assert cache.get("nonexistent") is None

        # Test overwriting
        cache.set("key1", "value2")
        assert cache.get("key1") == "value2"

    def test_cache_ttl_expiration(self):
        """Test that cached values expire after TTL."""
        cache = TTLCache(default_ttl_seconds=0.1)  # Very short TTL for testing

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Wait for expiration
        time.sleep(0.2)
        assert cache.get("key1") is None

    def test_cache_custom_ttl(self):
        """Test setting custom TTL for individual keys."""
        cache = TTLCache(default_ttl_seconds=60)

        # Set with custom TTL
        cache.set("key1", "value1", ttl_seconds=0.1)
        cache.set("key2", "value2", ttl_seconds=60)

        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"

        # Wait for key1 to expire
        time.sleep(0.2)
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"

    def test_cache_disabled_ttl(self):
        """Test that TTL=0 disables caching."""
        cache = TTLCache(default_ttl_seconds=60)

        cache.set("key1", "value1", ttl_seconds=0)
        assert cache.get("key1") is None

    def test_cache_clear(self):
        """Test clearing the cache."""
        cache = TTLCache(default_ttl_seconds=60)

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"

        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_cache_delete(self):
        """Test deleting a specific cache entry."""
        cache = TTLCache(default_ttl_seconds=60)

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"

        cache.delete("key1")

        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"

    def test_cache_delete_by_prefix(self):
        """Test deleting entries by prefix."""
        cache = TTLCache(default_ttl_seconds=60)

        cache.set("prefix:key1", "value1")
        cache.set("prefix:key2", "value2")
        cache.set("other:key1", "value3")

        assert cache.get("prefix:key1") == "value1"
        assert cache.get("prefix:key2") == "value2"
        assert cache.get("other:key1") == "value3"

        count = cache.delete_by_prefix("prefix:")

        assert count == 2
        assert cache.get("prefix:key1") is None
        assert cache.get("prefix:key2") is None
        assert cache.get("other:key1") == "value3"

    def test_cache_deep_copy(self):
        """Test that cached values are deep copied to prevent mutation."""
        cache = TTLCache(default_ttl_seconds=60)

        original_list = [1, 2, 3]
        cache.set("key1", original_list)

        # Modify the original
        original_list.append(4)

        # Cached value should be unchanged
        cached_value = cache.get("key1")
        assert cached_value == [1, 2, 3]
        assert cached_value is not original_list

    def test_cache_pydantic_model(self):
        """Test that Pydantic models are properly cached and retrieved."""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            name: str
            value: int

        cache = TTLCache(default_ttl_seconds=60)

        original_model = TestModel(name="test", value=42)
        cache.set("pydantic_key", original_model)

        # Retrieve from cache
        cached_model = cache.get("pydantic_key")

        # Should be a dictionary (serialized form)
        assert isinstance(cached_model, dict)
        assert cached_model == {"name": "test", "value": 42}

        # Should be able to reconstruct the model
        reconstructed = TestModel(**cached_model)
        assert reconstructed.name == "test"
        assert reconstructed.value == 42

    def test_cache_thread_safety(self):
        """Test that cache operations are thread-safe."""
        import threading

        cache = TTLCache(default_ttl_seconds=60)
        results = []

        def worker(thread_id: int):
            for i in range(10):
                key = f"key_{thread_id}_{i}"
                value = f"value_{thread_id}_{i}"
                cache.set(key, value)
                results.append(cache.get(key))

        # Create multiple threads
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All operations should have succeeded
        assert len(results) == 50
        assert all(result is not None for result in results)


class TestStableHash:
    """Test the stable_hash function."""

    def test_stable_hash_consistency(self):
        """Test that stable_hash produces consistent results."""
        data1 = {"a": 1, "b": 2, "c": [3, 4, 5]}
        data2 = {"b": 2, "a": 1, "c": [3, 4, 5]}  # Different order

        hash1 = stable_hash(data1)
        hash2 = stable_hash(data2)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    def test_stable_hash_different_inputs(self):
        """Test that different inputs produce different hashes."""
        hash1 = stable_hash({"a": 1})
        hash2 = stable_hash({"a": 2})
        hash3 = stable_hash({"b": 1})

        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3


class TestPostgresCache:
    """Test the PostgresCache class."""

    @pytest.fixture
    def mock_psycopg(self):
        """Mock psycopg connection."""
        with patch("pipeline.utils.psycopg") as mock_psycopg_module:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
            mock_psycopg_module.connect.return_value = mock_conn
            yield mock_psycopg_module, mock_conn, mock_cur

    def test_postgres_cache_basic_operations(self, mock_psycopg):
        """Test basic cache set/get operations."""
        mock_psycopg_module, mock_conn, mock_cur = mock_psycopg

        cache = PostgresCache("postgresql://test", "test_cache", default_ttl_seconds=60)

        # Test set
        cache.set("key1", "value1")
        assert mock_cur.execute.call_count >= 2  # Table init + insert

        # Test get - cache hit
        mock_cur.fetchone.return_value = ('"value1"', datetime.now(UTC) + timedelta(seconds=60))
        result = cache.get("key1")
        assert result == "value1"

        # Test get - cache miss
        mock_cur.fetchone.return_value = None
        result = cache.get("key2")
        assert result is None

    def test_postgres_cache_expiration(self, mock_psycopg):
        """Test that cached values expire after TTL."""
        mock_psycopg_module, mock_conn, mock_cur = mock_psycopg

        cache = PostgresCache("postgresql://test", "test_cache", default_ttl_seconds=60)

        # Expired entry
        mock_cur.fetchone.return_value = ('"value1"', datetime.now(UTC) - timedelta(seconds=1))
        result = cache.get("key1")
        assert result is None
        # Should have deleted expired entry
        assert any("DELETE" in str(call) for call in mock_cur.execute.call_args_list)

    def test_postgres_cache_delete(self, mock_psycopg):
        """Test deleting a cache entry."""
        mock_psycopg_module, mock_conn, mock_cur = mock_psycopg

        cache = PostgresCache("postgresql://test", "test_cache")
        cache.delete("key1")

        # Should have executed DELETE
        assert any("DELETE" in str(call) for call in mock_cur.execute.call_args_list)

    def test_postgres_cache_delete_by_prefix(self, mock_psycopg):
        """Test deleting entries by prefix."""
        mock_psycopg_module, mock_conn, mock_cur = mock_psycopg

        cache = PostgresCache("postgresql://test", "test_cache")
        mock_cur.rowcount = 3
        count = cache.delete_by_prefix("prefix:")

        assert count == 3
        # Should have executed DELETE with LIKE
        assert any("LIKE" in str(call) for call in mock_cur.execute.call_args_list)

    def test_postgres_cache_clear(self, mock_psycopg):
        """Test clearing all cache entries."""
        mock_psycopg_module, mock_conn, mock_cur = mock_psycopg

        cache = PostgresCache("postgresql://test", "test_cache")
        cache.clear()

        # Should have executed DELETE for cache_type
        assert any("cache_type" in str(call) for call in mock_cur.execute.call_args_list)

    def test_postgres_cache_pydantic_model(self, mock_psycopg):
        """Test that Pydantic models are properly cached and retrieved."""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            name: str
            value: int

        mock_psycopg_module, mock_conn, mock_cur = mock_psycopg

        cache = PostgresCache("postgresql://test", "test_cache")

        original_model = TestModel(name="test", value=42)
        cache.set("pydantic_key", original_model)

        # Retrieve from cache
        mock_cur.fetchone.return_value = (
            '{"name": "test", "value": 42}',
            datetime.now(UTC) + timedelta(seconds=60),
        )
        cached_model = cache.get("pydantic_key")

        # Should be a dictionary (serialized form)
        assert isinstance(cached_model, dict)
        assert cached_model == {"name": "test", "value": 42}

    def test_postgres_cache_error_handling(self, mock_psycopg):
        """Test that cache errors are handled gracefully."""
        mock_psycopg_module, mock_conn, mock_cur = mock_psycopg

        cache = PostgresCache("postgresql://test", "test_cache")

        # Simulate database error
        mock_psycopg_module.connect.side_effect = Exception("Database error")

        # Operations should not raise, but return None/do nothing
        result = cache.get("key1")
        assert result is None

        cache.set("key1", "value1")  # Should not raise
        cache.delete("key1")  # Should not raise
        cache.clear()  # Should not raise

    def test_postgres_cache_batch_cleanup(self, mock_psycopg):
        """Test that batch cleanup runs after 100 set operations."""
        mock_psycopg_module, mock_conn, mock_cur = mock_psycopg

        cache = PostgresCache("postgresql://test", "test_cache")

        # Reset call count after initialization
        mock_cur.execute.reset_mock()

        # Perform 100 set operations
        for i in range(100):
            cache.set(f"key{i}", f"value{i}")

        # Should have triggered batch cleanup (check for DELETE with expires_at)
        delete_calls = [
            call for call in mock_cur.execute.call_args_list if "expires_at" in str(call)
        ]
        assert len(delete_calls) > 0

    def test_postgres_cache_thread_safety(self, mock_psycopg):
        """Test that cache operations are thread-safe."""
        import threading

        mock_psycopg_module, mock_conn, mock_cur = mock_psycopg

        cache = PostgresCache("postgresql://test", "test_cache")
        results = []

        def worker(thread_id: int):
            for i in range(10):
                key = f"key_{thread_id}_{i}"
                value = f"value_{thread_id}_{i}"
                cache.set(key, value)
                # Mock successful get
                mock_cur.fetchone.return_value = (
                    f'"{value}"',
                    datetime.now(UTC) + timedelta(seconds=60),
                )
                result = cache.get(key)
                results.append(result)

        # Create multiple threads
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All operations should have succeeded
        assert len(results) == 50
        assert all(result is not None for result in results)

    def test_postgres_cache_missing_psycopg(self):
        """Test that PostgresCache raises ImportError if psycopg is not available."""
        with patch("pipeline.utils.psycopg", None):
            with pytest.raises(ImportError, match="psycopg is required"):
                PostgresCache("postgresql://test", "test_cache")


class TestEnvironmentConfiguration:
    """Test environment variable configuration."""

    @patch.dict("os.environ", {"CACHE_TTL_SECONDS": "3600"})
    def test_get_cache_ttl_from_env(self):
        """Test getting cache TTL from environment variable."""
        assert get_cache_ttl() == 3600

    @patch.dict("os.environ", {"LLM_CACHE_TTL_SECONDS": "7200"})
    def test_get_llm_cache_ttl_from_env(self):
        """Test getting LLM cache TTL from environment variable."""
        assert get_llm_cache_ttl() == 7200

    @patch.dict("os.environ", {"CACHE_TTL_SECONDS": "3600", "LLM_CACHE_TTL_SECONDS": "7200"})
    def test_get_llm_cache_ttl_fallback(self):
        """Test that LLM cache TTL falls back to general cache TTL."""
        assert get_llm_cache_ttl() == 7200

    @patch.dict("os.environ", {}, clear=True)
    def test_get_cache_ttl_default(self):
        """Test default cache TTL when no environment variable is set."""
        assert get_cache_ttl() == 1800  # 30 minutes default

    @patch.dict("os.environ", {}, clear=True)
    def test_get_llm_cache_ttl_default(self):
        """Test default LLM cache TTL when no environment variable is set."""
        assert get_llm_cache_ttl() == 172800  # 48 hours default

    @patch.dict("os.environ", {}, clear=True)
    def test_get_enrichment_cache_ttl_default(self):
        """Test default enrichment cache TTL when no environment variable is set."""
        assert get_enrichment_cache_ttl() == 172800  # 48 hours default

    @patch.dict("os.environ", {"ENRICHMENT_CACHE_TTL_SECONDS": "3600"})
    def test_get_enrichment_cache_ttl_from_env(self):
        """Test getting enrichment cache TTL from environment variable."""
        assert get_enrichment_cache_ttl() == 3600
